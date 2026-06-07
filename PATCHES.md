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

## Future pipeline patches (predicted)

These pipelines have known `executor 'local'` issues we'll need to patch when vendoring:

- **refolding/main.nf** — Line ~6: `createDirs` process. Apply identical patch.
- **rfdiffusion-end-to-end/main.nf** — Line ~172: `CreateBackboneFolders` process. Line ~187: `UnpackBackbones` process. Same pattern, two occurrences.
- **protein-clustering/module/createInputFolders.nf** — Line ~4: `createInputFolders` process. Same pattern.

All will need the same 5-pattern treatment used for proteinqc:
1. Remove `executor 'local'`, add Batch directives
2. Pin container tags (`:vN`)
3. Use ECR Private registry
4. Bake bin scripts into containers
5. Install `procps` in every Dockerfile
