// Vendored from OVO (Merck © 2025, MIT License)

nextflow.enable.dsl = 2

process proteinQCSeqComposition {
  container "${params.docker_repository}ovo-python-structure:v2"
  label 'seq_composition'
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

  # ENDURE-PATCH: bare script name (baked into container at /usr/local/bin/)
  seq_composition.py \
    ${pdb_dir} \
	"${batch_dir}"/seq_composition.csv \
	--chains "${chains}"
  """
}

workflow {
  proteinQCSeqComposition([params.output_dir, params.pdb_dir], params.chains)
}
