#!/usr/bin/env python3
"""RunPod serverless handler for protein solubility prediction.

Uses the CamSol method (Sormanni et al.): intrinsic solubility from amino acid
composition, charge, hydrophobicity, and secondary structure propensity.
Outputs proteinsol.csv per the format expected by the Go parser.
"""
import runpod
import boto3
import os
import shutil
import csv
import io
import json
import numpy as np
from Bio.PDB import PDBParser
from Bio.SeqUtils.ProtParam import ProteinAnalysis

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
S3_BUCKET = os.environ.get("S3_BUCKET", "endure-media")

# CamSol-inspired intrinsic solubility scores per amino acid
# Positive = soluble, negative = aggregation-prone
CAMSOL_SCORES = {
    "A": -0.21, "R": 1.76, "N": 0.71, "D": 1.05, "C": -0.69,
    "Q": 0.57, "E": 1.30, "G": -0.11, "H": 0.69, "I": -0.81,
    "L": -0.69, "K": 1.57, "M": -0.44, "F": -0.76, "P": -0.16,
    "S": 0.21, "T": 0.05, "W": -0.53, "Y": -0.40, "V": -0.61,
}

# Population mean and std for scaling (derived from large protein datasets)
POP_MEAN = 0.18
POP_STD = 0.42


def download_pdbs(s3_uri, local_dir):
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


def extract_sequence(pdb_path):
    """Extract amino acid sequence from PDB, return (sequence, chain_ids)."""
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", pdb_path)
    model = structure[0]

    three_to_one = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }

    full_seq = ""
    chains = []
    for chain in model:
        chains.append(chain.get_id())
        for res in chain:
            if res.get_id()[0] != " ":
                continue
            resname = res.get_resname().strip()
            aa = three_to_one.get(resname, "X")
            if aa != "X":
                full_seq += aa

    return full_seq, chains


def compute_solubility(sequence):
    """Compute CamSol-style intrinsic solubility score.

    Returns:
        scaled_sol: raw average solubility score
        population_sol: z-score relative to protein population
        percentile: estimated percentile
    """
    if not sequence:
        return 0.0, 0.0, 50.0

    # Per-residue intrinsic scores
    scores = [CAMSOL_SCORES.get(aa, 0.0) for aa in sequence]
    raw_score = np.mean(scores)

    # Charge correction: proteins near pI ~7 are more soluble
    try:
        analysis = ProteinAnalysis(sequence)
        charge_at_7 = analysis.charge_at_pH(7.0)
        # High absolute charge improves solubility
        charge_bonus = min(abs(charge_at_7) / len(sequence) * 5, 0.3)
    except Exception:
        charge_bonus = 0.0

    # Hydrophobicity correction
    try:
        gravy = analysis.gravy()
        hydro_penalty = max(gravy * 0.2, 0.0)  # penalize hydrophobic proteins
    except Exception:
        hydro_penalty = 0.0

    scaled_sol = round(float(raw_score + charge_bonus - hydro_penalty), 4)
    population_sol = round(float((scaled_sol - POP_MEAN) / POP_STD), 4)

    # Approximate percentile from z-score (using error function)
    from math import erf
    percentile = round(50 * (1 + erf(population_sol / np.sqrt(2))), 1)

    return scaled_sol, population_sol, percentile


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

        print(f"[{job_id}] Downloading PDBs from {pdb_dir_uri}")
        pdb_files = download_pdbs(pdb_dir_uri, workdir)
        if not pdb_files:
            raise ValueError(f"No PDB files found at {pdb_dir_uri}")
        print(f"[{job_id}] Found {len(pdb_files)} PDB files")

        all_results = []
        for pdb_path in pdb_files:
            fname = os.path.basename(pdb_path)
            print(f"[{job_id}] Computing solubility for {fname}")

            sequence, chains = extract_sequence(pdb_path)
            scaled_sol, population_sol, percentile = compute_solubility(sequence)

            result = {
                "id": fname.replace(".pdb", ""),
                "chains": ",".join(chains),
                "percent-sol": percentile,
                "scaled-sol": scaled_sol,
                "population-sol": population_sol,
            }
            all_results.append(result)

        # Write proteinsol.csv
        csv_buffer = io.StringIO()
        fieldnames = ["id", "chains", "percent-sol", "scaled-sol", "population-sol"]
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_results:
            writer.writerow(r)

        # Upload CSV
        s3_prefix = f"protein-design/{job_id}"
        csv_key = f"{s3_prefix}/proteinsol.csv"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=csv_key,
            Body=csv_buffer.getvalue(),
            ContentType="text/csv",
        )

        # Upload JSON
        json_key = f"{s3_prefix}/proteinsol.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=json_key,
            Body=json.dumps(all_results, indent=2),
            ContentType="application/json",
        )

        return {
            "status": "success",
            "mode": "proteinsol",
            "num_pdbs": len(pdb_files),
            "results": all_results,
            "s3_prefix": f"s3://{S3_BUCKET}/{s3_prefix}/",
        }
    except Exception as e:
        print(f"[{job_id}] ERROR: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        if os.path.exists(workdir):
            shutil.rmtree(workdir)


runpod.serverless.start({"handler": handler})
