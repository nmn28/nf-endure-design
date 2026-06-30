#!/usr/bin/env python3
"""RunPod serverless handler for AlphaFold2 initial guess (ColabDesign) + BindCraft."""
import runpod
import boto3
import csv
import os
import shutil
import subprocess
import json
import time
import glob

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
S3_BUCKET = os.environ.get("S3_BUCKET", "endure-protein-results")

AF2_PARAMS_DIR = "/opt/alphafold/params"
BINDCRAFT_DIR = "/opt/bindcraft"


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


def handle_colabdesign(job_id, job_input, outdir, workdir):
    """Original AF2 initial guess handler."""
    pdb_dir_uri = job_input["pdb_dir"]
    design_type = job_input.get("design_type", "scaffold")
    run_parameters = job_input.get("run_parameters", "")
    native_pdb_uri = job_input.get("native_pdb", "")
    num_recycles = job_input.get("num_recycles", 3)
    designed_chains = job_input.get("designed_chains", "A")

    # AF2 model configuration
    multimer = job_input.get("multimer", False)
    # Scaffold-specific
    no_templates = job_input.get("no_templates", False)
    # Binder-specific
    use_binder_template = job_input.get("use_binder_template", False)
    use_interface_template = job_input.get("use_interface_template", False)
    blind = job_input.get("blind", False)
    cyclic = job_input.get("cyclic", False)
    hotspot = job_input.get("hotspot", "")

    pdb_dir = os.path.join(workdir, "input_pdbs")
    print(f"[{job_id}] Downloading PDB directory: {pdb_dir_uri}")
    download_s3_directory(pdb_dir_uri, pdb_dir)

    pdb_count = len(glob.glob(os.path.join(pdb_dir, "*.pdb")))
    print(f"[{job_id}] Downloaded {pdb_count} PDB files")

    native_pdb = ""
    if native_pdb_uri:
        native_pdb = os.path.join(workdir, "native.pdb")
        print(f"[{job_id}] Downloading native PDB: {native_pdb_uri}")
        download_s3(native_pdb_uri, native_pdb)

    params_link = os.path.join(workdir, "alphafold_params")
    os.symlink(AF2_PARAMS_DIR, params_link)

    output_name = os.path.join(outdir, "af2_initial_guess")
    eval_script = f"af2_initial_guess_{design_type}_eval.py"

    print(f"[{job_id}] Running {eval_script}: {pdb_count} PDBs, {num_recycles} recycles, "
          f"multimer={multimer}")
    t0 = time.time()

    cmd = [
        "python3", f"/usr/local/bin/{eval_script}",
        pdb_dir,
        output_name,
        "--params", params_link,
        "--num-recycles", str(num_recycles),
        "--designed_chains", designed_chains,
    ]
    if multimer:
        cmd.append("--multimer")
    if native_pdb:
        cmd.extend(["--native-pdb", native_pdb])

    # Scaffold-specific flags
    if design_type == "scaffold":
        if no_templates:
            cmd.append("--no-templates")

    # Binder-specific flags
    if design_type == "binder":
        if use_binder_template:
            cmd.append("--use-binder-template")
        if use_interface_template:
            cmd.append("--use-interface-template")
        if blind:
            cmd.append("--blind")
        if cyclic:
            cmd.append("--cyclic")
        if hotspot:
            cmd.extend(["--hotspot", hotspot])

    if run_parameters:
        cmd.extend(run_parameters.split())

    env = os.environ.copy()
    env["MPLBACKEND"] = ""

    af2_result = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=workdir)
    if af2_result.returncode != 0:
        print(f"[{job_id}] AF2 stdout:\n{af2_result.stdout[-2000:]}")
        print(f"[{job_id}] AF2 stderr:\n{af2_result.stderr[-2000:]}")
        raise RuntimeError(f"AF2 initial guess failed: {af2_result.stderr[-500:]}")
    af2_time = time.time() - t0
    print(f"[{job_id}] AF2 initial guess completed in {af2_time:.1f}s")

    jsonl_path = output_name + ".jsonl"
    metrics_list = []
    if os.path.exists(jsonl_path):
        with open(jsonl_path) as f:
            for line in f:
                if line.strip():
                    metrics_list.append(json.loads(line))

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


