# tests/test_packaging.py
"""Guards on the packaging claims that fail silently.

A missing PEP 561 marker downgrades every downstream user to ``Any`` without a
warning anywhere, and a version string that has been forked between the module
and the build backend ships metadata disagreeing with ``pandid.__version__``. Both
are invisible in a checkout and expensive to fix once a release is on PyPI.

The third one is not recoverable at all: the purchased BSI/ISO standards under
``standards/`` and the third-party drawings under ``professional_examples/`` may
not be redistributed, and an sdist that carries them cannot be unpublished from
anyone's mirror. So the last two tests here build one and look inside it.
"""

import importlib
import importlib.metadata
import re
import shutil
import tarfile
from pathlib import Path

import pytest

import pandid

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# Paths that must not reach PyPI: the two that may not be redistributed at all,
# and the local working files that would carry whatever happens to be in them.
# Each has to be named in the sdist `exclude`, because the alternative -- letting
# hatchling infer them from .gitignore -- holds only while a .gitignore is there.
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
    """The body of ``[tool.hatch.build.targets.sdist]``, up to the next table."""
    table = re.search(r"^\[tool\.hatch\.build\.targets\.sdist\]$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    assert table, "pyproject.toml has no [tool.hatch.build.targets.sdist] table"
    return table.group(1)


def test_py_typed_marker_sits_next_to_the_package():
    """PEP 561: without this file a type checker ignores every annotation here."""
    assert (Path(pandid.__file__).parent / "py.typed").is_file()


def test_version_is_a_release_number():
    """A tag-driven release computes its tag from this string, so `0.1` won't do."""
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[abc]|rc)?\d*", pandid.__version__)


def test_installed_metadata_matches_module_version():
    try:
        installed = importlib.metadata.version("pandid")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("pandid is not installed; no distribution metadata to compare against")
    assert installed == pandid.__version__


def test_console_script_points_at_something_that_exists():
    """`pandid` is wired up in pyproject; a target that has moved fails at install
    time, in someone else's environment, long after the rename that broke it."""
    if not _PYPROJECT.is_file():
        pytest.skip("running against an installed package rather than a checkout")

    text = _PYPROJECT.read_text(encoding="utf-8")
    entry = re.search(r'^pandid = "([\w.]+):(\w+)"$', text, re.M)
    assert entry, "no [project.scripts] entry named pandid"
    module = importlib.import_module(entry.group(1))
    assert callable(getattr(module, entry.group(2)))


def test_pyproject_takes_its_version_from_the_module():
    """The build backend must read `pandid.__version__`, never restate it."""
    if not _PYPROJECT.is_file():
        pytest.skip("running against an installed package rather than a checkout")

    text = _PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r'^dynamic = \["version"\]', text, re.M)
    assert re.search(r'^path = "pandid/__init__\.py"$', text, re.M)
    assert re.search(r"^version = ", text, re.M) is None


def test_the_sdist_names_every_unshippable_path_itself():
    """Not "it is in .gitignore" -- that file is not guaranteed to be there."""
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
    """The condition that used to break the guarantee, made into a build.

    `git archive`, a CI step that cleans the tree, or a contributor building from
    an unpacked copy all present hatchling with a source tree and no .gitignore.
    This builds exactly that -- the real pyproject.toml, a decoy at every path the
    real tree keeps out -- and looks in the tarball.
    """
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
    # Every member is under a single `pandid-0.0.0/` directory; compare without it.
    shipped = {name.split("/", 1)[1] for name in names if "/" in name}

    assert not [name for name in shipped if name.lower().endswith(".pdf")]
    assert not decoys & shipped
    # ...and the exclusions did not eat the source the sdist exists to carry.
    assert "pandid/__init__.py" in shipped
