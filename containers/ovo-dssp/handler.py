#!/usr/bin/env python3
"""RunPod serverless handler for DSSP secondary structure + Ramachandran analysis.

For each PDB: runs DSSP, computes SS percentages, asphericity, Rg, Ramachandran.
Outputs dssp.csv per the format expected by the Go parser.
"""
import runpod
import boto3
import os
import shutil
import csv
import io
import json
import math
import subprocess
import numpy as np
from Bio.PDB import PDBParser

s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
S3_BUCKET = os.environ.get("S3_BUCKET", "endure-media")


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


def run_dssp(pdb_path):
    """Run mkdssp on a PDB file and return the DSSP output text."""
    try:
        result = subprocess.run(
            ["mkdssp", "-i", pdb_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            # Try alternative binary name
            result = subprocess.run(
                ["dssp", "-i", pdb_path],
                capture_output=True, text=True, timeout=60
            )
        return result.stdout if result.returncode == 0 else None
    except FileNotFoundError:
        return None


def parse_dssp_output(dssp_text):
    """Parse DSSP output text to extract per-residue SS assignments."""
    ss_assignments = []
    in_residues = False
    for line in dssp_text.split("\n"):
        if line.strip().startswith("#  RESIDUE"):
            in_residues = True
            continue
        if in_residues and len(line) >= 17:
            chain = line[11]
            ss = line[16]
            if ss == " ":
                ss = "-"
            ss_assignments.append({"chain": chain, "ss": ss})
    return ss_assignments


def compute_ramachandran(pdb_path):
    """Compute percentage of residues in allowed Ramachandran regions."""
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", pdb_path)
    model = structure[0]

    allowed = 0
    total = 0
    for chain in model:
        residues = [r for r in chain if r.get_id()[0] == " "]
        for i in range(1, len(residues) - 1):
            try:
                # Get phi/psi angles
                n_prev = residues[i - 1]["C"].get_vector()
                n_curr = residues[i]["N"].get_vector()
                ca = residues[i]["CA"].get_vector()
                c_curr = residues[i]["C"].get_vector()
                n_next = residues[i + 1]["N"].get_vector()

                phi = calc_dihedral(n_prev, n_curr, ca, c_curr)
                psi = calc_dihedral(n_curr, ca, c_curr, n_next)

                phi_deg = math.degrees(phi)
                psi_deg = math.degrees(psi)
                total += 1

                # Generous allowed regions (covers ~98% of good structures)
                if is_ramachandran_allowed(phi_deg, psi_deg):
                    allowed += 1
            except (KeyError, Exception):
                continue

    return (allowed / total * 100) if total > 0 else 0.0


def calc_dihedral(v1, v2, v3, v4):
    """Calculate dihedral angle between 4 vectors."""
    b1 = v2 - v1
    b2 = v3 - v2
    b3 = v4 - v3
    n1 = b1 ** b2  # cross product (Bio.PDB vectors)
    n2 = b2 ** b3
    m1 = n1 ** (b2.normalized())
    x = n1 * n2
    y = m1 * n2
    return -math.atan2(y, x)


def is_ramachandran_allowed(phi, psi):
    """Check if phi/psi falls in generously allowed Ramachandran regions."""
    # General allowed: alpha-helix, beta-sheet, left-handed helix, polyproline II
    if -180 <= phi <= -20 and -80 <= psi <= 180:
        return True
    if -180 <= phi <= -20 and -180 <= psi <= -120:
        return True
    if 20 <= phi <= 100 and -20 <= psi <= 80:
        return True  # left-handed helix
    return False


def compute_asphericity(ca_coords):
    """Asphericity from gyration tensor eigenvalues."""
    centroid = ca_coords.mean(axis=0)
    centered = ca_coords - centroid
    gyr = np.dot(centered.T, centered) / len(centered)
    eigenvalues = np.sort(np.linalg.eigvalsh(gyr))[::-1]
    l_sum = eigenvalues.sum()
    if l_sum == 0:
        return 0.0
    asph = 1.5 * np.sum((eigenvalues - l_sum / 3) ** 2) / (l_sum ** 2)
    return round(float(asph), 4)


def compute_rg(ca_coords):
    """Radius of gyration."""
    centroid = ca_coords.mean(axis=0)
    return round(float(np.sqrt(np.mean(np.sum((ca_coords - centroid) ** 2, axis=1)))), 2)


def analyze_pdb(pdb_path):
    """Full DSSP analysis for one PDB file."""
    fname = os.path.basename(pdb_path)

    # Run DSSP
    dssp_text = run_dssp(pdb_path)
    ss_string = ""
    ss_counts = {"H": 0, "E": 0, "G": 0, "T": 0, "-": 0}

    if dssp_text:
        assignments = parse_dssp_output(dssp_text)
        ss_string = "".join(a["ss"] for a in assignments)
        total = len(assignments)
        for a in assignments:
            ss = a["ss"]
            if ss in ss_counts:
                ss_counts[ss] += 1
            else:
                ss_counts["-"] += 1
    else:
        total = 0

    # Parse structure for Rg, asphericity
    parser = PDBParser(QUIET=True)
    structure = parser.get_structure("s", pdb_path)
    model = structure[0]

    chain_id = "A"
    ca_coords = []
    for chain in model:
        chain_id = chain.get_id()
        for res in chain:
            if "CA" in res:
                ca_coords.append(res["CA"].get_vector().get_array())
        break  # first chain only for now

    ca_arr = np.array(ca_coords) if ca_coords else np.array([]).reshape(0, 3)
    rg = compute_rg(ca_arr) if len(ca_arr) > 0 else 0.0
    asphericity = compute_asphericity(ca_arr) if len(ca_arr) > 2 else 0.0
    rama_pct = compute_ramachandran(pdb_path)

    return {
        "id": fname.replace(".pdb", ""),
        "chain": chain_id,
        "ss": ss_string,
        "helix_perc": round(ss_counts["H"] / total * 100, 1) if total > 0 else 0.0,
        "sheet_perc": round(ss_counts["E"] / total * 100, 1) if total > 0 else 0.0,
        "helix_310_perc": round(ss_counts["G"] / total * 100, 1) if total > 0 else 0.0,
        "turn_perc": round(ss_counts["T"] / total * 100, 1) if total > 0 else 0.0,
        "coil_perc": round(ss_counts["-"] / total * 100, 1) if total > 0 else 0.0,
        "asphericity": asphericity,
        "radius_of_gyration": rg,
        "ramachandran_allowed_perc": round(rama_pct, 1),
    }


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
            print(f"[{job_id}] Analyzing {os.path.basename(pdb_path)}")
            result = analyze_pdb(pdb_path)
            all_results.append(result)

        # Write dssp.csv
        csv_buffer = io.StringIO()
        fieldnames = [
            "id", "chain", "ss", "% H", "% E", "% G", "% T", "% -",
            "asphericity", "radius_of_gyration", "ramachandran_allowed_perc"
        ]
        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_results:
            writer.writerow({
                "id": r["id"],
                "chain": r["chain"],
                "ss": r["ss"],
                "% H": r["helix_perc"],
                "% E": r["sheet_perc"],
                "% G": r["helix_310_perc"],
                "% T": r["turn_perc"],
                "% -": r["coil_perc"],
                "asphericity": r["asphericity"],
                "radius_of_gyration": r["radius_of_gyration"],
                "ramachandran_allowed_perc": r["ramachandran_allowed_perc"],
            })

        # Upload CSV
        s3_prefix = f"protein-design/{job_id}"
        csv_key = f"{s3_prefix}/dssp.csv"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=csv_key,
            Body=csv_buffer.getvalue(),
            ContentType="text/csv",
        )

        # Upload JSON too for easy API consumption
        json_key = f"{s3_prefix}/dssp.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=json_key,
            Body=json.dumps(all_results, indent=2),
            ContentType="application/json",
        )

        return {
            "status": "success",
            "mode": "dssp",
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
