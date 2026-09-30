"""Check that default routing publishes only qualified completed drawings."""

from __future__ import annotations

import warnings
from unittest.mock import Mock

import pytest

from _layout_cases import build as build_biodiesel
from pandid import Flowsheet, GravitySeparator, Product, Reactor
from pandid.layout.candidates import generate
from pandid.layout.quality import admissible, measure_final
from pandid.layout.trials import _evaluate_candidate
from pandid.layout import trials
from pandid.routing import DefaultRouter
from scripts import layout_quality, route_quality
from scripts.layout_compare import _fingerprint


@pytest.mark.parametrize(
    "stem", ["10_ethanol_pfd", "16_demineralised_water", "17_stirred_reactor_train"]
)
def test_default_route_preserves_the_qualified_settled_drawing(stem: str) -> None:
    """Preserve the accepted trial and model identities through the final search.

    Parameters
    ----------
    stem : str
        Automatic corpus drawing with a qualifying first proposal.

    Returns
    -------
    None
        Final quality is admissible against the trial and identities survive.
    """
    fs, _ = layout_quality.build(stem, True)
    fs.layout()
    fs.route(DefaultRouter())
    proposal = generate(fs, limit=1)[0]
    result, accepted = _evaluate_candidate(fs, proposal.apply, face_choices=proposal.face_choices)
    assert result.qualified
    units, streams = tuple(fs.units), tuple(fs.streams)
    ports = tuple(tuple(unit.ports.values()) for unit in fs.units)
    fs.route()

    assert admissible(result.after, measure_final(fs))
    assert all(live is original for live, original in zip(fs.units, units))
    assert all(live is original for live, original in zip(fs.streams, streams))
    assert all(tuple(unit.ports.values()) == original for unit, original in zip(fs.units, ports))
    assert [unit.tap for unit in fs.units if hasattr(unit, "tap")] == [
        unit.tap for unit in accepted.units if hasattr(unit, "tap")
    ]


@pytest.mark.parametrize("stem", ["04_control_loop", "08_from_data", "16_demineralised_water"])
def test_refinement_repeats_from_author_intent_and_fresh_builds(stem: str) -> None:
    """Repeat the same choice from author intent and from a fresh build.

    Parameters
    ----------
    stem : str
        Example with or without an accepted bounded search move.

    Returns
    -------
    None
        Routing again, laying out again, and constructing anew agree.
    """
    fs, _ = layout_quality.build(stem, True)
    fs.layout()
    fs.route()
    fingerprint = _fingerprint(fs)
    fs.route()
    assert _fingerprint(fs) == fingerprint
    fs.layout()
    fs.route()
    assert _fingerprint(fs) == fingerprint

    fresh, _ = layout_quality.build(stem, True)
    fresh.layout()
    fresh.route()
    assert _fingerprint(fresh) == fingerprint


def test_column_row_compaction_shortens_a_control_sheet() -> None:
    """Accept a routed row change only when the drawing improves.

    Returns
    -------
    None
        The default drawing is shorter with no new crossing or hard finding.
    """
    fs, _ = layout_quality.build("04_control_loop", True)
    fs.layout()
    fs.route(DefaultRouter())
    before = measure_final(fs)
    fs.layout()
    fs.route()
    after = measure_final(fs)

    assert after.length < before.length
    assert after.area < before.area
    assert after.crossing_pairs <= before.crossing_pairs
    assert all(new <= old for old, new in zip(before.hard, after.hard))


def test_row_trial_does_not_replace_a_better_final_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the ordinary result when its final routing is better.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Disables row trials for the comparison drawing.

    Returns
    -------
    None
        The dewatering sheet retains its shorter baseline route.
    """
    with monkeypatch.context() as patch:
        patch.setattr(trials, "refine_rows", Mock(return_value=False))
        baseline, _ = layout_quality.build("13_mineral_dewatering", True)
        baseline.layout()
        baseline.route()
    actual, _ = layout_quality.build("13_mineral_dewatering", True)
    actual.layout()
    actual.route()

    before, after = measure_final(baseline), measure_final(actual)
    assert after.hard == before.hard
    assert after.crossing_pairs == before.crossing_pairs
    assert after.bends == before.bends
    assert after.length == before.length
    assert after.area == before.area


@pytest.mark.parametrize("stem", ["04_control_loop", "10_ethanol_pfd"])
def test_route_report_uses_the_published_graph(stem: str) -> None:
    """Report route quality from the published graph, not from trials.

    Parameters
    ----------
    stem : str
        Corpus drawing with a rejected or accepted first trial.

    Returns
    -------
    None
        Reported excess bends agree with the published route geometry.
    """
    fs, _ = layout_quality.build(stem, True)
    report = route_quality.measure_sheet(fs, stem)
    excess = sum(
        max(0, row.actual_bends - row.min_bends)
        for row in report.rows
        if row.min_bends is not None and not row.is_manual
    )
    assert excess == measure_final(fs).excess_bends


def test_route_report_ignores_an_unpublished_trial_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ignore a warning raised only by an unpublished trial.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the speculative pass with a warning-only trial.

    Returns
    -------
    None
        The report counts only routes absent from the live drawing.
    """

    def rejected(fs: Flowsheet) -> bool:
        """Emit a trial-only missing-route warning.

        Parameters
        ----------
        fs : Flowsheet
            Live drawing, left unchanged.

        Returns
        -------
        bool
            False because the trial is rejected.
        """
        warnings.warn("stream 'trial' is left unrouted", stacklevel=2)
        return False

    monkeypatch.setattr(trials, "refine_default", rejected)
    fs, _ = layout_quality.build("04_control_loop", True)
    report = route_quality.measure_sheet(fs, "04_control_loop")
    assert report.undrawn == []


