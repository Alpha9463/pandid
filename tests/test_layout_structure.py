"""Deterministic process structure without a placement side effect."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pandid import Flowsheet, units as U
from pandid.layout.structure import ProcessPath, infer


def _diamond(*, recycle: bool = False, different_arm: bool = False) -> Flowsheet:
    """Build two process branches sharing a split and merge.

    Parameters
    ----------
    recycle : bool, optional
        Connect the merge back to the upstream mixer.
    different_arm : bool, optional
        Use a reactor in the second arm instead of a pump.

    Returns
    -------
    Flowsheet
        Laid-out process graph with settled cycle-break marks.
    """
    fs = Flowsheet("Structure diamond")
    feed = fs.add(U.Feed("Feed"))
    head = fs.add(U.Mixer("Head", n_inlets=2)) if recycle else None
    split = fs.add(U.Splitter("Split"))
    first = fs.add(U.Pump("A"))
    second = fs.add(U.Reactor("B")) if different_arm else fs.add(U.Pump("B"))
    merge = fs.add(U.Mixer("Merge", n_inlets=2))
    if head is None:
        fs.connect(feed.outlet, split.inlet)
    else:
        fs.connect(feed.outlet, head.in_1)
        fs.connect(head.outlet, split.inlet)
    fs.connect(split.out_1, first.suction)
    fs.connect(first.discharge, merge.in_1)
    fs.connect(split.out_2, second.feed if different_arm else second.suction)
    fs.connect(second.outlet if different_arm else second.discharge, merge.in_2)
    if head is None:
        fs.connect(merge.outlet, fs.add(U.Product("Product")).inlet)
    else:
        fs.connect(merge.outlet, head.in_2)
    fs.layout()
    return fs


def test_chain_and_claims_use_stable_process_indices() -> None:
    """Condense a straight run and preserve its equipment preferences.

    Returns
    -------
    None
        The assertions cover chain ordering, claims, and repeatability.
    """
    fs = Flowsheet("Chain")
    feed = fs.add(U.Feed("F"))
    first = fs.add(U.Pump("P1"))
    second = fs.add(U.Pump("P2"))
    product = fs.add(U.Product("P"))
    fs.connect(feed.outlet, first.suction)
    fs.connect(first.discharge, second.suction)
    fs.connect(second.discharge, product.inlet)
    fs.layout()
    before = tuple(
        (unit.frame.x, unit.frame.y, unit.frame.col, unit.frame.row) for unit in fs.units
    )

    structure = infer(fs)
    assert structure == infer(fs)
    assert structure.unit_count == 4
    assert structure.components == ((0, 1, 2, 3),)
    assert structure.chains == (ProcessPath((0, 1, 2, 3), (0, 1, 2)),)
    assert structure.principal_paths == structure.chains
    assert structure.corridors == ()
    assert structure.claims
    assert all(0 <= claim.author < 4 and 0 <= claim.subject < 4 for claim in structure.claims)
    assert (
        tuple((unit.frame.x, unit.frame.y, unit.frame.col, unit.frame.row) for unit in fs.units)
        == before
    )
    with pytest.raises(FrozenInstanceError):
        structure.unit_count = 5


def test_matching_diamond_has_ordered_repeated_arms() -> None:
    """Recognize peers only when both arms share topology and port roles.

    Returns
    -------
    None
        The assertions cover branch order and conservative matching.
    """
    structure = infer(_diamond())
    assert len(structure.branches) == 1
    branch = structure.branches[0]
    assert (branch.split, branch.merge) == (1, 4)
    assert branch.arms == (
        ProcessPath((1, 2, 4), (1, 2)),
        ProcessPath((1, 3, 4), (3, 4)),
    )
    assert branch.repeated
    assert not infer(_diamond(different_arm=True)).branches[0].repeated
    assert len(structure.branch_regions) == 1
    assert tuple(arm.entry_stream for arm in structure.branch_regions[0].arms) == (1, 3)
    assert structure.branch_regions[0].closed


def test_nested_branch_region_keeps_all_inner_paths() -> None:
    """A broad split/merge record includes a fork inside one arm.

    Returns
    -------
    None
        The assertions cover nested paths without calling them peers.
    """
    fs = Flowsheet("Nested branch")
    feed = fs.add(U.Feed("Feed"))
    outer = fs.add(U.Splitter("Outer"))
    upper = fs.add(U.Pump("Upper"))
    inner = fs.add(U.Splitter("Inner"))
    left = fs.add(U.Pump("Left"))
    right = fs.add(U.Pump("Right"))
    inner_merge = fs.add(U.Mixer("Inner merge"))
    outer_merge = fs.add(U.Mixer("Outer merge"))
    fs.connect(feed.outlet, outer.inlet)
    fs.connect(outer.out_1, upper.suction)
    fs.connect(upper.discharge, outer_merge.in_1)
    fs.connect(outer.out_2, inner.inlet)
    fs.connect(inner.out_1, left.suction)
    fs.connect(left.discharge, inner_merge.in_1)
    fs.connect(inner.out_2, right.suction)
    fs.connect(right.discharge, inner_merge.in_2)
    fs.connect(inner_merge.outlet, outer_merge.in_2)
    fs.layout()

    structure = infer(fs)
    outer_region = next(region for region in structure.branch_regions if region.split == 1)
    assert outer_region.merge == 7
    assert outer_region.closed
    assert set(outer_region.arms[1].units) == {1, 3, 4, 5, 6, 7}
    assert set(outer_region.arms[1].streams) == {3, 4, 5, 6, 7, 8}
    assert all(branch.split != 1 for branch in structure.branches)


def test_branch_region_marks_a_merge_with_bypasses_as_partial() -> None:
    """A shared reachable merge does not close either bypassing arm.

    Returns
    -------
    None
        The assertions separate the common subregion from bypass paths.
    """
    fs = Flowsheet("Bypassed merge")
    source = fs.add(U.Splitter("Source"))
    left = fs.add(U.Splitter("Left"))
    right = fs.add(U.Splitter("Right"))
    merge = fs.add(U.Mixer("Merge"))
    left_end = fs.add(U.Product("Left end"))
    right_end = fs.add(U.Product("Right end"))
    fs.connect(source.out_1, left.inlet)
    fs.connect(source.out_2, right.inlet)
    fs.connect(left.out_1, merge.in_1)
    fs.connect(left.out_2, left_end.inlet)
    fs.connect(right.out_1, merge.in_2)
    fs.connect(right.out_2, right_end.inlet)
    fs.layout()

    region = next(region for region in infer(fs).branch_regions if region.split == 0)
    assert region.merge == 3
    assert not region.closed
    assert set(region.arms[0].streams) == {0, 2}
    assert set(region.arms[1].streams) == {1, 4}


def test_later_merge_closes_paths_after_an_earlier_partial_merge() -> None:
    """Keep a local shared merge and the later complete region distinct.

    Returns
    -------
    None
        The assertions preserve both the partial and closed topology.
    """
    fs = Flowsheet("Partial then closed")
    source = fs.add(U.Splitter("Source"))
    left = fs.add(U.Splitter("Left"))
    right = fs.add(U.Pump("Right"))
    first_merge = fs.add(U.Mixer("First merge"))
    bypass = fs.add(U.Pump("Bypass"))
    final_merge = fs.add(U.Mixer("Final merge"))
    fs.connect(source.out_1, left.inlet)
    fs.connect(source.out_2, right.suction)
    fs.connect(left.out_1, first_merge.in_1)
    fs.connect(left.out_2, bypass.suction)
    fs.connect(right.discharge, first_merge.in_2)
    fs.connect(first_merge.outlet, final_merge.in_1)
    fs.connect(bypass.discharge, final_merge.in_2)
    fs.layout()

    source_regions = [region for region in infer(fs).branch_regions if region.split == 0]
    assert [(region.merge, region.closed) for region in source_regions] == [(3, False), (5, True)]


def test_recycle_corridor_contains_both_forward_branches() -> None:
    """A return around a diamond spans both process paths.

    Returns
    -------
    None
        The corridor records all forward arms, independent of DFS parent.
    """
    fs = _diamond(recycle=True)
    structure = infer(fs)
    assert len(structure.corridors) == 1
    corridor = structure.corridors[0]
    assert corridor.head == 1
    assert corridor.tail == 5
    assert set(corridor.units) == {1, 2, 3, 4, 5}
    assert set(corridor.streams) == {1, 2, 3, 4, 5}
    assert structure.edges[corridor.recycle_stream].recycle
    assert structure.branches[0].repeated


def test_partial_pins_and_transformed_claims_are_snapshotted() -> None:
    """Keep pin axes and transforms separate from resolved coordinates.

    Returns
    -------
    None
        The assertions show that moving a frame does not alter structure.
    """
    fs = Flowsheet("Pinned")
    feed = fs.add(U.Feed("Feed"))
    pump = fs.add(U.Pump("Pump"))
    product = fs.add(U.Product("Product"))
    feed.pin(y=180)
    pump.pin(col=2, orientation=90, mirrored=True)
    fs.connect(feed.outlet, pump.suction)
    fs.connect(pump.discharge, product.inlet)
    fs.layout()
    original = infer(fs)
    assert original.pins[0].pin.y == 180
    assert original.pins[0].pin.x is None
    assert original.pins[1].pin.col == 2
    assert original.pins[1].pin.row is None
    assert original.pins[1].pin.orientation == 90
    assert original.pins[1].pin.mirrored
    assert original.claims
    pump.frame.x += 1000
    assert infer(fs) == original


def test_shared_boundary_supply_is_only_a_service_candidate() -> None:
    """Mark shared boundary supply runs without reserving geometry.

    Returns
    -------
    None
        The service hint remains an index-only, nongeometric record.
    """
    fs = Flowsheet("Shared supply")
    feed = fs.add(U.Feed("Water"))
    first = fs.add(U.Pump("A"))
    second = fs.add(U.Pump("B"))
    fs.connect(feed.outlet, first.suction)
    fs.connect(feed.outlet, second.suction)
    fs.layout()
    assert infer(fs).service_candidates == (0, 1)
