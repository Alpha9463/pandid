import heapq
import math
from typing import List, Tuple, Dict, Optional
from pandid.routing.visibility import VisibilityGraph

BEND_PENALTY = 500.0

# What the search is allowed to spend before it is called a bug rather than a
# hard sheet. A* terminates because ``visited`` settles each state at most
# once, and that argument holds only while the costs compare: a single NaN
# coordinate makes ``visited[state] <= g`` false for ever, so every state
# re-expands and the queue's paths grow until the process dies. A ceiling makes
# termination unconditional rather than conditional on the numbers.
#
# The budget is the larger of a flat floor and a per-node allowance, because
# the two bind at opposite ends. A small graph is cheap to re-cross, so its
# cost per node is high -- the worst of 14,107 real searches across the suite
# and the examples expands 9.5 states per node, on a graph of 219. A large
# graph is never crossed more than a fraction of the way: that same corpus
# never expands more than 2,411 states in total, on a graph of 3,082. So the
# floor carries the small graphs and the allowance carries the large, and each
# leaves about twenty times the worst measured demand.
MAX_EXPANSIONS_PER_NODE = 16
MIN_EXPANSION_BUDGET = 50_000

OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}

def get_dir(p1: Tuple[float, float], p2: Tuple[float, float]) -> Optional[str]:
    if p1[0] < p2[0]:
        return "E"
    if p1[0] > p2[0]:
        return "W"
    if p1[1] < p2[1]:
        return "S"
    if p1[1] > p2[1]:
        return "N"
    return None

def heuristic(a: Tuple[float, float], b: Tuple[float, float]) -> float:
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
    goal_dir: Optional[str] = None,
    edge_penalties: Optional[Dict[Tuple[Tuple[float, float], Tuple[float, float]], float]] = None,
    is_recycle: bool = False
) -> List[Tuple[float, float]]:
    """Find the shortest orthogonal path on the visibility graph using A*.

    start_dir: The OUTWARD normal direction of the source port. ``start`` is already
        the port's projected escape node, so this only seeds the travel direction;
        it is not re-imposed on the first step.
    goal_dir: The OUTWARD normal direction of the destination port. The path must arrive heading the opposite direction.

    Raises ``ValueError`` on a non-finite endpoint, and ``RuntimeError`` on a
    search that will not settle within its expansion budget. Both beat the
    alternative, which is a render that never returns at all.
    """
    for role, point in (("start", start), ("goal", goal)):
        if not (math.isfinite(point[0]) and math.isfinite(point[1])):
            raise ValueError(
                f"cannot route from a non-finite {role} {point!r}: every "
                f"comparison against it is false, so the search would settle "
                f"no state and never return."
            )

    if edge_penalties is None:
        edge_penalties = {}

    budget = max(MIN_EXPANSION_BUDGET, MAX_EXPANSIONS_PER_NODE * len(graph.nodes))
    expansions = 0

    # Priority queue: (f_score, g_score, counter, current_node, current_dir, path)
    # The counter breaks ties so equal (f, g) entries never fall through to
    # comparing the node tuples themselves.
    queue: list[tuple[float, float, int, tuple[float, float], Optional[str], list[tuple[float, float]]]] = []
    heapq.heappush(queue, (0, 0, 0, start, start_dir, [start]))
    
    # State key: ((x, y), dir)
    visited: Dict[Tuple[Tuple[float, float], Optional[str]], float] = {}
    
    # Count for tie-breaking
    counter = 1
    
    while queue:
        expansions += 1
        if expansions > budget:
            raise RuntimeError(
                f"routing {start} -> {goal} expanded {expansions} states over "
                f"{len(graph.nodes)} graph nodes, past the {budget} this graph "
                f"is allowed, without settling. The search is not converging: "
                f"suspect a coordinate that does not compare, or a cost that "
                f"keeps falling."
            )
        f, g, _, current, cur_dir, path = heapq.heappop(queue)

        if current == goal:
            return path
            
        state_key = (current, cur_dir)
        if state_key in visited and visited[state_key] <= g:
            continue
        visited[state_key] = g
        
        for neighbor in graph.edges.get(current, []):
            ndir = get_dir(current, neighbor)
            
            # 1. Never reverse along the axis just travelled. A reversal
            #    retraces the segment it just drew, and the cost model charges
            #    it a single bend, cheaper than the honest two-bend detour
            #    around the obstacle that provoked it, so without this ban the
            #    search prefers lines drawn over themselves.
            #
            #    ``start`` is the port's *projected* escape node and the caller
            #    draws the anchor->projection stub itself, so the square exit is
            #    already guaranteed. Seeding ``cur_dir`` with ``start_dir`` and
            #    banning the reverse is therefore the whole port constraint:
            #    the path may turn immediately, but never back over the stub.
            #    Re-imposing ``start_dir`` on the first step instead would buy an
            #    arbitrary extra hop outward before any turn was allowed.
            if cur_dir and ndir == OPPOSITE[cur_dir]:
                continue

            # 2. Goal approach. The router appends a perpendicular goal_proj->port
            #    segment, so the port is always entered squarely however
            #    goal_proj is reached. Allow reaching it head-on OR from either
            #    side; only forbid arriving from *behind* (heading along the
            #    outward normal = coming through the unit body). Requiring a
            #    strictly head-on arrival forces tall detours up to the sheet
            #    edge to line up above a top/bottom port.
            if neighbor == goal and goal_dir:
                if ndir == goal_dir:
                    continue
                    
            dist = abs(neighbor[0] - current[0]) + abs(neighbor[1] - current[1])
            cost = g + dist + edge_penalties.get((current, neighbor), 0.0)
            
            # Boundary penalty: penalize edges that lie exactly on an obstacle boundary
            if current[0] == neighbor[0]: # vertical
                for o in graph.obstacles:
                    if current[0] == o.x_min or current[0] == o.x_max:
                        if max(current[1], neighbor[1]) > o.y_min and min(current[1], neighbor[1]) < o.y_max:
                            cost += 2000
                            break
            elif current[1] == neighbor[1]: # horizontal
                for o in graph.obstacles:
                    if current[1] == o.y_min or current[1] == o.y_max:
                        if max(current[0], neighbor[0]) > o.x_min and min(current[0], neighbor[0]) < o.x_max:
                            cost += 2000
                            break
                            
            bend_cost = BEND_PENALTY
            if is_recycle:
                bend_cost = BEND_PENALTY / 2.0
                if (current[1] == neighbor[1] and current[1] not in graph.recycle_y
                        and current[1] not in (start[1], goal[1])):
                    # Penalize off-lane horizontal travel, EXCEPT at the stream's own
                    # port elevations: lets a short recycle run straight at its port
                    # height instead of dipping down to the lane and back.
                    cost += dist * 10.0
            else:
                # Recycle lanes are reserved for recycle streams. Forbid forward
                # streams from travelling along them so up-and-over routes hug the
                # equipment instead of spiking to the sheet edge (looks "cut off").
                if current[1] == neighbor[1] and current[1] in graph.recycle_y:
                    cost += 100000.0
            
            if cur_dir and ndir != cur_dir:
                cost += bend_cost
                
            h = heuristic(neighbor, goal)
            if is_recycle:
                h = h / 2.0  # reduce heuristic slightly so it explores the longer recycle lanes
            
            counter += 1
            heapq.heappush(queue, (cost + h, cost, counter, neighbor, ndir, path + [neighbor]))
            
    return []
