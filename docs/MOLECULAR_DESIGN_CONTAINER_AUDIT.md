# Molecular Design Container Audit

**Date:** 2026-06-08
**Audited on:** EC2 i-0c44876e3655c9b7f (us-west-2)
**Method:** Pull → inspect → delete for each image

## Summary Table

| Image | Size | Base Framework | Key Tool | Weights Baked | RunPod Handler | OVO Equivalent |
|-------|------|----------------|----------|---------------|----------------|----------------|
| endure-mosaic:latest | 13.4 GB | CUDA 12.6 / Python 3.11 | Boltz 2.2.1 | No (runtime download) | Yes | None — unique |
| endure-md:latest | 3.8 GB | CUDA 12.6 / Python 3.12 | OpenMM (inferred) | No | Yes | None — unique |
| endure-smallmol:latest | 15.8 GB | CUDA 12.6 / Python 3.12 | RDKit + Chai (inferred) | No | Yes | None — unique |
| endure-evedesign:latest | 8.5 GB | CUDA 12.6 / Python 3.12 | ESM + Biopython | No | Yes | None — unique |
| ovo-rfdiffusion:v2 | 19.8 GB | PyTorch 24.07 (CUDA 12.6) | RFdiffusion | Yes (Base_ckpt.pt, Complex_base_ckpt.pt) | Yes | NEW — from OVO pipeline |
| ovo-ligandmpnn:v2 | 19.2 GB | PyTorch 24.07 (CUDA 12.6) | LigandMPNN | Yes (get_model_params.sh) | Yes | NEW — from OVO pipeline |
| ovo-colabdesign:v2 | 14.9 GB | JAX 24.04 (CUDA) | ColabDesign + AF2 | Yes (15 AF2 param files) | Yes | NEW — from OVO pipeline |

## Key Findings

### 1. No Redundancy Between endure-* and ovo-* Containers

The 4 existing `endure-*` containers and 3 new `ovo-*` containers serve completely different purposes:

| Container | Purpose | Pipeline Stage |
|-----------|---------|---------------|
| endure-mosaic | Boltz structure prediction (PDB → structure) | Structure prediction |
| endure-md | Molecular dynamics simulation | Simulation |
| endure-smallmol | Small molecule design/docking | Drug design |
| endure-evedesign | Evolutionary design (ESM-based) | Sequence analysis |
| ovo-rfdiffusion | **Backbone generation** (de novo protein design) | OVO Stage 1 |
| ovo-ligandmpnn | **Sequence design** (ligand-aware) | OVO Stage 2 |
| ovo-colabdesign | **Structure validation** (AF2 initial guess) | OVO Stage 3 |

**Conclusion: Zero overlap.** No container can substitute for another. All 7 are needed.

### 2. Architecture Differences

**endure-* containers:**
- ENTRYPOINT: `/opt/nvidia/nvidia_entrypoint.sh` (NGC base image default — prints CUDA banner)
- All tools in `/opt/env/` virtualenv
- Monolithic handler.py + run_*.py pattern
- No custom bin scripts in /usr/local/bin/
- No model weights baked in (download at runtime via S3)

**ovo-* containers:**
- ENTRYPOINT: `null` (explicitly cleared for RunPod compatibility)
- Tools installed globally via pip
- handler.py delegates to bin scripts (validate_input.py, prepare_json.py, af2_initial_guess_*.py)
- Model weights baked in during Docker build for fast cold starts

### 3. Weight Baking Details

| Container | Weights | Size | Source |
|-----------|---------|------|--------|
| ovo-rfdiffusion | Base_ckpt.pt, Complex_base_ckpt.pt | ~922 MB | s3://endure-design-outputs/reference-models/rfdiffusion/ |
| ovo-ligandmpnn | 6 model param files (ligandmpnn, proteinmpnn, membrane, soluble, sc) | ~200 MB | get_model_params.sh (GitHub release) |
| ovo-colabdesign | 15 AF2 param .npz files (5 models × 3 variants) | ~5.2 GB compressed, ~15 GB extracted | s3://endure-design-outputs/reference-models/alphafold/ |

