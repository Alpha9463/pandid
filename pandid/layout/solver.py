"""One axis of placement, as a weighted least squares fit, in closed form.

Every claim on the sheet (:mod:`pandid.layout.claims`) is a preference
of the shape *the subject sits ``step`` further along this axis than the
author*, carrying a weight. No claim is a rule, so none has to be
dropped when two disagree; what is minimised instead is

.. code-block:: text

    sum over claims of  w * (p[subject] - p[author] - step) ** 2

which is the one statement that lets both ends of every run have a say.
Its stationary point is

.. code-block:: text

    p[k] = ( sum over claims ABOUT k of  w * (p[author] + step)
           + sum over claims BY    k of  w * (p[subject] - step) ) / sum w

-- the denominator running over every claim *touching* ``k``, so a
column authoring six claims at confidence 8 is stiff by 48 and barely
moves, while twenty neighbours asserting back at confidence 2 muster 40
between them and can. Weight is stiffness, not authority: nothing in
here ranks one claim over another, and a stiff relationship resists
deformation at both of its ends.

Why it is not iterated
----------------------
Written out over every unit at once, those stationary conditions are
``A p = b`` with ``A`` the weighted graph Laplacian -- symmetric,
diagonally dominant, and positive definite as soon as every connected
component holds one value that is not free to move. That is a linear
system with an exact answer, so it is **solved**, by Gaussian
elimination, rather than relaxed towards. There is therefore no
tolerance, no sweep cap, no seeding, no "did not converge" to report and
no float drift between one sweep and the next: one elimination order,
one answer, one rounding step at the end.

Why not a dense factorisation
-----------------------------
Because ``N`` is not bounded by the corpus. The widest shipped sheet is
101 units, where a dense Cholesky is ``101**3 / 6`` -- about 1.7e5
multiply-adds, nothing at all -- but
``tests/test_cycles_iterative.py`` lays out a **5000**-unit chain to
prove the walk does not recurse, and that is 2e10 multiply-adds over a
200 MB matrix, in a package that declares no dependencies and so has no
numpy to hand it to. A dense solve is not a slower answer there; it is
no answer.

The matrix is very sparse instead -- a P&ID unit has two or three
neighbours, near enough -- so it is eliminated **sparsely**, in
increasing order of degree (:func:`_ordering`). That is the classic
minimum-degree ordering, and on the shapes a flowsheet makes it is close
to optimal: a chain is eliminated end to end at ``O(N)`` with no fill-in
at all, and a real sheet's cost is dominated by whatever small dense
core is left once every unit of degree one or two has gone. The 5000
chain solves in the time the whole corpus does.

**The ordering is read off the sparsity pattern and never off the
numbers**, which is what keeps it deterministic: two candidates of equal
degree are separated by index, so the same sheet is eliminated in the
same order every run, and no comparison of two floats decides anything.

Pins are Dirichlet boundary conditions
--------------------------------------
A pinned unit is not a term in the objective and not an unknown in the
system: its row and column are struck out and its value is carried into
``b`` as a constant. It cannot be moved by construction, rather than by
a later pass being trusted not to move it -- which is what the engine
this replaces asked of its cycle breaker.
"""

from __future__ import annotations

import heapq
import math

#: Decimal places the solved position is quantised to before it is
#: rounded to a whole column or row. Doubles carry ~15 significant
#: digits and the positions are order 1e2, so the arithmetic noise is
#: around 1e-13; snapping at 1e-9 puts a value that is exactly a half in
#: theory exactly on the half in practice, so which way it rounds is a
#: stated rule and not a property of the elimination order.
PLACES = 9

#: ``(author, subject, weight, step)``: the subject sits ``step`` further
#: along the axis than the author, wanted this much. Index-based rather
#: than unit-based so that nothing about a P&ID reaches into the
#: arithmetic.
Pull = tuple[int, int, float, float]


def live(pulls: list[Pull]) -> list[Pull]:
    """The pulls that bear on the answer: positive weight, two ends.

    Both filters have to be applied *before* the components are found as
    well as before the matrix is built, or the two disagree about what
    is connected to what and a component the solve treats as free comes
    back unanchored -- a singular matrix. One function, called by both.
    """
    return [p for p in pulls if p[0] != p[1] and p[2] > 0.0]


