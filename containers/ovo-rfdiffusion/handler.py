#!/usr/bin/env python3
"""RunPod serverless handler for RFdiffusion (v1/v2) and RFdiffusion3 backbone generation.

Dispatch via job["input"]["version"]:
  - "v2" (default): RFdiffusion v1/v2 via run_inference.py -> PDB output
  - "v3": RFdiffusion3 via rfd3 CLI -> CIF.gz -> standardized PDB output
"""
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
RFD3_CKPT = "/opt/rfdiffusion3/models/rfd3_latest.ckpt"


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


def run_v2(job_input, job_id, outdir, workdir):
    """RFdiffusion v1/v2 backbone generation."""
    input_pdb_uri = job_input["input_pdb"]
    contig = job_input["contig"]
    num_designs = job_input.get("num_designs", 1)
    run_parameters = job_input.get("run_parameters", "")
    hotspot = job_input.get("hotspot", "")
    design_type = job_input.get("design_type", "scaffold")

    input_pdb = os.path.join(workdir, "input.pdb")
    print(f"[{job_id}] Downloading input PDB: {input_pdb_uri}")
    download_s3(input_pdb_uri, input_pdb)

    env = os.environ.copy()
    env["HYDRA_FULL_ERROR"] = "1"
    env["PYTHONPATH"] = f"{RFDIFFUSION_DIR}:{RFDIFFUSION_DIR}/env/SE3Transformer/"

    # Validate input
    print(f"[{job_id}] Validating input...")
    val_result = subprocess.run(
        ["python3", "/usr/local/bin/validate_input.py", input_pdb, contig],
        env=env, capture_output=True, text=True, cwd=workdir
    )
    if val_result.returncode != 0:
        err_detail = val_result.stderr.strip() or val_result.stdout.strip()
        print(f"[{job_id}] validate_input.py failed: {err_detail}")
        raise RuntimeError(f"Input validation failed: {err_detail}")

    # Run RFdiffusion
    print(f"[{job_id}] Running RFdiffusion v2: {num_designs} designs, contig={contig}")
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
    rf_result = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=workdir)
    if rf_result.returncode != 0:
        print(f"[{job_id}] RFdiffusion stdout:\n{rf_result.stdout[-2000:]}")
        print(f"[{job_id}] RFdiffusion stderr:\n{rf_result.stderr[-2000:]}")
        combined = rf_result.stdout[-1000:] + "\n---STDERR---\n" + rf_result.stderr[-1000:]
        raise RuntimeError(f"RFdiffusion failed: {combined}")
    inference_time = time.time() - t0
    print(f"[{job_id}] RFdiffusion v2 completed in {inference_time:.1f}s")

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
    std_result = subprocess.run(
        ["python3", "/usr/local/bin/standardize_pdb.py", pdb_dir, trb_dir, std_pdb_dir],
        env=env, capture_output=True, text=True
    )
    if std_result.returncode != 0:
        print(f"[{job_id}] standardize_pdb.py stderr:\n{std_result.stderr[-2000:]}")
        raise RuntimeError(f"standardize_pdb.py failed: {std_result.stderr[-500:]}")

    num_pdbs = len([f for f in os.listdir(pdb_dir) if f.endswith(".pdb")])
    return {
        "mode": "rfdiffusion",
        "version": "v2",
        "design_type": design_type,
        "num_designs": num_designs,
        "inference_time_sec": round(inference_time, 1),
        "num_pdbs": num_pdbs,
    }


