#!/usr/bin/env python3
"""Capture and compare drawing quality across the shipped examples.

Run ``snapshot --output baseline.json`` before an engine change and again with
a different output path afterward. Each snapshot writes SVG and PNG previews
beside its JSON file. Run ``compare --baseline baseline.json --candidate
candidate.json --review review.json`` to apply the release gate.

The review JSON maps a sheet stem to S1-S4 and G1-G4 findings. Changed authored
sheets use ``stem|authored``. Each finding gives ``verdict``, ``reason``, and the
exact ``before`` and ``after`` image paths recorded in the snapshots.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import gallery  # noqa: E402
import layout_quality  # noqa: E402
import route_quality  # noqa: E402

from pandid.layout.claims import read as read_claims  # noqa: E402
from pandid.layout.stages import process_streams, process_units  # noqa: E402
from pandid.portgeom import resolve_port, unit_box  # noqa: E402

HARD_KEYS = (
    "errors",
    "fallback",
    "route_crosses_unit",
    "unit_overlap",
    "undrawn",
    "pin_not_honored",
    "route_diagonal",
    "route_not_settled",
    "instrument_unplaced",
)
TOTAL_KEYS = ("crossings", "bends", "length", "area")
RULES = ("S1", "S2", "S3", "S4", "G1", "G2", "G3", "G4")
BASE_HEAD = "d8b59235ea7718e3216e2b2db2a64f4d500fb2aa"
BASE_STEMS = (
    "01_ammonia_loop",
    "02_manual_layout",
    "03_distillation_train",
    "04_control_loop",
    "05_reactor_recycle",
    "06_column_reflux",
    "07_metering_skid",
    "08_from_data",
    "09_line_numbers",
    "10_ethanol_pfd",
    "11_ethanol_pid",
    "12_block_flow_diagram",
    "13_mineral_dewatering",
    "14_tank_farm",
    "15_condensing_turbine",
    "16_demineralised_water",
    "17_stirred_reactor_train",
    "18_fixed_bed_recycle",
    "19_absorber_stripper",
    "20_molecular_sieve_dryer",
    "21_alumina_refinery",
)


@dataclass
class Comparison:
    """Classification and release-gate result for a snapshot pair.

    Attributes
    ----------
    passed : bool
        Whether the candidate satisfies every release criterion.
    improved, regressed, unchanged : list[str]
        Sheet stems in each exclusive comparison group.
    reasons : dict[str, list[str]]
        Per-sheet regression or missing-evidence explanations.
    aggregates : dict[str, tuple[float, float]]
        Baseline and candidate totals for each drawing metric.
    gate_reasons : list[str]
        Corpus-level reasons the release gate cannot pass.
    """

    passed: bool
    improved: list[str]
    regressed: list[str]
    unchanged: list[str]
    reasons: dict[str, list[str]]
    aggregates: dict[str, tuple[float, float]]
    gate_reasons: list[str]


def _round(value: float) -> float:
    """Round a measured coordinate for stable snapshot serialization.

    Parameters
    ----------
    value : float
        Coordinate or duration to serialize.

    Returns
    -------
    float
        Value rounded to six decimal places.
    """
    return round(value, 6)


def _fingerprint(fs) -> str:
    """Hash the resolved frames, port faces, routes, and convergence state.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out and routed flowsheet.

    Returns
    -------
    str
        SHA-256 digest of the normalized drawing geometry.
    """
    geometry = {
        "units": [
            (
                u.name,
                None
                if u.frame is None
                else (
                    _round(u.frame.x),
                    _round(u.frame.y),
                    _round(u.frame.w),
                    _round(u.frame.h),
                    u.frame.col,
                    u.frame.row,
                    u.frame.orientation,
                    u.frame.mirrored,
                    u.frame.mirror_y,
                    u.frame.label_pos,
                    sorted(u.frame.port_faces.items()),
                ),
            )
            for u in fs.units
        ],
        "streams": [
            (
                s.name,
                None
                if s.route is None
                else (
                    s.route.manual,
                    [(_round(x), _round(y)) for x, y in s.route.waypoints],
                ),
            )
            for s in fs.streams
        ],
        "converged": fs.route_converged,
    }
    encoded = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _largest_empty_band(boxes: list[tuple[float, float, float, float]], axis: int) -> float:
    """Find the largest gap between equipment boxes on one axis.

    Parameters
    ----------
    boxes : list[tuple[float, float, float, float]]
        Equipment bounds as ``(x0, y0, x1, y1)``.
    axis : int
        Coordinate index, zero for x and one for y.

    Returns
    -------
    float
        Width of the largest gap, or zero without boxes.
    """
    if not boxes:
        return 0.0
    spans = sorted((box[axis], box[axis + 2]) for box in boxes)
    end = spans[0][1]
    largest = 0.0
    for start, stop in spans[1:]:
        largest = max(largest, start - end)
        end = max(end, stop)
    return _round(largest)


def _proxy(
    value: float | int | None,
    *,
    note: str = "",
    status: str | None = None,
    offenders: list[str] | None = None,
) -> dict:
    """Package a rule signal with its measurement status.

    Parameters
    ----------
    value : float or int or None
        Signal value, or ``None`` when no measurement exists.
    note : str, optional
        Explanation of a diagnostic or unavailable signal.
    status : str or None, optional
        Explicit status overriding the status inferred from ``value``.
    offenders : list[str] or None, optional
        Streams or unit pairs contributing to the signal.

    Returns
    -------
    dict
        JSON-ready signal record.
    """
    return {
        "status": status or ("measured" if value is not None else "not_measured"),
        "value": value,
        "note": note,
        "offenders": offenders or [],
    }


def _proxies(fs, extent, fit_scale: float | None, route_report) -> dict:
    """Measure available structure and geometry rule signals.

    Parameters
    ----------
    fs : Flowsheet
        Final flowsheet geometry to inspect.
    extent : tuple[float, float, float, float] or None
        Drawing bounds, when available.
    fit_scale : float or None
        Scale required to fit the drawing on its requested page.
    route_report : SheetReport
        Final route measurements from ``route_quality.measure_sheet``.

    Returns
    -------
    dict
        Rule-keyed proxy records with explicit measurement statuses.
    """
    claims = read_claims(process_streams(fs))
    direction_violations = 0
    wrong_direction = []
    for claim in claims:
        a, b = claim.author.frame, claim.subject.frame
        if a is None or b is None:
            continue
        dx, dy = b.cx - a.cx, b.cy - a.cy
        if claim.eastward and claim.eastward * dx <= 0:
            direction_violations += 1
            wrong_direction.append(f"{claim.author.name} -> {claim.subject.name}")
        if claim.southward and claim.southward * dy <= 0:
            direction_violations += 1
            wrong_direction.append(f"{claim.author.name} -> {claim.subject.name}")

    backward_exits = []
    for stream in process_streams(fs):
        if stream.is_recycle:
            continue
        source, dest = stream.source.owner, stream.dest.owner
        if source is None or dest is None or source.frame is None or dest.frame is None:
            continue
        a = resolve_port(source, source.frame, stream.source.name)
        b = resolve_port(dest, dest.frame, stream.dest.name)
        nx, ny = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}[a.face]
        if (b.anchor[0] - a.anchor[0]) * nx + (b.anchor[1] - a.anchor[1]) * ny < -0.01:
            backward_exits.append(stream.name)

    boxes = [unit_box(u, u.frame) for u in process_units(fs) if u.frame is not None]
    excess_rows = [
        (row.name, max(0, row.actual_bends - row.min_bends))
        for row in route_report.rows
        if row.min_bends is not None and not row.is_manual
    ]
    excess_bends = sum(excess for _, excess in excess_rows)
    return {
        "S1.claim_direction_violations": _proxy(
            direction_violations,
            note="Diagnostic: conflicting claims can reward a visually worse layout",
            status="diagnostic",
            offenders=wrong_direction,
        ),
        "S2.group_span": _proxy(None, note="Group inference begins in Batch 2"),
        "S3.branch_inversions": _proxy(None, note="Branch ordering begins in Batch 2"),
        "S4.corridor_intrusion": _proxy(None, note="Corridor inference begins in Batch 2"),
        "G1.backward_exits": _proxy(len(backward_exits), offenders=backward_exits),
        "G2.excess_bends": _proxy(
            excess_bends,
            offenders=[
                name for name, excess in sorted(excess_rows, key=lambda row: -row[1]) if excess
            ],
        ),
        "G2.local_density": _proxy(None, note="Crossings and bends measured; density pending"),
        "G3.empty_x_band": _proxy(
            _largest_empty_band(boxes, 0),
            note="Diagnostic: an intentional corridor can be an empty band",
            status="diagnostic",
        ),
        "G3.empty_y_band": _proxy(
            _largest_empty_band(boxes, 1),
            note="Diagnostic: an intentional corridor can be an empty band",
            status="diagnostic",
        ),
        "G3.fit_scale": _proxy(
            None if fit_scale is None else _round(fit_scale),
            note="Not applicable without page_size" if fit_scale is None else "",
            status="not_applicable" if fit_scale is None else "measured",
        ),
        "G4.annotation_collisions": _proxy(None, note="No shared label bbox measure yet"),
    }


def _render(fs, kwargs: dict, stem: str, auto: bool, outdir: Path) -> dict[str, str]:
    """Write an SVG and, when available, a PNG for one sheet variant.

    Parameters
    ----------
    fs : Flowsheet
        Resolved flowsheet to draw.
    kwargs : dict
        Render options supplied by the example.
    stem : str
        Example identifier used in output filenames.
    auto : bool
        Whether placement pins were stripped during construction.
    outdir : Path
        Directory receiving the preview files.

    Returns
    -------
    dict[str, str]
        Absolute paths keyed by image extension.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    name = f"{stem}_{'auto' if auto else 'authored'}"
    options = dict(kwargs)
    options["check"] = False
    svg_path = outdir / f"{name}.svg"
    svg_path.write_text(gallery.normalize(fs.to_svg(**options)), encoding="utf-8")
    images = {"svg": str(svg_path.resolve())}
    try:
        png = gallery.rasterize(svg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"PNG unavailable for {name}: {exc}", file=sys.stderr)
        return images
    png_path = outdir / f"{name}.png"
    png_path.write_bytes(png)
    images["png"] = str(png_path.resolve())
    return images


