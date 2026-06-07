# Endure patches against OVO upstream

Grep for `ENDURE-PATCH` to find all patched lines in the repo.

When OVO releases pipeline updates, use this checklist to verify each patch is still semantically valid.

## proteinqc/main.nf
- Line ~32: removed `executor 'local'` from `createInputFolders`. Added `container`, `label 'cpu'`, `cpus 1`, `memory '1 GB'`. Reason: `executor 'local'` is incompatible with AWS Batch — causes `AwsSecretsProvider requires the use of the AWS Batch executor` on Seqera head node.

## proteinqc/modules/proteinqc-seq-composition/main.nf
- Replaced `python3 ${moduleDir}/bin/seq_composition.py` with bare `seq_composition.py`. Script baked into container at `/usr/local/bin/`. Reason: `${moduleDir}` resolves to head-node path, inaccessible from AWS Batch container without Wave/shared FS.

## proteinqc/modules/proteinqc-dssp/main.nf
- Same pattern: `python3 ${moduleDir}/bin/dssp.py` → `dssp.py`.

## proteinqc/modules/proteinqc-proteinsol/main.nf
- Same pattern: `python3 ${moduleDir}/bin/proteinsol.py` → `proteinsol.py`.

## (future) refolding/main.nf
- Line ~6: same pattern, `createDirs` process. Apply identical patch when vendored.

## (future) rfdiffusion-end-to-end/main.nf
- Line ~172: `CreateBackboneFolders` process. Same pattern.
- Line ~187: `UnpackBackbones` process. Same pattern.

## (future) protein-clustering/module/createInputFolders.nf
- Line ~4: `createInputFolders` process. Same pattern.
