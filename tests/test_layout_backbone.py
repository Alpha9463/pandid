"""Contract free inline devices into process runs without changing the sheet."""

from __future__ import annotations

from pandid import Feed, Flowsheet, Mixer, Product, Reducer, Tee, Valve
from pandid.layout.backbone import BackboneRun, infer_backbone
from pandid.layout.cycles import break_cycles


def test_backbone_contracts_a_free_inline_chain() -> None:
    """Keep the inline order and every original material stream.

    Returns
    -------
    None
        The chain has two equipment nodes and one ordered run.
    """
    fs = Flowsheet("Inline chain")
    source = fs.add(Feed("Feed"))
    valve = fs.add(Valve("HV-101")).pin(orientation=90)
    reducer = fs.add(Reducer("RD-101"))
    product = fs.add(Product("Product"))
    fs.connect(source.outlet, valve.inlet)
    fs.connect(valve.outlet, reducer.inlet)
    fs.connect(reducer.outlet, product.inlet)

    backbone = infer_backbone(fs)

    assert backbone.nodes == (0, 3)
    assert backbone.runs == (BackboneRun(source=0, dest=3, inline_units=(1, 2), streams=(0, 1, 2)),)
    assert valve.pin_ is not None and valve.pin_.orientation == 90
    assert all(unit.frame is None for unit in fs.units)
    assert all(stream.route is None for stream in fs.streams)


def test_backbone_retains_tees_pins_and_recycle_boundaries() -> None:
    """Keep branch, exact-pin, and recycle endpoints as placement nodes.

    Returns
    -------
    None
        Only the free valve on the forward run is contracted.
    """
    fs = Flowsheet("Branch and recycle")
    source = fs.add(Feed("Feed"))
    merge = fs.add(Mixer("Merge", n_inlets=2))
    branch = fs.add(Tee())
    free = fs.add(Valve("HV-101"))
    pinned = fs.add(Valve("HV-102")).pin(x=400)
    recycle_valve = fs.add(Valve("HV-103"))
    product = fs.add(Product("Product"))

    fs.connect(source.outlet, merge.in_1)
    fs.connect(merge.outlet, branch.inlet)
    fs.connect(branch.outlet, free.inlet)
    fs.connect(free.outlet, pinned.inlet)
    fs.connect(pinned.outlet, product.inlet)
    fs.connect(branch.branch, recycle_valve.inlet)
    recycle = fs.connect(recycle_valve.outlet, merge.in_2, draw_as_recycle=True)
    break_cycles(fs)
    assert recycle.is_recycle

    backbone = infer_backbone(fs)

    assert backbone.nodes == (0, 1, 2, 4, 5, 6)
    assert backbone.runs == (
        BackboneRun(source=0, dest=1, inline_units=(), streams=(0,)),
        BackboneRun(source=1, dest=2, inline_units=(), streams=(1,)),
        BackboneRun(source=2, dest=4, inline_units=(3,), streams=(2, 3)),
        BackboneRun(source=4, dest=6, inline_units=(), streams=(4,)),
        BackboneRun(source=2, dest=5, inline_units=(), streams=(5,)),
        BackboneRun(source=5, dest=1, inline_units=(), streams=(6,)),
    )
    assert pinned.pin_ is not None and pinned.pin_.x == 400
    assert tuple(i for run in backbone.runs for i in run.streams) == tuple(range(7))
