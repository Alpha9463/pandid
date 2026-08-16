"""
Example 18: Methanol Synthesis Loop A300, a fixed-bed recycle P&ID

Make-up synthesis gas is compressed into the loop, joins the recycle,
is heated against the converter effluent in E-301 and fired to reaction
temperature in H-301. R-301 is a packed catalytic converter; per pass it
turns only a few per cent of the gas, which is why the unreacted
remainder is separated in V-301 and sent round again. The crude
methanol leaves on level control, the loop pressure is held by the
purge, and the purge is what stops the inerts that arrive with the
make-up from accumulating for ever.

``Reactor(internals="packing")`` is the converter: ISO item 27.8's
crossed bed drawn into the same dished-end shell example 17's stirred
reactor and example 20's molecular sieve are drawn from. Naming
``internals=`` is also what leaves the **agitator out** -- a reactor is a
stirred tank unless it says otherwise, and a packed bed says otherwise,
so no stirrer is drawn through the catalyst.

Nothing is pinned. The engine ranks, orders, places and routes the whole
sheet, balloons included, and the recycle back to the mixing tee is what
it has to solve: the loop is torn, laid out as a forward train and drawn
back across the sheet as a recycle lane.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Compressor,
    Feed,
    Fitting,
    Flowsheet,
    Furnace,
    HeatExchanger,
    KnockoutDrum,
    Product,
    Reactor,
    Tee,
    Valve,
)
from pandid.document import Revision, TitleBlock, equipment_list, legend, notes


def main():
    fs = Flowsheet("Methanol Synthesis Loop A300", line_number_start=301)

    # --- Control loops ------------------------------------------------
    flow301 = fs.add_loop("F", 301)     # make-up gas
    temp302 = fs.add_loop("T", 302)     # converter inlet, a cascade master
    flow303 = fs.add_loop("F", 303)     # fired heater fuel gas, its slave
    press304 = fs.add_loop("P", 304)    # loop pressure, held on the purge
    level305 = fs.add_loop("L", 305)    # separator level

    # --- Equipment ----------------------------------------------------
    # internals="packing" is the catalyst bed, and it is also what says
    # this vessel is not stirred: Reactor fits ISO item 28.1's agitator
    # to a body the author put nothing in, and leaves it out of one they
    # did. A stirrer drawn through a fixed bed would be a machine the
    # plant does not have.
    rx = fs.add(Reactor("R-301", internals="packing", width=90, height=200,
                        description="Methanol Converter"))
    fehe = fs.add(HeatExchanger("E-301", variant="straight_tubes", width=120,
                                height=36,
                                description="Feed / Effluent Exchanger"))
    heater = fs.add(Furnace("H-301", description="Converter Fired Heater"))
    cooler = fs.add(HeatExchanger("E-302", variant="straight_tubes", width=120,
                                  height=36, description="Product Condenser"))
    sep = fs.add(KnockoutDrum("V-301", description="Crude Methanol Separator"))
    makeup_k = fs.add(Compressor("K-301", description="Make-up Gas Compressor"))
    recycle_k = fs.add(Compressor("K-302", description="Recycle Gas Compressor"))

    syngas = fs.add(Feed("Synthesis Gas", reference="P&ID-201"))
    fuel = fs.add(Feed("FGSH", header=True))
    cws = fs.add(Feed("CWSH", header=True))
    cwr = fs.add(Product("CWRH", header=True))
    # No flue-gas flag: ``units.Furnace`` draws the process coil and the
    # burner, and its three nozzles are the coil's two and the fuel. The
    # stack, the air preheat and the induced-draught fan are the heater's
    # own sheet, which is what the note at the foot of this one says.
    purge_gas = fs.add(Product("Purge to Fuel Gas", reference="P&ID-901"))
    crude = fs.add(Product("Crude Methanol", reference="P&ID-401"))

    # --- In-line devices ----------------------------------------------
    # Both junctions are piping and not plant, so both are tees: one
    # combines the make-up into the recycle, the other takes the purge
    # off the separator's gas. A tee is drawn identically either way --
    # it does not know which direction its branch runs.
    mix = fs.add(Tee(branch="inlet"))
    purge_tee = fs.add(Tee())

    fe301 = fs.add(Fitting(flow301.element("FE"), variant="orifice",
                           description="Make-up Gas Flow Element"))
    cv301 = fs.add(Valve(flow301.tag("CV"), variant="control", fail="closed",
                         description="Make-up Gas Control Valve"))
    fe303 = fs.add(Fitting(flow303.element("FE"), variant="orifice",
                           description="Fuel Gas Flow Element"))
    xv307 = fs.add(Valve("XV-307", variant="solenoid", fail="closed",
                         description="Fired Heater Fuel Trip Valve"))
    cv303 = fs.add(Valve(flow303.tag("CV"), variant="control", fail="closed",
                         description="Fuel Gas Control Valve"))
    cv304 = fs.add(Valve(press304.tag("CV"), variant="control", fail="open",
                         description="Loop Purge Control Valve"))
    cv305 = fs.add(Valve(level305.tag("CV"), variant="control", fail="closed",
                         description="Crude Methanol Control Valve"))

    # --- Process lines ------------------------------------------------
    # The pressure sequence is the loop's: make-up arrives at 30 barg and
    # K-301 lifts it to the 80 barg the loop runs at; K-302 puts back
    # only the 5 bar the circuit loses across the exchangers, the heater
    # and the bed, which is why the recycle machine is a small one beside
    # the make-up machine.
    fs.connect(syngas.outlet, fe301.inlet, size=300, service="SG",
               sequence=301, spec="CS")
    fs.connect(fe301.outlet, cv301.inlet)
    fs.connect(cv301.outlet, makeup_k.suction)
    fs.connect(makeup_k.discharge, mix.inlet, size=200, service="SG",
               sequence=302, spec="CS")

    # The cold gas goes tube side and the hot effluent shell side: the
    # tubes are what can be pulled and cleaned, and the loop's fouling is
    # on the effluent, which carries the wax and the carbonyls.
    fs.connect(mix.outlet, fehe.tube_in, size=350, service="LG", sequence=303,
               spec="CS")
    fs.connect(fehe.tube_out, heater.inlet, size=350, service="LG",
               sequence=314, spec="CS")
    # A number of its own either side of the heater: the coil is where
    # the metal changes, and 304 is the run that is above the carbon
    # steel's limit.
    inlet_line = fs.connect(heater.outlet, rx.feed, size=350, service="LG",
                            sequence=304, spec="LT")
    fs.connect(rx.outlet, fehe.shell_in, size=350, service="LG", sequence=305,
               spec="LT")
    fs.connect(fehe.shell_out, cooler.tube_in, size=350, service="LG",
               sequence=306, spec="CS")
    fs.connect(cooler.tube_out, sep.feed, size=350, service="LG",
               sequence=315, spec="CS")

    fs.connect(sep.liquid, cv305.inlet, size=100, service="CM", sequence=307,
               spec="SS")
    fs.connect(cv305.outlet, crude.inlet)

    loop_gas = fs.connect(sep.vapor, purge_tee.inlet, size=350, service="LG",
                          sequence=308, spec="CS")
    # The purge leaves on the run and the recycle on the branch. A tee is
    # drawn identically either way, so which port is which is a placement
    # decision rather than a piping one, and this way round is what puts
    # CV-304 beside the recycle machine instead of underneath it -- the
    # controller's output has to reach the actuator from above, and an
    # actuator under a compressor cannot be reached at all.
    fs.connect(purge_tee.outlet, cv304.inlet, size=80, service="PG",
               sequence=309, spec="CS")
    fs.connect(cv304.outlet, purge_gas.inlet)
    fs.connect(purge_tee.branch, recycle_k.suction, size=350, service="LG",
               sequence=316, spec="CS")
    # draw_as_recycle= is the author saying which edge closes the loop.
    # The engine finds it on its own here, and stating it keeps the sheet
    # saying so even if the topology around it is edited.
    fs.connect(recycle_k.discharge, mix.branch, size=350, service="LG",
               sequence=310, spec="CS", draw_as_recycle=True)

    fs.connect(fuel.outlet, fe303.inlet, size=80, service="FG", sequence=311,
               spec="CS")
    fs.connect(fe303.outlet, xv307.inlet)
    fs.connect(xv307.outlet, cv303.inlet)
    fs.connect(cv303.outlet, heater.fuel)

    fs.connect(cws.outlet, cooler.shell_in, size=250, service="CWS",
               sequence=312, spec="CS")
    fs.connect(cooler.shell_out, cwr.inlet, size=250, service="CWR",
               sequence=313, spec="CS")

    # --- Loop 301: the make-up gas ------------------------------------
    # The element's tag moves into a balloon on a short impulse line and
    # the plate is left unlettered; FT-301 stacks on that balloon, edge to
    # edge, reading the same element.
    fe301_b = fs.add_balloon(fe301, at="N", offset=38)
    ft301 = fs.add_instrument("FT", flow301, near=fe301_b, at="N", offset=23)
    fic301 = fs.add_instrument("FIC", flow301, near=ft301, at="N", offset=60,
                               variant="shared")
    fs.connect(ft301.sig_out, fic301.pv, kind="electric")
    fs.connect(fic301.sig_out, cv301.actuator, kind="pneumatic")

    # --- Loops 302/303: converter inlet temperature onto the fuel -----
    # The master reads the gas leaving the heater, not the bed: the bed
    # runs 40 C hotter than its inlet and lags it by minutes, so a loop
    # closed on the catalyst would be too slow to hold the inlet at all.
    # TI-306 is what says how hot the bed itself is.
    tt302 = fs.add_instrument("TT", temp302, sensing=inlet_line, at=0.5,
                              offset=60)
    tic302 = fs.add_instrument("TIC", temp302, near=tt302, at="N", offset=70,
                               variant="shared")
    tic302.annotate(high="TAH")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    fe303_b = fs.add_balloon(fe303, at="N", offset=38)
    ft303 = fs.add_instrument("FT", flow303, near=fe303_b, at="N", offset=23)
    fic303 = fs.add_instrument("FIC", flow303, near=ft303, at="N", offset=60,
                               variant="shared")
    # The measurement lands on pv and the master sets sig_in: a cascade
    # sets a setpoint, it does not stroke a valve.
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, cv303.actuator, kind="pneumatic")

    # --- Loop 304: loop pressure, held on the purge -------------------
    # Inerts arrive with the make-up, do not react and do not condense,
    # so with no purge the loop pressure climbs until the machines stall.
    # Letting the pressure open the purge is that balance drawn as one
    # loop rather than left to an operator with a hand valve.
    pt304 = fs.add_instrument("PT", press304, sensing=loop_gas, at=0.4,
                              offset=60)
    pic304 = fs.add_instrument("PIC", press304, near=pt304, at="N", offset=70,
                               variant="shared")
    pic304.annotate(high="PAH", low="PAL")
    fs.connect(pt304.sig_out, pic304.sig_in, kind="electric")
    fs.connect(pic304.sig_out, cv304.actuator, kind="pneumatic")

    # --- Loop 305: separator level on the crude draw ------------------
    lt305 = fs.add_instrument("LT", level305, sensing=sep, at="E", offset=60)
    lic305 = fs.add_instrument("LIC", level305, near=lt305, at="S", offset=70,
                               variant="shared")
    lic305.annotate(high="LAH", low="LAL")
    fs.connect(lt305.sig_out, lic305.sig_in, kind="electric")
    fs.connect(lic305.sig_out, cv305.actuator, kind="pneumatic")

    # --- Bed temperature and the fuel trip ----------------------------
    # A runaway on a copper catalyst sinters it, and the damage is
    # permanent, so the trip reads the bed and shuts the firing. TT-307
    # is a well of its own: a trip taking TIC-302's reading stops working
    # the moment that loop is put on manual.
    fs.add_instrument("TI", 306, sensing=rx, at="W", offset=60)
    tt307 = fs.add_instrument("TT", 307, sensing=rx, at="E", offset=60)
    fs.add_instrument("Z", 1, sensing=tt307, at="E", offset=44, variant="sis")
    # Over the valve rather than under it: a valve that states a fail
    # position writes FC beneath its tag, and a square standing there is
    # a square with lettering across it.
    fs.add_instrument("Z", 1, acting_on=xv307, at="N", offset=34, variant="sis")

    # --- Sheet furniture ----------------------------------------------
    # date= is stated rather than left blank: left blank, the renderer
    # fills in today's.
    fs.title_block = TitleBlock(
        title="Methanol Synthesis Loop",
        subtitle="A300 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-301",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1", scale="NTS",
        date="18/02/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "29/01/26", "Issued for internal review", "AA"),
            Revision("B", "18/02/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(equipment_list(fs, align="top-right", include=[
        "K-301", "E-301", "H-301", "R-301", "E-302", "V-301", "K-302",
    ]))
    fs.add_annotation(notes([
        "Z-1: converter high bed temperature. TT-307 is its own "
        "measurement, independent of TIC-302.",
        "H-301 flue gas and combustion air are on P&ID-302.",
        "Per-pass conversion is 5 to 7 %; the recycle ratio is 5:1 on "
        "molar flow.",
    ], title="GENERAL NOTES", numbered=False, align="bottom-left"))
    fs.add_annotation(legend({
        "CS": "Carbon Steel A106-B",
        "LT": "Low Temperature Carbon Steel A333-6",
        "SS": "Stainless Steel 316L",
        "SG": "Make-up Synthesis Gas",
        "LG": "Loop Gas",
        "PG": "Purge Gas",
        "CM": "Crude Methanol",
        "FGSH": "Fuel Gas Supply Header",
        "CWSH": "Cooling Water Supply Header",
        "CWRH": "Cooling Water Return Header",
    }, align="top-left"))

    fs.render(out("fixed_bed_recycle.svg"), border="zone", diagram="p&id")
    print("Generated fixed_bed_recycle.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
