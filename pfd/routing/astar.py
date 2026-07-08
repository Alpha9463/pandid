import heapq
from typing import List, Tuple, Dict, Optional
from pfd.routing.visibility import VisibilityGraph

BEND_PENALTY = 500.0

def get_dir(p1: Tuple[float, float], p2: Tuple[float, float]) -> Optional[str]:
    if p1[0] < p2[0]: return "E"
    if p1[0] > p2[0]: return "W"
    if p1[1] < p2[1]: return "S"
    if p1[1] > p2[1]: return "N"
    return None

def heuristic(a: Tuple[float, float], b: Tuple[float, float], current_dir: Optional[str]) -> float:
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    h = dx + dy
    # Add a penalty if a bend will be required to reach the goal
    if dx > 0 and dy > 0:
        h += BEND_PENALTY
    return h

def find_path(
    graph: VisibilityGraph, 
    start: Tuple[float, float], 
    goal: Tuple[float, float], 
    start_dir: Optional[str] = None, 
    goal_dir: Optional[str] = None
) -> List[Tuple[float, float]]:
    """
    Finds the shortest orthogonal path on the visibility graph using A*.
    start_dir: Forced direction for the first step from start.
    goal_dir: The OUTWARD normal direction of the destination port. The path must arrive heading the opposite direction.
    """
    
    # Priority queue: (f_score, g_score, current_node, current_dir, path)
    # The tiebreaker is intrinsically handled if we use an id, but since we store path, 
    # we'll just push path length as tiebreaker to avoid comparing node tuples if f and g match.
    queue = []
    heapq.heappush(queue, (0, 0, 0, start, start_dir, [start]))
    
    # State key: ((x, y), dir)
    visited: Dict[Tuple[Tuple[float, float], Optional[str]], float] = {}
    
    # Count for tie-breaking
    counter = 1
    
    while queue:
        f, g, _, current, cur_dir, path = heapq.heappop(queue)
        
        if current == goal:
            return path
            
        state_key = (current, cur_dir)
        if state_key in visited and visited[state_key] <= g:
            continue
        visited[state_key] = g
        
        for neighbor in graph.edges.get(current, []):
            ndir = get_dir(current, neighbor)
            
            # 1. Enforce start direction strictly
            if len(path) == 1 and start_dir and ndir != start_dir:
                continue
                
            # 2. Enforce goal direction strictly
            if neighbor == goal and goal_dir:
                required_arrival_dir = {"N": "S", "S": "N", "E": "W", "W": "E"}.get(goal_dir)
                if ndir != required_arrival_dir:
                    continue
                    
            dist = abs(neighbor[0] - current[0]) + abs(neighbor[1] - current[1])
            cost = g + dist
            if cur_dir and ndir != cur_dir:
                cost += BEND_PENALTY
                
            h = heuristic(neighbor, goal, ndir)
            
            counter += 1
            heapq.heappush(queue, (cost + h, cost, counter, neighbor, ndir, path + [neighbor]))
            
    return []
