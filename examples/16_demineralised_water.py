"""
Example 16: Demineralised water plant, laid out automatically

Raw water is stored, strained and pumped through a multimedia filter
and an activated carbon bed, then through a cation exchanger. A packed
degasser tower stripped with blower air takes the carbon dioxide off
before the anion exchanger, and a mixed bed polishes the water into
the demineralised water tank.

Nothing is pinned: the whole sheet is ranked, ordered, placed and
routed from the connections alone.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid.document import Revision, TitleBlock, equipment_list

from pandid import (
    Blower,
    Feed,
    Filter,
    Fitting,
    Flowsheet,
    IonExchanger,
    Product,
    Pump,
    Stripper,
    Tank,
    Valve,
    Vent,
)


def main():
    fs = Flowsheet("Demineralised Water Plant")

    raw = fs.add(Feed("Raw Water", reference="PFD-100"))
    t801 = fs.add(Tank("T-801", variant="dished_roof_conical_bottom",
                       description="Raw Water Tank"))
    st801 = fs.add(Fitting("ST-801", variant="strainer_duplex",
                           description="Transfer Pump Suction Strainer"))
    p801 = fs.add(Pump("P-801A/B", description="Raw Water Transfer Pump"))
    f801 = fs.add(Filter("F-801", description="Multimedia Filter"))
    f802 = fs.add(Filter("F-802", variant="fixed_bed",
                         description="Activated Carbon Filter"))
    ix801 = fs.add(IonExchanger("IX-801", description="Cation Exchanger"))

    # Packing, not a deck: a CO2 stripper wants surface area and the
    # lowest pressure drop the blower can push air through, and it has
    # no separation to hold on spec. ``variant="packed"`` is the body
    # that draws its own two beds on their support grids, so it takes no
    # ``internals=`` -- composing one onto it would draw a third bed.
    # ``Stripper``, not a plain ``Column``: it reboils on nothing but air,
    # so ``boilup_in`` is real and ``reflux_in``/``condenser_duty`` would
    # be two unconnected nozzles this tower never has.
    d801 = fs.add(Stripper("D-801", variant="packed",
                           description="Degasser Tower"))
    air = fs.add(Feed("Stripping Air"))
    b801 = fs.add(Blower("B-801", description="Degasser Air Blower"))
    vt801 = fs.add(Vent("VT-801", description="Degasser Vent"))

    p802 = fs.add(Pump("P-802A/B", description="Degassed Water Pump"))
    ix802 = fs.add(IonExchanger("IX-802", description="Anion Exchanger"))
    ix803 = fs.add(IonExchanger("IX-803", description="Mixed Bed Polisher"))
    t802 = fs.add(Tank("T-802", variant="conical",
                       description="Demineralised Water Tank"))
    hv801 = fs.add(Valve("HV-801", variant="manual",
                         description="Demin Water Outlet Valve"))
    header = fs.add(Product("To Demin Water Header", reference="PFD-200"))

    raw_in = fs.connect(raw.outlet, t801.inlet)
    fs.connect(t801.outlet, st801.inlet)
    fs.connect(st801.outlet, p801.suction)
    fs.connect(p801.discharge, f801.inlet)
    fs.connect(f801.outlet, f802.inlet)
    fs.connect(f802.outlet, ix801.inlet)

    fs.connect(ix801.outlet, d801.feed)
    air_in = fs.connect(air.outlet, b801.suction)
    fs.connect(b801.discharge, d801.boilup_in)
    fs.connect(d801.overhead, vt801.inlet)
    fs.connect(d801.bottoms, p802.suction)

    fs.connect(p802.discharge, ix802.inlet)
    fs.connect(ix802.outlet, ix803.inlet)
    fs.connect(ix803.outlet, t802.inlet)
    fs.connect(t802.outlet, hv801.inlet)
    product_out = fs.connect(hv801.outlet, header.inlet)

    # Raw water and stripping air in; demineralised water out. The
    # difference is the degasser's vent (equipment, not a sheet edge,
    # so it is not tabulated) plus the filter backwash and resin
    # regeneration this sheet does not draw.
    raw_in.properties = {"Flow (kg/h)": "10000"}
    air_in.properties = {"Flow (kg/h)": "200"}
    product_out.properties = {"Flow (kg/h)": "9700"}

    # date= is stated rather than left blank: left blank, the renderer
    # fills in today's.
    fs.title_block = TitleBlock(
        title="Demineralised Water",
        subtitle="U800 Process Flow Diagram",
        drawing_number="PFD-801",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        date="03/08/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "24/07/26", "Issued for internal review", "AA"),
            Revision("B", "03/08/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    # The duplex strainer and the outlet valve are bulk items bought by
    # the line, so neither takes an equipment-list row.
    fs.add_annotation(equipment_list(fs, align="top", include=[
        "T-801", "P-801A/B", "F-801", "F-802", "IX-801", "D-801", "B-801",
        "P-802A/B", "IX-802", "IX-803", "T-802",
    ]))

    fs.render(out("demineralised_water.svg"), border="zone", show_stream_table=True)
    print("Generated demineralised_water.svg")


if __name__ == "__main__":
    main()
