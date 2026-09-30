"""Test crossing-style rendering, export, validation, and public APIs."""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from _render_cases import copy_settled_case
from pandid import Flowsheet, spec, units as U
from pandid.cli import EXIT_OK, EXIT_USAGE, main
from pandid.geometry import Route
from pandid.render.drawio import _JUMP_STYLES, DrawioRenderer
from pandid.render.svg import (
    CROSSING_STYLE_DEFAULT,
    CROSSING_STYLES,
    CROSSING_UNMARKED,
    HOP_R,
    SvgRenderer,
    check_crossing_style,
    stream_polyline,
    unmarked_crossings,
)

MARKED = (
    "11_ethanol_pid",
    "16_demineralised_water",
    "18_fixed_bed_recycle",
)
_DRAWIO_KWARGS = (
    "diagram",
    "page_size",
    "border",
    "show_stream_table",
    "connections",
    "jump_direction",
)

_ARC = f"A {HOP_R:g} {HOP_R:g} 0 0 1 "


def _paths(svg: str) -> list[str]:
    """Return process-stream paths from an SVG document.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    list[str]
        Stream path commands in drawing order.
    """
    group = svg.split('<g id="streams">', 1)[1].split("</g>", 1)[0]
    return re.findall(r'<path d="(M [^"]*)" fill="none"', group)


def _marks(svg: str) -> tuple[int, int]:
    """Count crossing arcs and interruptions in an SVG document.

    Parameters
    ----------
    svg : str
        Rendered SVG document.

    Returns
    -------
    tuple[int, int]
        Arc count followed by interruption count.
    """
    paths = _paths(svg)
    return (sum(d.count(_ARC) for d in paths), sum(d.count("M ") - 1 for d in paths))


def _jumps(document: str) -> dict[str, str]:
    """Return Draw.io jump styles by edge identifier.

    Parameters
    ----------
    document : str
        Draw.io XML document.

    Returns
    -------
    dict[str, str]
        Non-plain jump styles keyed by edge identifier.
    """
    root = ET.fromstring(document).find("diagram/mxGraphModel/root")
    assert root is not None
    out = {}
    for cell in root.iter("mxCell"):
        style = dict(
            part.split("=", 1)  # pyright: ignore[reportArgumentType]
            for part in (cell.get("style") or "").split(";")
            if "=" in part
        )
        if style.get("jumpStyle", "none") != "none":
            out[cell.get("id") or ""] = style["jumpStyle"]
    return out


def _edge_order(document: str) -> list[str]:
    """Return stream edge identifiers in document order.

    Parameters
    ----------
    document : str
        Draw.io XML document.

    Returns
    -------
    list[str]
        Stream edge identifiers in document order.
    """
    root = ET.fromstring(document).find("diagram/mxGraphModel/root")
    assert root is not None
    return [
        cell.get("id") or ""
        for cell in root.iter("mxCell")
        if cell.get("edge") == "1" and re.fullmatch(r"s\d+", cell.get("id") or "")
    ]


def _found(fs: Flowsheet) -> list[Any]:
    """Return unmarked-crossing warnings from a flowsheet.

    Parameters
    ----------
    fs : Flowsheet
        Rendered flowsheet to inspect.

    Returns
    -------
    list[Any]
        Warnings with the unmarked-crossing code.
    """
    return [w for w in fs.warnings if w.code == CROSSING_UNMARKED]


def _pair(bend: float | None = None) -> Flowsheet:
    """Build a two-stream flowsheet with an optional manual crossing.

    Parameters
    ----------
    bend : float | None
        Vertical coordinate for the manual detour.

    Returns
    -------
    Flowsheet
        Settled two-stream flowsheet with an optional manual route.
    """
    fs = Flowsheet("crossing")
    a = fs.add(U.Feed("F1")).pin(x=60, y=175)
    b = fs.add(U.Product("P1")).pin(x=600, y=175)
    c = fs.add(U.Feed("F2")).pin(x=60, y=375)
    d = fs.add(U.Product("P2")).pin(x=600, y=375)
    fs.connect(a.outlet, b.inlet)
    run = fs.connect(c.outlet, d.inlet)
    fs.layout()
    fs.route()
    fs.renumber_streams()
    if bend is not None:
        run.route = Route(waypoints=[(300.0, 375.0), (300.0, bend), (400.0, bend), (400.0, 375.0)])
    return fs


