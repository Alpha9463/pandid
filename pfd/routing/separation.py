"""Post-processing pass to separate overlapping parallel segments."""

from typing import TYPE_CHECKING
from collections import defaultdict

if TYPE_CHECKING:
    from pfd.flowsheet import Flowsheet

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
                    "stream": s.name,
                    "seg_idx": i,
                    "track": round(p1[1]),
                    "min_val": x_min,
                    "max_val": x_max,
                    "is_fixed": is_fixed
                })
                h_offsets[(s.name, i)] = 0.0
                
            elif abs(p1[0] - p2[0]) < 0.1: # Vertical
                y_min, y_max = min(p1[1], p2[1]), max(p1[1], p2[1])
                v_segs.append({
                    "stream": s.name,
                    "seg_idx": i,
                    "track": round(p1[0]),
                    "min_val": y_min,
                    "max_val": y_max,
                    "is_fixed": is_fixed
                })
                v_offsets[(s.name, i)] = 0.0

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
                    
            fixed_streams = set()
            for seg in comp:
                if seg["is_fixed"]:
                    fixed_streams.add(seg["stream"])
                    
            non_fixed_streams = [s for s in streams_in_comp if s not in fixed_streams]
            assigned_offsets = {fs_name: 0.0 for fs_name in fixed_streams}
                
            current_offset_idx = 1
            if not fixed_streams:
                if non_fixed_streams:
                    assigned_offsets[non_fixed_streams[0]] = 0.0
                    non_fixed_streams = non_fixed_streams[1:]
            
            for s_name in non_fixed_streams:
                if current_offset_idx > 0:
                    assigned_offsets[s_name] = current_offset_idx * spacing
                    current_offset_idx = -current_offset_idx
                else:
                    assigned_offsets[s_name] = current_offset_idx * spacing
                    current_offset_idx = -current_offset_idx + 1
                    
            for seg in comp:
                offsets_dict[(seg["stream"], seg["seg_idx"])] = assigned_offsets[seg["stream"]]

    # 2. Group by track and resolve
    h_by_track = defaultdict(list)
    for seg in h_segs:
        h_by_track[seg["track"]].append(seg)
    for track, segs in h_by_track.items():
        resolve_track(segs, h_offsets)
        
    v_by_track = defaultdict(list)
    for seg in v_segs:
        v_by_track[seg["track"]].append(seg)
    for track, segs in v_by_track.items():
        resolve_track(segs, v_offsets)
        
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
            
            # Look at segment before (if any)
            if i > 0:
                seg_idx = i - 1
                if (s.name, seg_idx) in h_offsets:
                    dy = h_offsets[(s.name, seg_idx)]
                if (s.name, seg_idx) in v_offsets:
                    dx = v_offsets[(s.name, seg_idx)]
                    
            # Look at segment after (if any)
            if i < n_segs:
                seg_idx = i
                if (s.name, seg_idx) in h_offsets:
                    dy = h_offsets[(s.name, seg_idx)]
                if (s.name, seg_idx) in v_offsets:
                    dx = v_offsets[(s.name, seg_idx)]
                    
            new_pts.append((pt[0] + dx, pt[1] + dy))
            
        s.route.waypoints = new_pts
