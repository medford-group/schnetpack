"""
This module contains all functionalities required to load atomistic data,
generate batches and compute statistics. It makes use of the ASE database
for atoms [#ase2]_.

References
----------
.. [#ase2] Larsen, Mortensen, Blomqvist, Castelli, Christensen, Dułak, Friis,
   Groves, Hammer, Hargus:
   The atomic simulation environment -- a Python library for working with atoms.
   Journal of Physics: Condensed Matter, 9, 27. 2017.
"""

import logging
import os
import warnings
from base64 import b64encode, b64decode

import numpy as np
import torch
from ase.db import connect
from torch.utils.data import Dataset

from schnetpack import Structure
from schnetpack.environment import SimpleEnvironmentProvider, collect_atom_triples
from .partitioning import train_test_split

logger = logging.getLogger(__name__)

__all__ = ["AtomsData", "AtomsDataError", "DownloadableAtomsData", "AtomsConverter"]


class AtomsDataError(Exception):
    pass


class AtomsData(Dataset):
    """
    Base class for atomistic datasets.
    The data is stored in the referenced ase database and can be used to load data
    with the pytorch dataloader.

    Args:
        dbpath (str): path to directory containing database.
        subset (list, optional): indices to subset. Set to None for entire database.
        available_properties (list, optional): complete set of physical properties
            that are contained in the database.
        load_only (list, optional): reduced set of properties to be loaded
        units (list, optional): definition of units for all available properties
        environment_provider (spk.environment.BaseEnvironmentProvider): define how
            neighborhood is calculated
            (default=spk.environment.SimpleEnvironmentProvider).
        collect_triples (bool, optional): Set to True if angular features are needed.
        center_positions (bool): subtract center of mass from all positions
            (default=True)
    """

    ENCODING = "utf-8"

    def __init__(
        self,
        dbpath,
        subset=None,
        available_properties=None,
        load_only=None,
        units=None,
        environment_provider=SimpleEnvironmentProvider(),
        collect_triples=False,
        center_positions=True,
    ):
        self.dbpath = dbpath
        self.subset = subset
        self.load_only = load_only
        self.available_properties = self.get_available_properties(available_properties)
        if load_only is None:
            self.load_only = self.available_properties
        if units is None:
            units = [1.0] * len(self.available_properties)
        self.units = dict(zip(self.available_properties, units))
        self.environment_provider = environment_provider
        self.collect_triples = collect_triples
        self.center_positions = center_positions

    def get_available_properties(self, available_properties):
        """
        Get available properties from argument or database.

        Args:
            available_properties (list or None): all properties of the dataset

        Returns:
            (list): all properties of the dataset
        """
        # use the provided list
        if not os.path.exists(self.dbpath):
            if available_properties is None:
                raise AtomsDataError(
                    "Please define available_properties or set "
                    "db_path to an existing database!"
                )
            return available_properties
        # read database properties
        with connect(self.dbpath) as conn:
            atmsrw = conn.get(1)
            db_properties = list(atmsrw.data.keys())
            db_properties = [prop for prop in db_properties if not prop.startswith("_")]
            if db_properties == []:
                if hasattr(atmsrw,'energy'):
                    db_properties.append('energy')
                if hasattr(atmsrw,'forces'):
                    db_properties.append('forces')
        # check if properties match
        if available_properties is None or set(db_properties) == set(
            available_properties
        ):
            return db_properties

        raise AtomsDataError(
            "The available_properties {} do not match the "
            "properties in the database {}!".format(available_properties, db_properties)
        )

    def create_splits(self, num_train=None, num_val=None, split_file=None):
        warnings.warn(
            "create_splits is deprecated, "
            + "use schnetpack.data.train_test_split instead",
            DeprecationWarning,
        )
        return train_test_split(self, num_train, num_val, split_file)

    def create_subset(self, idx):
        """
        Returns a new dataset that only consists of provided indices.
        Args:
            idx (numpy.ndarray): subset indices

        Returns:
            schnetpack.data.AtomsData: dataset with subset of original data
        """
        idx = np.array(idx)
        subidx = (
            idx if self.subset is None or len(idx) == 0 else np.array(self.subset)[idx]
        )
        return type(self)(
            dbpath=self.dbpath,
            subset=subidx,
            load_only=self.load_only,
            environment_provider=self.environment_provider,
            collect_triples=self.collect_triples,
            center_positions=self.center_positions,
            available_properties=self.available_properties,
        )

    def __len__(self):
        if self.subset is None:
            with connect(self.dbpath) as conn:
                return conn.count()
        return len(self.subset)

    def __getitem__(self, idx):
        at, properties = self.get_properties(idx)
        properties["_idx"] = torch.LongTensor(np.array([idx], dtype=np.int))

        return properties

    def _subset_index(self, idx):
        # get row
        if self.subset is None:
            idx = int(idx)
        else:
            idx = int(self.subset[idx])
        return idx

    def get_atoms(self, idx):
        """
        Return atoms of provided index.

        Args:
            idx (int): atoms index

        Returns:
            ase.Atoms: atoms data

        """
        idx = self._subset_index(idx)
        with connect(self.dbpath) as conn:
            row = conn.get(idx + 1)
        at = row.toatoms()
        return at

    def get_metadata(self, key):
        with connect(self.dbpath) as conn:
            if key in conn.metadata.keys():
                return conn.metadata[key]
        return None

    def set_metadata(self, metadata):
        with connect(self.dbpath) as conn:
            conn.metadata = metadata

    def _add_system(self, conn, atoms, **properties):

        data = {}

        for pname in self.available_properties:
            try:
                prop = properties[pname]
            except:
                raise AtomsDataError("Required property missing:" + pname)

            try:
                pshape = prop.shape
                ptype = prop.dtype
            except:
                raise AtomsDataError(
                    "Required property `" + pname + "` has to be `numpy.ndarray`."
                )

            base64_bytes = b64encode(prop.tobytes())
            base64_string = base64_bytes.decode(AtomsData.ENCODING)
            data[pname] = base64_string
            data["_shape_" + pname] = pshape
            data["_dtype_" + pname] = str(ptype)

        conn.write(atoms, data=data)

    def add_system(self, atoms, **properties):
        with connect(self.dbpath) as conn:
            self._add_system(conn, atoms, **properties)

    def add_systems(self, atoms, property_list):
        with connect(self.dbpath) as conn:
            for at, prop in zip(atoms, property_list):
                self._add_system(conn, at, **prop)

    def get_properties(self, idx):
        idx = self._subset_index(idx)
        with connect(self.dbpath) as conn:
            row = conn.get(idx + 1)
        at = row.toatoms()

        # extract properties
        properties = {}
        for pname in self.load_only:
            # new data format
            try:
                shape = row.data["_shape_" + pname]
                dtype = row.data["_dtype_" + pname]
                prop = np.frombuffer(b64decode(row.data[pname]), dtype=dtype)
                prop = prop.reshape(shape)
            except:
                # fallback for properties stored directly
                # in the row
                if pname in row:
                    prop = row[pname]
                else:
                    prop = row.data[pname]

                try:
                    prop.shape
                except AttributeError as e:
                    prop = np.array([prop], dtype=np.float32)

            properties[pname] = torch.FloatTensor(prop)

        # extract/calculate structure
        properties = _convert_atoms(
            at,
            environment_provider=self.environment_provider,
            collect_triples=self.collect_triples,
            center_positions=self.center_positions,
            output=properties,
        )

        return at, properties

    def get_atomref(self, property):
        """
        Returns atomref for property.

        Args:
            property: property in the qm9 dataset

        Returns:
            list: list with atomrefs
        """
        labels = self.get_metadata("atref_labels")
        if labels is None:
            return None

        col = [i for i, l in enumerate(labels) if l == property]
        assert len(col) <= 1

        if len(col) == 1:
            col = col[0]
            atomref = np.array(self.get_metadata("atomrefs"))[:, col : col + 1]
        else:
            atomref = None

        return atomref

    def get_atomrefs(self, properties):
        """
        Return multiple atomrefs as dict.

        Args:
            properties (list or str): Desired properties for which the atomrefs are
                calculated.

        Returns:
            dict: atomic references
        """
        if type(properties) is not list:
            properties = [properties]
        return {p: self.get_atomref(p) for p in properties}