def measure_variant(stem: str, auto: bool, render_dir: Path | None = None) -> dict:
    """Capture geometry, route quality, hard findings, and previews.

    Parameters
    ----------
    stem : str
        Shipped example identifier.
    auto : bool
        Strip placement pins when building the example if true.
    render_dir : Path or None, optional
        Preview directory; ``None`` skips SVG and PNG output.

    Returns
    -------
    dict
        JSON-ready measurements for one authored or automatic variant.
    """
    fs, kwargs = layout_quality.build(stem, auto)
    measured_at = time.perf_counter()
    report = route_quality.measure_sheet(fs, stem)
    measurement_s = time.perf_counter() - measured_at
    issues = fs.validate(diagram=kwargs.get("diagram"))
    counts = Counter(issue.code for issue in issues)
    extent = layout_quality.sheet_extent(fs)
    area = 0.0 if extent is None else (extent[2] - extent[0]) * (extent[3] - extent[1])
    page = layout_quality.page_px(kwargs.get("page_size"))
    fit_scale = None
    if page is not None and extent is not None:
        width, height = extent[2] - extent[0], extent[3] - extent[1]
        fit_scale = min(1.0, page[0] / width, page[1] / height)

    timed, _ = layout_quality.build(stem, auto)
    start = time.perf_counter()
    timed.layout()
    layout_s = time.perf_counter() - start
    timed.route()
    layout_route_s = time.perf_counter() - start

    fingerprint = _fingerprint(fs)
    images = _render(fs, kwargs, stem, auto, render_dir) if render_dir else {}
    image_hashes = {
        ext: hashlib.sha256(Path(path).read_bytes()).hexdigest() for ext, path in images.items()
    }
    framed = [u for u in fs.units if u.frame is not None]
    extent_units = {}
    if framed:
        extent_units = {
            "west": min(framed, key=lambda u: u.frame.x).name,
            "east": max(framed, key=lambda u: u.frame.x_max).name,
            "north": min(framed, key=lambda u: u.frame.y).name,
            "south": max(framed, key=lambda u: u.frame.y_max).name,
        }
    return {
        "stem": stem,
        "auto": auto,
        "hard": {
            "errors": sum(issue.severity == "error" for issue in issues),
            "fallback": report.fallback,
            "route_crosses_unit": counts["route-crosses-unit"],
            "unit_overlap": counts["unit-overlap"],
            "undrawn": len(report.undrawn),
            "pin_not_honored": counts["pin-not-honored"],
            "route_diagonal": counts["route-diagonal"],
            "route_not_settled": counts["route-not-settled"],
            "instrument_unplaced": counts["instrument-unplaced"],
        },
        "author_intent": {
            "units": [
                {
                    "name": u.name,
                    "pin": None if u._pin is None else asdict(u._pin),
                    "pin_ports": dict(sorted(u._pin_ports.items())),
                    "explicit_faces": dict(sorted(u._port_faces.items())),
                }
                for u in fs.units
            ],
            "manual_routes": [
                {
                    "name": s.name,
                    "waypoints": [list(point) for point in s.route.waypoints],
                }
                for s in fs.streams
                if s.route is not None and s.route.manual
            ],
        },
        "issues": dict(sorted(counts.items())),
        "metrics": {
            "crossings": len(report.crossings),
            "bends": sum(row.actual_bends for row in report.rows),
            "length": _round(sum(row.length for row in report.rows)),
            "area": _round(area),
        },
        "proxies": _proxies(fs, extent, fit_scale, report),
        "offenders": {
            "fallback_streams": [row.name for row in report.rows if row.is_fallback],
            "route_rows": [
                {"name": row.name, "bends": row.actual_bends, "length": _round(row.length)}
                for row in report.rows
            ],
            "extent_units": extent_units,
            "crossings": [
                {
                    "horizontal": c.h_stream.name,
                    "vertical": c.v_stream.name,
                    "point": [_round(v) for v in c.point],
                }
                for c in report.crossings
            ],
            "issues": [
                {"severity": i.severity, "code": i.code, "message": i.message}
                for i in issues
                if i.code
                in (
                    "unit-overlap",
                    "route-crosses-unit",
                    "pin-not-honored",
                    "route-diagonal",
                    "route-not-settled",
                    "instrument-unplaced",
                )
            ],
        },
        "extent": None if extent is None else [_round(value) for value in extent],
        "runtime": {
            "layout_s": _round(layout_s),
            "layout_route_s": _round(layout_route_s),
            "measurement_s": _round(measurement_s),
        },
        "fingerprint": fingerprint,
        "images": images,
        "image_hashes": image_hashes,
    }


