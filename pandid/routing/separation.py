"""Separate routed streams that share a track.

Overlapping runs of different streams on tracks within :data:`SPACING`
move apart; end runs and manual routes keep their track.
"""

from typing import Any, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet
    from pandid.streams import Stream

#: Track grid step, and the least gap a moved run keeps.
SPACING = 6.0


def _compute_offsets(
    streams: "Sequence[Stream]", spacing: float
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]:
    """Return the offsets for horizontal and vertical segments.

    Parameters
    ----------
    streams : Sequence[Stream]
        Routed streams.
    spacing : float
        Track grid step, and the least gap a moved run keeps.

    Returns
    -------
    tuple[dict, dict]
        Horizontal and vertical offsets by ``(id(stream), segment)``.
    """
    # A run is a maximal chain of consecutive segments on one axis.
    h_runs: list[dict[str, Any]] = []
    v_runs: list[dict[str, Any]] = []

    h_offsets: dict[tuple[int, int], float] = {}
    v_offsets: dict[tuple[int, int], float] = {}

    from pandid.portgeom import unit_box

    for s in streams:
        if not s.route or not s.route.waypoints:
            continue

        ends = (s.source.owner, s.dest.owner)
        boxes = [unit_box(u, u.frame) for u in ends if u is not None and u.frame is not None]
        pts = s.route.waypoints
        n_segs = len(pts) - 1
        # Every run of a via() route is fixed.
        manual = s.route.manual
        # The run the previous segment extended, and its axis.
        open_run: dict[str, Any] | None = None
        open_axis: str | None = None

        for i in range(n_segs):
            p1, p2 = pts[i], pts[i+1]
            is_fixed = manual or (i == 0) or (i == n_segs - 1)
            flat_x = abs(p1[0] - p2[0]) < 0.1
            flat_y = abs(p1[1] - p2[1]) < 0.1

            if flat_x and flat_y:
                # A zero-length segment joins the run it interrupts.
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
                    "axis": axis,
                    "boxes": boxes,
                    "seg_idxs": [i],
                    "track": track,
                    "min_val": lo,
                    "max_val": hi,
                    "is_fixed": is_fixed,
                }
                open_axis = axis
                runs.append(open_run)
            offsets[(id(s), i)] = 0.0

    def enters(run, track):
        """Return whether a run on a track crosses its end units.

        Parameters
        ----------
        run : dict
            Run to test.
        track : float
            Candidate track coordinate.

        Returns
        -------
        bool
            Whether the run would enter one of its end units.
        """
        lo, hi = run["min_val"], run["max_val"]
        for x0, y0, x1, y1 in run["boxes"]:
            across, along = ((y0, y1), (x0, x1)) if run["axis"] == "h" else ((x0, x1), (y0, y1))
            if across[0] <= track <= across[1] and hi > along[0] and lo < along[1]:
                return True
        return False

    def resolve_track(runs, offsets_dict):
        """Assign target tracks to one cluster of nearby runs.

        Runs that overlap along their length form a component. In a
        component of several streams, fixed runs keep their track, a
        free run joins its stream's nearest fixed track, and any other
        run takes the nearest free slot on a ``spacing`` grid around
        the fixed runs' mean track, or all runs' if none is fixed.

        Parameters
        ----------
        runs : list[dict]
            Runs of one cluster.
        offsets_dict : dict[tuple[int, int], float]
            Offsets to write, by ``(id(stream), segment)``.
        """
        runs.sort(key=lambda r: r["min_val"])

        components = []
        current_comp = []
        current_max = -float('inf')

        for run in runs:
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
                continue

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
                own = [t for t in nozzles.get(run["stream"], []) if not enters(run, t)]
                if own:
                    track = run["track"]
                    run["target"] = min(own, key=lambda t: (abs(t - track), t))
                    continue
                k = 0
                while "target" not in run:
                    for cand in ((base,) if k == 0 else (base + k * spacing, base - k * spacing)):
                        if (all(abs(cand - o) >= spacing - 1e-9 for o in occupied)
                                and not enters(run, cand)):
                            run["target"] = cand
                            occupied.append(cand)
                            break
                    k += 1

            for run in comp:
                offset = run["target"] - run["track"]
                for seg_idx in run["seg_idxs"]:
                    offsets_dict[(run["stream"], seg_idx)] = offset

    def group_by_track(runs, tolerance):
        """Cluster runs whose tracks chain within ``tolerance``.

        Parameters
        ----------
        runs : list[dict]
            Runs on one axis.
        tolerance : float
            Largest gap between neighbouring tracks in a cluster.

        Returns
        -------
        list[list[dict]]
            Clusters in track order.
        """
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
    """Return each stream's waypoints moved by the segment offsets.

    Parameters
    ----------
    streams : Sequence[Stream]
        Routed streams.
    h_offsets : dict[tuple[int, int], float]
        Horizontal-segment offsets by ``(id(stream), segment)``.
    v_offsets : dict[tuple[int, int], float]
        Vertical-segment offsets by ``(id(stream), segment)``.

    Returns
    -------
    dict[int, list[tuple[float, float]]]
        Offset waypoints by ``id(stream)``, for each routed stream.
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


def separate_streams(fs: "Flowsheet") -> None:
    """Separate overlapping runs and rewrite every automatic route.

    Parameters
    ----------
    fs : Flowsheet
        Sheet with routed streams.
    """
    h_offsets, v_offsets = _compute_offsets(fs.streams, SPACING)
    new_waypoints = _apply_offsets(fs.streams, h_offsets, v_offsets)
    for s in fs.streams:
        if id(s) in new_waypoints and not s.route.manual:  # type: ignore[union-attr]
            s.route.waypoints = new_waypoints[id(s)]  # type: ignore[union-attr]


def preview_separated_waypoints(
    streams: "Sequence[Stream]",
) -> dict[int, list[tuple[float, float]]]:
    """Return each stream's separated waypoints.

    Parameters
    ----------
    streams : Sequence[Stream]
        Routed streams.

    Returns
    -------
    dict[int, list[tuple[float, float]]]
        Separated waypoints by ``id(stream)``, for each routed stream.
    """
    h_offsets, v_offsets = _compute_offsets(streams, SPACING)
    return _apply_offsets(streams, h_offsets, v_offsets)
