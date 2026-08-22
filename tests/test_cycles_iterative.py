"""#413: the cycle-breaking walk must not recurse to the depth of the
longest unbranched chain, and the iterative rewrite must mark exactly
the edges the recursive walk it replaced would have.

The second half is the one a golden corpus cannot promise on its own
-- the goldens exercise the shapes this project happens to draw, not
every shape a feedback-arc walk can be handed. So this file also
carries a small, self-contained copy of the *pre-fix* recursive walk
(``_reference_recursive_marks``) and compares its marking against the
real, current ``break_cycles`` over many generated topologies.
"""

from __future__ import annotations

import random
import sys

from pandid import Flowsheet, units as U
from pandid.layout.stages import process_streams, process_units
from pandid.layout.cycles import break_cycles
from pandid.streams import Stream
from pandid.units import Unit


def _build_chain(n: int) -> Flowsheet:
    fs = Flowsheet("chain")
    prev_port = fs.add(U.Feed("F")).outlet
    for i in range(n):
        u = fs.add(U.Pump(f"P-{i}"))
        fs.connect(prev_port, u.suction)
        prev_port = u.discharge
    fs.connect(prev_port, fs.add(U.Product("OUT")).inlet)
    return fs


def test_long_chain_lays_out_without_recursion_error():
    """A chain well past both the default recursion limit and the
    1500-unit chain #413 crashed on now lays out cleanly."""
    n = 5000
    assert n > sys.getrecursionlimit()
    fs = _build_chain(n)
    fs.layout()  # must not raise RecursionError
    recycles = [s for s in fs.streams if s.is_recycle]
    assert recycles == []  # a plain chain closes no loop


def test_long_chain_with_a_recycle_still_marks_it():
    """The walk still finds the one back edge on a long chain, not just
    surviving one with none. Built with a mixer at the head so the
    recycle has a nozzle of its own, and a splitter partway down so the
    tap feeding it back is a fresh outlet, not one the forward chain is
    already using."""
    n = 3000
    fs2 = Flowsheet("chain-with-recycle")
    feed = fs2.add(U.Feed("F"))
    head = fs2.add(U.Mixer("M", n_inlets=2))
    fs2.connect(feed.outlet, head.in_1)
    prev_port = head.outlet
    tap = None
    for i in range(n):
        if i == 1500:
            u = fs2.add(U.Splitter(f"SP-{i}", n_outlets=2))
            fs2.connect(prev_port, u.inlet)
            tap = u.out_2
            prev_port = u.out_1
        else:
            u = fs2.add(U.Pump(f"P-{i}"))
            fs2.connect(prev_port, u.suction)
            prev_port = u.discharge
    fs2.connect(prev_port, fs2.add(U.Product("OUT")).inlet)
    assert tap is not None
    fs2.connect(tap, head.in_2)  # recycle, back to the mixer's second inlet

    fs2.layout()
    recycles = [s for s in fs2.streams if s.is_recycle]
    assert len(recycles) == 1
    assert recycles[0].dest.owner is head


# --------------------------------------------------------------------
# Property test: the iterative walk marks the same edges the original
# recursive one did, over many generated topologies.
# --------------------------------------------------------------------


def _reference_recursive_marks(fs: Flowsheet) -> set[int]:
    """A frozen copy of ``break_cycles``'s walk exactly as it stood
    before #413 -- genuinely recursive, marking into a side set instead
    of ``Stream._is_recycle`` so it can run beside the real one without
    disturbing it.

    Returns the set of ``id(stream)`` marked as a recycle back-edge.
    """
    units = process_units(fs)
    marks: set[int] = set()
    if not units:
        return marks

    adj: dict[Unit, list[Stream]] = {u: [] for u in units}
    in_degree: dict[Unit, int] = {u: 0 for u in units}
    for s in process_streams(fs):
        assert s.source.owner is not None
        assert s.dest.owner is not None
        adj[s.source.owner].append(s)
        in_degree[s.dest.owner] += 1

    for u in units:
        adj[u].sort(key=lambda s: s.draw_as_recycle)

    visited: set[Unit] = set()
    stack: set[Unit] = set()

    def dfs(u: Unit) -> None:
        visited.add(u)
        stack.add(u)
        for s in adj[u]:
            v = s.dest.owner
            assert v is not None
            if v in stack:
                marks.add(id(s))
            elif v not in visited:
                dfs(v)
        stack.remove(u)

    feeds = [u for u in units if in_degree[u] == 0]
    if not feeds:
        highest = max(units, key=lambda x: len(adj[x]))
        feeds = [highest]
    for f in feeds:
        if f not in visited:
            dfs(f)
    for u in units:
        if u not in visited:
            dfs(u)
    return marks


