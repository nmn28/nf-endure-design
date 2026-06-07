// Vendored from OVO (Merck © 2025, MIT License)
// Adapted for AWS Batch execution with Docker containers.
// Original: ovo/pipelines/proteinqc/main.nf

nextflow.enable.dsl = 2

include { proteinQCSeqComposition } from './modules/proteinqc-seq-composition'
include { proteinQCDSSP } from './modules/proteinqc-dssp'
include { proteinQCProteinSol } from './modules/proteinqc-proteinsol'

def createCsvBatches(inputPath, batchSize) {
    def csvFile = file(inputPath)
    def lines = csvFile.readLines()
    def header = lines[0]
    def dataLines = lines[1..-1]
    def numRows = dataLines.size()
    def numBatches = Math.ceil(numRows / batchSize).intValue()

    def csvBatches = []
    for (int i = 0; i < numBatches; i++) {
        def startIdx = i * batchSize
        def endIdx = Math.min((i + 1) * batchSize, numRows)
        def batchLines = [header] + dataLines[startIdx..<endIdx]
        def batchFile = file("${workflow.workDir}/csv_batch_${i}.csv")
        batchFile.text = batchLines.join('\n')
        csvBatches << batchFile
    }
    return Channel.fromList(csvBatches)
}

process createInputFolders {
    // ENDURE-PATCH: removed 'executor local'; added Batch directives for AWS Batch execution
    container "${params.docker_repository}ovo-python-structure:v2"
    label 'cpu'
    cpus 1
    memory '1 GB'

    input:
        path inputs
    output:
        path pdb_dir, emit: pdb_dir
    script:
    """
        mkdir pdb_dir
        cp ${inputs} pdb_dir
    """
}

workflow ProteinQC {
  take:
    batches
    tools
    chains
  main:
    for (tool in tools) {
        switch (tool) {
            case 'seq_composition':
                proteinQCSeqComposition(batches, chains)
                break
            case 'dssp':
                proteinQCDSSP(batches, chains)
                break
            case 'proteinsol':
                proteinQCProteinSol(batches, chains)
                break
            default:
                throw new IllegalArgumentException("Tool ${tool} is not supported. Supported: seq_composition, dssp, proteinsol")
        }
    }
}

workflow {
    [
        'tools',
        'input_pdb',
        'chains',
    ].each { param ->
        params[param] = null
        if (!params[param]) {
            throw new IllegalArgumentException("Argument --${param} is required!")
        }
    }
    println "Nextflow version: ${nextflow.version}"
    println "Running ProteinQC for: ${params.input_pdb}"
    def tools = params.tools.split(',')
    def fileBatches
    if (params.input_pdb.endsWith('.csv')) {
      fileBatches = createCsvBatches(params.input_pdb, params.batch_size)
    } else {
      def pdbPaths
      if (params.input_pdb.endsWith('.txt')) {
          pdbPaths = Channel.fromList(file(params.input_pdb).readLines())
      } else if (params.input_pdb.endsWith('.pdb')) {
          pdbPaths = Channel.fromPath(params.input_pdb)
      } else if (params.input_pdb.endsWith('/')) {
          pdbPaths = Channel.fromPath(params.input_pdb + '*.pdb')
      } else {
          throw new IllegalArgumentException("Input file must be a .pdb file, a .csv file with sequences, a .txt file with a list of .pdb files, or a directory ending with /, got: ${params.input_pdb}")
      }
      createInputFolders(pdbPaths.collate(params.batch_size))
      fileBatches = createInputFolders.out
    }
    indexes = Channel.of(1..(1000000.intdiv(params.batch_size)))
    batches = fileBatches.merge(indexes, { pdb_dir, idx -> ["contig1_batch${idx}", pdb_dir] })

    ProteinQC(batches, tools, params.chains)
}