class DownloadableAtomsData(AtomsData):
    def __init__(
        self,
        dbpath,
        subset=None,
        load_only=None,
        available_properties=None,
        units=None,
        environment_provider=SimpleEnvironmentProvider(),
        collect_triples=False,
        center_positions=True,
        download=False,
    ):

        super(DownloadableAtomsData, self).__init__(
            dbpath=dbpath,
            subset=subset,
            available_properties=available_properties,
            load_only=load_only,
            units=units,
            environment_provider=environment_provider,
            collect_triples=collect_triples,
            center_positions=center_positions,
        )
        if download:
            self.download()

    def download(self):
        """
        Wrapper function for the download method.
        """
        if os.path.exists(self.dbpath):
            logger.info(
                "The dataset has already been downloaded and stored "
                "at {}".format(self.dbpath)
            )
        else:
            logger.info("Starting download")
            folder = os.path.dirname(os.path.abspath(self.dbpath))
            if not os.path.exists(folder):
                os.makedirs(folder)
            self._download()

    def _download(self):
        """
        To be implemented in deriving classes.
        """
        raise NotImplementedError


def _convert_atoms(
    atoms,
    environment_provider=SimpleEnvironmentProvider(),
    collect_triples=False,
    center_positions=False,
    output=None,
):
    """
        Helper function to convert ASE atoms object to SchNetPack input format.

        Args:
            atoms (ase.Atoms): Atoms object of molecule
            environment_provider (callable): Neighbor list provider.
            device (str): Device for computation (default='cpu')
            output (dict): Destination for converted atoms, if not None

    Returns:
        dict of torch.Tensor: Properties including neighbor lists and masks
            reformated into SchNetPack input format.
    """
    if output is None:
        inputs = {}
    else:
        inputs = output

    # Elemental composition
    inputs[Structure.Z] = torch.LongTensor(atoms.numbers.astype(np.int))
    positions = atoms.positions.astype(np.float32)
    if center_positions:
        positions -= atoms.get_center_of_mass()
    inputs[Structure.R] = torch.FloatTensor(positions)
    inputs[Structure.cell] = torch.FloatTensor(atoms.cell.astype(np.float32))

    # get atom environment
    nbh_idx, offsets = environment_provider.get_environment(atoms)

    # Get neighbors and neighbor mask
    inputs[Structure.neighbors] = torch.LongTensor(nbh_idx.astype(np.int))

    # Get cells
    inputs[Structure.cell] = torch.FloatTensor(atoms.cell.astype(np.float32))
    inputs[Structure.cell_offset] = torch.FloatTensor(offsets.astype(np.float32))

    # If requested get neighbor lists for triples
    if collect_triples:
        nbh_idx_j, nbh_idx_k, offset_idx_j, offset_idx_k = collect_atom_triples(nbh_idx)
        inputs[Structure.neighbor_pairs_j] = torch.LongTensor(nbh_idx_j.astype(np.int))
        inputs[Structure.neighbor_pairs_k] = torch.LongTensor(nbh_idx_k.astype(np.int))

        inputs[Structure.neighbor_offsets_j] = torch.LongTensor(
            offset_idx_j.astype(np.int)
        )
        inputs[Structure.neighbor_offsets_k] = torch.LongTensor(
            offset_idx_k.astype(np.int)
        )

    return inputs


