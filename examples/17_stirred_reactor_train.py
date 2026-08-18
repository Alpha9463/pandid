"""
Example 17: Propylene Glycol Reaction A200, a jacketed CSTR as a P&ID

Propylene oxide and process water are metered, mixed and charged to
R-101, a jacketed continuous stirred tank with a top-entering turbine
agitator. The hydrolysis is strongly exothermic, so the heat goes out
through the jacket into cooling water and the reactor temperature is
what sets that water's flow; the product leaves on level control and is
cooled in E-201 on its way to storage.

The sheet is the composition layer drawn as plant. ``agitator="turbine"``
puts ISO item 28.4's stirrer in the shell and item 20.6's drive motor on
the shaft above it, and ``variant="jacketed"`` is the body it turns in.
Neither is a symbol of its own: both are marks composed onto the same
dished-end vessel that example 18's packed bed and example 20's
molecular sieve are drawn from.

Five loops and one trip, which is what makes this a P&ID rather than a
PFD with valves on it -- charge flow, a reactor-temperature master
cascading onto the jacket cooling-water flow, reactor level, reactor
pressure, and a runaway interlock that shuts the feed and opens the
quench on either of two measurements of its own.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    ControlValve,
    Feed,
    Fitting,
    FlowElement,
    Flowsheet,
    Product,
    Pump,
    Reactor,
    ShellAndTubeExchanger,
    SolenoidValve,
    Tee,
    Valve,
)
from pandid.document import Revision, TitleBlock, equipment_list, legend, notes
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Propylene Glycol Reaction A200", line_number_start=201)

    # --- Control loops ------------------------------------------------
    # Each number is declared once here instead of typed on every balloon
    # that carries it. Members still type their own functional letters
    # and the handle checks the first of them, so a TT put on a flow loop
    # raises at the line that wrote it.
    flow201 = fs.add_loop("F", 201)     # propylene oxide charge
    temp202 = fs.add_loop("T", 202)     # reactor temperature, a cascade master
    level203 = fs.add_loop("L", 203)    # reactor level
    press204 = fs.add_loop("P", 204)    # reactor pressure
    flow205 = fs.add_loop("F", 205)     # jacket cooling water, temp202's slave

    # --- Equipment ----------------------------------------------------
    # agitator= and variant= answer two different questions and this
    # vessel answers both: the body is jacketed, and what turns inside it
    # is ISO item 28.4's turbine. Naming the agitator is also what brings
    # the motor and the ``drive`` nozzle on it -- ISO item 1.27 draws the
    # stirrer and its drive together, so there is no keyword for one
    # without the other.
    #
    # 152 x 360 and not 130 x 360: the motor is a circle, and its size is
    # worked out from the jacketed body's own 52 x 123,3 box, so a box of
    # another shape draws it as an oval. 152 is the width that shape asks
    # for at the height this sheet wants, and every elevation below is a
    # fraction of that height and does not move.
    rx = fs.add(Reactor("R-101", variant="jacketed", agitator="turbine",
                        width=152, height=360,
                        description="Propylene Glycol Reactor"))
    cooler = fs.add(ShellAndTubeExchanger("E-201", variant="straight_tubes", width=130,
                                          height=40, description="Product Cooler"))
    pump = fs.add(Pump("P-201A/B", description="Propylene Oxide Charge Pump"))

    # header=True is one service tapped wherever the sheet wants it, so
    # both cooling-water tie-ins carry CWSH and the return carries CWRH.
    po_feed = fs.add(Feed("Propylene Oxide", reference="P&ID-101"))
    water = fs.add(Feed("Process Water", reference="P&ID-101"))
    quench = fs.add(Feed("QWSH", header=True))
    cws_jkt = fs.add(Feed("CWSH", header=True))
    cws_cool = fs.add(Feed("CWSH", header=True))
    cwr_cool = fs.add(Product("CWRH", header=True))
    vent_gas = fs.add(Product("To Vent Scrubber", reference="P&ID-902"))
    glycol = fs.add(Product("Crude Propylene Glycol", reference="P&ID-301"))

    # --- In-line devices ----------------------------------------------
    xv201 = fs.add(SolenoidValve("XV-201", fail="closed",
                                 description="Reactor Feed Trip Valve"))
    # No label_pos: an element's tag goes in a balloon rather than beside
    # the symbol, so nothing is written against the venturi itself. See
    # add_balloon() below.
    fe201 = fs.add(FlowElement(flow201.element("FE"),
                               description="Propylene Oxide Flow Element"))
    # loop.tag() composes without checking the first letter and cannot: a
    # final control element is not tagged from the measured variable. A
    # primary element goes through loop.element(), which does check.
    cv201 = fs.add(ControlValve(flow201.tag("CV"), fail="closed",
                                description="Propylene Oxide Control Valve"))
    hv202 = fs.add(Valve("HV-202", description="Process Water Block Valve"))
    # Both tees combine rather than split, and a tee is drawn identically
    # either way: it does not know which way its branch runs.
    charge = fs.add(Tee(branch="inlet"))    # the water joins the oxide
    mixer = fs.add(Fitting("M-201", variant="static_mixer",
                           description="Reactor Charge Static Mixer"))
    dump = fs.add(Tee(branch="inlet"))      # the quench joins the charge
    xv206 = fs.add(SolenoidValve("XV-206", fail="open",
                                 description="Reactor Quench Valve"))
    cv204 = fs.add(ControlValve(press204.tag("CV"), fail="open",
                                description="Reactor Vent Control Valve"))
    cv203 = fs.add(ControlValve(level203.tag("CV"), fail="closed",
                                description="Product Draw Control Valve"))
    hv205 = fs.add(Valve("HV-205", description="Jacket Cooling Water Block Valve"))
    fe205 = fs.add(FlowElement(flow205.element("FE"),
                               description="Jacket Cooling Water Flow Element"))
    cv205 = fs.add(ControlValve(flow205.tag("CV"), fail="open",
                                description="Jacket Cooling Water Control Valve"))
    hv207 = fs.add(Valve("HV-207", description="E-201 Cooling Water Block Valve"))

    # --- Placement ----------------------------------------------------
    # Pinned by nozzle, not by corner: pin(port=...) asks the symbol
    # where its own nozzle sits, so no rescaling of the artwork can leave
    # a valve off its run. A boundary flag is pinned at the tip of its
    # arrow.
    rx_x, rx_y = 640.0, 230.0
    rx.pin(x=rx_x, y=rx_y)
    # The charge nozzle and the jacket's tie-in are at the same height on
    # opposite walls, so the whole middle of the sheet lies on one
    # elevation and the balloons that read the vessel have the wall above
    # it to themselves.
    charge_y = rx_y + port_offset(rx, "feed")[1]
    jacket_y = rx_y + port_offset(rx, "duty")[1]
    vent_y = rx_y + port_offset(rx, "vent")[1]
    draw_x = rx_x + port_offset(rx, "outlet")[0]

    # Pinned by its discharge: a pump's two nozzles are 20 units apart up
    # the casing, so pinning the suction would leave every run downstream
    # of it stepping over that gap instead of lying on one elevation.
    pump.pin(x=150).pin(port="discharge", y=charge_y)
    po_feed.pin(port="outlet", x=80,
                y=pump.pin_.y + port_offset(pump, "suction")[1])
    # 120 units of clear run between the pump and the trip valve, and it
    # is the line number that asks for them: the discharge is a line of
    # its own, twelve characters of it, and a number with less than half
    # of itself lying beside its own run is written on a leader instead.
    # mirrored="y" turns the solenoid's operator down, away from the trip
    # square standing over it.
    xv201.pin(mirrored="y").pin(port="inlet", x=340, y=charge_y)
    fe201.pin(port="inlet", x=410, y=charge_y)
    cv201.pin(port="inlet", x=470, y=charge_y)
    charge.pin(port="inlet", x=520, y=charge_y)
    mixer.pin(port="inlet", x=545, y=charge_y)
    dump.pin(port="inlet", x=590, y=charge_y)

    water_run_y = 620.0
    water.pin(port="outlet", x=80, y=water_run_y)
    hv202.pin(port="inlet", x=300, y=water_run_y)

    quench_run_y = 740.0
    quench.pin(port="outlet", x=80, y=quench_run_y)
    xv206.pin(mirrored="y").pin(port="inlet", x=340, y=quench_run_y)

    # The vent turns up east of the balloons that read the vessel rather
    # than between them and their wall: an impulse line runs straight out
    # of the face it is taken from, so a riser standing any closer would
    # be crossed by every one of them.
    vent_run_y = 120.0
    vent_riser_x = 1000.0
    cv204.pin(port="inlet", x=1150, y=vent_run_y)
    vent_gas.pin(port="inlet", x=1540, y=vent_run_y)

    # The jacket water runs east to west, so every device on it is
    # mirrored end to end and the header flag is the far one.
    cws_jkt.pin(mirrored=True).pin(port="outlet", x=1540, y=jacket_y)
    hv205.pin(mirrored=True).pin(port="inlet", x=1420, y=jacket_y)
    fe205.pin(mirrored=True).pin(port="inlet", x=1300, y=jacket_y)
    cv205.pin(mirrored=True).pin(port="inlet", x=1150, y=jacket_y)

    product_y = 720.0
    cv203.pin(port="inlet", x=880, y=product_y)
    cooler.pin(x=1040).pin(port="tube_in", y=product_y)
    shell_in_x = cooler.pin_.x + port_offset(cooler, "shell_in")[0]
    shell_out_x = cooler.pin_.x + port_offset(cooler, "shell_out")[0]
    cws_cool.pin(port="outlet", x=shell_in_x, y=590)
    hv207.pin(orientation=90).pin(port="inlet", x=shell_in_x, y=640)
    cwr_cool.pin(port="inlet", x=shell_out_x, y=850)
    glycol.pin(port="inlet", x=1540, y=product_y)

    # --- Process lines ------------------------------------------------
    # The oxide arrives at 3 barg, is lifted to 8 barg by P-201 and is
    # let down across CV-201 into the 2 barg reactor; the water and the
    # quench both tie in downstream of that valve, off headers held above
    # the reactor. Nothing on this sheet runs into a higher pressure than
    # it left.
    fs.connect(po_feed.outlet, pump.suction, size=80, service="PO",
               sequence=201, spec="SS")
    fs.connect(pump.discharge, xv201.inlet, size=50, service="PO",
               sequence=202, spec="SS")
    fs.connect(xv201.outlet, fe201.inlet)
    fs.connect(fe201.outlet, cv201.inlet)
    fs.connect(cv201.outlet, charge.inlet)
    fs.connect(water.outlet, hv202.inlet, size=50, service="PW", sequence=203,
               spec="CS")
    fs.connect(hv202.outlet, charge.branch)
    fs.connect(charge.outlet, mixer.inlet, size=80, service="RC", sequence=204,
               spec="SS")
    fs.connect(mixer.outlet, dump.inlet)
    fs.connect(dump.outlet, rx.feed)

    # The quench ties into the charge line downstream of the trip valve
    # and not into a nozzle of its own, so the interlock that shuts
    # XV-201 opens XV-206 into the same penetration and the cold water
    # lands where the impeller is already pumping. A dedicated dump
    # nozzle is the alternative and costs a second hole in the shell.
    fs.connect(quench.outlet, xv206.inlet, size=80, service="QWS",
               sequence=205, spec="CS")
    fs.connect(xv206.outlet, dump.branch)

    # A line that carries a balloon is routed by hand with via(): an
    # attached instrument hangs off the *routed* path, so a line the
    # router is free to re-bend takes its instrumentation elsewhere with
    # it. The vent nozzle is on the head's east shoulder, inside the
    # drawn box, so a waypoint on the nozzle's own x would take the riser
    # back up through the vessel it left.
    off_gas = fs.connect(rx.vent, cv204.inlet, size=100, service="VG",
                         sequence=206, spec="SS").via(
                             [(vent_riser_x, vent_y),
                              (vent_riser_x, vent_run_y)])
    fs.connect(cv204.outlet, vent_gas.inlet)

    # **The jacket has one nozzle where the plant has two.**
    # ``units.Reactor`` declares a single ``duty`` connection, so cooling
    # water can be drawn onto the jacket and cannot be drawn off it: the
    # return to CWRH that every jacket really has is not on this sheet,
    # and it is the one line here a reader should not take from the
    # drawing. A ``duty_out`` on the vessel is the fix; until then the
    # note below says where the return is.
    fs.connect(cws_jkt.outlet, hv205.inlet, size=150, service="CWS",
               sequence=207, spec="CS")
    fs.connect(hv205.outlet, fe205.inlet)
    fs.connect(fe205.outlet, cv205.inlet)
    fs.connect(cv205.outlet, rx.duty)

    draw = fs.connect(rx.outlet, cv203.inlet, size=100, service="PG",
                      sequence=208, spec="SS").via([(draw_x, product_y)])
    fs.connect(cv203.outlet, cooler.tube_in)
    # A number of its own and not the draw's: the run either side of an
    # exchanger is a different temperature and a different line.
    fs.connect(cooler.tube_out, glycol.inlet, size=100, service="PG",
               sequence=211, spec="SS")
    fs.connect(cws_cool.outlet, hv207.inlet, size=100, service="CWS",
               sequence=209, spec="CS")
    fs.connect(hv207.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, cwr_cool.inlet, size=100, service="CWR",
               sequence=210, spec="CS")

    # --- Loop 201: the oxide charge -----------------------------------
    # The element's tag moves into a balloon on a short impulse line and
    # the venturi is left unlettered; FT-201 then stacks over that
    # balloon, edge to edge, reading the same element. near=, because
    # nothing is drawn between two touching balloons.
    fe201_b = fs.add_balloon(fe201, at="N", offset=38)
    ft201 = fs.add_instrument("FT", flow201, near=fe201_b, at="N", offset=23)
    fic201 = fs.add_instrument("FIC", flow201, near=ft201, at="N", offset=60,
                               variant="shared")
    fic201.nozzle("sig_out", "E")
    fs.connect(ft201.sig_out, fic201.pv, kind="electric")
    fs.connect(fic201.sig_out, cv201.actuator, kind="pneumatic")

    # --- Loops 202/205: reactor temperature onto the jacket water -----
    # The measurement the whole sheet exists for. TIC-202 sets FIC-205's
    # setpoint rather than stroking a valve, which is what a cascade is:
    # the slave holds the water flow the master asks for, so a swing in
    # cooling-water pressure is corrected before the reactor temperature
    # has moved at all.
    tt202 = fs.add_instrument("TT", temp202, sensing=rx, at="E", offset=80)
    # South of its transmitter and not north: the vent leaves the head's
    # east shoulder, so the paper above this balloon belongs to the
    # off-gas riser.
    tic202 = fs.add_instrument("TIC", temp202, near=tt202, at="S", offset=130,
                               variant="shared")
    tic202.nozzle("sig_out", "E")
    # The alarms are lettering in this balloon's own quadrants, high above
    # the centre line and low below, so neither is a second instrument and
    # neither spends a face.
    tic202.annotate(high="TAH", low="TAL")
    fs.connect(tt202.sig_out, tic202.sig_in, kind="electric")

    fe205_b = fs.add_balloon(fe205, at="N", offset=38)
    ft205 = fs.add_instrument("FT", flow205, near=fe205_b, at="N", offset=23)
    fic205 = fs.add_instrument("FIC", flow205, near=ft205, at="W", offset=90,
                               variant="shared")
    fic205.nozzle("sig_out", "S")
    # The measurement lands on pv and the master sets sig_in: a cascade
    # sets a setpoint, it does not stroke a valve.
    fs.connect(ft205.sig_out, fic205.pv, kind="electric")
    fs.connect(tic202.sig_out, fic205.sig_in, kind="software")
    fs.connect(fic205.sig_out, cv205.actuator, kind="pneumatic")

    # --- Loop 203: reactor level on the product draw ------------------
    lt203 = fs.add_instrument("LT", level203, sensing=rx, at="W", offset=90)
    lic203 = fs.add_instrument("LIC", level203, near=lt203, at="N", offset=90,
                               variant="shared")
    lic203.nozzle("sig_out", "E")
    lic203.annotate(high="LAH", low="LAL")
    fs.connect(lt203.sig_out, lic203.sig_in, kind="electric")
    fs.connect(lic203.sig_out, cv203.actuator, kind="pneumatic")

    # --- Loop 204: reactor pressure on the vent -----------------------
    pt204 = fs.add_instrument("PT", press204, sensing=off_gas, at=0.6,
                              offset=70, angle=-90)
    pic204 = fs.add_instrument("PIC", press204, near=pt204, at="E", offset=90,
                               variant="shared")
    pic204.nozzle("sig_out", "E")   # the valve it strokes stands above and right
    pic204.annotate(high="PAH")
    fs.connect(pt204.sig_out, pic204.sig_in, kind="electric")
    fs.connect(pic204.sig_out, cv204.actuator, kind="pneumatic")

    # --- The runaway trip, on measurements of its own -----------------
    # 207 and 208 are typed literals rather than declared loops: nothing
    # else on the sheet is tagged either, so a loop here would be a
    # balloon the drawing does not have.
    #
    # The transmitter and not TIC-202: a trip reading the controller
    # reads what it last asked the valve for, so it stops working the
    # moment the loop is put on manual. TT-207 is a well of its own on
    # the draw, which is the vessel's contents leaving it, so the two
    # temperatures share no element and no impulse line. Loss of
    # agitation is the second input, because an unstirred jacket cools
    # the wall and not the batch.
    tt207 = fs.add_instrument("TT", 207, sensing=draw, at=0.12, offset=90)
    si208 = fs.add_instrument("ST", 208, sensing=rx, at="N", offset=70)
    fs.add_instrument("Z", 1, sensing=tt207, at="E", offset=44, variant="sis")
    fs.add_instrument("Z", 1, sensing=si208, at="N", offset=40, variant="sis")
    # The same square a third and a fourth time, on the two valves it
    # strokes: Instrument(variant="sis") is the one symbol allowed to
    # carry its tag more than once.
    # Over each valve rather than under it: a valve that states a fail
    # position writes FC or FO beneath its tag, and a square standing
    # there is a square with lettering across it.
    fs.add_instrument("Z", 1, acting_on=xv201, at="N", offset=34, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv206, at="N", offset=34, variant="sis")

    # --- Sheet furniture ----------------------------------------------
    # date= and scale= are stated rather than left blank: left blank, the
    # renderer fills in today's date and the ratio it fitted the sheet at.
    fs.title_block = TitleBlock(
        title="Propylene Glycol Reaction",
        subtitle="A200 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-201",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        scale="NTS",
        date="04/02/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "16/01/26", "Issued for internal review", "AA"),
            Revision("B", "04/02/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    # include= names the rows: the two tees and the static mixer are bulk
    # items bought by the line and carry no equipment-list row.
    fs.add_annotation(equipment_list(fs, align="top-right", include=[
        "R-101", "P-201A/B", "E-201",
    ]))
    # Unnumbered: a number in a notes box is a flag note drawn on the line
    # it applies to, and there is no flag primitive to draw one with.
    fs.add_annotation(notes([
        "Z-1: reactor runaway trip. TT-207 and ST-208 are its own "
        "measurements, independent of TIC-202.",
        "Z-1 shuts XV-201 and opens XV-206 together; the quench is sized "
        "for the full reactor inventory.",
        "R-101 jacket cooling water return is on P&ID-202.",
    ], title="GENERAL NOTES", numbered=False, align="bottom-left"))
    fs.add_annotation(legend({
        "SS": "Stainless Steel 316L",
        "CS": "Carbon Steel A106-B",
        "PO": "Propylene Oxide",
        "PW": "Process Water",
        "RC": "Reactor Charge",
        "PG": "Propylene Glycol",
        "VG": "Reactor Vent Gas",
        "CWSH": "Cooling Water Supply Header",
        "CWRH": "Cooling Water Return Header",
        "QWSH": "Quench Water Supply Header",
    }, align="top-left"))

    fs.render(out("stirred_reactor_train.svg"), page_size="A3", border="zone",
              diagram="p&id")
    print("Generated stirred_reactor_train.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()

