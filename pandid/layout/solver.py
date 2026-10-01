"""Fit one placement axis by weighted least squares, solved exactly.

Each claim (:mod:`pandid.layout.claims`) asks that the subject sit
``step`` further along the axis than the author, with weight ``w``. The
fit minimises

.. code-block:: text

    sum over claims of  w * (p[subject] - p[author] - step) ** 2

Its stationary conditions form ``A p = b``, where ``A`` is the weighted
graph Laplacian. Weight acts as stiffness at both ends of a claim; no
claim outranks another.

The system is solved directly, not iterated, so there is no tolerance or
convergence check. ``A`` is symmetric positive definite once every
connected component has one fixed node, so Gaussian elimination needs no
pivoting. It is eliminated sparsely in minimum-degree order
(:func:`_ordering`): a chain costs O(N) with no fill-in, which keeps very
long chains (5,000 units in ``tests/test_cycles_iterative.py``) fast
without numpy. The order depends only on the sparsity pattern, with ties
broken by index, so the same sheet always solves the same way.

Pinned nodes are boundary conditions: they are removed from the unknowns
and their values move into ``b``, so a pin cannot move.
"""

from __future__ import annotations

import heapq
import math

#: Decimal places a solved position is rounded to before it is snapped to
#: a whole rank. Arithmetic noise is about 1e-13 at these magnitudes, so a
#: position that is a half in theory stays exactly a half.
PLACES = 9

#: ``(author, subject, weight, step)`` by node index: the subject sits
#: ``step`` further along the axis than the author, with this weight.
Pull = tuple[int, int, float, float]


def live(pulls: list[Pull]) -> list[Pull]:
    """Return the pulls that affect the fit.

    :func:`components` and :func:`relax` both filter through this, so they
    agree on which nodes are connected.

    Parameters
    ----------
    pulls : list[Pull]
        All pulls on the axis.

    Returns
    -------
    list[Pull]
        Pulls with positive weight between two different nodes.
    """
    return [p for p in pulls if p[0] != p[1] and p[2] > 0.0]


def components(size: int, pulls: list[Pull]) -> list[list[int]]:
    """Return the connected components of the pull graph.

    Parameters
    ----------
    size : int
        Number of nodes.
    pulls : list[Pull]
        Pulls on the axis.

    Returns
    -------
    list[list[int]]
        Components ordered by their lowest node, each sorted by index.
    """
    adjacent: list[list[int]] = [[] for _ in range(size)]
    for author, subject, _weight, _step in live(pulls):
        adjacent[author].append(subject)
        adjacent[subject].append(author)

    seen = [False] * size
    out: list[list[int]] = []
    for root in range(size):
        if seen[root]:
            continue
        seen[root] = True
        group = [root]
        frontier = [root]
        while frontier:
            node = frontier.pop()
            for peer in adjacent[node]:
                if not seen[peer]:
                    seen[peer] = True
                    group.append(peer)
                    frontier.append(peer)
        out.append(sorted(group))
    return out


def relax(size: int, pulls: list[Pull], fixed: dict[int, float]) -> list[float]:
    """Fit every node's position on one axis.

    Parameters
    ----------
    size : int
        Number of nodes.
    pulls : list[Pull]
        Pulls on the axis.
    fixed : dict[int, float]
        Positions that may not move: pins, plus one anchor chosen by the
        caller for each component (:func:`components`) without a pin.

    Returns
    -------
    list[float]
        Position of every node, in index order.

    Raises
    ------
    AssertionError
        If a component has no fixed node, which makes ``A`` singular.
    """
    edges = live(pulls)
    free = [node for node in range(size) if node not in fixed]
    at = {node: row for row, node in enumerate(free)}
    n = len(free)

    a: list[dict[int, float]] = [{row: 0.0} for row in range(n)]
    b = [0.0] * n
    for author, subject, weight, step in edges:
        # Each end adds a term to its own row: +step for the subject,
        # -step for the author.
        for node, other, sign in ((subject, author, 1.0), (author, subject, -1.0)):
            row = at.get(node)
            if row is None:
                continue  # a pinned node has no row
            here = a[row]
            here[row] += weight
            column = at.get(other)
            if column is None:
                b[row] += weight * fixed[other]
            else:
                here[column] = here.get(column, 0.0) - weight
            b[row] += sign * weight * step

    return _scatter(size, free, fixed, _solve_spd(a, b))


