// Vendored from OVO (Merck © 2025, MIT License)

nextflow.enable.dsl = 2

process proteinQCProteinSol {
  container "${params.docker_repository}ovo-proteinsol:v2"
  label 'proteinsol'
  cpus 1
  memory "1 GB"
  publishDir { params.publish_dir ?: 'results' }
  input:
    tuple val(batch_dir), path(pdb_dir)
    val chains
  output:
    path "${batch_dir}/*", emit: output_csv
  script:
  """
  set -euxo pipefail

  mkdir "${batch_dir}"

  # ProteinSol Perl software is baked into the container at
  # /opt/protein-sol-sequence-prediction-software
  # The script looks there first; no runtime download needed.
  if [[ ! -d /opt/protein-sol-sequence-prediction-software ]]; then
      echo "ERROR: ProteinSol software not found in container" >&2
      exit 1
  fi
  ln -s /opt/ ./lib

  # ENDURE-PATCH: bare script name (baked into container at /usr/local/bin/)
  proteinsol.py \
    ${pdb_dir} \
    "${batch_dir}/proteinsol.csv" \
    --chains "${chains}"

  # remove lib link to avoid nextflow access issues when scanning output directory
  rm lib
  """
}

workflow {
  proteinQCProteinSol([params.output_dir, params.pdb_dir], params.chains)
}