def _random_flowsheet(rng: random.Random, n_nodes: int) -> Flowsheet:
    """A random flowsheet of pumps, mixers, splitters, feeds and
    products, connected by a random matching of outlets to inlets --
    dense enough to fold back on itself into cycles, self-loops and
    disconnected islands, all of which the walk must handle."""
    fs = Flowsheet("prop")
    out_slots = []
    in_slots = []
    for i in range(n_nodes):
        roll = rng.random()
        if roll < 0.12:
            u = fs.add(U.Feed(f"F{i}"))
            out_slots.append(u.outlet)
        elif roll < 0.24:
            u = fs.add(U.Product(f"D{i}"))
            in_slots.append(u.inlet)
        elif roll < 0.55:
            u = fs.add(U.Pump(f"P{i}"))
            in_slots.append(u.suction)
            out_slots.append(u.discharge)
        elif roll < 0.77:
            k = rng.randint(2, 4)
            u = fs.add(U.Mixer(f"M{i}", n_inlets=k))
            in_slots.extend(u.inlets)
            out_slots.append(u.outlet)
        else:
            k = rng.randint(2, 4)
            u = fs.add(U.Splitter(f"S{i}", n_outlets=k))
            in_slots.append(u.inlet)
            out_slots.extend(u.outlets)

    rng.shuffle(out_slots)
    rng.shuffle(in_slots)
    for src, dst in zip(out_slots, in_slots):
        fs.connect(src, dst, draw_as_recycle=rng.random() < 0.2)
    return fs


def test_iterative_marking_matches_recursive_reference_over_random_topologies():
    seeds = range(400)
    for seed in seeds:
        rng = random.Random(seed)
        n_nodes = rng.randint(3, 40)
        fs_old = _random_flowsheet(random.Random(seed), n_nodes)
        fs_new = _random_flowsheet(random.Random(seed), n_nodes)
        # Same seed, same construction order -> the two flowsheets have
        # the same units and streams in the same order.
        assert len(fs_old.streams) == len(fs_new.streams)

        old_marks = _reference_recursive_marks(fs_old)
        old_by_index = {j for j, s in enumerate(fs_old.streams) if id(s) in old_marks}

        break_cycles(fs_new)
        new_by_index = {j for j, s in enumerate(fs_new.streams) if s.is_recycle}

        assert old_by_index == new_by_index, (
            f"seed={seed} n_nodes={n_nodes}: recycle marking differs "
            f"between the recursive reference and the iterative walk"
        )


def test_iterative_marking_matches_recursive_reference_on_fixed_shapes():
    """A handful of hand-picked shapes the random corpus might miss:
    a self-loop, a diamond with a cross-back edge, several disconnected
    loops, and a sheet with no feed at all."""

    def _self_loop() -> Flowsheet:
        fs = Flowsheet("self-loop")
        m = fs.add(U.Mixer("M", n_inlets=2))
        feed = fs.add(U.Feed("F"))
        fs.connect(feed.outlet, m.in_1)
        fs.connect(m.outlet, m.in_2)  # a unit feeding its own other inlet
        return fs

    def _diamond_with_cross_back_edge() -> Flowsheet:
        fs = Flowsheet("diamond")
        feed = fs.add(U.Feed("F"))
        split = fs.add(U.Splitter("S", n_outlets=2))
        left = fs.add(U.Mixer("ML", n_inlets=2))  # takes the cross edge too
        left_pump = fs.add(U.Pump("PL"))
        right = fs.add(U.Splitter("SR", n_outlets=2))  # feeds merge and crosses back
        merge = fs.add(U.Mixer("M", n_inlets=2))
        prod = fs.add(U.Product("D"))
        fs.connect(feed.outlet, split.inlet)
        fs.connect(split.out_1, left.in_1)
        fs.connect(split.out_2, right.inlet)
        fs.connect(left.outlet, left_pump.suction)
        fs.connect(left_pump.discharge, merge.in_1)
        fs.connect(right.out_1, merge.in_2)
        # Back edge crossing from the right branch into the left one.
        fs.connect(right.out_2, left.in_2)
        fs.connect(merge.outlet, prod.inlet)
        return fs

    def _closed_loop_no_feed() -> Flowsheet:
        fs = Flowsheet("closed-loop")
        a = fs.add(U.Pump("A"))
        b = fs.add(U.Pump("B"))
        c = fs.add(U.Pump("C"))
        fs.connect(a.discharge, b.suction)
        fs.connect(b.discharge, c.suction)
        fs.connect(c.discharge, a.suction)
        return fs

    def _disconnected_loops() -> Flowsheet:
        fs = Flowsheet("islands")
        for tag in ("1", "2", "3"):
            a = fs.add(U.Pump(f"A{tag}"))
            b = fs.add(U.Pump(f"B{tag}"))
            fs.connect(a.discharge, b.suction)
            fs.connect(b.discharge, a.suction)
        return fs

    for builder in (
        _diamond_with_cross_back_edge,
        _closed_loop_no_feed,
        _disconnected_loops,
    ):
        fs_old = builder()
        fs_new = builder()
        old_marks = _reference_recursive_marks(fs_old)
        old_by_index = {j for j, s in enumerate(fs_old.streams) if id(s) in old_marks}
        break_cycles(fs_new)
        new_by_index = {j for j, s in enumerate(fs_new.streams) if s.is_recycle}
        assert old_by_index == new_by_index, builder.__name__

    # A unit feeding its own other inlet needs Port capacity we don't
    # have with a shared Mixer instance across two builds, so it is
    # checked on its own, once, directly.
    fs = _self_loop()
    old_marks = _reference_recursive_marks(fs)
    old_by_index = {j for j, s in enumerate(fs.streams) if id(s) in old_marks}
    fs2 = _self_loop()
    break_cycles(fs2)
    new_by_index = {j for j, s in enumerate(fs2.streams) if s.is_recycle}
    assert old_by_index == new_by_index
