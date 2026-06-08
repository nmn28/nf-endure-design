# Endure patches against OVO upstream

Vendored from: https://github.com/MSDLLCpapers/ovo (MIT)
Vendoring date: 2026-06-06
Last OVO commit synced: `develop` branch HEAD at time of vendor (2026-06-06)

Grep for `ENDURE-PATCH` to find all patched lines in the repo.

When OVO releases pipeline updates, use this checklist to verify each patch is still semantically valid.

## proteinqc

### pipelines/proteinqc/main.nf

**Line ~32 (createInputFolders process):**
- Removed: `executor 'local'`
- Added: `container`, `label 'cpu'`, `cpus 1`, `memory '1 GB'`
- Reason: `executor 'local'` is incompatible with AWS Batch — causes `AwsSecretsProvider requires the use of the AWS Batch executor` on Seqera head node.

**Line ~33 (container reference):**
- Changed: `container "${params.docker_repository}ovo-python-structure"` → `:v2` tag pinned
- Reason: nf-core best practice — never use `:latest`

### pipelines/proteinqc/nextflow.config

**awsbatch profile (new addition):**
- Added: `process { withLabel: 'cpu' { queue = params.cpu_queue } }`
- Reason: routes Batch tasks to correct Forge queue

**awsbatch profile:**
- Added: `params.docker_repository = '799850497656.dkr.ecr.us-west-2.amazonaws.com/'`
- Reason: ECR Private container registry (IAM auth, no PAT rotation)

### pipelines/proteinqc/modules/proteinqc-seq-composition/main.nf

