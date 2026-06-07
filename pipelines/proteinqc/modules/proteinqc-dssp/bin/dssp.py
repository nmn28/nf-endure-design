import glob
import os
import argparse
import traceback

import pandas as pd
import tempfile
from typing import List, Tuple
from Bio import PDB
from Bio.PDB import PDBParser
from Bio.PDB.DSSP import DSSP
import numpy as np
import MDAnalysis as mda
from MDAnalysis.analysis import dihedrals
from MDAnalysis.analysis.data.filenames import Rama_ref


def call_dssp(pdb_path):
    structure = PDBParser().get_structure("struct", pdb_path)
    return DSSP(structure[0], pdb_path, dssp="mkdssp")


def prepare_pdb(pdb_path, pdb_path_clean, chain_ids: List[str] = None):
    """Make sure that HEADER is on first row in the PDB file to avoid breaking DSSP input
    and only keep ATOM, HETATM and LINK entries
    """
    header_idx = None
    with open(pdb_path) as f:
        for i, line in enumerate(f):
            if line.upper().startswith("HEADER"):
                header_idx = i
                if i > 0:
                    print(f"Skipping first {i} lines of PDB file before HEADER")
                break

    with open(pdb_path_clean, "wt") as w:
        if header_idx is None:
            w.write("HEADER                                                                          \n")
            header_idx = 0

        with open(pdb_path) as f:
            for i, line in enumerate(f):
                if chain_ids is not None and line.startswith("ATOM"):
                    if line[21] not in chain_ids:
                        continue
                if i >= header_idx and (
                    line.startswith("ATOM")
                    or line.startswith("HEADER")
                    or line.startswith("HETATM")
                    or line.startswith("LINK")
                ):
                    w.write(line)