def run_v3(job_input, job_id, outdir, workdir):
    """RFdiffusion3 backbone generation via rfd3 CLI."""
    input_pdb_uri = job_input["input_pdb"]
    contig = job_input["contig"]
    num_designs = job_input.get("num_designs", 1)
    run_parameters = job_input.get("run_parameters", "")
    hotspot = job_input.get("hotspot", "")
    design_type = job_input.get("design_type", "scaffold")
    dump_trajectories = job_input.get("dump_trajectories", False)
    spec_overrides = job_input.get("spec_overrides", "")

    if not os.path.exists(RFD3_CKPT):
        raise RuntimeError(f"RFdiffusion3 checkpoint not found at {RFD3_CKPT}")

    input_pdb = os.path.join(workdir, "input.pdb")
    print(f"[{job_id}] Downloading input PDB: {input_pdb_uri}")
    download_s3(input_pdb_uri, input_pdb)

    # Build RFd3 input JSON spec (converts v1 contig to v3 format)
    spec_json = os.path.join(workdir, "input_spec.json")
    build_cmd = [
        "python3", "/usr/local/bin/build_input_json.py",
        "--input_structure_path", input_pdb,
        "--contig", contig,
        "--hotspot", hotspot,
        "--output_json", spec_json,
    ]
    if spec_overrides:
        overrides_file = os.path.join(workdir, "spec_overrides.json")
        with open(overrides_file, "w") as f:
            f.write(spec_overrides if isinstance(spec_overrides, str) else json.dumps(spec_overrides))
        build_cmd.extend(["--spec_overrides_file", overrides_file])

    build_result = subprocess.run(build_cmd, capture_output=True, text=True, cwd=workdir)
    if build_result.returncode != 0:
        raise RuntimeError(f"build_input_json.py failed: {build_result.stderr[-500:]}")
    print(f"[{job_id}] Built RFd3 input spec: {build_result.stdout.strip()}")

    # Run RFdiffusion3
    rfd3_outdir = os.path.join(workdir, "rfd3_output")
    os.makedirs(rfd3_outdir, exist_ok=True)

    print(f"[{job_id}] Running RFdiffusion3: {num_designs} designs, contig={contig}")
    t0 = time.time()
    cmd = [
        "rfd3", "design",
        f"out_dir={rfd3_outdir}",
        f"inputs={spec_json}",
        f"ckpt_path={RFD3_CKPT}",
        f"n_batches={num_designs}",
        "diffusion_batch_size=1",
        f"dump_trajectories={str(dump_trajectories).lower()}",
        f"global_prefix={job_id}",
        "skip_existing=False",
    ]
    if run_parameters:
        cmd.extend(run_parameters.split())

    rf_result = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    if rf_result.returncode != 0:
        combined = rf_result.stdout[-1000:] + "\n---STDERR---\n" + rf_result.stderr[-1000:]
        raise RuntimeError(f"RFdiffusion3 failed: {combined}")
    inference_time = time.time() - t0
    print(f"[{job_id}] RFdiffusion3 completed in {inference_time:.1f}s")

    # Organize outputs
    cif_dir = os.path.join(outdir, "rfdiffusion3_cif")
    json_dir = os.path.join(outdir, "rfdiffusion3_json")
    traj_dir = os.path.join(outdir, "rfdiffusion3_traj")
    std_pdb_dir = os.path.join(outdir, "rfdiffusion_standardized_pdb")
    os.makedirs(cif_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)
    os.makedirs(traj_dir, exist_ok=True)
    os.makedirs(std_pdb_dir, exist_ok=True)

    for f in os.listdir(rfd3_outdir):
        src = os.path.join(rfd3_outdir, f)
        if f.endswith(".cif.gz"):
            shutil.move(src, os.path.join(cif_dir, f))
        elif f.endswith(".json"):
            shutil.move(src, os.path.join(json_dir, f))
        elif "traj" in f:
            shutil.move(src, os.path.join(traj_dir, f))

    # Standardize CIF.gz -> PDB
    print(f"[{job_id}] Standardizing CIF outputs to PDB...")
    std_result = subprocess.run(
        [
            "python3", "/usr/local/bin/standardize_cif.py",
            "--cif_dir", cif_dir,
            "--json_dir", json_dir,
            "--output_dir", std_pdb_dir,
            "--input_contig", contig,
            "--hotspot", hotspot,
        ],
        capture_output=True, text=True
    )
    if std_result.returncode != 0:
        raise RuntimeError(f"standardize_cif.py failed: {std_result.stderr[-500:]}")

    num_cifs = len([f for f in os.listdir(cif_dir) if f.endswith(".cif.gz")])
    num_pdbs = len([f for f in os.listdir(std_pdb_dir) if f.endswith(".pdb")])
    return {
        "mode": "rfdiffusion3",
        "version": "v3",
        "design_type": design_type,
        "num_designs": num_designs,
        "inference_time_sec": round(inference_time, 1),
        "num_cifs": num_cifs,
        "num_pdbs": num_pdbs,
    }


def handler(job):
    job_input = job["input"]
    job_id = job["id"]
    version = job_input.get("version", "v2")
    outdir = f"/tmp/results/{job_id}"
    workdir = f"/tmp/work/{job_id}"

    for d in [outdir, workdir]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

    try:
        if version == "v3":
            result = run_v3(job_input, job_id, outdir, workdir)
        else:
            result = run_v2(job_input, job_id, outdir, workdir)

        # Upload results to S3
        s3_prefix = f"protein-design/{job_id}"
        uploaded = upload_directory(outdir, s3_prefix)
        print(f"[{job_id}] Uploaded {len(uploaded)} files to s3://{S3_BUCKET}/{s3_prefix}/")

        return {
            "status": "success",
            **result,
            "s3_prefix": f"s3://{S3_BUCKET}/{s3_prefix}/",
        }
    except Exception as e:
        print(f"[{job_id}] ERROR: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        for d in [outdir, workdir]:
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)


runpod.serverless.start({"handler": handler})
