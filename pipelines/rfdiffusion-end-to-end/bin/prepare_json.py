#!/usr/bin/env python3
import glob
import os
import argparse
import json


REMARK_KEYS = [
    "Input contig",
    "Standardized contig",
    "Inpaint seq",
    "Chains",
    "Input hotspots",
    "Standardized hotspots",
]

REQUIRED_REMARK_KEYS = [
    "Standardized contig",
    "Chains",
]


def is_designed(contig_chain: str) -> bool:
    """
    Check if the contig chain is fixed or not.
    :param contig_chain: str, the contig chain string
    :return: bool, True if fixed, False otherwise
    """
    for segment in contig_chain.removesuffix("/0").split("/"):
        if not segment[0].isalpha():
            return True
    return False


def get_remark_header(pdb_path: str) -> tuple[str, list[str]]:
    """
    Get the REMARK header from the PDB file.
    :param pdb_path: str, path to the PDB file
    :return: str, REMARK header
    """
    with open(pdb_path, "r") as f:
        lines = f.readlines()

    all_remark_lines = []
    remark_header = ""
    for line in lines:
        if line.startswith("REMARK   1"):
            all_remark_lines.append(line.strip().removeprefix("REMARK   1 "))
            remark_header += line

    return remark_header, all_remark_lines


def parse_remark_lines(stripped_remark_lines: list[str]) -> dict[str, str]:
    """
    :param stripped_remark_lines:
        str, lines from the PDB file header, stripped of the "REMARK   1" prefix
    :return: dict, parsed remarks

    Example: example header to read
        REMARK   1 Input contig: "A45-46/10-15/A45-46/0 B24-26/5/B24-26/0 "
        REMARK   1 Input contig: "C10-20"
        REMARK   1 Standardized contig: "A45-46/13-13/A45-46/0 B24-26/5-5/B24-26/"
        REMARK   1 Standardized contig: "0 C10-20/0"
        REMARK   1 Chains: "A B C"
        REMARK   1 Input hotspots:
        REMARK   1 Standardized hotspots:
    """

    parsed_remark = {}
    for key in REMARK_KEYS:
        # Get lines that begin with this key
        remark_lines = [line.removeprefix(f"{key}:").strip() for line in stripped_remark_lines if line.startswith(key)]
        if not remark_lines and key in REQUIRED_REMARK_KEYS:
            raise ValueError(f"Missing REMARK line for key: {key}")

        values = []
        for line in remark_lines:
            if not line:
                if key in REQUIRED_REMARK_KEYS:
                    raise ValueError(f"Empty JSON value after key {key} in PDB file REMARK header")
                continue

            values.append(json.loads(line))

        parsed_remark[key] = "".join(values)

    return parsed_remark


def parse_inpaint_seq(inpaint_seq: str) -> list[tuple[str, int]]:
    """Parse A2-4/A10-12 to [("A", 2), ("A", 3), ("A", 4), ("A", 10), ("A", 11), ("A", 12)]"""
    if not inpaint_seq.strip():
        return []
    inpaint_s_list = []
    for i in inpaint_seq.strip().split("/"):
        if "-" in i:
            inpaint_s_list.extend([(i[0], p) for p in range(int(i.split("-")[0][1:]), int(i.split("-")[1]) + 1)])
        else:
            inpaint_s_list.append((i[0], int(i[1:])))
    return inpaint_s_list