def snapshot(stems: list[str] | None = None, render_dir: Path | None = None) -> dict:
    """Measure both variants of each selected shipped example.

    Parameters
    ----------
    stems : list[str] or None, optional
        Example identifiers; an empty list or ``None`` selects the complete gallery.
    render_dir : Path or None, optional
        Directory for SVG and PNG previews.

    Returns
    -------
    dict
        Baseline revision, rulebook identifier, and variant records.

    Raises
    ------
    ValueError
        If a selected example is absent from the gallery.
    """
    selected = stems or gallery.sheets()
    unknown = sorted(set(selected) - set(gallery.sheets()))
    if unknown:
        raise ValueError(f"unknown example(s): {', '.join(unknown)}")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return {
        "head": head,
        "rulebook": "pandid-layout-quality-rules 2026-09-26",
        "variants": [
            measure_variant(stem, auto, render_dir) for stem in selected for auto in (False, True)
        ],
    }


def _indexed(data: dict) -> dict[tuple[str, bool], dict]:
    """Index snapshot variants by example and placement mode.

    Parameters
    ----------
    data : dict
        Snapshot containing a ``variants`` list.

    Returns
    -------
    dict[tuple[str, bool], dict]
        Variant lookup keyed by stem and automatic-mode flag.

    Raises
    ------
    ValueError
        If a variant key appears more than once.
    """
    variants = {(row["stem"], row["auto"]): row for row in data["variants"]}
    if len(variants) != len(data["variants"]):
        raise ValueError("snapshot has duplicate sheet variants")
    return variants


