#!/usr/bin/env python3
"""RunPod serverless handler for RFdiffusion backbone generation."""
import runpod
import boto3
import os
import shutil
import subprocess
import json
import time

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
S3_BUCKET = os.environ.get("S3_BUCKET", "endure-protein-results")

MODELS_DIR = "/opt/rfdiffusion/models"
RFDIFFUSION_DIR = "/opt/RFdiffusion"


def download_s3(s3_uri, local_path):
    """Download s3://bucket/key to local_path."""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    s3.download_file(parts[0], parts[1], local_path)


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
        input_pdb_uri = job_input["input_pdb"]  # s3://bucket/path/to.pdb
        contig = job_input["contig"]             # e.g. "A82-87/10/A92-97"
        num_designs = job_input.get("num_designs", 1)
        run_parameters = job_input.get("run_parameters", "")
        hotspot = job_input.get("hotspot", "")
        design_type = job_input.get("design_type", "scaffold")

        # Download input PDB
        input_pdb = os.path.join(workdir, "input.pdb")
        print(f"[{job_id}] Downloading input PDB: {input_pdb_uri}")
        download_s3(input_pdb_uri, input_pdb)

        # Set up environment
        env = os.environ.copy()
        env["HYDRA_FULL_ERROR"] = "1"
        env["PYTHONPATH"] = f"{RFDIFFUSION_DIR}:{RFDIFFUSION_DIR}/env/SE3Transformer/"

        # Validate input
        print(f"[{job_id}] Validating input...")
        subprocess.run(
            ["validate_input.py", input_pdb, contig],
            env=env, check=True, cwd=workdir
        )

        # Run RFdiffusion
        print(f"[{job_id}] Running RFdiffusion: {num_designs} designs, contig={contig}")
        t0 = time.time()
        cmd = [
            "python3", f"{RFDIFFUSION_DIR}/scripts/run_inference.py",
            f"inference.output_prefix={workdir}/output/design",
            f"inference.model_directory_path={MODELS_DIR}",
            f"inference.input_pdb={input_pdb}",
            f"inference.num_designs={num_designs}",
            f"contigmap.contigs=[{contig}]",
        ]
        if hotspot:
            cmd.append(f"ppi.hotspot_res=[{hotspot}]")
        if run_parameters:
            cmd.extend(run_parameters.split())
        subprocess.run(cmd, env=env, check=True, cwd=workdir)
        inference_time = time.time() - t0
        print(f"[{job_id}] RFdiffusion completed in {inference_time:.1f}s")

        # Organize outputs
        pdb_dir = os.path.join(outdir, "rfdiffusion_pdb")
        trb_dir = os.path.join(outdir, "rfdiffusion_trb")
        std_pdb_dir = os.path.join(outdir, "rfdiffusion_standardized_pdb")
        os.makedirs(pdb_dir, exist_ok=True)
        os.makedirs(trb_dir, exist_ok=True)
        os.makedirs(std_pdb_dir, exist_ok=True)

        output_dir = os.path.join(workdir, "output")
        for f in os.listdir(output_dir):
            src = os.path.join(output_dir, f)
            if f.endswith(".pdb"):
                shutil.move(src, os.path.join(pdb_dir, f))
            elif f.endswith(".trb"):
                shutil.move(src, os.path.join(trb_dir, f))

        # Standardize PDBs
        print(f"[{job_id}] Standardizing PDBs...")
        subprocess.run(
            ["standardize_pdb.py", pdb_dir, trb_dir, std_pdb_dir],
            env=env, check=True
        )

        # Upload
        s3_prefix = f"protein-design/{job_id}"
        uploaded = upload_directory(outdir, s3_prefix)
        print(f"[{job_id}] Uploaded {len(uploaded)} files to s3://{S3_BUCKET}/{s3_prefix}/")

        return {
            "status": "success",
            "mode": "rfdiffusion",
            "design_type": design_type,
            "num_designs": num_designs,
            "inference_time_sec": round(inference_time, 1),
            "num_pdbs": len([f for f in os.listdir(pdb_dir) if f.endswith(".pdb")]),
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
