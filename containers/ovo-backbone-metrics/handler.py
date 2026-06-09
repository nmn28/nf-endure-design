#!/usr/bin/env python3
"""RunPod serverless handler for backbone quality metrics (CPU-only).

Computes per-PDB:
  - Radius of gyration (Å)
  - Contact order (relative)
  - Number of CA-CA steric clashes (< 3.0 Å)
  - Backbone bond angle deviations
  - Chain lengths
"""
import runpod
import boto3
import os
import shutil
import json
import numpy as np
from Bio.PDB import PDBParser
from scipy.spatial.distance import pdist, squareform

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
S3_BUCKET = os.environ.get("S3_BUCKET", "endure-protein-results")

CLASH_THRESHOLD = 3.0  # Å — CA-CA distance below this is a clash
CONTACT_THRESHOLD = 8.0  # Å — CA-CA distance below this counts as contact


def download_s3_dir(s3_uri, local_dir):
    """Download all PDB files from s3://bucket/prefix/ to local_dir."""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket, prefix = parts[0], parts[1].rstrip("/") + "/"
    paginator = s3.get_paginator("list_objects_v2")
    downloaded = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".pdb"):
                fname = os.path.basename(key)
                local_path = os.path.join(local_dir, fname)
                s3.download_file(bucket, key, local_path)
                downloaded.append(local_path)
    return downloaded


def compute_metrics(pdb_path):
    """Compute backbone metrics for a single PDB file."""
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", pdb_path)
    model = structure[0]

    results = {}
    for chain in model:
        chain_id = chain.get_id()
        ca_atoms = []
        for res in chain:
            if "CA" in res:
                ca_atoms.append(res["CA"].get_vector().get_array())

        if len(ca_atoms) < 3:
            continue

        ca_coords = np.array(ca_atoms)
        n_res = len(ca_coords)

        # Radius of gyration
        centroid = ca_coords.mean(axis=0)
        rog = np.sqrt(np.mean(np.sum((ca_coords - centroid) ** 2, axis=1)))

        # Contact order (relative)
        dists = squareform(pdist(ca_coords))
        contact_sum = 0
        contact_count = 0
        for i in range(n_res):
            for j in range(i + 4, n_res):  # skip neighbors
                if dists[i, j] < CONTACT_THRESHOLD:
                    contact_sum += abs(j - i)
                    contact_count += 1
        rel_contact_order = (contact_sum / (contact_count * n_res)) if contact_count > 0 else 0.0

        # Steric clashes (CA-CA < 3.0 Å, excluding sequential neighbors)
        n_clashes = 0
        for i in range(n_res):
            for j in range(i + 3, n_res):
                if dists[i, j] < CLASH_THRESHOLD:
                    n_clashes += 1

        results[chain_id] = {
            "chain": chain_id,
            "length": n_res,
            "radius_of_gyration": round(float(rog), 2),
            "relative_contact_order": round(float(rel_contact_order), 4),
            "num_clashes": int(n_clashes),
            "passed": n_clashes == 0,
        }

    return results


def handler(job):
    job_input = job["input"]
    job_id = job["id"]
    workdir = f"/tmp/work/{job_id}"

    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    os.makedirs(workdir, exist_ok=True)

    try:
        pdb_dir_uri = job_input.get("pdb_dir_uri") or job_input.get("input_pdb")
        if not pdb_dir_uri:
            raise ValueError("pdb_dir_uri or input_pdb is required")

        clash_threshold = job_input.get("clash_threshold", CLASH_THRESHOLD)

        # Download PDBs
        print(f"[{job_id}] Downloading PDBs from {pdb_dir_uri}")
        pdb_files = download_s3_dir(pdb_dir_uri, workdir)
        if not pdb_files:
            raise ValueError(f"No PDB files found at {pdb_dir_uri}")
        print(f"[{job_id}] Found {len(pdb_files)} PDB files")

        # Compute metrics for each
        all_metrics = {}
        passed = 0
        failed = 0
        for pdb_path in pdb_files:
            fname = os.path.basename(pdb_path)
            metrics = compute_metrics(pdb_path)
            all_metrics[fname] = metrics
            # A design passes if ALL chains pass
            design_passes = all(c["passed"] for c in metrics.values())
            if design_passes:
                passed += 1
            else:
                failed += 1

        # Upload results JSON to S3
        s3_prefix = f"protein-design/{job_id}"
        results_key = f"{s3_prefix}/backbone_metrics.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=results_key,
            Body=json.dumps(all_metrics, indent=2),
            ContentType="application/json",
        )

        return {
            "status": "success",
            "mode": "backbone_metrics",
            "num_pdbs": len(pdb_files),
            "passed": passed,
            "failed": failed,
            "metrics": all_metrics,
            "s3_prefix": f"s3://{S3_BUCKET}/{s3_prefix}/",
        }
    except Exception as e:
        print(f"[{job_id}] ERROR: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        if os.path.exists(workdir):
            shutil.rmtree(workdir)


runpod.serverless.start({"handler": handler})