def components(size: int, pulls: list[Pull]) -> list[list[int]]:
    """The connected components of the pull graph, each in index order.

    In the order their lowest member appears, so a caller choosing an
    anchor per component gets the same component in the same place on
    every run.
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
    """Every node's position on one axis, fitted to ``pulls``.

    ``fixed`` holds the nodes that may not move -- the author's pins,
    plus one anchor per component that has none, which the caller picks
    because which unit deserves to be the origin of a drawing is a
    question about drawings. Every component (:func:`components`) must
    hold one: without it that component's positions are determined only
    up to a shared translation, the matrix is singular, and
    :func:`_solve_spd` says so rather than handing back a drawing.
    """
    edges = live(pulls)
    free = [node for node in range(size) if node not in fixed]
    at = {node: row for row, node in enumerate(free)}
    n = len(free)

    a: list[dict[int, float]] = [{row: 0.0} for row in range(n)]
    b = [0.0] * n
    for author, subject, weight, step in edges:
        # Each end of a claim contributes one term to its own row. The
        # sign is which end this is: +1 where the row's node is the
        # subject and the step is measured towards it, -1 where it is
        # the author and the step is measured away.
        for node, other, sign in ((subject, author, 1.0), (author, subject, -1.0)):
            row = at.get(node)
            if row is None:
                continue  # a pinned node has no row; it is all constant
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
    """The free nodes' answers and the fixed nodes' values, in index order."""
    out = [0.0] * size
    for node, value in fixed.items():
        out[node] = value
    for row, node in enumerate(free):
        out[node] = solved[row]
    return out


def _solve_spd(a: list[dict[int, float]], b: list[float]) -> list[float]:
    """``A x = b`` for a sparse symmetric positive definite ``A``.

    Symmetric Gaussian elimination, both triangles held so that the
    neighbours of a row can be read without a search. Eliminating node
    ``k`` states ``x[k]`` in terms of what is left and substitutes it
    into every row that mentioned it, which fills in an edge between
    each pair of ``k``'s neighbours -- and choosing ``k`` by degree
    (:func:`_ordering`) is what keeps that fill small.

    No pivoting, and none needed: an anchored Laplacian is positive
    definite, so every pivot is positive whatever symmetric permutation
    is applied. That is what lets the order come from the graph rather
    than from a comparison of two floats, and so what makes the same
    sheet eliminate the same way on every run.

    ``a`` and ``b`` are read and written in place; :func:`relax` builds
    both fresh per axis and nothing else holds them.
    """
    steps: list[tuple[int, float, list[tuple[int, float]]]] = []
    for k in _ordering(a):
        row = a[k]
        pivot = row.pop(k)
        # Positive by construction, an anchored Laplacian being SPD. A
        # pivot at or below zero means the caller left a component
        # unanchored, which is a bug in the caller and not a sheet to
        # draw round.
        assert pivot > 0.0, "the pull graph has an unanchored component"
        # Sorted, so the arithmetic is done in a canonical order rather
        # than in whichever order the fill-in happened to arrive: float
        # addition is not associative and the sums below are where a
        # different order would show up in the answer.
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
    """The elimination order: least connected first, ties by index.

    Minimum degree, recomputed as the fill-in changes it, which on a
    flowsheet's shapes costs almost nothing and saves almost
    everything: a chain is all degree two and comes out linear, while
    eliminating it in index order would be linear as well but the same
    chain wired into a plant would not be.

    The heap carries a degree that may be stale by the time it is
    popped -- eliminating a node changes its neighbours' degrees, and
    finding and mending their heap entries costs more than letting a
    superseded one surface and be discarded. A node is admitted only
    when the degree it was pushed with is the degree it still has.
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
    """The whole column or row a fitted position lands on.

    Rounded **half away from zero**, at :data:`PLACES`. Half away rather
    than Python's half-to-even because the sheet has a symmetry the
    banker's rule does not: a peer half a step east of its source and one
    half a step west are the same drawing mirrored, and to-even sends the
    first to 0 and the second to -1. Which is also why the value is
    quantised first -- a half that arrives as 0.49999999999999994 is a
    half.
    """
    value = round(value, PLACES)
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)
