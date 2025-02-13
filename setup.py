import os
import io

from setuptools import setup, find_packages


def read(fname):
    with io.open(os.path.join(os.path.dirname(__file__), fname), encoding="utf-8") as f:
        return f.read()


setup(
    name="schnetpack",
    version="0.2.1",
    author="Kristof T. Schuett, Michael Gastegger, Pan Kessel, Kim Nicoli",
    email="kristof.schuett@tu-berlin.de",
    url="https://github.com/atomistic-machine-learning/schnetpack",
    packages=find_packages("src"),
    scripts=[
        "src/scripts/schnetpack_qm9.py",
        "src/scripts/schnetpack_md17.py",
        "src/scripts/schnetpack_matproj.py",
        "src/scripts/schnetpack_ase.py",
        "src/scripts/schnetpack_ani1.py",
        "src/scripts/schnetpack_load.py",
        "src/scripts/schnetpack_molecular_dynamics.py",
        "src/scripts/schnetpack_parse.py",
        "src/scripts/schnetpack_omdb.py",
    ],
    package_dir={"": "src"},
    python_requires=">=3.6",
    install_requires=[
        "torch>=0.4.1",
        "numpy",
        "ase>=3.16",
        "h5py",
        "tensorboardX",
        "sacred==0.7.4",
        "tqdm",
        "h5py",
        "pyyaml",
    ],
    extras_require={"test": ["pytest", "sacred"]},
    license="MIT",
    description="SchNetPack - Deep Neural Networks for Atomistic Systems",
    long_description=read("README.md"),
)
