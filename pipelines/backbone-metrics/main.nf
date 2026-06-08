// Vendored from OVO (Merck (c) 2025, MIT License)
nextflow.enable.dsl = 2

process BackboneMetrics {
  container "${params.docker_repository}ovo-python-structure:v2"  // ENDURE-PATCH: static container
  label "cpu"  // ENDURE-PATCH: label
  cpus 1
  memory "4 GB"
  publishDir { params.publish_dir }
  input:
    tuple val(batch_dir), path(pdb_dir)
    val hotspot
    val cyclic
    val filters
  output:
    tuple val (batch_dir), path ("${batch_dir}/backbones_filtered/"), emit: filtered_pdb_dir
    path "${batch_dir}/backbone_metrics.csv", emit: output_csv
  script:
  """
  set -euxo pipefail

  mkdir "${batch_dir}"

  backbone_metrics.py \
    ${pdb_dir} \
    "${batch_dir}/backbone_metrics.csv" \
    ${hotspot ? "--hotspot ${hotspot}" : ""} \
    ${cyclic ? "--cyclic" : ""} \
    --filtered-output "${batch_dir}/backbones_filtered" \
    --filters "${filters}"
  """
}

workflow {
    def hotspot = params.hotspot ?: ''
    BackboneMetrics(
      [params.output_dir, params.pdb_dir],
      hotspot,
      params.cyclic,
      params.filters
    )
}
