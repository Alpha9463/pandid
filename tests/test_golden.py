"""Compare each example's SVG to its golden and check rendered nozzle positions."""

import os
import re
from pathlib import Path

import pytest

from _render_cases import SCENARIOS as SCENARIOS, copy_settled_case
from _svg_compare import normalize as _normalize
from pandid.document import equipment_list
from pandid.render.debug import _BOX, _PORT

GOLDEN_DIR = Path(__file__).parent / "golden"
UPDATE = os.environ.get("PANDID_UPDATE_GOLDEN") == "1"

#: Representative exact-output checks for manual placement, furnished PFDs,
#: dense P&IDs, BFDs, and automatic layout.
GOLDEN_SCENARIOS = (
    "02_manual_layout",
    "03_distillation_train",
    "11_ethanol_pid",
    "12_block_flow_diagram",
    "18_fixed_bed_recycle",
)


def test_a_shared_settled_case_does_not_share_mutable_geometry(settled_gallery):
    """Keep cached routes and render options unchanged after a copy is mutated."""
    source, source_options = settled_gallery["11_ethanol_pid"]
    copied, copied_options = copy_settled_case(settled_gallery, "11_ethanol_pid")

    copied.streams[0].route = None
    copied_options["diagram"] = "pfd"

    assert copied is not source
    assert source.streams[0].route is not None
    assert source_options.get("diagram") != "pfd"


def _diff_message(name: str, golden: str, actual: str) -> str:
    """Build a concise diagnostic for the first SVG difference.

    Parameters
    ----------
    name : str
        Name of the golden fixture.
    golden : str
        Expected normalized SVG.
    actual : str
        Newly rendered SVG.

    Returns
    -------
    str
        First differing line with nearby context.
    """
    exp = golden.split("\n")
    act = actual.split("\n")
    for i, (e, a) in enumerate(zip(exp, act)):
        if e == a:
            continue
        lo, hi = max(0, i - 2), min(max(len(exp), len(act)), i + 3)
        ctx = []
        for k in range(lo, hi):
            ek = exp[k] if k < len(exp) else "<no line>"
            ak = act[k] if k < len(act) else "<no line>"
            mark = ">>" if k == i else "  "
            ctx.append(f"{mark} [{k}] golden: {ek}")
            ctx.append(f"{mark} [{k}] actual: {ak}")
        return f"{name}: first mismatch at line {i} of {max(len(exp), len(act))}\n" + "\n".join(ctx)
    return f"{name}: identical prefix but line counts differ (golden {len(exp)}, actual {len(act)})"


def _check_golden(name: str, svg: str) -> None:
    """Compare one SVG with its committed golden fixture.

    Parameters
    ----------
    name : str
        Name of the golden fixture.
    svg : str
        Newly rendered SVG.

    Returns
    -------
    None
        Writes the normalized fixture only when golden updates are enabled.
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
    if golden != normalized:
        pytest.fail(_diff_message(name, golden, normalized), pytrace=False)


@pytest.mark.parametrize("name", GOLDEN_SCENARIOS, ids=GOLDEN_SCENARIOS)
def test_golden_svg(settled_gallery, name):
    """Match each representative example's SVG to its committed golden."""
    fs, kwargs = copy_settled_case(settled_gallery, name)
    _check_golden(name, fs.to_svg(**kwargs))


def test_a_version_bump_does_not_move_a_fixture(monkeypatch):
    """Version metadata changes leave the normalized drawing unchanged."""
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
    """Round a coordinate to the SVG serialization precision.

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


@pytest.mark.parametrize("name", list(SCENARIOS), ids=list(SCENARIOS))
def test_no_sheet_draws_a_nozzle_off_the_body_it_belongs_to(settled_gallery, name):
    """Every rendered nozzle lies on its owning equipment body."""
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


def test_only_representative_examples_have_golden_fixtures():
    """Store exact SVG fixtures only for the representative coverage set."""
    assert sorted(path.stem for path in GOLDEN_DIR.glob("*.svg")) == list(GOLDEN_SCENARIOS)


def test_the_fractionator_schedules_only_equipment_that_exists():
    """The bottoms product leaves through the scheduled reboiler."""
    fs = SCENARIOS["06_column_reflux"][0]()
    col = next(u for u in fs.units if u.name == "T-701")
    reb = next(u for u in fs.units if u.name == "E-702")
    assert col.bottoms.stream.dest.owner is reb  # nothing invented in the sump
    assert reb.bottoms.stream is not None
    assert reb.bottoms.stream.dest.owner.name == "Bottoms"
    assert [tag for tag, _ in equipment_list(fs).rows] == [
        "T-701",
        "E-701",
        "V-701",
        "E-702",
    ]