def _review_findings(
    review: dict, stem: str, before: dict, after: dict, *, required: bool
) -> tuple[set[str], list[str]]:
    """Validate rule reviews and their linked preview images.

    Parameters
    ----------
    review : dict
        Human findings keyed by sheet and rule identifier.
    stem : str
        Review key, including ``|authored`` for an authored variant.
    before, after : dict
        Baseline and candidate variant records.
    required : bool
        Require all rule findings when the variant geometry changed.

    Returns
    -------
    tuple[set[str], list[str]]
        Rules reviewed as better and reasons for invalid or worse findings.
    """
    findings = review.get(stem, {})
    better: set[str] = set()
    problems = []
    if required:
        missing = sorted(set(RULES) - set(findings))
        if missing:
            problems.append(f"missing visual review for {', '.join(missing)}")
    for rule, finding in findings.items():
        if (
            not isinstance(finding, dict)
            or rule not in RULES
            or finding.get("verdict")
            not in (
                "better",
                "same",
                "worse",
                "not_applicable",
            )
        ):
            problems.append(f"invalid rule review for {rule}")
            continue
        if finding["verdict"] == "worse":
            problems.append(f"{rule} is visually worse: {finding.get('reason', '')}")
        if not required and finding["verdict"] != "better":
            continue
        if not all(finding.get(field) for field in ("reason", "before", "after")):
            problems.append(f"{rule} review lacks a reason or before/after image")
            continue
        if finding["before"] == finding["after"]:
            problems.append(f"{rule} review uses the same before/after image")
            continue
        valid_images = True
        for field, row in (("before", before), ("after", after)):
            image = finding[field]
            matching = [ext for ext, path in row.get("images", {}).items() if path == image]
            if not matching or not Path(image).is_file():
                valid_images = False
                break
            ext = matching[0]
            actual_hash = hashlib.sha256(Path(image).read_bytes()).hexdigest()
            if row.get("image_hashes", {}).get(ext) != actual_hash:
                valid_images = False
                break
        if not valid_images:
            problems.append(f"{rule} review images do not match rendered snapshots")
        elif finding["verdict"] == "better":
            better.add(rule)
    return better, problems