ROOMY = 100.0
TIGHT = 171.0


def _svg(fs: Flowsheet, **opts: Any) -> str:
    """Render a flowsheet with the SVG backend.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to render.
    **opts : Any
        SVG rendering options.

    Returns
    -------
    str
        SVG document.
    """
    return SvgRenderer().render(fs, **opts)


def _drawio(fs: Flowsheet, **opts: Any) -> str:
    """Render a flowsheet with the Draw.io backend.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to render.
    **opts : Any
        Draw.io rendering options.

    Returns
    -------
    str
        Draw.io XML document.
    """
    return DrawioRenderer().render(fs, **opts)


@pytest.mark.parametrize("stem", MARKED, ids=MARKED)
def test_naming_the_default_draws_what_not_naming_it_draws(
    settled_gallery: dict[str, tuple[Flowsheet, dict[str, Any]]], stem: str
) -> None:
    """Check that naming the default preserves SVG and Draw.io output.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict[str, Any]]]
        Session-scoped routed gallery source.
    stem : str
        Representative gallery example name.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    default = fs.to_svg(**kwargs)
    assert sum(_marks(default)) > 0, f"{stem} has no crossing and proves nothing"
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    assert fs.to_svg(**kwargs, crossing_style=CROSSING_STYLE_DEFAULT) == default

    export = {k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS}
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    fs.to_svg(**kwargs)
    plain_call = fs.to_drawio(**export)
    assert _jumps(plain_call), f"{stem} exports no jump and proves nothing"
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    fs.to_svg(**kwargs)
    assert fs.to_drawio(**export, crossing_style=CROSSING_STYLE_DEFAULT) == plain_call


def test_each_style_draws_its_own_mark_and_nothing_else():
    """Check each style against an equivalent uncrossed stream.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    arc = _svg(_pair(ROOMY), crossing_style="arc")
    gap = _svg(_pair(ROOMY), crossing_style="gap")
    plain = _svg(_pair(ROOMY), crossing_style="plain")

    assert _marks(arc) == (2, 0), "the arc bridges both crossings in one subpath"
    assert _marks(gap) == (0, 2), "the interruption breaks the run at both"
    assert _marks(plain) == (0, 0), "a plain crossing marks neither"
    straight = _paths(_svg(_pair(None)))
    turned = [d for d in _paths(plain) if "300" in d]
    assert len(turned) == 1
    assert turned[0].count("L ") == 5, "the vertical run keeps all five legs"
    assert _ARC not in turned[0] and turned[0].count("M ") == 1
    assert len(straight) == len(_paths(plain))


def test_the_mark_takes_the_same_run_whichever_mark_it_is():
    """Check that arcs and interruptions use the same stream extent.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    arc_run = [d for d in _paths(_svg(_pair(ROOMY), crossing_style="arc")) if _ARC in d][0]
    gap_run = [d for d in _paths(_svg(_pair(ROOMY), crossing_style="gap")) if d.count("M ") > 1][0]
    point = re.compile(r"[LMA][^LMA]*?([\d.]+),([\d.]+)")
    arc_points = point.findall(arc_run)
    assert arc_points == point.findall(gap_run), (
        "the two marks end at the same points, so the run they take out is "
        "the same run and a sheet redrawn in the other convention needs "
        "nothing else to move"
    )
    ys = {float(y) for x, y in arc_points if float(x) == 300.0}
    assert {175.0 - HOP_R, 175.0 + HOP_R} <= ys


def test_the_interruption_leaves_one_line_and_not_two():
    """Check that an interruption remains one SVG path.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(ROOMY)
    gap = _svg(fs, crossing_style="gap")
    assert len(_paths(gap)) == len(_paths(_svg(_pair(ROOMY))))
    broken = [d for d in _paths(gap) if d.count("M ") > 1][0]
    run = stream_polyline(fs.streams[1])
    assert broken.startswith(f"M {run[0][0]},")
    assert broken.endswith(f"L {run[-1][0]},{run[-1][1]}"), (
        "the last command is the run reaching its own end, so marker-end "
        "lands there and not at the break"
    )


