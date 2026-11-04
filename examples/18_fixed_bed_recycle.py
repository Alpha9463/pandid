"""
Example 18: Methanol Synthesis Loop A300, a fixed-bed recycle P&ID

Make-up synthesis gas is compressed into the loop, joins the recycle,
is heated against the converter effluent in E-301 and fired to reaction
temperature in H-301. The packed converter R-301 reacts a few per cent
per pass; V-301 separates the crude methanol, which leaves on level
control, and the unreacted gas is recycled, the loop pressure held on
the purge. Nothing is pinned; the engine draws the recycle as a lane.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Compressor,
    ControlValve,
    Feed,
    Fitting,
    Flowsheet,
    Furnace,
    KnockoutDrum,
    Product,
    Reactor,
    ShellAndTubeExchanger,
    SolenoidValve,
    Tee,
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
    # internals="packing" draws the catalyst bed and no agitator.
    rx = fs.add(Reactor("R-301", internals="packing", width=124, height=200,
                        description="Methanol Converter"))
    fehe = fs.add(ShellAndTubeExchanger("E-301", variant="straight_tubes", width=120,
                                        height=36,
                                        description="Feed / Effluent Exchanger"))
    heater = fs.add(Furnace("H-301", description="Converter Fired Heater"))
    cooler = fs.add(ShellAndTubeExchanger("E-302", variant="straight_tubes", width=120,
                                          height=36, description="Product Condenser"))
    sep = fs.add(KnockoutDrum("V-301", description="Crude Methanol Separator"))
    makeup_k = fs.add(Compressor("K-301", description="Make-up Gas Compressor"))
    recycle_k = fs.add(Compressor("K-302", description="Recycle Gas Compressor"))

    syngas = fs.add(Feed("Synthesis Gas", reference="P&ID-201"))
    fuel = fs.add(Feed("FGSH", header=True))
    cws = fs.add(Feed("CWSH", header=True))
    cwr = fs.add(Product("CWRH", header=True))
    purge_gas = fs.add(Product("Purge to Fuel Gas", reference="P&ID-901"))
    crude = fs.add(Product("Crude Methanol", reference="P&ID-401"))

    # --- In-line devices ----------------------------------------------
    # One tee joins the make-up to the recycle, the other takes the purge.
    mix = fs.add(Tee(branch="inlet"))
    purge_tee = fs.add(Tee())

    fe301 = fs.add(Fitting(flow301.element("FE"), variant="orifice",
                           description="Make-up Gas Flow Element"))
    cv301 = fs.add(ControlValve(flow301.tag("CV"), fail="closed",
                                description="Make-up Gas Control Valve"))
    fe303 = fs.add(Fitting(flow303.element("FE"), variant="orifice",
                           description="Fuel Gas Flow Element"))
    xv307 = fs.add(SolenoidValve("XV-307", fail="closed",
                                 description="Fired Heater Fuel Trip Valve"))
    cv303 = fs.add(ControlValve(flow303.tag("CV"), fail="closed",
                                description="Fuel Gas Control Valve"))
    cv304 = fs.add(ControlValve(press304.tag("CV"), fail="open",
                                description="Loop Purge Control Valve"))
    cv305 = fs.add(ControlValve(level305.tag("CV"), fail="closed",
                                description="Crude Methanol Control Valve"))

    # --- Process lines ------------------------------------------------
    fs.connect(syngas.outlet, fe301.inlet, size=300, service="SG",
               sequence=301, spec="CS")
    fs.connect(fe301.outlet, cv301.inlet)
    fs.connect(cv301.outlet, makeup_k.suction)
    fs.connect(makeup_k.discharge, mix.inlet, size=200, service="SG",
               sequence=302, spec="CS")

    # Cold gas tube side, hot effluent shell side.
    fs.connect(mix.outlet, fehe.tube_in, size=350, service="LG", sequence=303,
               spec="CS")
    fs.connect(fehe.tube_out, heater.inlet, size=350, service="LG",
               sequence=314, spec="CS")
    # The hot lines either side of R-301 are alloy steel.
    inlet_line = fs.connect(heater.outlet, rx.feed, size=350, service="LG",
                            sequence=304, spec="AS")
    fs.connect(rx.outlet, fehe.shell_in, size=350, service="LG", sequence=305,
               spec="AS")
    fs.connect(fehe.shell_out, cooler.tube_in, size=350, service="LG",
               sequence=306, spec="CS")
    fs.connect(cooler.tube_out, sep.feed, size=350, service="LG",
               sequence=315, spec="CS")

    fs.connect(sep.liquid, cv305.inlet, size=100, service="CM", sequence=307,
               spec="SS")
    fs.connect(cv305.outlet, crude.inlet)

    loop_gas = fs.connect(sep.vapor, purge_tee.inlet, size=350, service="LG",
                          sequence=308, spec="CS")
    # The purge leaves on the run, the recycle on the branch.
    fs.connect(purge_tee.outlet, cv304.inlet, size=80, service="PG",
               sequence=309, spec="CS")
    fs.connect(cv304.outlet, purge_gas.inlet)
    fs.connect(purge_tee.branch, recycle_k.suction, size=350, service="LG",
               sequence=316, spec="CS")
    # Name the edge that closes the loop.
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
    # Move the element's tag into a balloon; FT-301 stacks on it.
    fe301_b = fs.add_balloon(fe301, face="N", offset=38)
    ft301 = fs.add_instrument("FT", flow301, near=fe301_b, face="N", offset=23)
    fic301 = fs.add_instrument("FIC", flow301, near=ft301, face="N", offset=60,
                               variant="shared")
    fs.connect(ft301.sig_out, fic301.pv, kind="electric")
    fs.connect(fic301.sig_out, cv301.actuator, kind="pneumatic")

    # --- Loops 302/303: converter inlet temperature onto the fuel -----
    # The master reads the gas leaving the heater.
    tt302 = fs.add_instrument("TT", temp302, sensing=inlet_line, at=0.5,
                              offset=60)
    tic302 = fs.add_instrument("TIC", temp302, near=tt302, face="N", offset=70,
                               variant="shared")
    tic302.annotate(high="TAH")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    fe303_b = fs.add_balloon(fe303, face="N", offset=38)
    ft303 = fs.add_instrument("FT", flow303, near=fe303_b, face="N", offset=23)
    fic303 = fs.add_instrument("FIC", flow303, near=ft303, face="N", offset=60,
                               variant="shared")
    # The measurement lands on pv, the master's setpoint on sig_in.
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, cv303.actuator, kind="pneumatic")

    # --- Loop 304: loop pressure, held on the purge -------------------
    pt304 = fs.add_instrument("PT", press304, sensing=loop_gas, at=0.4,
                              offset=60)
    pic304 = fs.add_instrument("PIC", press304, near=pt304, face="N", offset=70,
                               variant="shared")
    pic304.annotate(high="PAH", low="PAL")
    fs.connect(pt304.sig_out, pic304.sig_in, kind="electric")
    fs.connect(pic304.sig_out, cv304.actuator, kind="pneumatic")

    # --- Loop 305: separator level on the crude draw ------------------
    # The controller stands over the valve it strokes.
    lt305 = fs.add_instrument("LT", level305, sensing=sep, face="E", offset=60)
    lic305 = fs.add_instrument("LIC", level305, near=cv305, face="N", offset=52,
                               variant="shared")
    lic305.annotate(high="LAH", low="LAL")
    fs.connect(lt305.sig_out, lic305.sig_in, kind="electric")
    fs.connect(lic305.sig_out, cv305.actuator, kind="pneumatic")

    # --- Bed temperature and the fuel trip ----------------------------
    # Z-1 reads the bed through TT-307 and shuts the fuel.
    fs.add_instrument("TI", 306, sensing=rx, face="N", offset=60)
    tt307 = fs.add_instrument("TT", 307, sensing=rx, face="E", offset=60)
    fs.add_instrument("Z", 1, sensing=tt307, face="E", offset=44, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv307, face="N", offset=34, variant="sis")

    # --- Sheet furniture ----------------------------------------------
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
        "AS": "Alloy Steel A335 P11",
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
