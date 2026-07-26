# tests/test_packaging.py
"""Guards on the two packaging claims that fail silently.

A missing PEP 561 marker downgrades every downstream user to ``Any`` without a
warning anywhere, and a version string that has been forked between the module
and the build backend ships metadata disagreeing with ``pfd.__version__``. Both
are invisible in a checkout and expensive to fix once a release is on PyPI.
"""

import importlib.metadata
import re
from pathlib import Path

import pytest

import pfd

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_py_typed_marker_sits_next_to_the_package():
    """PEP 561: without this file a type checker ignores every annotation here."""
    assert (Path(pfd.__file__).parent / "py.typed").is_file()


def test_version_is_a_release_number():
    """A tag-driven release computes its tag from this string, so `0.1` won't do."""
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[abc]|rc)?\d*", pfd.__version__)


def test_installed_metadata_matches_module_version():
    try:
        installed = importlib.metadata.version("pandid")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("pandid is not installed; no distribution metadata to compare against")
    assert installed == pfd.__version__


def test_pyproject_takes_its_version_from_the_module():
    """The build backend must read `pfd.__version__`, never restate it."""
    if not _PYPROJECT.is_file():
        pytest.skip("running against an installed package rather than a checkout")

    text = _PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r'^dynamic = \["version"\]', text, re.M)
    assert re.search(r'^path = "pfd/__init__\.py"$', text, re.M)
    assert re.search(r"^version = ", text, re.M) is None
