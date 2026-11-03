#!/usr/bin/env python3
"""Compare each example as authored with the same example with its placement stripped.

    python scripts/layout_quality.py                    # every example
    python scripts/layout_quality.py 10_ethanol_pfd      # one of them
    python scripts/layout_quality.py --render OUT_DIR    # also write auto SVG/PNG
    python scripts/layout_quality.py --worst 15          # widen the offender lists

Print each variant's extent, page fit, ``layout()`` time and ``validate()``
counts, then the routing tables of ``scripts/route_quality.py``. Write nothing
under ``docs/gallery/``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import gallery  # noqa: E402
import route_quality  # noqa: E402

import pandid.portgeom as portgeom_mod  # noqa: E402
import pandid.streams as streams_mod  # noqa: E402
import pandid.units as units_mod  # noqa: E402
from pandid.flowsheet import Flowsheet  # noqa: E402
from pandid.render.svg import _PAGE_SIZES, _PX_PER_MM  # noqa: E402
from pandid.validate import Issue  # noqa: E402

Extent = tuple[float, float, float, float]  # x0, y0, x1, y1

# ---------------------------------------------------------------------------
# Stripping placement
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def strip_placement():
    """Strip placement from every example built inside the ``with`` block.

    ``pin()`` keeps ``orientation=`` and ``mirrored=`` and drops ``col``,
    ``row``, ``x``, ``y`` and ``port``. ``Stream.via()`` does nothing, and
    ``pinned_x()``/``pinned_y()`` return ``0.0``. Restore all four on exit.
    """
    original_pin = units_mod.Unit.pin
    original_via = streams_mod.Stream.via
    original_pinned_x = portgeom_mod.pinned_x
    original_pinned_y = portgeom_mod.pinned_y

    _UNCHANGED = units_mod._UNCHANGED
    _UNSTATED = units_mod._UNSTATED

    def stripped_pin(self, *, col=None, row=None, x=None, y=None,
                      orientation=_UNCHANGED, mirrored=_UNCHANGED, port=_UNSTATED):
        return original_pin(self, col=None, row=None, x=None, y=None,
                             orientation=orientation, mirrored=mirrored, port=None)

    def stripped_via(self, waypoints):
        return self

    def dummy_axis(unit, port_name=None):
        return 0.0

    units_mod.Unit.pin = stripped_pin
    streams_mod.Stream.via = stripped_via
    portgeom_mod.pinned_x = dummy_axis
    portgeom_mod.pinned_y = dummy_axis
    try:
        yield
    finally:
        units_mod.Unit.pin = original_pin
        streams_mod.Stream.via = original_via
        portgeom_mod.pinned_x = original_pinned_x
        portgeom_mod.pinned_y = original_pinned_y


def build(stem: str, auto: bool) -> tuple[Flowsheet, dict]:
    """The flowsheet *stem*'s example builds, placement stripped if *auto*.

    A fresh build every call (:func:`gallery.flowsheet` re-imports the
    example module each time), which is what both the timing loop and a
    correctness-minded caller want: nothing carried over from a previous
    run's mutated units.
    """
    if auto:
        with strip_placement():
            with contextlib.redirect_stdout(io.StringIO()):
                return gallery.flowsheet(stem)
    with contextlib.redirect_stdout(io.StringIO()):
        return gallery.flowsheet(stem)


# ---------------------------------------------------------------------------
# Sheet extent and page fit
# ---------------------------------------------------------------------------

def page_px(page_size: Optional[str]) -> Optional[tuple[float, float]]:
    if page_size is None:
        return None
    mm = _PAGE_SIZES.get(page_size.upper())
    return None if mm is None else (mm[0] * _PX_PER_MM, mm[1] * _PX_PER_MM)


def sheet_extent(fs: Flowsheet) -> Optional[Extent]:
    """The bounding box of every unit's resolved frame, or ``None`` before
    a sheet has been laid out.

    Read after ``route()``, not just ``layout()``: an attached balloon's
    frame is only settled once ``place_attached`` has run against the
    drawn routes (see ``pandid/layout/__init__.py``), and ``route()`` is
    what runs that to a fixed point.
    """
    frames = [u.frame for u in fs.units if u.frame is not None]
    if not frames:
        return None
    return (
        min(f.x for f in frames),
        min(f.y for f in frames),
        max(f.x_max for f in frames),
        max(f.y_max for f in frames),
    )


# ---------------------------------------------------------------------------
# One sheet, one variant
# ---------------------------------------------------------------------------


@dataclass
class LayoutReport:
    stem: str
    auto: bool
    route: "route_quality.SheetReport"
    issues: list[Issue] = field(default_factory=list)
    extent: Optional[Extent] = None
    page_size: Optional[str] = None
    layout_s: float = 0.0

    @property
    def extent_wh(self) -> Optional[tuple[float, float]]:
        if self.extent is None:
            return None
        x0, y0, x1, y1 = self.extent
        return x1 - x0, y1 - y0

    @property
    def aspect(self) -> Optional[float]:
        wh = self.extent_wh
        return None if wh is None or wh[1] <= 0 else wh[0] / wh[1]

    @property
    def fit_scale(self) -> Optional[float]:
        """What ``page_size`` would draw this sheet at, approximately.

        ``pandid/render/svg.py``'s ``_fit_scale`` never enlarges a small
        drawing (fixed furniture would swell out of proportion) and
        shrinks a large one just enough to clear the free region left
        after the title strip, border and any docked boxes claim their
        share of the page. This computes the same ``min(1.0, page/content)``
        against the *whole* page, without subtracting that furniture, so
        it is an optimistic upper bound: the real render's scale is this
        number or smaller. A sheet with no ``page_size`` (fit-to-content)
        has no scale to report.
        """
        wh = self.extent_wh
        page = page_px(self.page_size)
        if wh is None or page is None:
            return None
        return min(1.0, page[0] / wh[0] if wh[0] > 0 else 1.0,
                    page[1] / wh[1] if wh[1] > 0 else 1.0)

    @property
    def errors(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def issue_count(self, code: str) -> int:
        return sum(1 for i in self.issues if i.code == code)


def measure_variant(stem: str, auto: bool, layout_repeat: int = 5) -> LayoutReport:
    """Time ``layout()`` (best of *layout_repeat* fresh builds), then
    measure a further fresh build fully -- reusing
    ``route_quality.measure_sheet`` for the routing half and
    ``Flowsheet.validate`` for the geometry findings.
    """
    best = float("inf")
    for _ in range(layout_repeat):
        fs, _kwargs = build(stem, auto)
        t0 = time.perf_counter()
        fs.layout()
        best = min(best, time.perf_counter() - t0)

    fs, kwargs = build(stem, auto)
    name = f"{stem}+auto" if auto else stem
    route_report = route_quality.measure_sheet(fs, name)
    issues = fs.validate(diagram=kwargs.get("diagram"))
    return LayoutReport(
        stem=stem, auto=auto, route=route_report, issues=issues,
        extent=sheet_extent(fs), page_size=kwargs.get("page_size"), layout_s=best,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_layout_table(reports: list[LayoutReport]) -> None:
    header = (
        f"{'sheet':<26}{'var':<7}{'units':>6}{'w':>7}{'h':>7}{'aspect':>7}"
        f"{'scale':>7}{'layout':>9}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        wh = r.extent_wh
        w = f"{wh[0]:.0f}" if wh else "n/a"
        h = f"{wh[1]:.0f}" if wh else "n/a"
        asp = f"{r.aspect:.2f}" if r.aspect is not None else "n/a"
        scale = r.fit_scale
        scale_s = "n/a" if scale is None else ("1:1" if scale >= 1.0 else f"1:{1 / scale:.2g}")
        variant = "auto" if r.auto else "pinned"
        print(f"{r.stem:<26}{variant:<7}{r.route.units:>6}{w:>7}{h:>7}{asp:>7}"
              f"{scale_s:>7}{r.layout_s * 1000:>7.1f}ms")
    print("-" * len(header))


def print_validate_table(reports: list[LayoutReport]) -> None:
    header = (
        f"{'sheet':<26}{'var':<7}{'errors':>7}{'warnings':>9}"
        f"{'unit-ovl':>9}{'rt-x-unit':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        variant = "auto" if r.auto else "pinned"
        print(f"{r.stem:<26}{variant:<7}{r.errors:>7}{r.warnings:>9}"
              f"{r.issue_count('unit-overlap'):>9}{r.issue_count('route-crosses-unit'):>10}")
    print("-" * len(header))


def print_deltas(pinned: list[LayoutReport], auto: list[LayoutReport]) -> None:
    """One line per sheet: what changed, pinned to auto, in the numbers
    that matter most -- area, crossings, errors."""
    print(f"\n{'sheet':<26}{'area x':>8}{'crossings':>11}{'errors':>8}{'warnings':>10}")
    by_stem_auto = {r.stem: r for r in auto}
    for p in pinned:
        a = by_stem_auto.get(p.stem)
        if a is None:
            continue
        p_wh, a_wh = p.extent_wh, a.extent_wh
        if p_wh and a_wh and p_wh[0] * p_wh[1] > 0:
            area_x = f"{(a_wh[0] * a_wh[1]) / (p_wh[0] * p_wh[1]):.2f}"
        else:
            area_x = "n/a"
        print(f"{p.stem:<26}{area_x:>8}"
              f"{len(p.route.crossings):>5} ->{len(a.route.crossings):>3}"
              f"{p.errors:>4} ->{a.errors:>3}"
              f"{p.warnings:>5} ->{a.warnings:>4}")


def render_auto(stems: list[str], outdir: pathlib.Path) -> None:
    """Write ``{stem}_auto.svg``/``.png`` for each sheet in *stems*, for
    visual inspection -- never into ``docs/gallery/``, which is the
    hand-placed corpus this script measures against, not a target.

    Rendered with ``check=False``: a colliding auto-placed sheet should
    still be *seen*, not refused. ``measure_variant`` already gathers
    ``validate()``'s findings separately, without that suppression.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        fs, kwargs = build(stem, auto=True)
        render_kwargs = dict(kwargs)
        render_kwargs["check"] = False
        svg = gallery.normalize(fs.to_svg(**render_kwargs))
        svg_path = outdir / f"{stem}_auto.svg"
        svg_path.write_text(svg, encoding="utf-8")
        try:
            png = gallery.rasterize(svg)
        except Exception as exc:  # optional [pdf] backend not installed
            print(f"wrote {svg_path} (PNG skipped: {exc})")
            continue
        png_path = outdir / f"{stem}_auto.png"
        png_path.write_bytes(png)
        print(f"wrote {svg_path} and {png_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("sheet", nargs="*", help="example stems; default is all of them")
    ap.add_argument("--render", metavar="DIR", type=pathlib.Path, default=None,
                     help="also write auto-placed SVG/PNG for each sheet into DIR")
    ap.add_argument("--repeat", type=int, default=5,
                     help="layout() timing passes per sheet, best wins (default 5)")
    ap.add_argument("--worst", type=int, default=10,
                     help="offenders listed per category (default 10)")
    args = ap.parse_args()

    known = gallery.sheets()
    stems = args.sheet or known
    for stem in stems:
        if stem not in known:
            raise SystemExit(f"no such example: {stem}\nknown sheets: {', '.join(known)}")

    pinned = [measure_variant(s, auto=False, layout_repeat=args.repeat) for s in stems]
    auto = [measure_variant(s, auto=True, layout_repeat=args.repeat) for s in stems]

    print("=== extent, aspect, page fit, layout time ===")
    print_layout_table(pinned + auto)

    print("\n=== validate() findings ===")
    print_validate_table(pinned + auto)

    print_deltas(pinned, auto)

    print("\n=== routing quality: pinned corpus (scripts/route_quality.py) ===")
    route_quality.print_sheet_table([r.route for r in pinned])
    route_quality.print_crossing_summary([r.route for r in pinned])

    print("\n=== routing quality: auto-placed corpus ===")
    route_quality.print_sheet_table([r.route for r in auto])
    route_quality.print_crossing_summary([r.route for r in auto])
    route_quality.print_undrawn([r.route for r in auto])
    route_quality.print_worst([r.route for r in auto], args.worst)

    if args.render is not None:
        print(f"\n=== rendering auto-placed sheets to {args.render} ===")
        render_auto(stems, args.render)


if __name__ == "__main__":
    main()
