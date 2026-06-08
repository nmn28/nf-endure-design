#!/usr/bin/env python3
"""RunPod serverless handler for AlphaFold2 initial guess (ColabDesign)."""
import runpod
import boto3
import os
import shutil
import subprocess
import json
import time
import glob

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
S3_BUCKET = os.environ.get("S3_BUCKET", "endure-protein-results")

AF2_PARAMS_DIR = "/opt/alphafold/params"


def download_s3(s3_uri, local_path):
    """Download s3://bucket/key to local_path."""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    s3.download_file(parts[0], parts[1], local_path)


def download_s3_directory(s3_uri, local_dir):
    """Download all files under an S3 prefix to local_dir."""
    os.makedirs(local_dir, exist_ok=True)
    parts = s3_uri.rstrip("/").replace("s3://", "").split("/", 1)
    bucket, prefix = parts[0], parts[1]
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or obj["Size"] == 0:
                continue
            rel = os.path.relpath(key, prefix)
            if rel.startswith("..") or rel == ".":
                continue
            local_path = os.path.join(local_dir, rel)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            s3.download_file(bucket, key, local_path)


def upload_directory(local_dir, s3_prefix):
    """Upload all files in local_dir to s3://{S3_BUCKET}/{s3_prefix}/."""
    uploaded = []
    for root, _, files in os.walk(local_dir):
        for f in files:
            local_path = os.path.join(root, f)
            rel_path = os.path.relpath(local_path, local_dir)
            s3_key = f"{s3_prefix}/{rel_path}"
            s3.upload_file(local_path, S3_BUCKET, s3_key)
            uploaded.append(s3_key)
    return uploaded


def handler(job):
    job_input = job["input"]
    job_id = job["id"]
    outdir = f"/tmp/results/{job_id}"
    workdir = f"/tmp/work/{job_id}"

    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(workdir, exist_ok=True)

    try:
        # Required inputs
        pdb_dir_uri = job_input["pdb_dir"]              # s3://bucket/path/to/pdbs/
        design_type = job_input.get("design_type", "scaffold")  # "scaffold" or "binder"
        run_parameters = job_input.get("run_parameters", "")

        # Optional
        native_pdb_uri = job_input.get("native_pdb", "")  # s3://bucket/path/to/native.pdb
        num_recycles = job_input.get("num_recycles", 3)
        designed_chains = job_input.get("designed_chains", "A")

        # Download input PDB directory
        pdb_dir = os.path.join(workdir, "input_pdbs")
        print(f"[{job_id}] Downloading PDB directory: {pdb_dir_uri}")
        download_s3_directory(pdb_dir_uri, pdb_dir)

        pdb_count = len(glob.glob(os.path.join(pdb_dir, "*.pdb")))
        print(f"[{job_id}] Downloaded {pdb_count} PDB files")

        # Download native PDB if provided
        native_pdb = ""
        if native_pdb_uri:
            native_pdb = os.path.join(workdir, "native.pdb")
            print(f"[{job_id}] Downloading native PDB: {native_pdb_uri}")
            download_s3(native_pdb_uri, native_pdb)

        # Symlink baked AF2 params
        params_link = os.path.join(workdir, "alphafold_params")
        os.symlink(AF2_PARAMS_DIR, params_link)

        # Run AF2 initial guess
        output_name = os.path.join(outdir, "af2_initial_guess")
        eval_script = f"af2_initial_guess_{design_type}_eval.py"

        print(f"[{job_id}] Running {eval_script}: {pdb_count} PDBs, {num_recycles} recycles")
        t0 = time.time()

        cmd = [
            "python3", f"/usr/local/bin/{eval_script}",
            pdb_dir,
            output_name,
            "--params", params_link,
            "--num-recycles", str(num_recycles),
            "--designed_chains", designed_chains,
        ]
        if native_pdb:
            cmd.extend(["--native-pdb", native_pdb])
        if run_parameters:
            cmd.extend(run_parameters.split())

        env = os.environ.copy()
        env["MPLBACKEND"] = ""  # prevent matplotlib issues

        af2_result = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=workdir)
        if af2_result.returncode != 0:
            print(f"[{job_id}] AF2 stdout:\n{af2_result.stdout[-2000:]}")
            print(f"[{job_id}] AF2 stderr:\n{af2_result.stderr[-2000:]}")
            raise RuntimeError(f"AF2 initial guess failed: {af2_result.stderr[-500:]}")
        af2_time = time.time() - t0
        print(f"[{job_id}] AF2 initial guess completed in {af2_time:.1f}s")

        # Parse metrics from JSONL
        jsonl_path = output_name + ".jsonl"
        metrics_list = []
        if os.path.exists(jsonl_path):
            with open(jsonl_path) as f:
                for line in f:
                    if line.strip():
                        metrics_list.append(json.loads(line))

        # Upload
        s3_prefix = f"protein-design/{job_id}"
        uploaded = upload_directory(outdir, s3_prefix)
        print(f"[{job_id}] Uploaded {len(uploaded)} files to s3://{S3_BUCKET}/{s3_prefix}/")

        output_pdb_count = len(glob.glob(os.path.join(output_name, "*.pdb")))
        return {
            "status": "success",
            "mode": "colabdesign",
            "design_type": design_type,
            "num_input_pdbs": pdb_count,
            "num_output_pdbs": output_pdb_count,
            "af2_time_sec": round(af2_time, 1),
            "metrics": metrics_list,
            "s3_prefix": f"s3://{S3_BUCKET}/{s3_prefix}/"
        }
    except Exception as e:
        print(f"[{job_id}] ERROR: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        for d in [outdir, workdir]:
            if os.path.exists(d):
                shutil.rmtree(d)


runpod.serverless.start({"handler": handler})
