# Copyright (c) 2014, The MITRE Corporation. All rights reserved.
# See LICENSE.txt for complete terms.

from os.path import abspath, dirname, join
from setuptools import setup, find_packages

INIT_FILE = join(dirname(abspath(__file__)), 'maec', '__init__.py')

def get_version():
    with open(INIT_FILE) as f:
        for line in f.readlines():
            if line.startswith("__version__"):
                version = line.split()[-1].strip('"')
                return version
        raise AttributeError("Package does not have a __version__")

with open('README.rst') as f:
    readme = f.read()

setup(
    name="maec",
    version=get_version(),
    author="MAEC Project",
    author_email="maec@mitre.org",
    description="An API for parsing and creating MAEC content.",
    long_description=readme,
    url="http://maec.mitre.org",
    packages=find_packages(),
    install_requires=['lxml>=2.3', 'cybox>=2.1.0.0,<2.1.1.0'],
    classifiers=[
        "Programming Language :: Python",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
    ]
)
