"""Process regions used to keep proposed group moves safe."""

from __future__ import annotations

from pandid import Flowsheet, units as U
from pandid.layout.structure import infer


def test_closed_branch_region_contains_both_arm_interiors() -> None:
    """Keep each complete arm between a split and merge together.

    Returns
    -------
    None
        Both arm interiors are present in a closed region.
    """
    fs = Flowsheet("Closed branch")
    split = fs.add(U.Splitter("Split"))
    first = fs.add(U.Pump("First"))
    second = fs.add(U.Pump("Second"))
    merge = fs.add(U.Mixer("Merge", n_inlets=2))
    fs.connect(split.out_1, first.suction)
    fs.connect(first.discharge, merge.in_1)
    fs.connect(split.out_2, second.suction)
    fs.connect(second.discharge, merge.in_2)
    fs.layout()

    region = infer(fs).branch_regions[0]
    assert region.closed
    assert (region.split, region.merge) == (0, 3)
    assert {tuple(arm.units) for arm in region.arms} == {(0, 1, 3), (0, 2, 3)}


def test_bypass_keeps_a_shared_merge_partial() -> None:
    """Do not treat an arm with a bypass as a closed move group.

    Returns
    -------
    None
        The shared merge remains marked partial.
    """
    fs = Flowsheet("Partial branch")
    source = fs.add(U.Splitter("Source"))
    left = fs.add(U.Splitter("Left"))
    right = fs.add(U.Splitter("Right"))
    merge = fs.add(U.Mixer("Merge", n_inlets=2))
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
