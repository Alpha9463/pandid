"""Bounded layout search against completed route geometry."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pandid.layout.candidates import MAX_CANDIDATES, generate_moves
from pandid.layout.conflicts import Conflict
from pandid.layout.quality import Quality, measure_final, search_admissible
from pandid.layout.settle import settle
from pandid.layout.stages import process_units
from pandid.layout.structure import Structure, infer
from pandid.layout.trials import _evaluate_candidate, _publish_candidate

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.geometry import Frame


SearchStatus = Literal["converged", "unresolved", "budget_exhausted"]


@dataclass(frozen=True)
class SearchBudget:
    """Deterministic limits on layout proposals and exact routing.

    Attributes
    ----------
    max_passes : int
        Maximum accepted-move selection passes.
    max_proposals_per_pass : int
        Maximum ranked moves fully routed in one pass.
    max_exact_trials : int
        Maximum fully settled detached drawings for the whole search.
    """

    max_passes: int
    max_proposals_per_pass: int
    max_exact_trials: int

    def __post_init__(self) -> None:
        """Reject negative work limits.

        Returns
        -------
        None
            Nonnegative limits are retained.

        Raises
        ------
        ValueError
            If any limit is negative.
        """
        if min(self.max_passes, self.max_proposals_per_pass, self.max_exact_trials) < 0:
            raise ValueError("search limits must be nonnegative")


@dataclass(frozen=True)
class SearchResult:
    """Outcome of one opt-in layout search.

    Attributes
    ----------
    status : SearchStatus
        Whether hard rules are satisfied, unresolved, or budget-limited.
    accepted_moves : int
        Number of published placement moves.
    exact_trials : int
        Number of detached drawings settled and routed.
    conflicts : tuple[Conflict, ...]
        Named final-geometry findings, including crossing pairs.
    """

    status: SearchStatus
    accepted_moves: int
    exact_trials: int
    conflicts: tuple[Conflict, ...]


def _fingerprint(fs: Flowsheet) -> tuple:
    """Identify visited final geometries independently of object identity.

    Parameters
    ----------
    fs : Flowsheet
        Completed drawing to identify.

    Returns
    -------
    tuple
        Rounded frames, selected faces, and final routes in stable order.
    """
    frames = tuple(
        None
        if unit.frame is None
        else (
            round(unit.frame.x, 6),
            round(unit.frame.y, 6),
            tuple(sorted(unit.frame.port_faces.items())),
            unit.frame.label_pos,
        )
        for unit in fs.units
    )
    routes = tuple(
        None
        if stream.route is None
        else (
            tuple((round(x, 6), round(y, 6)) for x, y in stream.route.waypoints),
            stream.route.used_fallback,
        )
        for stream in fs.streams
    )
    return frames, routes


def _centre(frame: Frame) -> tuple[float, float]:
    """Return a unit frame's drawn centre.

    Parameters
    ----------
    frame : Frame
        Resolved unit frame.

    Returns
    -------
    tuple[float, float]
        Horizontal and vertical centre coordinates.
    """
    return frame.x + frame.w / 2, frame.y + frame.h / 2


def _direction_violations(structure: Structure, frames: tuple[Frame, ...]) -> float:
    """Count confidence-weighted reversals of placement claims.

    Parameters
    ----------
    structure : Structure
        Process placement claims.
    frames : tuple[Frame, ...]
        Process frames in structure order.

    Returns
    -------
    float
        Sum of violated claim weights across both axes.
    """
    total = 0.0
    for claim in structure.claims:
        author = _centre(frames[claim.author])
        subject = _centre(frames[claim.subject])
        for wanted, actual in (
            (claim.eastward, subject[0] - author[0]),
            (claim.southward, subject[1] - author[1]),
        ):
            if wanted and wanted * actual < -1e-6:
                total += claim.confidence
    return total


def _branch_inversions(
    structure: Structure, seed: tuple[Frame, ...], frames: tuple[Frame, ...]
) -> int:
    """Count closed-arm vertical order reversals from the solver seed.

    Parameters
    ----------
    structure : Structure
        Closed and partial split/merge regions.
    seed, frames : tuple[Frame, ...]
        Original and proposed process frames.

    Returns
    -------
    int
        Number of arm pairs whose original vertical order reversed.
    """
    inversions = 0
    for region in structure.branch_regions:
        if not region.closed:
            continue
        interiors = [
            tuple(index for index in arm.units if index not in (region.split, region.merge))
            for arm in region.arms
        ]
        for first in range(len(interiors)):
            if not interiors[first]:
                continue
            for second in range(first + 1, len(interiors)):
                if not interiors[second]:
                    continue
                seed_delta = sum(_centre(seed[index])[1] for index in interiors[first]) / len(
                    interiors[first]
                ) - sum(_centre(seed[index])[1] for index in interiors[second]) / len(
                    interiors[second]
                )
                new_delta = sum(_centre(frames[index])[1] for index in interiors[first]) / len(
                    interiors[first]
                ) - sum(_centre(frames[index])[1] for index in interiors[second]) / len(
                    interiors[second]
                )
                if seed_delta * new_delta < -1e-6:
                    inversions += 1
    return inversions


def _connected_span(structure: Structure, frames: tuple[Frame, ...]) -> float:
    """Measure direct material-neighbour separation.

    Parameters
    ----------
    structure : Structure
        Material process edges.
    frames : tuple[Frame, ...]
        Process frames in structure order.

    Returns
    -------
    float
        Mean Manhattan centre distance over material edges.
    """
    if not structure.edges:
        return 0.0
    total = 0.0
    for edge in structure.edges:
        source = _centre(frames[edge.source])
        dest = _centre(frames[edge.dest])
        total += abs(dest[0] - source[0]) + abs(dest[1] - source[1])
    return total / len(structure.edges)


def _placement_deviation(
    structure: Structure, seed: tuple[Frame, ...], frames: tuple[Frame, ...]
) -> float:
    """Measure confidence-weighted changes in relative claim geometry.

    Parameters
    ----------
    structure : Structure
        Claim edges and their confidence weights.
    seed, frames : tuple[Frame, ...]
        Initial and proposed process frames.

    Returns
    -------
    float
        Normalized relative-displacement penalty.
    """
    total = 0.0
    for claim in structure.claims:
        first_seed = _centre(seed[claim.author])
        second_seed = _centre(seed[claim.subject])
        first = _centre(frames[claim.author])
        second = _centre(frames[claim.subject])
        for axis in (0, 1):
            original = second_seed[axis] - first_seed[axis]
            current = second[axis] - first[axis]
            body_size = (
                seed[claim.author].w + seed[claim.subject].w
                if axis == 0
                else seed[claim.author].h + seed[claim.subject].h
            )
            total += claim.confidence * abs(current - original) / max(abs(original), body_size, 1.0)
    return total


def _process_frames(fs: Flowsheet) -> tuple[Frame, ...]:
    """Read all process frames in structure-inference order.

    Parameters
    ----------
    fs : Flowsheet
        Laid-out drawing.

    Returns
    -------
    tuple[Frame, ...]
        Process frames in stable unit order.

    Raises
    ------
    ValueError
        If a process unit has no frame.
    """
    frames = tuple(unit.frame for unit in process_units(fs))
    if any(frame is None for frame in frames):
        raise ValueError("search requires all process units to have frames")
    return frames  # type: ignore[return-value]


def _score(
    quality: Quality,
    structure: Structure,
    seed: tuple[Frame, ...],
    frames: tuple[Frame, ...],
) -> tuple[float, ...]:
    """Order final drawings using the fixed-seed lexicographic contract.

    Parameters
    ----------
    quality : Quality
        Final route and conflict measurements.
    structure : Structure
        Process claims and branch regions.
    seed, frames : tuple[Frame, ...]
        Initial and proposed process geometry.

    Returns
    -------
    tuple[float, ...]
        Hard findings, crossings, structure, and route costs in order.
    """
    return (
        float(len(quality.hard_conflicts)),
        float(len(quality.crossing_pairs)),
        _direction_violations(structure, frames),
        float(_branch_inversions(structure, seed, frames)),
        _connected_span(structure, frames),
        float(quality.excess_bends),
        float(quality.bends),
        quality.length,
        quality.area,
        _placement_deviation(structure, seed, frames),
    )


def _structure_admissible(
    structure: Structure,
    seed: tuple[Frame, ...],
    incumbent: tuple[Frame, ...],
    after: tuple[Frame, ...],
) -> bool:
    """Reject regressions in the measured process-structure proxies.

    Parameters
    ----------
    structure : Structure
        Claims, material edges, and branch regions.
    seed, incumbent, after : tuple[Frame, ...]
        Initial, current, and trial process frames.

    Returns
    -------
    bool
        Whether claim direction, arm order, and neighbour span hold.
    """
    return (
        _direction_violations(structure, after)
        <= _direction_violations(structure, incumbent) + 1e-6
        and _branch_inversions(structure, seed, after)
        <= _branch_inversions(structure, seed, incumbent)
        and _connected_span(structure, after) <= _connected_span(structure, incumbent) + 1e-6
    )


def _search_result(
    fs: Flowsheet, status: SearchStatus, accepted: int, exact: int, quality: Quality
) -> SearchResult:
    """Attach the final search outcome to derived drawing state.

    Parameters
    ----------
    fs : Flowsheet
        Drawing receiving the result.
    status : SearchStatus
        Completion classification.
    accepted, exact : int
        Published moves and fully routed trial counts.
    quality : Quality
        Final drawing measurements.

    Returns
    -------
    SearchResult
        Stored search result with stable conflict identities.
    """
    conflicts = tuple(
        sorted(
            (
                *quality.hard_conflicts,
                *(Conflict("crossing", streams=pair) for pair in quality.crossing_pairs),
            )
        )
    )
    result = SearchResult(status, accepted, exact, conflicts)
    fs._layout_search_result = result
    return result


def search_layout(fs: Flowsheet, budget: SearchBudget) -> SearchResult:
    """Search legal placements against completed routes without reseeding.

    Parameters
    ----------
    fs : Flowsheet
        Fully laid-out and routed drawing. Accepted moves update only
        its derived geometry and preserve model object identities.
    budget : SearchBudget
        Deterministic proposal and exact-route limits.

    Returns
    -------
    SearchResult
        Converged, unresolved, or budget-exhausted final state.

    Raises
    ------
    ValueError
        If input geometry is stale.
    """
    if fs._layout_stale or fs._route_stale:
        raise ValueError("search requires completed layout and routing")
    fs._layout_search_result = None
    live_quality = measure_final(fs)
    working = copy.deepcopy(fs)
    working._layout_search_result = None
    if fs._search_seed_frames is not None:
        for unit, frame in zip(process_units(working), fs._search_seed_frames):
            unit.frame = copy.deepcopy(frame)
    settle(working)
    seed_quality = measure_final(working)
    incumbent_quality = seed_quality
    structure = infer(working)
    seed_frames = tuple(copy.deepcopy(frame) for frame in _process_frames(working))
    seen = {_fingerprint(working)}
    accepted = 0
    exact = 0
    exhausted = False

    for _ in range(budget.max_passes):
        proposal_cap = min(budget.max_proposals_per_pass + 1, MAX_CANDIDATES)
        available = generate_moves(
            working,
            tuple(
                sorted(
                    (
                        *incumbent_quality.hard_conflicts,
                        *(
                            Conflict("crossing", streams=pair)
                            for pair in incumbent_quality.crossing_pairs
                        ),
                    )
                )
            ),
            limit=proposal_cap,
        )
        proposals = available[: budget.max_proposals_per_pass]
        if not proposals:
            if available:
                exhausted = True
            break
        incumbent_frames = _process_frames(working)
        best_score = _score(incumbent_quality, structure, seed_frames, incumbent_frames)
        best_drawing = None
        best_quality = None
        examined: set[tuple] = set()
        for move in proposals:
            if exact >= budget.max_exact_trials:
                exhausted = True
                break
            trial, drawing = _evaluate_candidate(working, move.apply, canonical=True)
            exact += 1
            fingerprint = _fingerprint(drawing)
            if fingerprint in seen or fingerprint in examined:
                continue
            examined.add(fingerprint)
            if not search_admissible(seed_quality, incumbent_quality, trial.after):
                continue
            frames = _process_frames(drawing)
            if not _structure_admissible(structure, seed_frames, incumbent_frames, frames):
                continue
            score = _score(trial.after, structure, seed_frames, frames)
            if score < best_score:
                best_score = score
                best_drawing = drawing
                best_quality = trial.after
        if best_drawing is None or best_quality is None:
            exhausted = exhausted or len(available) > len(proposals)
            break
        working = best_drawing
        accepted += 1
        incumbent_quality = best_quality
        seen.add(_fingerprint(working))
        if exhausted:
            break
    else:
        exhausted = bool(generate_moves(working, limit=1))

    live_frames = _process_frames(fs)
    publish = (
        _fingerprint(working) != _fingerprint(fs)
        and search_admissible(live_quality, live_quality, incumbent_quality)
        and _structure_admissible(structure, seed_frames, live_frames, _process_frames(working))
        and _score(incumbent_quality, structure, seed_frames, _process_frames(working))
        < _score(live_quality, structure, seed_frames, live_frames)
    )
    if publish:
        _publish_candidate(fs, working)
        final_quality = incumbent_quality
    else:
        accepted = 0
        final_quality = live_quality

    if not final_quality.hard_conflicts and not any(final_quality.hard):
        status: SearchStatus = "converged"
    elif exhausted or (budget.max_passes == 0 and bool(generate_moves(working, limit=1))):
        status = "budget_exhausted"
    else:
        status = "unresolved"
    return _search_result(fs, status, accepted, exact, final_quality)
