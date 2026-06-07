# Endure patches against OVO upstream

Grep for `ENDURE-PATCH` to find all patched lines in the repo.

When OVO releases pipeline updates, use this checklist to verify each patch is still semantically valid.

## proteinqc/main.nf
- Line ~32: removed `executor 'local'` from `createInputFolders`. Added `container`, `label 'cpu'`, `cpus 1`, `memory '1 GB'`. Reason: `executor 'local'` is incompatible with AWS Batch — causes `AwsSecretsProvider requires the use of the AWS Batch executor` on Seqera head node.

## (future) refolding/main.nf
- Line ~6: same pattern, `createDirs` process. Apply identical patch when vendored.

## (future) rfdiffusion-end-to-end/main.nf
- Line ~172: `CreateBackboneFolders` process. Same pattern.
- Line ~187: `UnpackBackbones` process. Same pattern.

## (future) protein-clustering/module/createInputFolders.nf
- Line ~4: `createInputFolders` process. Same pattern.
