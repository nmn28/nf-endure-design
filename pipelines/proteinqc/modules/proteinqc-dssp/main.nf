// Vendored from OVO (Merck © 2025, MIT License)

nextflow.enable.dsl = 2

process proteinQCDSSP {
  container "${params.docker_repository}ovo-dssp"
  label 'dssp'
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

  python3 ${moduleDir}/bin/dssp.py \
    ${pdb_dir} \
	"${batch_dir}"/dssp.csv \
	--chains "${chains}"
  """
}

workflow {
  proteinQCDSSP([params.output_dir, params.pdb_dir], params.chains)
}