def _better_proxies(before: dict, after: dict) -> set[str]:
    """Identify rule families with an improved measured proxy.

    Parameters
    ----------
    before, after : dict
        Baseline and candidate variant records.

    Returns
    -------
    set[str]
        Rule identifiers with a qualifying measured improvement.
    """
    improved: set[str] = set()
    for name, old in before.get("proxies", {}).items():
        new = after.get("proxies", {}).get(name, {})
        if name == "G3.fit_scale":
            if old.get("value") is not None and new.get("value") is not None:
                if new["value"] > old["value"] + 0.001:
                    improved.add("G3")
            continue
        if old.get("status") == new.get("status") == "measured":
            if new["value"] < old["value"] - 0.001:
                improved.add(name.split(".", 1)[0])
    return improved


def _regressions(before: dict, after: dict, *, auto: bool) -> list[str]:
    """Find hard and bounded soft regressions for one variant.

    Parameters
    ----------
    before, after : dict
        Baseline and candidate variant records.
    auto : bool
        Apply automatic-layout soft limits if true; otherwise check author intent.

    Returns
    -------
    list[str]
        Reasons the candidate variant regressed.
    """
    reasons = []
    if not auto and before.get("author_intent") != after.get("author_intent"):
        reasons.append("authored pins, explicit faces, or manual routes changed")
    for key in HARD_KEYS:
        if after["hard"][key] > before["hard"][key]:
            reasons.append(f"{key} increased {before['hard'][key]} -> {after['hard'][key]}")
    old, new = before["metrics"], after["metrics"]
    if new["crossings"] > old["crossings"]:
        reasons.append(f"crossings increased {old['crossings']} -> {new['crossings']}")
        before_crossings = {
            (c["horizontal"], c["vertical"], tuple(c["point"]))
            for c in before.get("offenders", {}).get("crossings", [])
        }
        added = [
            c
            for c in after.get("offenders", {}).get("crossings", [])
            if (c["horizontal"], c["vertical"], tuple(c["point"])) not in before_crossings
        ]
        if added:
            reasons.append(
                "new crossing examples: "
                + ", ".join(
                    f"{c['horizontal']} / {c['vertical']} at {c['point']}" for c in added[:3]
                )
            )
    if auto:
        if new["bends"] > min(old["bends"] + 1, old["bends"] * 1.03):
            reasons.append(f"bends increased {old['bends']} -> {new['bends']}")
        if new["length"] > old["length"] * 1.02 + 0.1:
            reasons.append(f"route length increased {old['length']} -> {new['length']}")
            old_rows = before.get("offenders", {}).get("route_rows", [])
            new_rows = after.get("offenders", {}).get("route_rows", [])
            if len(old_rows) == len(new_rows):
                largest = max(
                    ((n["length"] - o["length"], n["name"]) for o, n in zip(old_rows, new_rows)),
                    default=(0, ""),
                )
                if largest[0] > 0:
                    reasons.append(f"longest added route: {largest[1]} +{largest[0]:.1f}px")
        if new["area"] > old["area"] * 1.02 + 1.0:
            reasons.append(f"drawing area increased {old['area']} -> {new['area']}")
            bounds = after.get("offenders", {}).get("extent_units", {})
            if bounds:
                reasons.append(
                    "extent units: "
                    + ", ".join(f"{direction}={unit}" for direction, unit in bounds.items())
                )
    return reasons


