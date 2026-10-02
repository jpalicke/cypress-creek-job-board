# ABOUTME: Checks that the package imports and exposes the version from its metadata.
# ABOUTME: The version has one source of truth, pyproject.toml, read through package metadata.
from importlib.metadata import version

import cypress_creek


def test_version_matches_package_metadata() -> None:
    assert cypress_creek.__version__ == version("cypress-creek")