**Process body:**
- Changed: `python3 ${moduleDir}/bin/seq_composition.py` → `seq_composition.py`
- Reason: `${moduleDir}` resolves to head-node path, inaccessible from AWS Batch container without Wave/shared FS. Officially anti-pattern per Nextflow creator (issue #2240).
- Script is now baked into `/usr/local/bin/` of the ovo-python-structure container.

**Container reference:**
- Pinned to `:v2`

### pipelines/proteinqc/modules/proteinqc-dssp/main.nf
- Same pattern: `python3 ${moduleDir}/bin/dssp.py` → `dssp.py`
- Container pinned to `:v2`

### pipelines/proteinqc/modules/proteinqc-proteinsol/main.nf
- Same pattern: `python3 ${moduleDir}/bin/proteinsol.py` → `proteinsol.py`
- Container pinned to `:v2`

## rfdiffusion-backbone

### pipelines/rfdiffusion-backbone/main.nf

**Line ~9 (RFdiffusion process container):**
- Removed: OVO's dynamic conda/container resolution (`conda { params.getSharedEnv(...) }`, `container "${ workflow.containerEngine ... }"`)
- Added: `container "${params.docker_repository}ovo-rfdiffusion:v1"`
- Reason: Same as proteinqc — pinned ECR container for AWS Batch

**Line ~9 (label):**
- Changed: no label → `label 'gpu'`
- Reason: routes to GPU Forge queue via nextflow.config `withLabel: gpu` block

**Lines ~42-43, ~77-78 (bin script references):**
- Changed: `python3 ${moduleDir}/bin/validate_input.py` → `validate_input.py`
- Changed: `python3 ${moduleDir}/bin/standardize_pdb.py` → `standardize_pdb.py`
- Reason: Same as proteinqc — `${moduleDir}` is head-node path, inaccessible from Batch workers

**Lines ~35-43 (RFdiffusion lib setup):**
- Changed: conditional git clone fallback → simple `ln -s /opt/ ./lib` (RFdiffusion pre-installed in container)
- Reason: Container has RFdiffusion at `/opt/RFdiffusion`, no need for runtime git clone

### pipelines/rfdiffusion-backbone/nextflow.config

**rfdiffusion_models_path:**
- Changed: `"${params.reference_files_dir}/rfdiffusion_models/"` → `"s3://endure-design-outputs/reference-models/rfdiffusion/"`
- Reason: Models staged on S3, not local filesystem

**awsbatch profile (new addition):**
- Added: `process.executor = 'awsbatch'`, `params.docker_repository = '799850497656.dkr.ecr.us-west-2.amazonaws.com/'`
- Reason: Same as proteinqc — ECR Private container registry

**process withLabel: gpu:**
- Added: `queue = params.gpu_queue`
- Reason: Routes GPU tasks to correct Forge GPU queue

## Container ENTRYPOINT Override Pattern (ENDURE-PATCH)

External base images may set ENTRYPOINT to a command (e.g., `python run.py`, NVIDIA JAX wrapper), which conflicts with Nextflow's `.command.run` bash wrapper. Symptom: container fails in ~2 seconds with no `.command.log`, `.command.out`, or `.command.err` written. Zero-second failure with no output is the diagnostic signal.

**Rule:** For every external base image, add `ENTRYPOINT []` as the last line of the Dockerfile unless explicitly verified that the base image leaves ENTRYPOINT unset.

**Confirmed cases requiring override:**
- `rosettacommons/ligandmpnn` (sets `python run.py`) — caught in Run #5
- `nvcr.io/nvidia/jax:24.04-py3` (sets NVIDIA wrapper) — caught in Run #6

**Future containers to audit before vendoring:**
- `ovo-boltz` (if based on huggingface/Boltz official image)
- `ovo-huggingface-transformers` (if based on official HF image)
- `ovo-esm` (if based on official Facebook AI image)
- `ovo-proteinmpnn-fastrelax` (if uses PyRosetta or ProteinMPNN base)

**Verification command:**
```bash
docker inspect --format='{{json .Config.Entrypoint}}' <image>
```

If output is anything other than `null` or `[]`, add `ENTRYPOINT []` to the Dockerfile.

## rfdiffusion-end-to-end (E2E pipeline)

### E2E Run History — Bugs Found and Patched

| Run | Bug | Fix |
|-----|-----|-----|
| #1 (`18Ea4NM7rxFjhJ`) | Config eval order: `params.gpu_queue` null in `withLabel` blocks | Move queue params to params-file, not profile |
| #2 (`2sGQYlYAOxCU4k`) | Container shebang missing on `validate_input.py` | Rebuild `ovo-rfdiffusion:v1` with shebang-fixed scripts |
| #3 (`1NB3ANUFTudlIq`) | `diffuser.T=2` < 15 assertion in RFdiffusion | Changed to `diffuser.T=25` |
| #4 (`4QyTdyPHD8HUte`) | DSL2 `bin/` not staged for `include`d modules | Created unified `bin/` in E2E pipeline root (15 scripts) |
| #5 (`4M1QFotg9Soghe`) | RosettaCommons LigandMPNN ENTRYPOINT conflict | Added `ENTRYPOINT []` to LigandMPNN Dockerfile |
| #6 (`2m3z2X2Dii0bUv`) | NVIDIA JAX ColabDesign ENTRYPOINT conflict | Added `ENTRYPOINT []` to ColabDesign Dockerfile |

### pipelines/rfdiffusion-end-to-end/nextflow.config

**ECR registry:**
- Changed: `339712971032.dkr.ecr.us-east-1.amazonaws.com/` → `799850497656.dkr.ecr.us-west-2.amazonaws.com/`
- Reason: Correct AWS account and region

**S3 model paths:**
- Changed: `s3://endure-design-models/` → `s3://endure-design-outputs/reference-models/`
- Reason: Models staged on our S3 bucket, not OVO's

**Queue params:**
- Changed: Queue values from awsbatch profile → top-level params (set via params-file)
- Reason: Nextflow evaluates `process.withLabel` before profile params merge

### pipelines/rfdiffusion-end-to-end/bin/ (unified)

Created unified bin/ directory containing ALL scripts from ALL sub-pipelines (15 scripts). Required because Nextflow DSL2 only auto-stages `bin/` from the main script's directory, not from `include`d modules.

### pipelines/refolding/main.nf

**ESMFold and Boltz includes:**
- Commented out `include { ESMFold }` and `include { BoltzRefolding }`
- Replaced workflow blocks with `throw new IllegalArgumentException(...)`
- Reason: ESMFold and Boltz pipelines not yet vendored; include statements would cause compile-time failure

**AlphaFold include path:**
- Changed: `'../alphafold-initial-guess'` (relative path, ENDURE-PATCH)
- Reason: OVO uses absolute HealthOmics paths

## Future pipeline patches (predicted)

These pipelines have known `executor 'local'` issues we'll need to patch when vendoring:

- **refolding/main.nf** — Line ~6: `createDirs` process. Apply identical patch.
- **rfdiffusion-end-to-end/main.nf** — Line ~172: `CreateBackboneFolders` process. Line ~187: `UnpackBackbones` process. Same pattern, two occurrences.
- **protein-clustering/module/createInputFolders.nf** — Line ~4: `createInputFolders` process. Same pattern.

All will need the same 6-pattern treatment used for proteinqc:
1. Remove `executor 'local'`, add Batch directives
2. Pin container tags (`:vN`)
3. Use ECR Private registry
4. Bake bin scripts into containers
5. Install `procps` in every Dockerfile
6. Add `ENTRYPOINT []` if base image sets an entrypoint

## Post-launch optimizations (deferred)

### AF2 weights extraction

The AF2 stage extracts the 5.2GB `alphafold_params_2022-12-06.tar` at runtime in every task via `tar -xf`. This adds 3-5 min per AF2 task wall-clock.

Optimization: pre-extract the tar on S3 to `s3://endure-design-outputs/reference-models/alphafold-extracted/`, mount the directory directly. Saves 3-5 min per AF2 task. Estimated effort: S (one-time S3 op + config path update).

Defer until: AF2 task count per run is high enough that 3-5 min × N tasks matters (currently 1 design per run).
