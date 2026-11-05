"""Test the `pandid` command line: what it prints and what it exits with."""

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
        {
            "from": ["Raw Feed", "outlet"],
            "to": ["P-101", "suction"],
            "properties": {"Flow (kg/h)": "4200"},
        },
        {"from": ["P-101", "discharge"], "to": ["FV-101", "inlet"]},
        {
            "from": ["FV-101", "outlet"],
            "to": ["To Unit 200", "inlet"],
            "properties": {"Flow (kg/h)": "4200"},
        },
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

# A sheet whose one stream is routed the long way round: one route-detour warning.
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
            "properties": {"Flow (kg/h)": "4200"},
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


# A mixer whose two inlets are pitched inside the arrowheads they carry.
CROWDED = {
    "name": "Crowded Nozzles",
    "units": [
        {"kind": "Feed", "name": "A"},
        {"kind": "Feed", "name": "B"},
        # Height 14 crowds both the inlet arrowheads and the inlet lines.
        {"kind": "Mixer", "name": "M-1", "n_inlets": 2, "height": 14},
        {"kind": "Product", "name": "P"},
    ],
    "streams": [
        {"from": ["A", "outlet"], "to": ["M-1", "in_1"]},
        {"from": ["B", "outlet"], "to": ["M-1", "in_2"]},
        {"from": ["M-1", "outlet"], "to": ["P", "inlet"]},
    ],
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
    """Check that draw options reach the renderer and draw what ``to_svg`` would."""
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
    """Check that bare ``--debug`` draws the default grid and ``--debug 100`` sets the pitch."""
    out = tmp_path / "sheet.svg"
    argv = ["draw", str(_spec_file(tmp_path)), "-o", str(out), *flag]
    assert main(argv) == EXIT_OK
    assert out.read_text(encoding="utf-8") == Flowsheet.from_dict(SPEC).to_svg(debug=debug)


def test_draw_says_how_many_warnings_the_drawing_carries(tmp_path, capsys):
    out = tmp_path / "d.svg"
    argv = ["draw", str(_spec_file(tmp_path, DETOUR)), "-o", str(out), "--stream-table"]
    assert main(argv) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out.startswith("wrote ")
    assert "1 warning" in captured.err
    assert "pandid validate" in captured.err


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
    """Check that validate exits 0 on a sheet with only a warning and reports it."""
    assert main(["validate", str(_spec_file(tmp_path, DETOUR))]) == EXIT_OK
    out = capsys.readouterr().out
    assert "warning: route-detour:" in out
    assert "0 errors, 1 warning" in out


def test_validate_answers_about_the_drawing_it_is_told_about(tmp_path, capsys):
    """Check that ``validate --diagram p&id`` drops nozzles-crowded and keeps lines-crowded."""
    spec = _spec_file(tmp_path, CROWDED)
    assert main(["validate", str(spec)]) == EXIT_OK
    assert "warning: nozzles-crowded: M-1.in_1 and M-1.in_2" in capsys.readouterr().out

    assert main(["validate", "--diagram", "p&id", str(spec)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "nozzles-crowded" not in out
    assert "warning: lines-crowded: S1 and S2" in out


def test_draw_sends_the_reader_to_validate_for_the_sheet_it_drew(tmp_path, capsys):
    """Check that the validate hint after draw carries ``--diagram`` only when draw had one."""
    out = tmp_path / "d.svg"
    argv = ["draw", str(_spec_file(tmp_path, DETOUR)), "-o", str(out)]
    assert main(argv) == EXIT_OK
    err = capsys.readouterr().err
    assert "see: pandid validate " in err and "--diagram" not in err

    assert main([*argv, "--diagram", "p&id"]) == EXIT_OK
    assert "see: pandid validate --diagram 'p&id' " in capsys.readouterr().err


# --- symbols ------------------------------------------------------------------


def test_symbols_lists_every_symbol_in_the_registry(capsys):
    from pandid.render.symbols import default_registry

    assert main(["symbols"]) == EXIT_OK
    captured = capsys.readouterr()
    assert "HeatExchanger (hex)" in captured.out
    for _, variant in default_registry._symbols:
        assert variant in captured.out
    assert f"{len(default_registry._symbols)} symbols" in captured.err


@pytest.mark.parametrize(
    ("kind", "shown"),
    [("valve", ["control", "psv"]), ("Valve", ["control", "psv"]), ("heat_exchanger", ["kettle"])],
)
def test_symbols_filters_by_kind_however_a_spec_spells_it(kind, shown, capsys):
    assert main(["symbols", "--kind", kind]) == EXIT_OK
    out = capsys.readouterr().out
    assert all(variant in out for variant in shown)
    assert "Pump" not in out


def test_symbols_rejects_an_unknown_kind_with_the_nearest_match(capsys):
    assert main(["symbols", "--kind", "vlave"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "did you mean 'Valve'?" in err
    assert "HeatExchanger" in err


# --- the errors a user actually makes -----------------------------------------


def test_a_malformed_spec_names_the_entry_and_the_fix(tmp_path, capsys):
    spec = _spec_file(tmp_path, {"name": "T", "units": [{"kind": "Pomp", "name": "P-101"}]})
    assert main(["draw", str(spec)]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert err.startswith("error: units[0]: unknown equipment kind 'Pomp'")
    assert "did you mean 'Pump'?" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("name", ["missing.yaml", "missing.yml", "missing.json"])
def test_a_missing_file_is_the_missing_file_even_with_no_pyyaml(
    tmp_path, capsys, monkeypatch, name
):
    """Check that a missing spec file exits 1 naming the file, not PyYAML, when PyYAML is absent."""
    monkeypatch.setitem(sys.modules, "yaml", None)  # makes `import yaml` fail
    assert main(["draw", str(tmp_path / name)]) == EXIT_FAILED
    err = capsys.readouterr().err
    assert name in err and "PyYAML" not in err
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
    "argv",
    [
        [],
        ["draw"],
        ["validate"],
        ["frobnicate"],
        ["draw", "x.json", "--border", "fancy"],
        ["draw", "x.json", "--nonsense"],
    ],
)
def test_a_command_line_that_cannot_be_parsed_exits_two(argv):
    assert main(argv) == EXIT_USAGE


def test_the_four_exit_codes_are_four_different_numbers():
    """Check that the four exit codes are distinct."""
    codes = (EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_MISSING_DEPENDENCY)
    assert len(set(codes)) == len(codes)


def test_help_calls_the_command_by_the_name_it_is_installed_under(capsys):
    assert main(["--help"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("usage: pandid")


def test_version_reports_the_distribution(capsys):
    import pandid

    assert main(["--version"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == f"pandid {pandid.__version__}"


def test_python_m_runs_the_same_entry_point():
    import pandid.__main__ as entry
    import pandid.cli

    assert entry.main is pandid.cli.main
