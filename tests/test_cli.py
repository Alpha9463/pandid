"""The `pandid` command line: what it prints, and what it exits with.

The whole point of the CLI is that the person running it did not want to write
Python, so every one of these asserts on the *message* as well as the code. A
traceback reaching someone who mistyped a file name, or a mistyped page size
that exits 0, is the failure this file exists to catch.

`main(argv)` is called directly rather than through a subprocess: the exit code
is its return value, so there is nothing a shell would add.
"""

import json
import sys

import pytest

from pandid import Flowsheet
from pandid.cli import EXIT_FAILED, EXIT_MISSING_DEPENDENCY, EXIT_OK, EXIT_USAGE, main

SPEC = {
    "name": "Feed Skid",
    "units": [
        {"kind": "Feed", "name": "Raw Feed"},
        {"kind": "Pump", "name": "P-101"},
        {"kind": "Valve", "name": "FV-101", "variant": "control"},
        {"kind": "Product", "name": "To Unit 200"},
    ],
    "streams": [
        {"from": ["Raw Feed", "outlet"], "to": ["P-101", "suction"]},
        {"from": ["P-101", "discharge"], "to": ["FV-101", "inlet"]},
        {"from": ["FV-101", "outlet"], "to": ["To Unit 200", "inlet"]},
    ],
}

YAML_SPEC = """\
name: Feed Skid
units:
  - {kind: Feed, name: Raw Feed}
  - {kind: Pump, name: P-101}
  - {kind: Valve, name: FV-101, variant: control}
  - {kind: Product, name: To Unit 200}
streams:
  - {from: [Raw Feed, outlet], to: [P-101, suction]}
  - {from: [P-101, discharge], to: [FV-101, inlet]}
  - {from: [FV-101, outlet], to: [To Unit 200, inlet]}
"""

# A sheet with nothing wrong with it but a stream sent the long way round, so
# the router reports a detour: a warning, and warnings never stop a drawing.
#
# The corners are stated as well as the sides. `via` squares nothing up, so a
# waypoint off the axis of the nozzle before it draws a diagonal -- which is a
# `route-diagonal` finding of its own and would make this fixture about two
# things.
DETOUR = {
    "name": "Long Way Round",
    "units": [
        {"kind": "Feed", "name": "F", "pin": {"x": 60, "y": 175}},
        {"kind": "Product", "name": "P", "pin": {"x": 360, "y": 175}},
    ],
    "streams": [
        {
            "from": ["F", "outlet"],
            "to": ["P", "inlet"],
            "via": [[110, 600], [300, 600], [300, 200]],
        }
    ],
}

# Two units pinned on top of one another: an error, and no drawing.
OVERLAP = {
    "name": "Overlapping Pins",
    "units": [
        {"kind": "Pump", "name": "P-101", "pin": {"x": 300, "y": 200}},
        {"kind": "Valve", "name": "FV-101", "pin": {"x": 320, "y": 200}},
    ],
    "streams": [{"from": ["P-101", "discharge"], "to": ["FV-101", "inlet"]}],
}


def _spec_file(tmp_path, spec=SPEC, name="plant.json"):
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


# --- draw ---------------------------------------------------------------------


def test_draw_writes_the_file_and_reports_what_is_on_it(tmp_path, capsys):
    out = tmp_path / "plant.svg"
    assert main(["draw", str(_spec_file(tmp_path)), "-o", str(out)]) == EXIT_OK
    assert "<svg" in out.read_text(encoding="utf-8")
    assert capsys.readouterr().out == f"wrote {out}  (4 units, 3 streams)\n"


def test_draw_without_an_output_names_it_after_the_spec(tmp_path, capsys):
    spec = _spec_file(tmp_path)
    assert main(["draw", str(spec)]) == EXIT_OK
    assert (tmp_path / "plant.svg").is_file()
    assert "plant.svg" in capsys.readouterr().out


def test_draw_reads_yaml(tmp_path, capsys):
    pytest.importorskip("yaml")
    spec = tmp_path / "plant.yaml"
    spec.write_text(YAML_SPEC, encoding="utf-8")
    assert main(["draw", str(spec)]) == EXIT_OK
    assert (tmp_path / "plant.svg").is_file()
    assert "4 units, 3 streams" in capsys.readouterr().out


