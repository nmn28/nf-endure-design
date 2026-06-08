#!/usr/bin/env python3
from Bio import PDB


class PDBSelector(PDB.Select):
    """Class helper that selects a specific chain in a PDB file."""

    def __init__(self, chain_id, start_residue=None, end_residue=None):
        self.chain_id = chain_id
        self.start_residue = start_residue
        self.end_residue = end_residue

    def accept_model(self, model):
        return True  # Accept all models

    def accept_chain(self, chain):
        return chain.id == self.chain_id

    # TODO: Handle insertion codes
    def accept_residue(self, residue):
        # Accept residue if its id[1] falls within the specified range
        if self.start_residue and self.end_residue:
            return self.start_residue <= residue.id[1] <= self.end_residue
        else:
            return True

    def accept_atom(self, model):
        return True  # Accept all atoms


def get_resname_resnum_atomname_atomnum_str(atom_ppdb, residue_indices: list | None) -> str | None:
    """Return a string of resname_resnum_atomname_atomnum for each atom in the list of residue_indices."""
    if not residue_indices:
        return None

    interfaces_residues_str = ",".join(
        atom_ppdb.loc[residue_indices].apply(
            lambda row: "_".join([row.residue_name, str(row.residue_number), row.atom_name, str(row.atom_number)]),
            axis=1,
        )
    )
    return interfaces_residues_str