def get_ramachandran_stats(angles):
    # Regions are computed from a reference set of 500 PDB files from
    # Simon C. Lovell, Ian W. Davis, W. Bryan Arendall, Paul I. W. de Bakker, J. Michael Word, Michael G. Prisant, Jane S. Richardson, and David C. Richardson.
    # Structure validation by Cα geometry: ϕ,ψ and Cβ deviation. Proteins: Structure, Function, and Bioinformatics, 50(3):437–450, January 2003. 03997.
    # URL: http://doi.wiley.com/10.1002/prot.10286 (visited on 2020-02-06), doi:10.1002/prot.10286.
    # The allowed region includes 90% data points, while the marginally allowed region includes 99% data points.
    rama_ref = np.load(Rama_ref)
    n_outliers = 0
    n_allowed = 0
    n_marginally_allowed = 0

    for phi, psi in angles:
        if pd.isna(phi) or pd.isna(psi):
            continue
        i = int((phi + 180) // 4)
        j = int((psi + 180) // 4)
        value = rama_ref[j, i]  # careful: rows=Y, cols=X

        # Source of thresholds for allowed and marginally allowed regions:
        # https://github.com/MDAnalysis/mdanalysis/blob/91146c581eee22aa6508a4d45cc271cb4d9d1509/package/MDAnalysis/analysis/dihedrals.py#L558
        if value >= 17:
            n_allowed += 1
        elif value >= 1:
            n_marginally_allowed += 1
        else:
            n_outliers += 1
    total = angles.shape[0]
    return (n_allowed, n_marginally_allowed, n_outliers, total)


def get_shape_descriptors(pdb_path) -> dict:
    u = mda.Universe(pdb_path)

    protein = u.select_atoms(f"protein")

    if len(protein.residues) == 0:
        return {}

    # Asphericity
    # (0,1) where 0 = perfect sphere
    # See: Dima, R. I., & Thirumalai, D. (2004). Asymmetry in the shapes of folded and denatured states of proteins. J Phys Chem B, 108(21), 6564-6570. doi:10.1021/jp037128y
    asphericity = protein.asphericity()

    # Shape parameter
    # S > 0 corresponds to prolate and S < 0 represents oblate
    # See: Dima, R. I., & Thirumalai, D. (2004). Asymmetry in the shapes of folded and denatured states of proteins. J Phys Chem B, 108(21), 6564-6570. doi:10.1021/jp037128y
    shape_param = protein.shape_parameter()

    # Radius of gyration
    # Rg* = R0 * N^v (Flory Law)
    # R0 = prefactor in units of spatial distance (3A)
    # v = Flory scaling exponent
    # v = 1/3 corresponds to a perfect spherical globule -> Rg* = R0 * N^(1/3)
    # v = 0.588 corresponds to a random coil -> Rg* = R0 * N^(0.588)
    # See: Dima, R. I., & Thirumalai, D. (2004). Asymmetry in the shapes of folded and denatured states of proteins. J Phys Chem B, 108(21), 6564-6570. doi:10.1021/jp037128y
    # See: Kohn, Jonathan E et al. “Random-coil behavior and the dimensions of chemically unfolded proteins.” Proceedings of the National Academy of Sciences of the United States of America vol. 101,34 (2004): 12491-6. doi:10.1073/pnas.0403643101
    rg = protein.radius_of_gyration()

    # Compare to radius of gyration of a perfect sphere
    N_residues = len(protein.residues)
    N_cube_root = N_residues ** (1 / 3)
    rg_sphere = 3 * N_cube_root
    rg_ratio = rg / rg_sphere  # < 1 tight packing, > 1 loose packing

    # Ramachandran statistics
    rama = dihedrals.Ramachandran(protein).run()
    angles = rama.results.angles[0]
    n_allowed, n_marginally_allowed, n_outliers, total = get_ramachandran_stats(angles)
    perc_allowed = n_allowed / total * 100
    perc_marginally_allowed = n_marginally_allowed / total * 100
    perc_outliers = n_outliers / total * 100

    return {
        "asphericity": asphericity,
        "shape_parameter": shape_param,
        "radius_of_gyration": rg,
        "radius_of_gyration_normalized": rg_ratio,
        "ramachandran_allowed_perc": perc_allowed,
        "ramachandran_marginally_allowed_perc": perc_marginally_allowed,
        "ramachandran_outliers_perc": perc_outliers,
    }


def prepare_chain_group_pdbs(pdb_path, out_dir: str, chains_str: str) -> Tuple[List[str], List[str]]:
    """Prepare PDB files for each chain group specified.

    :param path: Path to PDB file
    :param out_dir: Output directory to save prepared PDB files
    :param chains_str: String specifying chain groups, ";" separated groups, "," separated chains within group.
                   Example: "A,B;C" will analyze chains A and B combined as one entry, and chain C as another entry.
                   Use "FULL" to analyze all available chains as one entry.
                   Use "EACH" to analyze each chain separately.

    :return: List of chain groups (['A', 'B', 'A,B']) and corresponding list of prepared PDB file paths
    """
    with open(pdb_path) as f:
        available_chains = sorted(
            {line[21].strip() for line in f if line.startswith("ATOM") and len(line) > 21 and line[21].strip()}
        )
    print("Available chains:", available_chains)

    chain_groups = []
    for group in chains_str.split(";"):
        if group == "EACH":
            chain_groups.extend(available_chains)
        elif group == "FULL":
            chain_groups.append(",".join(available_chains))
        else:
            if missing_chains := sorted(set(group.split(",")).difference(available_chains)):
                raise ValueError(
                    f"Requested chain {missing_chains} is missing in structure: {pdb_path}, available chains: {available_chains}"
                )
            chain_groups.append(group)

    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for chain_group in chain_groups:
        pdb_path_chain_subset = os.path.join(
            out_dir, f"{os.path.basename(pdb_path).removesuffix('.pdb')}.{chain_group}.pdb"
        )
        prepare_pdb(pdb_path, pdb_path_chain_subset, chain_group.split(","))
        paths.append(pdb_path_chain_subset)

    return chain_groups, paths


def get_dssp_df(paths, chains_str: str):
    """Get dataframe with one row for each PDB and chain group

    :param paths: List of paths to PDB files
    :param chains_str: List of chain IDs to analyze, ";" separated groups, "," separated chains within group.
                   Example: "A,B;C" will analyze chains A and B combined as one entry, and chain C as another entry.
                   Use "FULL" to analyze all available chains as one entry.
                   Use "EACH" to analyze each chain separately.
    :return: DataFrame with DSSP and shape descriptors
    """
    results = []
    for i, path in enumerate(paths):
        basename = os.path.basename(path).removesuffix(".pdb")
        print(f"Processing {i + 1}/{len(paths)}: {basename}")

        chain_groups, chain_pdb_paths = prepare_chain_group_pdbs(path, "prepared_pdb", chains_str)
        for chain_group, pdb_path_chain_subset in zip(chain_groups, chain_pdb_paths):
            try:
                dssp = call_dssp(pdb_path_chain_subset)
                res_num = ",".join([f"{key[1][0]}{key[1][1]}{key[1][2]}".strip() for key in dssp.keys()])
                seq = "".join([dssp[key][1] for key in dssp.keys()])
                ss = "".join([dssp[key][2] for key in dssp.keys()])
                # rsa = [dssp[key][3] for key in dssp.keys()]
                # interface = difference between exposure in isolation and exposure when all chains are present is greater than 0.1
                # interface = ''.join(['1' if dssp[key][3] - all_chains_dssp[key][3] > 0.1 else '0' for key in dssp.keys()])

                shape_descriptors = get_shape_descriptors(pdb_path_chain_subset)
                results.append(
                    {
                        "id": basename,
                        "chain": chain_group,
                        "res_num": res_num,
                        "seq": seq,
                        "ss": ss,
                        #'rsa': rsa,
                        #'interface': interface,
                        **shape_descriptors,
                    }
                )
            except Exception as e:
                print("----")
                print("Error processing:", pdb_path_chain_subset)
                traceback.print_exc()
                print("----")
                results.append(
                    {
                        "id": basename,
                        "chain": chain_group,
                        "error": str(e),
                    }
                )

    df = pd.DataFrame(results).set_index("id")
    # H: Alpha helix (4-12)
    # B: Isolated beta-bridge residue
    # E: Strand
    # G: 3-10 helix
    # I: Pi helix
    # T: Turn
    # S: Bend
    # -: None
    ss_options = ["H", "B", "E", "G", "I", "T", "S", "-"]
    ss_columns = [f"% {option}" for option in ss_options]
    if "ss" in df.columns:
        df[ss_columns] = df["ss"].apply(
            lambda x: pd.Series([None] * len(ss_options))
            if pd.isna(x) or len(x) == 0
            else pd.Series(x.count(option) / len(x) * 100 for option in ss_options)
        )
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_path", type=str)
    parser.add_argument("output_csv", type=str)
    parser.add_argument("--chains", type=str, required=True, help="Chain(s) to analyze, comma-separated")
    options = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(options.input_path, "*.pdb")))
    if not paths:
        raise ValueError(f"No pdb files found in: {options.input_path}")

    print(f"Processing {len(paths):,} structures")
    df = get_dssp_df(paths, chains_str=options.chains)
    print(df)
    df.to_csv(options.output_csv)
    print("Saved to:", options.output_csv)