def _improved_rules(before: dict, after: dict) -> set[str]:
    """Find rule families backed by a qualifying numeric improvement.

    Parameters
    ----------
    before, after : dict
        Baseline and candidate automatic variant records.

    Returns
    -------
    set[str]
        Improved rule identifiers eligible for human review matching.
    """
    old, new = before["metrics"], after["metrics"]
    improved = _better_proxies(before, after)
    if (
        after["hard"]["fallback"] < before["hard"]["fallback"]
        or after["hard"]["route_crosses_unit"] < before["hard"]["route_crosses_unit"]
    ):
        improved.add("G1")
    if new["crossings"] < old["crossings"]:
        improved.add("G2")
    if new["length"] < old["length"] * 0.98 - 0.1:
        improved.add("G2")
    if new["area"] < old["area"] * 0.98 - 1.0:
        improved.add("G3")
    return improved


def compare(before: dict, after: dict, review: dict | None = None) -> Comparison:
    """Apply the fixed corpus release gate to two snapshots.

    Parameters
    ----------
    before, after : dict
        Baseline and candidate snapshot records.
    review : dict or None, optional
        Human S1-S4 and G1-G4 findings with matching preview paths.

    Returns
    -------
    Comparison
        Per-sheet classifications, aggregate measurements, and gate outcome.

    Raises
    ------
    ValueError
        If variant sets differ or author-intent records are missing.
    """
    base, current = _indexed(before), _indexed(after)
    if base.keys() != current.keys():
        raise ValueError("baseline and candidate contain different sheet variants")
    if any("author_intent" not in row for row in (*base.values(), *current.values())):
        raise ValueError("snapshot is missing authored pin and manual-route intent")
    review = review or {}
    stems = sorted({stem for stem, auto in base if auto})
    gate_reasons = []
    if before.get("head") != BASE_HEAD:
        gate_reasons.append(f"baseline head must be {BASE_HEAD}")
    if tuple(stems) != BASE_STEMS:
        gate_reasons.append("snapshot is not the fixed 21-sheet example corpus")
    reasons: dict[str, list[str]] = {}
    improved, regressed, unchanged = [], [], []
    for stem in stems:
        old, new = base[(stem, True)], current[(stem, True)]
        problem = _regressions(old, new, auto=True)
        authored_problem = _regressions(base[(stem, False)], current[(stem, False)], auto=False)
        problem.extend(f"authored: {reason}" for reason in authored_problem)
        changed = old["fingerprint"] != new["fingerprint"]
        authored_changed = (
            base[(stem, False)]["fingerprint"] != current[(stem, False)]["fingerprint"]
        )
        if not changed and (
            old["metrics"] != new["metrics"] or old.get("proxies") != new.get("proxies")
        ):
            problem.append("metrics changed without a changed drawing")
        reviewed, review_problem = _review_findings(review, stem, old, new, required=changed)
        problem.extend(review_problem)
        _, authored_review_problem = _review_findings(
            review,
            f"{stem}|authored",
            base[(stem, False)],
            current[(stem, False)],
            required=authored_changed,
        )
        problem.extend(f"authored: {reason}" for reason in authored_review_problem)
        measurable = _improved_rules(old, new)
        if problem:
            regressed.append(stem)
        elif measurable & reviewed:
            improved.append(stem)
        else:
            unchanged.append(stem)
            if measurable:
                problem.append("measured rule improvement lacks matching positive visual review")
        reasons[stem] = problem

    aggregates = {
        key: (
            sum(base[(stem, True)]["metrics"][key] for stem in stems),
            sum(current[(stem, True)]["metrics"][key] for stem in stems),
        )
        for key in TOTAL_KEYS
    }
    aggregate_ok = all(
        new <= old + (0.1 if key == "length" else 1.0 if key == "area" else 0)
        for key, (old, new) in aggregates.items()
    )
    aggregate_improvements = sum(
        new < old - (0.1 if key == "length" else 1.0 if key == "area" else 0)
        for key, (old, new) in aggregates.items()
    )
    hard_clear = all(
        current[(stem, True)]["hard"]["fallback"] == 0
        and current[(stem, True)]["hard"]["route_crosses_unit"] == 0
        for stem in stems
    )
    passed = (
        not gate_reasons
        and len(improved) >= 11
        and not regressed
        and aggregate_ok
        and aggregate_improvements >= 2
        and hard_clear
    )
    return Comparison(passed, improved, regressed, unchanged, reasons, aggregates, gate_reasons)


