"""Test the guide in pandid's module docstring."""

import itertools
import textwrap

import pandid
from pandid.cli import EXIT_OK, main

GUIDE = 'python -c "import pandid; print(pandid.__doc__)"'


def _example() -> str:
    """Return the code block that follows the guide's ``::`` marker."""
    doc = pandid.__doc__ or ""
    assert "::\n" in doc, "the guide has no example block"
    after = doc.split("::\n", 1)[1].splitlines()
    block = itertools.takewhile(lambda line: not line or line.startswith("    "), after)
    return textwrap.dedent("\n".join(block))


def test_the_guide_example_draws_a_clean_sheet(tmp_path, monkeypatch):
    """Check that the guide's example runs, writes its drawing and leaves no finding."""
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {}
    exec(_example(), namespace)
    assert (tmp_path / "cooler.svg").is_file()
    fs = namespace["fs"]
    assert isinstance(fs, pandid.Flowsheet)
    assert fs.validate() == []


def test_cli_help_names_the_guide(capsys):
    """Check that ``pandid --help`` names the command that prints the guide."""
    assert main(["--help"]) == EXIT_OK
    assert GUIDE in " ".join(capsys.readouterr().out.split())
