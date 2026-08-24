"""Post-processing pass to separate overlapping parallel segments."""

from typing import Any, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream

def _compute_offsets(
    streams: "Sequence[Stream]", spacing: float
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    """The h/v offsets ``separate_streams`` applies, without applying them.

    Split out so a caller can ask "where would this settle" without
    committing to it -- ``DefaultRouter.route()`` wants a preview of the
    streams routed so far, mid-loop, to price crossings against something
    closer to the drawn sheet than raw pre-separation geometry, but must
    not let that preview *become* the drawn sheet: this pass resolves every
    stream against every other one currently in the picture, so running it
    for real after each new stream would keep re-settling every earlier
    one's track against a shifting set of neighbours, and the final render
    would depend on routing order. One real, non-previewing call, against
    the complete final set, stays the only thing that writes waypoints.
    """
    # 1. Collect all runs.
    #
    # The unit is a *run* -- a maximal chain of consecutive segments on one axis
    # -- rather than a single segment. Consecutive segments on the same axis
    # share a waypoint, so they are collinear: they are one drawn line, and
    # offsetting them by different amounts would tear that line into a diagonal.
    # Such chains are ordinary, not exotic: the simplifier leaves one behind
    # every time it keeps a projection point that happened to be collinear.
    #
    # Tracks are the raw coordinate. Rounding the track and then applying
    # ``target - track`` to the unrounded waypoint leaves the run at
    # ``target + (raw - round(raw))``, up to half a pixel off the slot the
    # resolver picked for it -- which is enough to land a pair closer together
    # than the minimum spacing the resolver was enforcing.
    h_runs: list[dict[str, Any]] = []
    v_runs: list[dict[str, Any]] = []

    h_offsets: dict[tuple[int, int], float] = {}
    v_offsets: dict[tuple[int, int], float] = {}

    for s in streams:
        if not s.route or not s.route.waypoints:
            continue

        pts = s.route.waypoints
        n_segs = len(pts) - 1
        # The run the previous segment extended, and which axis it lies on.
        open_run: dict[str, Any] | None = None
        open_axis: str | None = None

        for i in range(n_segs):
            p1, p2 = pts[i], pts[i+1]
            is_fixed = (i == 0) or (i == n_segs - 1)
            flat_x = abs(p1[0] - p2[0]) < 0.1
            flat_y = abs(p1[1] - p2[1]) < 0.1

            if flat_x and flat_y:
                # A zero-length segment points nowhere, so it names no track of
                # its own. Carry it along with the run it interrupts, whichever
                # axis that is, so the run stays one line.
                if open_run is not None:
                    open_run["is_fixed"] = open_run["is_fixed"] or is_fixed
                    open_run["seg_idxs"].append(i)
                    offsets = h_offsets if open_axis == "h" else v_offsets
                    offsets[(id(s), i)] = 0.0
                continue

            if flat_y:  # Horizontal
                axis, runs, offsets = "h", h_runs, h_offsets
                track = p1[1]
                lo, hi = min(p1[0], p2[0]), max(p1[0], p2[0])
            elif flat_x:  # Vertical
                axis, runs, offsets = "v", v_runs, v_offsets
                track = p1[0]
                lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
            else:
                open_run, open_axis = None, None
                continue

            if open_run is not None and open_axis == axis:
                open_run["min_val"] = min(open_run["min_val"], lo)
                open_run["max_val"] = max(open_run["max_val"], hi)
                open_run["is_fixed"] = open_run["is_fixed"] or is_fixed
                open_run["seg_idxs"].append(i)
            else:
                open_run = {
                    "stream": id(s),
                    "seg_idxs": [i],
                    "track": track,
                    "min_val": lo,
                    "max_val": hi,
                    "is_fixed": is_fixed,
                }
                open_axis = axis
                runs.append(open_run)
            offsets[(id(s), i)] = 0.0

    def resolve_track(runs, offsets_dict):
        runs.sort(key=lambda r: r["min_val"])

        components = []
        current_comp = []
        current_max = -float('inf')

        for run in runs:
            # Overlap condition
            if run["min_val"] <= current_max + 0.1:
                current_comp.append(run)
                current_max = max(current_max, run["max_val"])
            else:
                if current_comp:
                    components.append(current_comp)
                current_comp = [run]
                current_max = run["max_val"]

        if current_comp:
            components.append(current_comp)


        for comp in components:
            if len(comp) <= 1:
                continue

            if len({run["stream"] for run in comp}) <= 1:
                continue  # one stream's own runs, nothing to separate

            # Resolve to absolute *target tracks*, not per-run deltas: the runs
            # in a component start on slightly different tracks, so nudging each
            # by its own delta can land two of them closer together than they
            # began. A run attached to a port ("fixed") must stay put -- it
            # holds the line on its nozzle -- so it claims its own track and
            # everyone else takes the nearest free slot on a spacing grid.
            #
            # Every fixed run claims its own track, one claim per *run* and not
            # one per stream: a stream that jogs between two nozzles contributes
            # two fixed runs at different heights, and giving the whole stream a
            # single track drags the second nozzle's run off it and flattens the
            # jog into a zero-length segment.
            fixed = [run for run in comp if run["is_fixed"]]
            pool = fixed or comp
            base = sum(run["track"] for run in pool) / len(pool)

            occupied = [run["track"] for run in fixed]
            nozzles: dict[int, list[float]] = {}
            for run in fixed:
                run["target"] = run["track"]
                nozzles.setdefault(run["stream"], []).append(run["track"])

            for run in comp:
                if run["is_fixed"]:
                    continue
                own = nozzles.get(run["stream"])
                if own:
                    # A free run of a stream already pinned in this component
                    # joins the nearer of its own nozzle tracks instead of taking
                    # a slot of its own. It is the same line: straightening it
                    # onto the track it is already heading for is what un-doubles
                    # it, and a slot of its own would only add two bends.
                    track = run["track"]
                    run["target"] = min(own, key=lambda t: (abs(t - track), t))
                    continue
                k = 0
                while "target" not in run:
                    for cand in ((base,) if k == 0 else (base + k * spacing, base - k * spacing)):
                        # Slots are compared at the spacing exactly; the epsilon
                        # only absorbs the float error in ``base + k * spacing``.
                        if all(abs(cand - o) >= spacing - 1e-9 for o in occupied):
                            run["target"] = cand
                            occupied.append(cand)
                            break
                    k += 1

            for run in comp:
                offset = run["target"] - run["track"]
                for seg_idx in run["seg_idxs"]:
                    offsets_dict[(run["stream"], seg_idx)] = offset

    # 2. Group by track and resolve.
    #
    # Tracks are clustered by proximity, not exact equality: two parallel runs a
    # couple of pixels apart are visually one doubled line (2px strokes), but an
    # exact-match bucket would file them separately and never separate them.
    # Single-linkage on the sorted tracks (compare against the previous run, not
    # the cluster's first member) keeps a run of near-coincident tracks in one
    # cluster; ``resolve_track`` then only separates those that also overlap
    # along their length, so genuinely distinct runs are left alone.
    def group_by_track(runs, tolerance):
        groups: list[list] = []
        current: list = []
        prev_track = None
        for run in sorted(runs, key=lambda r: r["track"]):
            if current and run["track"] - prev_track <= tolerance:
                current.append(run)
            else:
                if current:
                    groups.append(current)
                current = [run]
            prev_track = run["track"]
        if current:
            groups.append(current)
        return groups

    # The window is exactly ``spacing``. A neighbour closer than that is one the
    # resolver could nudge a run into, so it still has to be in the same cluster
    # and resolved in the same pass; a run further away than that is already
    # legible and has nothing to gain. Chaining at twice the spacing would sweep
    # up runs a comfortable 10–12px apart and then pack them onto the grid at the
    # 6px minimum (closer together than they started) and, where one stream
    # contributed two tracks to the cluster, would flatten that stream's own jog
    # onto a neighbour's track.
    window = spacing
    for group in group_by_track(h_runs, window):
        resolve_track(group, h_offsets)

    for group in group_by_track(v_runs, window):
        resolve_track(group, v_offsets)

    return h_offsets, v_offsets


def _apply_offsets(
    streams: "Sequence[Stream]",
    h_offsets: dict[tuple[int, int], float],
    v_offsets: dict[tuple[int, int], float],
) -> dict[int, list[tuple[float, float]]]:
    """Every stream's waypoints with ``h_offsets``/``v_offsets`` applied,
    keyed by ``id(stream)`` -- the shared arithmetic ``separate_streams``
    writes back and ``preview_separated_waypoints`` only hands to a caller.
    """
    result: dict[int, list[tuple[float, float]]] = {}
    for s in streams:
        if not s.route or not s.route.waypoints:
            continue

        pts = s.route.waypoints
        n_segs = len(pts) - 1
        new_pts = []

        for i, pt in enumerate(pts):
            dx = 0.0
            dy = 0.0

            if i > 0:
                seg_idx = i - 1
                if (id(s), seg_idx) in h_offsets:
                    dy = h_offsets[(id(s), seg_idx)]
                if (id(s), seg_idx) in v_offsets:
                    dx = v_offsets[(id(s), seg_idx)]

            # A waypoint's own segment wins over the one before it.
            if i < n_segs:
                seg_idx = i
                if (id(s), seg_idx) in h_offsets:
                    dy = h_offsets[(id(s), seg_idx)]
                if (id(s), seg_idx) in v_offsets:
                    dx = v_offsets[(id(s), seg_idx)]

            new_pts.append((pt[0] + dx, pt[1] + dy))

        result[id(s)] = new_pts
    return result


def separate_streams(fs: "Flowsheet", spacing: float = 6.0) -> None:
    """Detect overlapping parallel segments and offset them.

    This operates on the route waypoints in-place. The only caller that may
    do so -- see ``preview_separated_waypoints`` for the non-mutating form
    ``DefaultRouter.route()`` uses mid-loop, and ``_compute_offsets`` for why
    a second real (mutating) call per stream is not an option.
    """
    h_offsets, v_offsets = _compute_offsets(fs.streams, spacing)
    new_waypoints = _apply_offsets(fs.streams, h_offsets, v_offsets)
    for s in fs.streams:
        if id(s) in new_waypoints:
            s.route.waypoints = new_waypoints[id(s)]  # type: ignore[union-attr]


def preview_separated_waypoints(
    streams: "Sequence[Stream]", spacing: float = 6.0
) -> dict[int, list[tuple[float, float]]]:
    """Where ``separate_streams`` would put every already-routed stream's
    waypoints, without writing any of them back.

    ``DefaultRouter.route()`` rebuilds its crossing index from this after
    each stream, over the streams routed so far, so a later stream's search
    prices crossings against something much closer to the sheet that will
    actually get drawn than raw, pre-separation geometry -- without making
    the drawn sheet itself depend on routing order, which running the real,
    writing pass more than once would (see ``_compute_offsets``).

    Not a perfect match for the final drawing even so: a stream not yet
    routed can still pull an *already*-recorded track when it is added, the
    same way any later stream in this preview's own set can -- ``_compute
    _offsets`` resolves every run against every other one *currently*
    passed to it, from each one's own raw, undisplaced track, so a track
    two streams settled between themselves is not fixed once a third
    arrives to share it. Concretely: two unfixed runs sharing a track
    resolve to +0px/+6px; add a *third*, port-fixed run onto the +6px one
    -- unremarkable on its own, a fixed run always keeps its own track --
    and the recompute that follows moves *both* of the first two again,
    to +12px/+0px, not just makes room for the newcomer.

    #483's own corpus does exercise this, measured correctly the second
    time: capturing each stream's preview *at its own* ``settle()`` call
    (not the last preview it happens to appear in, which is a different
    question and trivially matches the final pass by construction) and
    comparing against its final, post-``separate_streams`` waypoints finds
    14 divergences out of 1032 already-routed streams checked, across both
    the pinned and auto-placed forms of all 21 shipped examples -- max
    shift 19.37px, all five on auto-placed sheets. The consequence is real:
    a later search can be undercharged for a crossing the finished drawing
    actually has, because the earlier stream's track moves again after
    that search already ran. Tracked as #509, with a reproduced case
    (``06_column_reflux+auto``, streams ``S7``/``S5``) rather than fixed
    here -- closing it needs either a second, full-set-aware separation
    pass before the crossing-sensitive decisions, or re-checking every
    stream against the real geometry after ``separate_streams``'s one true
    pass, both a larger change than this preview mechanism itself.
    """
    h_offsets, v_offsets = _compute_offsets(streams, spacing)
    return _apply_offsets(streams, h_offsets, v_offsets)