def _copy_changed_images(before: dict, after: dict, outdir: Path) -> None:
    """Copy before and after previews for changed variants.

    Parameters
    ----------
    before, after : dict
        Baseline and candidate snapshot records.
    outdir : Path
        Destination for paired SVG and PNG files.

    Returns
    -------
    None
        Preview files are written to ``outdir``.

    Raises
    ------
    ValueError
        If a changed variant lacks an SVG or PNG preview.
    """
    base, current = _indexed(before), _indexed(after)
    outdir.mkdir(parents=True, exist_ok=True)
    for key in sorted(base):
        if base[key]["fingerprint"] == current[key]["fingerprint"]:
            continue
        stem, auto = key
        label = f"{stem}_{'auto' if auto else 'authored'}"
        for side, variant in (("before", base[key]), ("after", current[key])):
            if not all(
                Path(variant.get("images", {}).get(ext, "")).is_file() for ext in ("svg", "png")
            ):
                raise ValueError(f"{label} {side} has no SVG/PNG; rerun snapshot with --render-dir")
            for ext, source in variant.get("images", {}).items():
                path = Path(source)
                shutil.copy2(path, outdir / f"{label}_{side}.{ext}")


def _print_comparison(result: Comparison) -> None:
    """Print per-sheet classifications and aggregate gate totals.

    Parameters
    ----------
    result : Comparison
        Completed comparison to report on standard output.

    Returns
    -------
    None
        The summary is printed to standard output.
    """
    for reason in result.gate_reasons:
        print(f"gate: {reason}")
    for status, names in (
        ("improved", result.improved),
        ("regressed", result.regressed),
        ("unchanged", result.unchanged),
    ):
        print(f"{status}: {len(names)}")
        for name in names:
            print(f"  {name}")
            for reason in result.reasons[name]:
                print(f"    {reason}")
    for key, (old, new) in result.aggregates.items():
        print(f"auto {key}: {old:.1f} -> {new:.1f}")
    print("release gate: PASS" if result.passed else "release gate: FAIL")


