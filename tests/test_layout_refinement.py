"""Integration checks for publishing a qualified completed drawing."""

from __future__ import annotations

import warnings
from unittest.mock import Mock

import pytest

from pandid import Flowsheet
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
    """The final search preserves the accepted trial and model identities.

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


@pytest.mark.parametrize(
    "stem", ["04_control_loop", "08_from_data", "16_demineralised_water"]
)
def test_refinement_repeats_from_author_intent_and_fresh_builds(stem: str) -> None:
    """Rebuilds make the same choice without using prior derived geometry.

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
    """Trial searches do not change the final route-quality report.

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
    """Speculative warnings do not count as missing final routes.

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
    """A one-point manual ``via`` is a valid routed stream.

    Returns
    -------
    None
        The final route report does not count manual waypoints as undrawn.
    """
    fs, _ = layout_quality.build("11_ethanol_pid", False)
    report = route_quality.measure_sheet(fs, "11_ethanol_pid")
    assert report.undrawn == []