def handle_bindcraft(job_id, job_input, outdir, workdir):
    """BindCraft binder design handler."""
    # Required inputs
    target_pdb_uri = job_input["target_pdb"]  # s3://bucket/path/to/target.pdb
    target_chains = job_input.get("target_chains", "A")
    binder_length_min = job_input.get("binder_length_min", 65)
    binder_length_max = job_input.get("binder_length_max", 150)
    num_final_designs = job_input.get("num_final_designs", 10)
    hotspot_residues = job_input.get("hotspot_residues", "")

    # Protocol presets
    design_protocol = job_input.get("design_protocol", "default")  # default/beta_sheet/peptide
    prediction_protocol = job_input.get("prediction_protocol", "default")  # default/hard_target
    filter_type = job_input.get("filter_type", "default")  # default/peptide/relaxed/none

    # Download target PDB
    target_pdb_local = os.path.join(workdir, "target.pdb")
    print(f"[{job_id}] Downloading target PDB: {target_pdb_uri}")
    download_s3(target_pdb_uri, target_pdb_local)

    # Build target settings JSON
    design_path = os.path.join(outdir, "bindcraft_output")
    os.makedirs(design_path, exist_ok=True)

    target_settings = {
        "design_path": design_path,
        "binder_name": f"bc_{job_id[:8]}",
        "starting_pdb": target_pdb_local,
        "chains": target_chains,
        "target_hotspot_residues": hotspot_residues,
        "lengths": [binder_length_min, binder_length_max],
        "number_of_final_designs": num_final_designs,
    }
    target_settings_path = os.path.join(workdir, "target_settings.json")
    with open(target_settings_path, "w") as f:
        json.dump(target_settings, f, indent=2)

    # Resolve filter preset
    filter_map = {
        "default": "default_filters.json",
        "peptide": "peptide_filters.json",
        "relaxed": "relaxed_filters.json",
        "none": "no_filters.json",
    }
    filter_file = os.path.join(BINDCRAFT_DIR, "settings_filters", filter_map.get(filter_type, "default_filters.json"))

    # Resolve advanced settings preset
    suffix_parts = []
    if design_protocol == "beta_sheet":
        suffix_parts.append("betasheet")
    elif design_protocol == "peptide":
        suffix_parts.append("peptide")
    else:
        suffix_parts.append("default")

    if design_protocol == "peptide":
        suffix_parts.append("3stage_multimer")
    else:
        suffix_parts.append("4stage_multimer")

    if prediction_protocol == "hard_target":
        suffix_parts.append("hardtarget")

    advanced_name = "_".join(suffix_parts) + ".json"
    advanced_file = os.path.join(BINDCRAFT_DIR, "settings_advanced", advanced_name)
    if not os.path.exists(advanced_file):
        # Fallback to default
        advanced_file = os.path.join(BINDCRAFT_DIR, "settings_advanced", "default_4stage_multimer.json")

    # Symlink AF2 params for BindCraft
    af2_link = os.path.join(workdir, "params")
    os.symlink(AF2_PARAMS_DIR, af2_link)

    print(f"[{job_id}] Running BindCraft: lengths [{binder_length_min}-{binder_length_max}], "
          f"chains={target_chains}, designs={num_final_designs}, protocol={design_protocol}")
    t0 = time.time()

    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    env["AF2_PARAMS_DIR"] = AF2_PARAMS_DIR

    cmd = [
        "python3", os.path.join(BINDCRAFT_DIR, "bindcraft.py"),
        "--settings", target_settings_path,
        "--filters", filter_file,
        "--advanced", advanced_file,
    ]

    bc_result = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=BINDCRAFT_DIR)
    bc_time = time.time() - t0
    print(f"[{job_id}] BindCraft completed in {bc_time:.1f}s (exit code {bc_result.returncode})")

    if bc_result.returncode != 0:
        print(f"[{job_id}] BindCraft stdout:\n{bc_result.stdout[-2000:]}")
        print(f"[{job_id}] BindCraft stderr:\n{bc_result.stderr[-2000:]}")
        # BindCraft may still produce partial results even on non-zero exit
        if not os.path.exists(design_path):
            raise RuntimeError(f"BindCraft failed: {bc_result.stderr[-500:]}")

    # Parse final design stats CSV
    designs = []
    stats_csv = os.path.join(design_path, "final_design_stats.csv")
    if os.path.exists(stats_csv):
        with open(stats_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                design = {"id": row.get("Design", ""), "descriptors": {}}
                for k, v in row.items():
                    if k == "Design":
                        continue
                    try:
                        design["descriptors"][k] = float(v)
                    except (ValueError, TypeError):
                        pass
                designs.append(design)

    # Count accepted PDBs
    accepted_dir = os.path.join(design_path, "Accepted")
    accepted_pdbs = glob.glob(os.path.join(accepted_dir, "*.pdb")) if os.path.exists(accepted_dir) else []

    # Upload results
    s3_prefix = f"protein-design/{job_id}/bindcraft"
    uploaded = upload_directory(design_path, s3_prefix)
    print(f"[{job_id}] Uploaded {len(uploaded)} files to s3://{S3_BUCKET}/{s3_prefix}/")

    return {
        "status": "success",
        "mode": "bindcraft",
        "num_accepted_designs": len(accepted_pdbs),
        "num_total_designs": len(designs),
        "bindcraft_time_sec": round(bc_time, 1),
        "designs": designs,
        "s3_prefix": f"s3://{S3_BUCKET}/{s3_prefix}/",
    }


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
        mode = job_input.get("mode", "colabdesign")

        if mode == "bindcraft":
            return handle_bindcraft(job_id, job_input, outdir, workdir)
        else:
            return handle_colabdesign(job_id, job_input, outdir, workdir)
    except Exception as e:
        print(f"[{job_id}] ERROR: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        for d in [outdir, workdir]:
            if os.path.exists(d):
                shutil.rmtree(d)


runpod.serverless.start({"handler": handler})