def _print_offenders(before: dict, after: dict, review: dict) -> None:
    """Print changed metrics and the streams or units responsible.

    Parameters
    ----------
    before, after : dict
        Baseline and candidate snapshot records.
    review : dict
        Human rule findings included in the offender report.

    Returns
    -------
    None
        The offender table is printed to standard output.
    """
    base, current = _indexed(before), _indexed(after)
    metric_rule = {"crossings": "G2", "bends": "G2", "length": "G2", "area": "G3"}
    print("sheet | variant | rule | metric | before -> after | responsible stream/units")
    for (stem, auto), old in sorted(base.items()):
        new = current[(stem, auto)]
        variant = "auto" if auto else "authored"
        if old["fingerprint"] == new["fingerprint"] and old["metrics"] == new["metrics"]:
            continue
        old_rows = {row["name"]: row for row in old.get("offenders", {}).get("route_rows", [])}
        new_rows = {row["name"]: row for row in new.get("offenders", {}).get("route_rows", [])}
        for metric in TOTAL_KEYS:
            prior, now = old["metrics"][metric], new["metrics"][metric]
            if prior == now:
                continue
            responsible = ""
            if metric in ("bends", "length"):
                deltas = [
                    (abs(row[metric] - old_rows[name][metric]), name)
                    for name, row in new_rows.items()
                    if name in old_rows and row[metric] != old_rows[name][metric]
                ]
                if deltas:
                    responsible = max(deltas)[1]
            elif metric == "crossings":
                before_pairs = {
                    (c["horizontal"], c["vertical"], tuple(c["point"]))
                    for c in old.get("offenders", {}).get("crossings", [])
                }
                after_pairs = {
                    (c["horizontal"], c["vertical"], tuple(c["point"]))
                    for c in new.get("offenders", {}).get("crossings", [])
                }
                changed = sorted(before_pairs ^ after_pairs)
                if changed:
                    responsible = f"{changed[0][0]} / {changed[0][1]}"
            else:
                responsible = ", ".join(
                    f"{side}={unit}"
                    for side, unit in new.get("offenders", {}).get("extent_units", {}).items()
                )
            print(
                f"{stem} | {variant} | {metric_rule[metric]} | {metric} | "
                f"{prior:.1f} -> {now:.1f} | {responsible}"
            )
        for metric in HARD_KEYS:
            prior, now = old["hard"][metric], new["hard"][metric]
            if prior == now:
                continue
            details = new if now > prior else old
            offenders = details.get("offenders", {})
            responsible = (
                ", ".join(offenders.get("fallback_streams", [])[:3])
                if metric == "fallback"
                else "; ".join(issue["message"] for issue in offenders.get("issues", [])[:2])
            )
            print(f"{stem} | {variant} | H | {metric} | {prior} -> {now} | {responsible}")
        for metric, prior in old.get("proxies", {}).items():
            now = new.get("proxies", {}).get(metric, {})
            if prior.get("value") is None or now.get("value") is None:
                continue
            if prior["value"] == now["value"]:
                continue
            responsible = ", ".join(
                (now if now["value"] > prior["value"] else prior).get("offenders", [])[:3]
            )
            print(
                f"{stem} | {variant} | {metric.split('.', 1)[0]} | {metric} "
                f"({now.get('status')}) | {prior['value']:.1f} -> {now['value']:.1f} | {responsible}"
            )
        findings = review.get(stem if auto else f"{stem}|authored", {})
        for rule, finding in sorted(findings.items()):
            if not isinstance(finding, dict):
                continue
            if finding.get("verdict") in ("better", "worse"):
                print(
                    f"{stem} | {variant} | {rule} | visual | "
                    f"{finding['verdict']} | {finding.get('reason', '')}"
                )


def main() -> int:
    """Run the snapshot or comparison command-line workflow.

    Returns
    -------
    int
        Zero for a completed snapshot or passing comparison; one for a failed gate.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("snapshot", help="measure the shipped examples")
    capture.add_argument("--output", required=True, type=Path)
    capture.add_argument("--render-dir", type=Path)
    capture.add_argument("sheet", nargs="*")
    checking = commands.add_parser("compare", help="apply the release gate")
    checking.add_argument("--baseline", required=True, type=Path)
    checking.add_argument("--candidate", required=True, type=Path)
    checking.add_argument("--review", type=Path)
    checking.add_argument("--render-changed", type=Path)
    args = parser.parse_args()
    if args.command == "snapshot":
        render_dir = args.render_dir or args.output.with_name(args.output.stem + "-renders")
        data = snapshot(args.sheet, render_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(data['variants'])} variants to {args.output}")
        return 0
    before = json.loads(args.baseline.read_text(encoding="utf-8"))
    after = json.loads(args.candidate.read_text(encoding="utf-8"))
    review = json.loads(args.review.read_text(encoding="utf-8")) if args.review else {}
    result = compare(before, after, review)
    _print_comparison(result)
    _print_offenders(before, after, review)
    if args.render_changed:
        _copy_changed_images(before, after, args.render_changed)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