### 4. endure-* Container Details

#### endure-mosaic (Boltz 2.2.1)
- **Purpose:** Structure prediction using Boltz
- **Key packages:** boltz 2.2.1, biopython, pytorch (in base)
- **Handler:** `/opt/handler.py` + `/opt/run_mosaic.py` (21.6 KB)
- **Go backend:** `RUNPOD_MOSAIC_ENDPOINT_ID` → `StartMosaicJob()`

#### endure-md (Molecular Dynamics)
- **Purpose:** Molecular dynamics simulations
- **Key packages:** OpenMM (inferred from run_md.py, 25 KB)
- **Handler:** `/opt/handler.py` + `/opt/run_md.py`
- **Go backend:** `RUNPOD_MD_ENDPOINT_ID` → `StartMDJob()`

#### endure-smallmol (Small Molecule Design)
- **Purpose:** Small molecule design, docking, drug-like property prediction
- **Key packages:** RDKit, Chai (inferred), scipy, matplotlib
- **Handler:** `/opt/handler.py` + `/opt/run_smallmol.py` (18 KB)
- **Go backend:** `RUNPOD_SMALLMOL_ENDPOINT_ID` → `StartSmallmolJob()`

#### endure-evedesign (Evolutionary Design)
- **Purpose:** Evolutionary sequence design using ESM models
- **Key packages:** ESM, biopython, scipy
- **Handler:** `/opt/handler.py` (11.3 KB) + `/opt/run_evedesign.py` (46.5 KB — largest handler)
- **Go backend:** `RUNPOD_EVEDESIGN_ENDPOINT_ID` → `StartEvedesignJob()`

### 5. Missing OVO CPU Containers (Not on Docker Hub)

The OVO Nextflow pipeline also uses 3 CPU utility containers that were NOT found on Docker Hub:
- `ovo-python-structure` — PDB parsing/metrics
- `ovo-dssp` — Secondary structure assignment (DSSP)
- `ovo-proteinsol` — Solubility prediction (ProteinSol)

These run as Nextflow processes on AWS Batch (CPU), not as RunPod serverless endpoints. They are **not needed** for the RunPod migration since their functionality is handled by the bin scripts baked into the GPU containers.

### 6. Go Backend Routing (Current State)

```
protein_tools.go switch(jobType):
  "mosaic"    → RUNPOD_MOSAIC_ENDPOINT_ID    → StartMosaicJob()
  "md"        → RUNPOD_MD_ENDPOINT_ID        → StartMDJob()
  "smallmol"  → RUNPOD_SMALLMOL_ENDPOINT_ID  → StartSmallmolJob()
  "evedesign" → RUNPOD_EVEDESIGN_ENDPOINT_ID → StartEvedesignJob()

  // NOT YET WIRED:
  "ovo_rfdiffusion"  → RUNPOD_OVO_RFDIFFUSION_ENDPOINT_ID  → StartOvoRfdiffusionJob()
  "ovo_ligandmpnn"   → RUNPOD_OVO_LIGANDMPNN_ENDPOINT_ID   → StartOvoLigandmpnnJob()
  "ovo_colabdesign"  → RUNPOD_OVO_COLABDESIGN_ENDPOINT_ID  → StartOvoColabdesignJob()
```

## Recommendations

1. **No containers to deprecate or merge** — all 7 serve distinct purposes
2. **Proceed with Go backend wiring** — add 3 new endpoint config vars + Start*Job methods
3. **Consider baking weights into endure-* containers** — currently they download at runtime, which slows cold starts. The ovo-* pattern (bake during build) is superior.
4. **Fix ENTRYPOINT on endure-* containers** — they inherit NGC's entrypoint which prints a CUDA banner to stdout. Adding `ENTRYPOINT []` would be cleaner for RunPod.