@pytest.mark.parametrize("style", CROSSING_STYLES, ids=CROSSING_STYLES)
@pytest.mark.parametrize("stem", MARKED, ids=MARKED)
def test_the_export_marks_the_runs_the_sheet_marks_and_marks_them_alike(
    settled_gallery: dict[str, tuple[Flowsheet, dict[str, Any]]], stem: str, style: str
) -> None:
    """Check SVG and Draw.io style parity on representative sheets.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict[str, Any]]]
        Session-scoped routed gallery source.
    stem : str
        Representative gallery example name.
    style : str
        Requested crossing style.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs, kwargs = copy_settled_case(settled_gallery, stem)
    paths = _paths(fs.to_svg(**kwargs, crossing_style=style))
    assert len(paths) == len(fs.streams)
    marked = {n for n, d in enumerate(paths) if _ARC in d or d.count("M ") > 1}
    export = {k: v for k, v in kwargs.items() if k in _DRAWIO_KWARGS}
    document = fs.to_drawio(**export, crossing_style=style)
    jumps = _jumps(document)

    if style == "plain":
        assert not jumps, f"{stem}: plain crossings, and the export hops anyway"
        assert not marked, f"{stem}: plain crossings, and the sheet marked one"
        order = _edge_order(document)
        assert order == sorted(order, key=lambda i: int(i[1:])), (
            f"{stem}: nothing hops, so nothing had to be written after "
            f"anything, and the edges must come out in stream order"
        )
        return

    assert marked, f"{stem}: no run marked, so this case proves nothing"
    assert set(jumps) <= {f"s{n}" for n in marked}, (
        f"{stem}: the export marks {sorted(set(jumps))}, the sheet marks "
        f"{sorted(f's{n}' for n in marked)} -- a mark the sheet does not draw "
        f"states the wrong pipe passes over"
    )
    assert set(jumps.values()) == {_JUMP_STYLES[style]}, (
        f"{stem}: exported as {sorted(set(jumps.values()))}, drawn as {style}"
    )


def test_the_export_writes_one_jump_size_for_either_mark():
    """Check Draw.io jump-size consistency across marked styles.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(ROOMY)
    arc = _drawio(fs, crossing_style="arc")
    gap = _drawio(fs, crossing_style="gap")
    sizes = [set(re.findall(r"jumpSize=(\d+)", doc)) for doc in (arc, gap)]
    assert sizes[0] and sizes[0] == sizes[1]
    assert arc.replace("jumpStyle=arc", "jumpStyle=gap") == gap, (
        "the style is the only thing that differs between the two exports"
    )


@pytest.mark.parametrize("bad", ["", "none", "Arc", "hop", "break", "arcs", "gap "])
def test_an_unknown_crossing_style_is_refused_and_names_what_is_accepted(bad: str) -> None:
    """Check invalid style validation and diagnostics.

    Parameters
    ----------
    bad : str
        Invalid crossing-style value.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    with pytest.raises(ValueError) as raised:
        check_crossing_style(bad)
    message = str(raised.value)
    assert "crossing_style" in message
    assert repr(bad) in message
    for name in CROSSING_STYLES:
        assert repr(name) in message


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Capture preview SVG without opening a window.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest monkeypatch fixture.

    Returns
    -------
    dict[str, str]
        Preview SVG keyed by ``"svg"``.
    """
    from pandid.render import preview as P

    seen: dict[str, str] = {}

    def fake(svg: str, *, title: str = "") -> str:
        """Capture a preview SVG without opening a window.

        Parameters
        ----------
        svg : str
            SVG document passed to the preview backend.
        title : str, default=""
            Preview window title.

        Returns
        -------
        str
            Fixed preview result.
        """
        seen["svg"] = svg
        return "window"

    monkeypatch.setattr(P, "preview", fake)
    return seen