def _scatter(size: int, free: list[int], fixed: dict[int, float],
             solved: list[float]) -> list[float]:
    """Merge solved free positions and fixed positions into one list.

    Parameters
    ----------
    size : int
        Number of nodes.
    free : list[int]
        Free node indices, in solve order.
    fixed : dict[int, float]
        Fixed node positions.
    solved : list[float]
        Solved position per free node.

    Returns
    -------
    list[float]
        Position of every node, in index order.
    """
    out = [0.0] * size
    for node, value in fixed.items():
        out[node] = value
    for row, node in enumerate(free):
        out[node] = solved[row]
    return out


def _solve_spd(a: list[dict[int, float]], b: list[float]) -> list[float]:
    """Solve ``A x = b`` for a sparse symmetric positive definite ``A``.

    Symmetric Gaussian elimination in :func:`_ordering` order, without
    pivoting; every pivot of an anchored Laplacian is positive. Both
    triangles are stored so a row's neighbours are read directly.

    Parameters
    ----------
    a : list[dict[int, float]]
        Rows of ``A`` as ``{column: value}``. Modified in place.
    b : list[float]
        Right-hand side. Modified in place.

    Returns
    -------
    list[float]
        Solution ``x``.

    Raises
    ------
    AssertionError
        If a pivot is not positive (a component was left unanchored).
    """
    steps: list[tuple[int, float, list[tuple[int, float]]]] = []
    for k in _ordering(a):
        row = a[k]
        pivot = row.pop(k)
        # A non-positive pivot means the caller left a component unanchored.
        assert pivot > 0.0, "the pull graph has an unanchored component"
        # Sort so the sums run in a fixed order; float addition is not
        # associative.
        neighbours = sorted(row.items())
        for i, a_ki in neighbours:
            factor = a_ki / pivot
            here = a[i]
            del here[k]
            b[i] -= factor * b[k]
            for j, a_kj in neighbours:
                here[j] = here.get(j, 0.0) - factor * a_kj
        steps.append((k, pivot, neighbours))

    x = [0.0] * len(b)
    for k, pivot, neighbours in reversed(steps):
        total = b[k]
        for i, a_ki in neighbours:
            total -= a_ki * x[i]
        x[k] = total / pivot
    return x


def _ordering(a: list[dict[int, float]]) -> list[int]:
    """Return the minimum-degree elimination order, ties broken by index.

    Degrees are updated as fill-in changes them. Heap entries may be stale;
    an entry is used only when its degree still matches the node's current
    degree.

    Parameters
    ----------
    a : list[dict[int, float]]
        Rows of ``A``; only the sparsity pattern is read.

    Returns
    -------
    list[int]
        Row indices in elimination order.
    """
    live_rows = [dict(row) for row in a]
    heap = [(len(row) - 1, node) for node, row in enumerate(live_rows)]
    heapq.heapify(heap)
    gone = [False] * len(live_rows)
    out: list[int] = []
    while heap:
        degree, node = heapq.heappop(heap)
        if gone[node] or degree != len(live_rows[node]) - 1:
            continue
        gone[node] = True
        out.append(node)
        peers = [i for i in live_rows[node] if i != node]
        for i in peers:
            row = live_rows[i]
            del row[node]
            for j in peers:
                if j != i:
                    row.setdefault(j, 0.0)
            heapq.heappush(heap, (len(row) - 1, i))
    return out


def discretise(value: float) -> int:
    """Round a fitted position to a whole column or row.

    The value is first rounded to :data:`PLACES` decimals, then rounded
    half away from zero, so positions half a step either side of zero
    mirror each other (Python's ``round`` rounds half to even).

    Parameters
    ----------
    value : float
        Fitted position.

    Returns
    -------
    int
        Whole rank.
    """
    value = round(value, PLACES)
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)