def test_draw_options_reach_the_renderer(tmp_path, capsys):
    """The CLI is a shell over `render()`, so it must draw exactly what it would."""
    out = tmp_path / "sheet.svg"
    argv = [
        "draw",
        str(_spec_file(tmp_path)),
        "-o",
        str(out),
        "--page-size",
        "A3",
        "--border",
        "zone",
        "--diagram",
        "p&id",
        "--stream-table",
        "--jump-direction",
        "horizontal",
    ]
    assert main(argv) == EXIT_OK
    assert out.read_text(encoding="utf-8") == Flowsheet.from_dict(SPEC).to_svg(
        page_size="A3",
        border="zone",
        diagram="p&id",
        show_stream_table=True,
        jump_direction="horizontal",
    )
    assert "(A3, 4 units, 3 streams)" in capsys.readouterr().out


def test_draw_leaves_the_debug_overlay_off_unless_it_is_asked_for(tmp_path):
    out = tmp_path / "plain.svg"
    assert main(["draw", str(_spec_file(tmp_path)), "-o", str(out)]) == EXIT_OK
    assert out.read_text(encoding="utf-8") == Flowsheet.from_dict(SPEC).to_svg()


@pytest.mark.parametrize(
    "flag, debug",
    [(["--debug"], True), (["--debug", "100"], 100.0)],
    ids=["bare", "with-spacing"],
)
def test_draw_debug_takes_a_spacing_or_none(tmp_path, flag, debug):
    """``--debug`` alone is the default grid; ``--debug 100`` sets the pitch."""
    out = tmp_path / "sheet.svg"
    argv = ["draw", str(_spec_file(tmp_path)), "-o", str(out), *flag]
    assert main(argv) == EXIT_OK
    assert out.read_text(encoding="utf-8") == Flowsheet.from_dict(SPEC).to_svg(debug=debug)