def test_route_report_accepts_manual_intermediate_waypoints() -> None:
    """Count a manual route with one waypoint as drawn.

    Returns
    -------
    None
        The final route report does not count manual waypoints as undrawn.
    """
    fs, _ = layout_quality.build("11_ethanol_pid", False)
    report = route_quality.measure_sheet(fs, "11_ethanol_pid")
    assert report.undrawn == []


def _sealed_by_alignment(pinned: bool = False) -> tuple[Flowsheet, dict[str, object]]:
    """Build a sheet whose row alignment seals a separator's south exit.

    Aligning S-2's feed with R-1's outlet lifts S-2 to 9 px below S-1, inside
    the stub of S-1's connected underflow.

    Parameters
    ----------
    pinned : bool, optional
        Pin every unit at the sealed pixel positions instead of grid ranks.

    Returns
    -------
    tuple[Flowsheet, dict[str, object]]
        The sheet, with its units and the underflow stream by name.
    """
    fs = Flowsheet("Sealed exit")
    reactor = fs.add(Reactor("R-1"))
    upper = fs.add(GravitySeparator("S-1"))
    lower = fs.add(GravitySeparator("S-2"))
    drain = fs.add(Product("Drain"))
    if pinned:
        reactor.pin(x=50, y=50)
        upper.pin(x=232, y=56)
        lower.pin(x=232, y=185)
        drain.pin(x=432, y=91)
    else:
        reactor.pin(col=0, row=0)
        upper.pin(col=1, row=0)
        lower.pin(col=1, row=1)
        drain.pin(col=2, row=0)
    fs.connect(reactor.outlet, lower.feed)
    underflow = fs.connect(upper.underflow, drain.inlet)
    return fs, {"upper": upper, "lower": lower, "underflow": underflow}


def test_default_route_clears_an_exit_sealed_by_row_alignment() -> None:
    """Undo the alignment that puts a unit inside a connected nozzle stub.

    Returns
    -------
    None
        The underflow is routed clear, grid ranks hold, and a second route
        and a fresh build draw the same sheet.
    """
    fs, parts = _sealed_by_alignment()
    fs.layout()
    fs.route(DefaultRouter())
    assert parts["underflow"].route.used_fallback

    fs.layout()
    fs.route()
    upper, lower = parts["upper"].frame, parts["lower"].frame
    assert not parts["underflow"].route.used_fallback
    assert not measure_final(fs).hard_conflicts
    assert lower.y - upper.y_max >= 25
    assert (upper.row, lower.row) == (0, 1)

    fingerprint = _fingerprint(fs)
    fs.route()
    assert _fingerprint(fs) == fingerprint
    fresh, _ = _sealed_by_alignment()
    fresh.route()
    assert _fingerprint(fresh) == fingerprint


def test_exit_repair_leaves_pinned_units_in_place() -> None:
    """Keep pinned units where the author put them when an exit is sealed.

    Returns
    -------
    None
        Both separators stay on their pins and the blocked route is reported.
    """
    fs, parts = _sealed_by_alignment(pinned=True)
    fs.route()

    upper, lower = parts["upper"].frame, parts["lower"].frame
    assert (upper.x, upper.y, lower.x, lower.y) == (232, 56, 232, 185)
    assert parts["underflow"].route.used_fallback
    assert any(issue.code == "route-crosses-unit" for issue in fs.validate())


def test_default_route_clears_the_unpinned_biodiesel_sheet() -> None:
    """Route the unpinned biodiesel sheet without a line through equipment.

    Returns
    -------
    None
        No stream uses the fallback and no hard conflict remains.
    """
    fs, _ = build_biodiesel(pinned=False)
    fs.route()

    quality = measure_final(fs)
    assert not any(stream.route.used_fallback for stream in fs.streams)
    assert not quality.hard_conflicts and not any(quality.hard)
    assert not any(issue.code == "route-crosses-unit" for issue in fs.validate())