@pytest.mark.parametrize("call", ["to_svg", "to_drawio", "render", "show"])
def test_every_call_that_takes_the_word_refuses_a_word_it_cannot_draw(
    call: str, tmp_path: pathlib.Path, shown: dict[str, str]
) -> None:
    """Check public entry points reject invalid crossing styles.

    Parameters
    ----------
    call : str
        Public rendering method name.
    tmp_path : pathlib.Path
        Temporary output directory.
    shown : dict[str, str]
        Captured preview documents.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(ROOMY)
    out = tmp_path / "sheet.svg"
    with pytest.raises(ValueError, match="crossing_style"):
        if call == "render":
            fs.render(out, crossing_style="hop", check=False)
        elif call == "show":
            fs.show(crossing_style="hop", check=False)
        else:
            getattr(fs, call)(crossing_style="hop", check=False)
    assert not out.exists(), "a refused option must not leave a drawing behind"
    assert not shown, "a refused option must not have been drawn either"


def test_every_entry_point_hands_the_word_on(tmp_path: pathlib.Path, shown: dict[str, str]) -> None:
    """Check public entry points preserve the requested crossing style.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary output directory.
    shown : dict[str, str]
        Captured preview documents.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    svg = tmp_path / "sheet.svg"
    drawio = tmp_path / "sheet.drawio"
    _pair(ROOMY).render(svg, crossing_style="arc", check=False)
    assert svg.read_text(encoding="utf-8") == _pair(ROOMY).to_svg(crossing_style="arc", check=False)
    assert svg.read_text(encoding="utf-8") != _pair(ROOMY).to_svg(check=False), (
        "...and the two really are different drawings, or this proves nothing"
    )
    _pair(ROOMY).render(drawio, crossing_style="arc", check=False)
    assert drawio.read_text(encoding="utf-8") == _pair(ROOMY).to_drawio(
        crossing_style="arc", check=False
    )
    _pair(ROOMY).show(crossing_style="arc", check=False)
    assert shown["svg"] == _pair(ROOMY).to_svg(crossing_style="arc", check=False)


def test_both_renderers_refuse_it_too():
    """Check direct renderers reject invalid crossing styles.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(ROOMY)
    for renderer in (SvgRenderer(), DrawioRenderer()):
        with pytest.raises(ValueError, match="crossing_style"):
            renderer.render(fs, crossing_style="semicircle")


_SPEC = """\
{"name": "Skid",
 "units": [{"kind": "Feed", "name": "Raw Feed"},
           {"kind": "Pump", "name": "P-101"},
           {"kind": "Product", "name": "To Unit 200"}],
 "streams": [{"from": ["Raw Feed", "outlet"], "to": ["P-101", "suction"]},
             {"from": ["P-101", "discharge"], "to": ["To Unit 200", "inlet"]}]}
"""


def test_the_shell_offers_exactly_the_three_the_api_offers(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Check CLI choices and forwarding match the rendering API.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary output directory.
    capsys : pytest.CaptureFixture[str]
        Captured CLI output fixture.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    spec_file = tmp_path / "sheet.json"
    spec_file.write_text(_SPEC, encoding="utf-8")
    out = tmp_path / "cli.svg"
    argv = ["draw", str(spec_file), "-o", str(out), "--crossing-style", "gap"]
    assert main(argv) == EXIT_OK
    capsys.readouterr()
    assert out.read_text(encoding="utf-8") == spec.from_json(spec_file).to_svg(crossing_style="gap")
    assert main(["draw", str(spec_file), "-o", str(out), "--crossing-style", "hop"]) == EXIT_USAGE


def test_the_model_does_not_carry_the_crossing_style():
    """Check crossing style remains a rendering option.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(ROOMY)
    before = fs.to_dict()
    fs.to_svg(crossing_style="gap", check=False)
    assert fs.to_dict() == before
    assert "crossing_style" not in repr(before)
    assert "jump_direction" not in repr(before)
    with pytest.raises(spec.SpecError, match="crossing_style"):
        spec.from_dict({**before, "crossing_style": "gap"})


@pytest.mark.parametrize("style", ["arc", "gap"])
def test_a_crossing_with_no_room_for_its_mark_is_reported(style: str) -> None:
    """Check an unmarkable crossing produces a style-specific warning.

    Parameters
    ----------
    style : str
        Requested crossing style.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(TIGHT)
    svg = _svg(fs, crossing_style=style)
    assert _marks(svg) == (0, 0), "no mark fits, so none is drawn"
    findings = _found(fs)
    assert len(findings) == 2, "two crossings drawn bare, two said out loud"
    mark = "arc" if style == "arc" else "interruption"
    for finding in findings:
        assert finding.severity == "warning"
        assert "S1" in finding.message and "S2" in finding.message
        assert "175" in finding.message, "the point a reader has to go and look at"
        assert f"the {mark} marking a crossing" in finding.message, (
            "the finding names the mark the sheet was drawing, not the arc"
        )
        assert "via()" in finding.message, "and what to do about it"
        assert "crossing_style='plain'" in finding.message, (
            "...including the cure #499 made available"
        )


def test_a_plain_sheet_reports_nothing_because_it_promised_nothing():
    """Check plain crossings suppress unmarked-crossing warnings.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(TIGHT)
    _svg(fs)
    assert _found(fs), (
        "the fixture reports nothing at the default style, so the assertion "
        "below would pass on a sheet that had nothing to silence"
    )
    _svg(fs, crossing_style="plain")
    assert not _found(fs)


