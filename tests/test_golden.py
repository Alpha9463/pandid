"""Test representative SVG fixtures and rendered nozzle placement."""

import difflib
import os
import re
from pathlib import Path

import pytest

from _render_cases import SCENARIOS as SCENARIOS, copy_settled_case
from pandid.document import equipment_list
from pandid.render.debug import _BOX, _PORT
from pandid.render.svg import PROVENANCE_CLOSE, PROVENANCE_OPEN

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("PANDID_UPDATE_GOLDEN") == "1"

#: Representative manual, PFD, P&ID, BFD, and automatic-layout fixtures.
GOLDEN_SCENARIOS = (
    "02_manual_layout",
    "03_distillation_train",
    "11_ethanol_pid",
    "12_block_flow_diagram",
    "18_fixed_bed_recycle",
)

#: Finding codes a golden sheet is drawn with.
GOLDEN_FINDINGS = {
    "18_fixed_bed_recycle": ["route-along-unit", "route-crosses-near-nozzle"],
}


def _check_golden(name: str, svg: str) -> None:
    """Compare an SVG document with its approved fixture.

    Parameters
    ----------
    name : str
        Golden fixture name.
    svg : str
        Rendered SVG document text.
    """
    path = GOLDEN_DIR / f"{name}.svg"
    normalized = _normalize(svg)
    if UPDATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(normalized, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(f"no golden at {path}; regenerate with PANDID_UPDATE_GOLDEN=1", pytrace=False)
    golden = _normalize(path.read_text(encoding="utf-8"))
    assert golden == normalized, "".join(
        difflib.unified_diff(golden.splitlines(True), normalized.splitlines(True), n=2)
    )


_PROVENANCE = re.compile(f"{re.escape(PROVENANCE_OPEN)}.*?{re.escape(PROVENANCE_CLOSE)}", re.S)


def _normalize(svg: str) -> str:
    """Empty the fenced provenance block of an SVG document.

    Parameters
    ----------
    svg : str
        SVG document.

    Returns
    -------
    str
        SVG document with only the provenance fences left.
    """
    return _PROVENANCE.sub(f"{PROVENANCE_OPEN}\n{PROVENANCE_CLOSE}", svg)


@pytest.mark.parametrize("name", GOLDEN_SCENARIOS, ids=GOLDEN_SCENARIOS)
def test_golden_svg(settled_gallery, name):
    """Match representative renders and their findings to approved fixtures.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict]]
        Settled gallery flowsheets and render options.
    name : str
        Scenario or stream identifier under test.
    """
    fs, kwargs = copy_settled_case(settled_gallery, name)
    svg = fs.to_svg(**kwargs)
    assert [warning.code for warning in fs.warnings] == GOLDEN_FINDINGS.get(name, []), (
        f"{name}: {[str(warning) for warning in fs.warnings]}"
    )
    _check_golden(name, svg)


def test_a_version_bump_does_not_move_a_fixture(monkeypatch):
    """Keep golden fixtures independent of version metadata.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace runtime state.
    """
    import pandid

    name = "03_distillation_train"
    build, kwargs = SCENARIOS[name]
    at_this_version = build().to_svg(**kwargs)
    monkeypatch.setattr(pandid, "__version__", "99.99.99")
    at_another = build().to_svg(**kwargs)

    assert at_this_version != at_another, "the version is not in the rendered file at all"
    assert _normalize(at_this_version) == _normalize(at_another)
    _check_golden(name, at_another)


_DEBUG_CIRCLE = re.compile(
    r'<circle cx="(-?[\d.]+)" cy="(-?[\d.]+)" r="[\d.]+" fill="' + re.escape(_PORT) + '"'
)
_DEBUG_BOX = re.compile(
    r'<rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="(-?[\d.]+)" height="(-?[\d.]+)" '
    r'fill="none" stroke="' + re.escape(_BOX) + '"'
)


def _drawn(value: "str | float") -> float:
    """Round a coordinate to SVG serialization precision.

    Parameters
    ----------
    value : str | float
        Coordinate captured from SVG or resolved by the model.

    Returns
    -------
    float
        Coordinate rounded to one decimal place.
    """
    return round(float(value), 1)


@pytest.mark.parametrize("name", GOLDEN_SCENARIOS, ids=GOLDEN_SCENARIOS)
def test_representative_sheets_draw_nozzles_on_their_own_bodies(settled_gallery, name):
    """Test that representative sheets draw nozzles on their own bodies.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict]]
        Settled gallery flowsheets and render options.
    name : str
        Scenario or stream identifier under test.
    """
    from pandid.portgeom import resolve_port, unit_box

    fs, kwargs = copy_settled_case(settled_gallery, name)
    overlaid = {**kwargs, "debug": True}
    svg = fs.to_svg(**overlaid)
    dots = {(_drawn(x), _drawn(y)) for x, y in _DEBUG_CIRCLE.findall(svg)}
    boxes = {(_drawn(x), _drawn(y), _drawn(w), _drawn(h)) for x, y, w, h in _DEBUG_BOX.findall(svg)}
    assert dots and boxes, f"{name}: the overlay drew no markers to measure"

    off_body = []
    for unit in fs.units:
        if unit.frame is None:
            continue
        x0, y0, x1, y1 = unit_box(unit, unit.frame)
        assert (_drawn(x0), _drawn(y0), _drawn(x1 - x0), _drawn(y1 - y0)) in boxes, (
            f"{name}: {unit.name}'s box is not one the sheet drew"
        )
        for port in unit.ports:
            px, py = resolve_port(unit, unit.frame, port).point
            assert (_drawn(px), _drawn(py)) in dots, (
                f"{name}: {unit.name}.{port} is not a nozzle the sheet drew"
            )
            if not (x0 <= px <= x1 and y0 <= py <= y1):
                off_body.append(
                    f"{unit.name}.{port} at ({px:.1f}, {py:.1f}) is outside "
                    f"({x0:.1f}, {y0:.1f})..({x1:.1f}, {y1:.1f})"
                )
    assert off_body == [], f"{name} draws {len(off_body)} nozzles off their own bodies"


def test_the_fractionator_schedules_only_equipment_that_exists():
    """Keep the fractionator schedule aligned with its process topology."""
    fs = SCENARIOS["06_column_reflux"][0]()
    col = next(u for u in fs.units if u.name == "T-701")
    reb = next(u for u in fs.units if u.name == "E-702")
    # The column bottoms stream enters the reboiler.
    assert col.bottoms.stream.dest.owner is reb
    assert reb.bottoms.stream is not None
    assert reb.bottoms.stream.dest.owner.name == "Bottoms"
    assert [tag for tag, _ in equipment_list(fs).rows] == [
        "T-701",
        "E-701",
        "V-701",
        "E-702",
    ]


def test_each_alumina_off_page_flag_has_its_partner_on_the_sheet_it_names():
    """Pair every alumina refinery flag that names another sheet of its set."""
    sheets = {}
    for n in (1, 2, 3):
        fs = SCENARIOS[f"21_alumina_refinery_{n}"][0]()
        assert fs.title_block is not None
        sheets[fs.title_block.drawing_number] = fs
    assert len(sheets) == 3, "two sheets share a drawing number"

    opposite = {"feed": "product", "product": "feed"}
    pairs = 0
    for number, fs in sheets.items():
        for flag in fs.units:
            if flag.kind not in opposite or flag.reference not in sheets:
                continue
            partners = [
                unit
                for unit in sheets[flag.reference].units
                if unit.kind == opposite[flag.kind]
                and unit.name == flag.name
                and unit.reference == number
            ]
            assert len(partners) == 1, (
                f"{number} {flag.kind} {flag.name!r} has {len(partners)} partners on {flag.reference}"
            )
            (port,) = flag.ports.values()
            (partner_port,) = partners[0].ports.values()
            assert port.stream is not None and partner_port.stream is not None
            assert port.stream.name == partner_port.stream.name
            pairs += 1
    # Three crossings, each seen from both of its ends.
    assert pairs == 6
