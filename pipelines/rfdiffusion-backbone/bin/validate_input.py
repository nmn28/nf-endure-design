import argparse
import os
import glob

from biopandas.pdb import PandasPdb


def is_designed(contig_chain_or_segment: str) -> bool:
    """
    Check if the contig chain is fixed or not.
    :param contig_chain: str, the contig chain string
    :return: bool, True if designed, False if is fixed
    """
    for segment in contig_chain_or_segment.removesuffix("/0").split("/"):
        if not segment[0].isalpha():
            return True
    return False


def get_insertion_codes(pdb_path: str, contig_chains: list[str]) -> list[str]:
    """
    Get the insertion codes from the PDB files.
    :Args:
        pdb_path: str, path to the PDB file
        contig_chains: list[str], list of contig chains
    :return: A set of insertion codes.
    """

    ppdb = PandasPdb().read_pdb(pdb_path)
    chains = ppdb.df["ATOM"]["chain_id"].unique().tolist()

    residues_in_fixed_segments_by_chain = {}
    for contig_chain in contig_chains:
        for segment in contig_chain.split("/"):
            # Check if segment is designed
            if is_designed(segment):
                continue

            chain = segment[0]

            assert chain in chains, f"Chain {chain} not found in PDB file {pdb_path}. Chains found: {chains}"
            start, end = map(int, segment[1:].split("-"))

            residues_in_fixed_segments_by_chain.setdefault(chain, [])
            residues_in_fixed_segments_by_chain[chain] += list(range(start, end + 1))

    insertion_codes_residues = []
    for index, row in ppdb.df["ATOM"][["chain_id", "residue_number", "insertion"]].drop_duplicates().iterrows():
        if row["insertion"] and row["residue_number"]:
            if row["chain_id"] not in residues_in_fixed_segments_by_chain:
                continue

            if row["residue_number"] in residues_in_fixed_segments_by_chain[row["chain_id"]]:
                insertion_codes_residues.append(str(row["residue_number"]) + row["insertion"])
    return insertion_codes_residues


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdb_path", type=str)
    parser.add_argument("contig", type=str)
    options = parser.parse_args()

    if os.path.isdir(options.input_pdb_path):
        pdb_paths = sorted(glob.glob(os.path.join(options.input_pdb_path, "*.pdb")))
    else:
        pdb_paths = [options.input_pdb_path]

    print("Checking if there is a designable chain in contig")
    contig_chains = options.contig.split(" ")
    num_designed_segments = 0
    for contig_chain in contig_chains:
        num_designed_segments += sum(is_designed(segment) for segment in contig_chain.removesuffix("/0").split("/"))
    assert num_designed_segments, f"Invalid contig {options.contig}. No designed segments specified."

    print("Checking for insertion codes")
    insertion_codes_by_pdb_path = {pdb_path: get_insertion_codes(pdb_path, contig_chains) for pdb_path in pdb_paths}

    for pdb_path, insertion_codes in insertion_codes_by_pdb_path.items():
        assert not insertion_codes, (
            f"Found insertion codes {insertion_codes} in {pdb_path}. Please remove them before running the pipeline. "
        )