def get_designed_residues(remark_dict: dict[str, str]) -> str:  # I can use remark_dict as input of this function here
    """
    Get the designed residues from the PDB file.
    :Arg:
        remark_dict: dict, parsed remarks
    :Return:
        designed_residues: str, designed residues in the format "A1 A2 A3 ..."
    Steps:
        - Read remarks lines from the PDB file header;
        - get designed residues to be written in the input json for LigandMPNN;
    """

    contigs_str = remark_dict.get("Standardized contig", None)
    chains_str = remark_dict.get("Chains", None)
    inpaint_seq = remark_dict.get("Inpaint seq", None)
    assert contigs_str, "No Standardized contigs found."
    assert chains_str, "No Standardized contigs found."

    contig_chains = contigs_str.split(" ")
    chains = chains_str.split(" ")

    # For example [("A", 2), ("A", 3), ("A", 4), ("A", 10), ("A", 11), ("A", 12)]
    parsed_inpaint_seq = set(parse_inpaint_seq(inpaint_seq))

    assert len(contig_chains) == len(chains), (
        f"Number of contigs and chains do not match: {len(contig_chains)} != {len(chains)}"
    )

    designed_residues = []
    for idx_chain, contig_chain in enumerate(contig_chains):
        chain = chains[idx_chain]

        i = 1
        assert " " not in contig_chain

        for segment in contig_chain.removesuffix("/0").split("/"):
            if is_designed(segment):
                start_len, end_len = map(int, segment.split("-"))
                assert start_len == end_len, (
                    f"Start len and end len of design segment should coincide: "
                    f"{start_len} != {end_len} in {contig_chain} "
                )

                for _ in range(start_len):
                    designed_residues.append(f"{chain}{i}")
                    i += 1

            else:
                input_chain = segment[0]
                # A10-12 -> 10, 12
                start, end = map(int, segment[1:].split("-"))
                for input_resnum in range(start, end + 1):
                    if (input_chain, input_resnum) in parsed_inpaint_seq:
                        # Fixed structure but inpainted (masked) sequence -> design this residue
                        designed_residues.append(f"{chain}{i}")
                    i += 1

    return " ".join(designed_residues)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdb_dir", type=str, help="Input directory with PDB files")
    parser.add_argument("--pdb_ids_json", type=str, help="Output json filename for multiple PDB input")
    parser.add_argument(
        "--redesigned_residues_json", type=str, help="Output json filename to redesign specific residues"
    )
    parser.add_argument(
        "--remark_json", default="./remark_multi.json", help="Output json filename to save REMARK lines from PDB files"
    )

    options = parser.parse_args()

    if os.path.isdir(options.pdb_dir):
        paths = sorted(glob.glob(os.path.join(options.pdb_dir, "*.pdb")))
        # paths = [pdb_path.replace("_standardized", "") for pdb_path in paths]
        print(f"Reading sequences from {len(paths):,} PDBs")
        pdb_path_ids = {pdb_path: "" for pdb_path in paths}

        remark_header_by_pdb_path = {}
        remark_lines_by_pdb_path = {}
        for pdb_path in paths:
            remark_header, remark_lines = get_remark_header(pdb_path)
            if not remark_header:
                raise ValueError(
                    f'This script requires a "standardized" PDB output with the REMARK header '
                    f"(as produced by the ovo rfdiffusion-backbone workflow), "
                    f"no header found in: {pdb_path}"
                )

            remark_header_by_pdb_path[pdb_path] = remark_header
            remark_lines_by_pdb_path[pdb_path] = remark_lines

        redesigned_residues_by_pdb_path = {
            pdb_path: get_designed_residues(parse_remark_lines(remark_lines))
            for pdb_path, remark_lines in remark_lines_by_pdb_path.items()
        }
    else:
        raise ValueError("Input must be a directory with PDB files")

    # Write pdb ids json
    with open(options.pdb_ids_json, "w") as f:
        json.dump(pdb_path_ids, f)
    print("Saved pdb ids to:", options.pdb_ids_json)

    # Write REMARK lines per pdb
    with open(options.remark_json, "w") as f:
        json.dump(remark_header_by_pdb_path, f)
    print("Saved remark lines to:", options.remark_json)

    # Write redesigned residues json
    with open(options.redesigned_residues_json, "w") as f:
        json.dump(redesigned_residues_by_pdb_path, f)
    print("Saved redesigned residues to:", options.redesigned_residues_json)
