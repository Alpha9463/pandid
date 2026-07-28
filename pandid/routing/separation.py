"""Post-processing pass to separate overlapping parallel segments."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.flowsheet import Flowsheet

def separate_streams(fs: "Flowsheet", spacing: float = 6.0) -> None:
    """Detect overlapping parallel segments and offset them.
    
    This operates on the route waypoints in-place.
    """
    # 1. Collect all segments
    h_segs = []
    v_segs = []
    
    h_offsets = {}
    v_offsets = {}
    
    for s in fs.streams:
        if not s.route or not s.route.waypoints:
            continue
            
        pts = s.route.waypoints
        n_segs = len(pts) - 1
        
        for i in range(n_segs):
            p1, p2 = pts[i], pts[i+1]
            is_fixed = (i == 0) or (i == n_segs - 1)
            
            if abs(p1[1] - p2[1]) < 0.1: # Horizontal
                x_min, x_max = min(p1[0], p2[0]), max(p1[0], p2[0])
                h_segs.append({
                    "stream": id(s),
                    "seg_idx": i,
                    "track": round(p1[1]),
                    "min_val": x_min,
                    "max_val": x_max,
                    "is_fixed": is_fixed
                })
                h_offsets[(id(s), i)] = 0.0
                
            elif abs(p1[0] - p2[0]) < 0.1: # Vertical
                y_min, y_max = min(p1[1], p2[1]), max(p1[1], p2[1])
                v_segs.append({
                    "stream": id(s),
                    "seg_idx": i,
                    "track": round(p1[0]),
                    "min_val": y_min,
                    "max_val": y_max,
                    "is_fixed": is_fixed
                })
                v_offsets[(id(s), i)] = 0.0

    def resolve_track(segments, offsets_dict):
        segments.sort(key=lambda s: s["min_val"])
        
        components = []
        current_comp = []
        current_max = -float('inf')
        
        for seg in segments:
            # Overlap condition
            if seg["min_val"] <= current_max + 0.1:
                current_comp.append(seg)
                current_max = max(current_max, seg["max_val"])
            else:
                if current_comp:
                    components.append(current_comp)
                current_comp = [seg]
                current_max = seg["max_val"]
                
        if current_comp:
            components.append(current_comp)
            
        for comp in components:
            if len(comp) <= 1:
                continue

            streams_in_comp = []
            for seg in comp:
                if seg["stream"] not in streams_in_comp:
                    streams_in_comp.append(seg["stream"])
            if len(streams_in_comp) <= 1:
                continue  # one stream's own segments, nothing to separate

            # Resolve to absolute *target tracks*, not per-segment deltas: the
            # segments in a component start on slightly different tracks, so
            # nudging each by its own delta can land two of them closer together
            # than they began. Segments attached to a port ("fixed") must stay
            # put (they hold the line on its nozzle), so they claim their track
            # and everyone else takes the nearest free slot on a spacing grid.
            fixed_track: dict = {}
            for seg in comp:
                if seg["is_fixed"] and seg["stream"] not in fixed_track:
                    fixed_track[seg["stream"]] = seg["track"]

            if fixed_track:
                base = sum(fixed_track.values()) / len(fixed_track)
            else:
                base = sum(s["track"] for s in comp) / len(comp)

            targets = dict(fixed_track)
            occupied = list(fixed_track.values())
            for st in streams_in_comp:
                if st in targets:
                    continue
                k = 0
                while True:
                    for cand in ((base,) if k == 0 else (base + k * spacing, base - k * spacing)):
                        if all(abs(cand - o) >= spacing - 0.5 for o in occupied):
                            targets[st] = cand
                            occupied.append(cand)
                            break
                    if st in targets:
                        break
                    k += 1

            for seg in comp:
                offsets_dict[(seg["stream"], seg["seg_idx"])] = (
                    targets[seg["stream"]] - seg["track"])

    # 2. Group by track and resolve.
    #
    # Tracks are clustered by proximity, not exact equality: two parallel runs a
    # couple of pixels apart are visually one doubled line (2px strokes), but an
    # exact-match bucket would file them separately and never separate them.
    # Single-linkage on the sorted tracks (compare against the previous segment,
    # not the cluster's first member) keeps a run of near-coincident tracks in
    # one cluster; ``resolve_track`` then only separates those that also overlap
    # along their length, so genuinely distinct runs are left alone.
    def group_by_track(segs, tolerance):
        groups: list[list] = []
        current: list = []
        prev_track = None
        for seg in sorted(segs, key=lambda s: s["track"]):
            if current and seg["track"] - prev_track <= tolerance:
                current.append(seg)
            else:
                if current:
                    groups.append(current)
                current = [seg]
            prev_track = seg["track"]
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
    for group in group_by_track(h_segs, window):
        resolve_track(group, h_offsets)

    for group in group_by_track(v_segs, window):
        resolve_track(group, v_offsets)
        
    # 3. Apply offsets to waypoints
    for s in fs.streams:
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
            
        s.route.waypoints = new_pts