class AtomsConverter:
    """
    Convert ASE atoms object to an input suitable for the SchNetPack
    ML models.

    Args:
        environment_provider (callable): Neighbor list provider.
        pair_provider (callable): Neighbor pair provider (required for angular
            functions)
        device (str): Device for computation (default='cpu')
    """

    def __init__(
        self,
        environment_provider=SimpleEnvironmentProvider(),
        collect_triples=False,
        device=torch.device("cpu"),
    ):
        self.environment_provider = environment_provider
        self.collect_triples = collect_triples

        # Get device
        self.device = device

    def __call__(self, atoms):
        """
        Args:
            atoms (ase.Atoms): Atoms object of molecule

        Returns:
            dict of torch.Tensor: Properties including neighbor lists and masks
                reformated into SchNetPack input format.
        """
        inputs = _convert_atoms(atoms, self.environment_provider, self.collect_triples)

        # Calculate masks
        inputs[Structure.atom_mask] = torch.ones_like(inputs[Structure.Z]).float()
        mask = inputs[Structure.neighbors] >= 0
        inputs[Structure.neighbor_mask] = mask.float()

        if self.collect_triples:
            inputs[Structure.neighbor_pairs_mask] = torch.ones_like(
                inputs[Structure.neighbor_pairs_j]
            ).float()

        # Add batch dimension and move to CPU/GPU
        for key, value in inputs.items():
            inputs[key] = value.unsqueeze(0).to(self.device)

        return inputs
