# tests/test_packaging.py
"""Test the packaging: the PEP 561 marker, the version source, the console script,
and the paths the sdist leaves out."""

import importlib
import importlib.metadata
import re
import shutil
import tarfile
from pathlib import Path

import pytest

import pandid

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# Paths the sdist `exclude` must name.
_MUST_NOT_SHIP = (
    "standards",
    "professional_examples",
    ".claude",
    ".superpowers",
    ".agents",
    ".venv",
    "renders",
    "test_diagram.svg",
    "skills-lock.json",
    "uv.lock",
)


def _sdist_table(text: str) -> str:
    """Return the body of ``[tool.hatch.build.targets.sdist]``, up to the next table."""
    table = re.search(r"^\[tool\.hatch\.build\.targets\.sdist\]$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert table, "pyproject.toml has no [tool.hatch.build.targets.sdist] table"
    return table.group(1)


def test_py_typed_marker_sits_next_to_the_package():
    """Check that the PEP 561 ``py.typed`` marker sits in the package directory."""
    assert (Path(pandid.__file__).parent / "py.typed").is_file()


def test_version_is_a_release_number():
    """Check that ``pandid.__version__`` is a three-part release number."""
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[abc]|rc)?\d*", pandid.__version__)


def test_installed_metadata_matches_module_version():
    try:
        installed = importlib.metadata.version("pandid")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("pandid is not installed; no distribution metadata to compare against")
    assert installed == pandid.__version__


def test_console_script_points_at_something_that_exists():
    """Check that the ``pandid`` console script names a callable that exists."""
    if not _PYPROJECT.is_file():
        pytest.skip("running against an installed package rather than a checkout")

    text = _PYPROJECT.read_text(encoding="utf-8")
    entry = re.search(r'^pandid = "([\w.]+):(\w+)"$', text, re.M)
    assert entry, "no [project.scripts] entry named pandid"
    module = importlib.import_module(entry.group(1))
    assert callable(getattr(module, entry.group(2)))


def test_pyproject_takes_its_version_from_the_module():
    """Check that pyproject reads its version from ``pandid.__version__``, not restates it."""
    if not _PYPROJECT.is_file():
        pytest.skip("running against an installed package rather than a checkout")

    text = _PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r'^dynamic = \["version"\]', text, re.M)
    assert re.search(r'^path = "pandid/__init__\.py"$', text, re.M)
    assert re.search(r"^version = ", text, re.M) is None


def test_the_sdist_names_every_unshippable_path_itself():
    """Check that the sdist ``exclude`` names every path in ``_MUST_NOT_SHIP``."""
    if not _PYPROJECT.is_file():
        pytest.skip("running against an installed package rather than a checkout")

    table = _sdist_table(_PYPROJECT.read_text(encoding="utf-8"))
    missing = [path for path in _MUST_NOT_SHIP if f'"{path}"' not in table]
    assert not missing, (
        "[tool.hatch.build.targets.sdist] exclude does not name "
        + ", ".join(missing)
        + ". Add each one: without it the path ships from any tree with no .gitignore."
    )


def test_a_built_sdist_carries_no_pdf_when_there_is_no_gitignore(tmp_path):
    """Check that an sdist built with no .gitignore ships no PDF and no excluded decoy."""
    sdist = pytest.importorskip(
        "hatchling.builders.sdist",
        reason="hatchling is not installed, so there is no backend to build with",
    )
    if not _PYPROJECT.is_file():
        pytest.skip("running against an installed package rather than a checkout")

    project = tmp_path / "src"
    (project / "pandid").mkdir(parents=True)
    (project / "pandid" / "__init__.py").write_text('__version__ = "0.0.0"\n', encoding="utf-8")
    shutil.copyfile(_PYPROJECT, project / "pyproject.toml")
    for named_by_metadata in ("README.md", "LICENSE", "LICENSE-APACHE", "NOTICE"):
        (project / named_by_metadata).write_text("stand-in\n", encoding="utf-8")

    decoys = {
        "standards/BS EN ISO 10628-1-2015.pdf",
        "professional_examples/P&ID_301.pdf",
        ".claude/settings.local.json",
        ".superpowers/skill.md",
        ".agents/notes.md",
        ".venv/Lib/site-packages/anything.pdf",
        "renders/scratch.svg",
        "test_diagram.svg",
        "skills-lock.json",
        "uv.lock",
    }
    for decoy in decoys:
        path = project / decoy
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("decoy\n", encoding="utf-8")
    assert not (project / ".gitignore").exists(), "the point of the test is that there is none"

    (artifact,) = sdist.SdistBuilder(str(project)).build(directory=str(tmp_path / "dist"))
    with tarfile.open(artifact) as tar:
        names = tar.getnames()
    # Strip the leading `pandid-0.0.0/` directory from each member.
    shipped = {name.split("/", 1)[1] for name in names if "/" in name}

    assert not [name for name in shipped if name.lower().endswith(".pdf")]
    assert not decoys & shipped
    assert "pandid/__init__.py" in shipped
