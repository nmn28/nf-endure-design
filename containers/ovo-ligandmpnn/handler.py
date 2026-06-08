#!/usr/bin/env python3
"""RunPod serverless handler for LigandMPNN sequence design."""
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

LIGANDMPNN_DIR = "/opt/LigandMPNN"


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
        pdb_dir_uri = job_input["pdb_dir"]           # s3://bucket/path/to/pdbs/
        num_seq_per_target = job_input.get("num_seq_per_target", 4)
        run_parameters = job_input.get("run_parameters", "")

        # Download input PDB directory
        pdb_dir = os.path.join(workdir, "input_pdbs")
        print(f"[{job_id}] Downloading PDB directory: {pdb_dir_uri}")
        download_s3_directory(pdb_dir_uri, pdb_dir)

        pdb_count = len(glob.glob(os.path.join(pdb_dir, "*.pdb")))
        print(f"[{job_id}] Downloaded {pdb_count} PDB files")

        # Symlink model params
        model_params = os.path.join(workdir, "model_params")
        os.symlink(f"{LIGANDMPNN_DIR}/model_params", model_params)

        # Prepare JSON files (extract design regions from PDB REMARK headers)
        pdb_json = os.path.join(workdir, "pdb_ids.json")
        redesigned_json = os.path.join(workdir, "redesigned_residues_multi.json")
        remark_json = os.path.join(workdir, "remark_multi.json")

        print(f"[{job_id}] Preparing JSON from PDB headers...")
        prep_result = subprocess.run([
            "python3", "/usr/local/bin/prepare_json.py",
            "--pdb_dir", pdb_dir,
            "--pdb_ids_json", pdb_json,
            "--redesigned_residues_json", redesigned_json,
            "--remark_json", remark_json,
        ], capture_output=True, text=True, cwd=workdir)
        if prep_result.returncode != 0:
            print(f"[{job_id}] prepare_json.py stderr:\n{prep_result.stderr[-2000:]}")
            raise RuntimeError(f"prepare_json.py failed: {prep_result.stderr[-500:]}")

        # Run LigandMPNN
        print(f"[{job_id}] Running LigandMPNN: {num_seq_per_target} seqs/target")
        t0 = time.time()
        cmd = [
            "python", f"{LIGANDMPNN_DIR}/run.py",
            "--model_type", "ligand_mpnn",
            "--pdb_path_multi", pdb_json,
            "--redesigned_residues_multi", redesigned_json,
            "--out_folder", os.path.join(outdir, "ligandmpnn"),
            "--number_of_batches", str(num_seq_per_target),
            "--pack_side_chains", "1",
            "--number_of_packs_per_design", "1",
            "--repack_everything", "1",
        ]
        if run_parameters:
            cmd.extend(run_parameters.split())
        mpnn_result = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
        if mpnn_result.returncode != 0:
            print(f"[{job_id}] LigandMPNN stdout:\n{mpnn_result.stdout[-2000:]}")
            print(f"[{job_id}] LigandMPNN stderr:\n{mpnn_result.stderr[-2000:]}")
            raise RuntimeError(f"LigandMPNN failed: {mpnn_result.stderr[-500:]}")
        mpnn_time = time.time() - t0
        print(f"[{job_id}] LigandMPNN completed in {mpnn_time:.1f}s")

        # Copy REMARK headers to output PDBs
        packed_dir = os.path.join(outdir, "ligandmpnn", "packed")
        std_dir = os.path.join(outdir, "ligandmpnn", "standardized_pdb")
        os.makedirs(std_dir, exist_ok=True)

        remarks_result = subprocess.run([
            "bash", "/usr/local/bin/copy_remarks.sh", remark_json, packed_dir, std_dir
        ], capture_output=True, text=True, cwd=workdir)
        if remarks_result.returncode != 0:
            print(f"[{job_id}] copy_remarks.sh stderr:\n{remarks_result.stderr[-2000:]}")
            raise RuntimeError(f"copy_remarks.sh failed: {remarks_result.stderr[-500:]}")

        # Upload
        s3_prefix = f"protein-design/{job_id}"
        uploaded = upload_directory(outdir, s3_prefix)
        print(f"[{job_id}] Uploaded {len(uploaded)} files to s3://{S3_BUCKET}/{s3_prefix}/")

        packed_count = len(glob.glob(os.path.join(packed_dir, "*.pdb")))
        return {
            "status": "success",
            "mode": "ligandmpnn",
            "num_input_pdbs": pdb_count,
            "num_output_pdbs": packed_count,
            "mpnn_time_sec": round(mpnn_time, 1),
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