def test_draw_says_how_many_warnings_the_drawing_carries(tmp_path, capsys):
    out = tmp_path / "d.svg"
    assert main(["draw", str(_spec_file(tmp_path, DETOUR)), "-o", str(out)]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out.startswith("wrote ")
    assert "1 warning" in captured.err
    assert "pandid validate" in captured.err  # ...and where to read it


def test_draw_refuses_a_flowsheet_validation_rejects(tmp_path, capsys):
    assert main(["draw", str(_spec_file(tmp_path, OVERLAP))]) == EXIT_FAILED
    assert "P-101 and FV-101 overlap" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.svg"))


# --- validate -----------------------------------------------------------------


def test_validate_passes_a_sound_flowsheet(tmp_path, capsys):
    spec = _spec_file(tmp_path)
    assert main(["validate", str(spec)]) == EXIT_OK
    assert capsys.readouterr().out == f"{spec}: no problems found (4 units, 3 streams)\n"


def test_validate_fails_on_an_error_and_names_it(tmp_path, capsys):
    assert main(["validate", str(_spec_file(tmp_path, OVERLAP))]) == EXIT_FAILED
    out = capsys.readouterr().out
    assert "error: unit-overlap: P-101 and FV-101 overlap" in out
    assert "1 error" in out


def test_validate_passes_on_warnings_alone(tmp_path, capsys):
    """Warnings never stop a render, so gating a script on them would be wrong."""
    assert main(["validate", str(_spec_file(tmp_path, DETOUR))]) == EXIT_OK
    out = capsys.readouterr().out
    assert "warning: route-detour:" in out
    assert "0 errors, 1 warning" in out


# --- symbols ------------------------------------------------------------------


def test_symbols_lists_every_symbol_in_the_registry(capsys):
    # The listing is built from the unit classes, and the registry is the other
    # side of the same fact, so a symbol the classes cannot reach shows up here
    # as a variant missing from the output or a count that disagrees.
    from pandid.render.symbols import default_registry

    assert main(["symbols"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "HeatExchanger (hex)" in captured.out  # ...with the kind the engine files it under
    for _, variant in default_registry._symbols:
        assert variant in captured.out
    assert f"{len(default_registry._symbols)} symbols" in captured.err


@pytest.mark.parametrize("kind", ["valve", "Valve"])
def test_symbols_filters_by_kind(kind, capsys):
    assert main(["symbols", "--kind", kind]) == EXIT_OK
    out = capsys.readouterr().out
    assert "control" in out and "psv" in out
    assert "Pump" not in out


def test_symbols_takes_the_kind_however_a_spec_spells_it(capsys):
    assert main(["symbols", "--kind", "heat_exchanger"]) == EXIT_OK
    assert "kettle" in capsys.readouterr().out


def test_symbols_rejects_an_unknown_kind_with_the_nearest_match(capsys):
    assert main(["symbols", "--kind", "vlave"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "did you mean 'Valve'?" in err
    assert "HeatExchanger" in err  # ...and the whole catalogue behind it


# --- the errors a user actually makes -----------------------------------------


def test_a_malformed_spec_names_the_entry_and_the_fix(tmp_path, capsys):
    spec = _spec_file(tmp_path, {"name": "T", "units": [{"kind": "Pomp", "name": "P-101"}]})
    assert main(["draw", str(spec)]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert err.startswith("error: units[0]: unknown equipment kind 'Pomp'")
    assert "did you mean 'Pump'?" in err
    assert "Traceback" not in err


def test_a_missing_file_is_one_line_not_a_traceback(tmp_path, capsys):
    assert main(["draw", str(tmp_path / "missing.yaml")]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert "missing.yaml" in err
    assert len(err.splitlines()) == 1


def test_a_file_that_is_not_a_spec_says_what_one_is(tmp_path, capsys):
    notes = tmp_path / "notes.txt"
    notes.write_text("not a flowsheet", encoding="utf-8")
    assert main(["draw", str(notes)]) == EXIT_FAILED
    assert ".yaml, .yml or .json" in capsys.readouterr().err


def test_an_unknown_page_size_names_the_ones_that_work(tmp_path, capsys):
    assert main(["draw", str(_spec_file(tmp_path)), "--page-size", "A9"]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert "A9" in err
    assert "A3" in err and "A0" in err


def test_an_unsupported_output_extension_names_the_ones_that_work(tmp_path, capsys):
    spec = _spec_file(tmp_path)
    assert main(["draw", str(spec), "-o", str(tmp_path / "plant.bmp")]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert ".bmp" in err
    assert ".svg" in err and ".pdf" in err


def test_the_yaml_extra_is_named_when_pyyaml_is_missing(tmp_path, monkeypatch, capsys):
    spec = tmp_path / "plant.yaml"
    spec.write_text(YAML_SPEC, encoding="utf-8")
    monkeypatch.setitem(sys.modules, "yaml", None)  # makes `import yaml` fail
    assert main(["draw", str(spec)]) == EXIT_MISSING_DEPENDENCY
    err = capsys.readouterr().err
    assert "PyYAML" in err
    assert "pip install 'pandid[yaml]'" in err


def test_the_pdf_extra_is_named_when_the_backend_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "svglib.svglib", None)  # makes the import fail
    spec = _spec_file(tmp_path)
    assert main(["draw", str(spec), "-o", str(tmp_path / "plant.pdf")]) == EXIT_MISSING_DEPENDENCY
    err = capsys.readouterr().err
    assert "svglib" in err
    assert "pip install 'pandid[pdf]'" in err


# --- the command line itself --------------------------------------------------


@pytest.mark.parametrize(
    "argv", [[], ["draw"], ["validate"], ["frobnicate"], ["draw", "x.json", "--border", "fancy"]]
)
def test_a_command_line_that_cannot_be_parsed_exits_two(argv):
    assert main(argv) == EXIT_USAGE


def test_the_four_exit_codes_are_four_different_numbers():
    """A script gates on these, so success, rejection, usage and a missing
    extra have to be tellable apart."""
    codes = (EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_MISSING_DEPENDENCY)
    assert len(set(codes)) == len(codes)


def test_help_calls_the_command_by_the_name_it_is_installed_under(capsys):
    assert main(["--help"]) == EXIT_OK
    out = capsys.readouterr().out
    # argparse defaults to sys.argv[0], which under pytest is the test runner.
    assert out.startswith("usage: pandid")


def test_version_reports_the_distribution(capsys):
    import pandid

    assert main(["--version"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == f"pandid {pandid.__version__}"


def test_python_m_runs_the_same_entry_point():
    import pandid.__main__ as entry
    import pandid.cli

    assert entry.main is pandid.cli.main