def test_the_finding_counts_the_crossings_the_sheet_left_bare():
    """Check warnings equal the rendered model's unmarked crossings.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    for bend, marks in ((ROOMY, 2), (TIGHT, 0)):
        fs = _pair(bend)
        svg = _svg(fs)
        assert sum(_marks(svg)) == marks
        assert len(unmarked_crossings(fs)) == _crossings(fs) - marks
        assert len(_found(fs)) == _crossings(fs) - marks


def _crossings(fs: Flowsheet) -> int:
    """Count strict orthogonal crossings from stream geometry.

    Parameters
    ----------
    fs : Flowsheet
        Flowsheet to inspect or render.

    Returns
    -------
    int
        Number of strict vertical-horizontal crossings.
    """
    horizontal, vertical = [], []
    for s in fs.streams:
        points = stream_polyline(s)
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if y1 == y2 and x1 != x2:
                horizontal.append((s, min(x1, x2), max(x1, x2), y1))
            elif x1 == x2 and y1 != y2:
                vertical.append((s, min(y1, y2), max(y1, y2), x1))
    return sum(
        1
        for run, lo, hi, at in vertical
        for other, c_lo, c_hi, c_at in horizontal
        if run is not other and c_lo < at < c_hi and lo < c_at < hi
    )


def test_a_crossing_moved_clear_stops_being_reported():
    """Check rerendering removes resolved crossing warnings.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    fs = _pair(TIGHT)
    _svg(fs)
    assert _found(fs)
    fs.streams[1].route = Route(
        waypoints=[(300.0, 375.0), (300.0, ROOMY), (400.0, ROOMY), (400.0, 375.0)]
    )
    _svg(fs)
    assert not _found(fs)


def test_the_settled_gallery_has_no_unmarked_crossings(
    settled_gallery: dict[str, tuple[Flowsheet, dict[str, Any]]],
) -> None:
    """Check that every shipped route has enough clearance for default marks.

    Parameters
    ----------
    settled_gallery : dict[str, tuple[Flowsheet, dict[str, Any]]]
        Session-scoped routed gallery source.

    Returns
    -------
    None
        Assertion result for default crossing clearance.
    """
    crossings = 0
    for stem, (flowsheet, options) in settled_gallery.items():
        crossings += _crossings(flowsheet)
        direction = options.get("jump_direction", "vertical")
        assert not unmarked_crossings(flowsheet, direction), stem
    assert crossings, "the gallery has no crossings to check"


def test_every_crossing_style_default_is_the_package_default():
    """Check public parameters use the package crossing-style default.

    Returns
    -------
    None
        Assertion result for the stated behaviour.
    """
    import inspect
    import pkgutil
    import importlib

    import pandid
    from pandid.render.svg import CROSSING_STYLE_DEFAULT, CROSSING_STYLES

    assert CROSSING_STYLE_DEFAULT in CROSSING_STYLES

    seen = 0
    for info in pkgutil.walk_packages(pandid.__path__, "pandid."):
        module = importlib.import_module(info.name)
        for _, obj in inspect.getmembers(module, inspect.isfunction):
            if obj.__module__ != info.name:
                continue
            parameter = inspect.signature(obj).parameters.get("crossing_style")
            if parameter is None or parameter.default is inspect.Parameter.empty:
                continue
            seen += 1
            assert parameter.default == CROSSING_STYLE_DEFAULT, (
                f"{info.name}.{obj.__qualname__} defaults crossing_style to "
                f"{parameter.default!r}, not {CROSSING_STYLE_DEFAULT!r}"
            )
    assert seen, "no crossing_style parameter was found, so nothing was checked"
