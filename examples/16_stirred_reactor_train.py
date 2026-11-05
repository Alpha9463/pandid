"""
Example 16: Propylene Glycol Reaction A200, a jacketed CSTR as a P&ID

Propylene oxide and process water are metered, mixed and charged to
R-101, a jacketed continuous stirred tank with a turbine agitator. The
reactor temperature cascades onto the jacket cooling-water flow, the
product leaves on level control through the cooler E-201, and a runaway
trip shuts the feed and opens the quench.
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
from pandid.document import Revision, TitleBlock, equipment_table, legend, notes
from pandid.portgeom import pinned_x, pinned_y, port_offset


def main():
    fs = Flowsheet("Propylene Glycol Reaction A200", line_number_start=201)

    # --- Control loops ------------------------------------------------
    flow201 = fs.add_loop("F", 201)     # propylene oxide charge
    temp202 = fs.add_loop("T", 202)     # reactor temperature, a cascade master
    level203 = fs.add_loop("L", 203)    # reactor level
    press204 = fs.add_loop("P", 204)    # reactor pressure
    flow205 = fs.add_loop("F", 205)     # jacket cooling water, temp202's slave

    # --- Equipment ----------------------------------------------------
    # agitator= adds the stirrer, its drive motor and the drive nozzle.
    # Sized in the symbol's proportions so the motor stays round.
    rx = fs.add(Reactor("R-101", variant="jacketed", agitator="turbine",
                        width=152, height=360,
                        description="Propylene Glycol Reactor"))
    cooler = fs.add(ShellAndTubeExchanger("E-201", variant="straight_tubes", width=130,
                                          height=40, description="Product Cooler"))
    pump = fs.add(Pump("P-201A/B", description="Propylene Oxide Charge Pump"))

    # header=True lets several flags name the same header.
    po_feed = fs.add(Feed("Propylene Oxide", reference="P&ID-101"))
    water = fs.add(Feed("Process Water", reference="P&ID-101"))
    quench = fs.add(Feed("QWSH", header=True))
    cws_jkt = fs.add(Feed("CWSH", header=True))
    cwr_jkt = fs.add(Product("CWRH", header=True))
    cws_cool = fs.add(Feed("CWSH", header=True))
    cwr_cool = fs.add(Product("CWRH", header=True))
    vent_gas = fs.add(Product("To Vent Scrubber", reference="P&ID-902"))
    glycol = fs.add(Product("Crude Propylene Glycol", reference="P&ID-301"))

    # --- In-line devices ----------------------------------------------
    xv201 = fs.add(SolenoidValve("XV-201", fail="closed",
                                 description="Reactor Feed Trip Valve"))
    # The element's tag goes in a balloon; see add_balloon() below.
    fe201 = fs.add(FlowElement(flow201.element("FE"),
                               description="Propylene Oxide Flow Element"))
    # loop.tag() names a final element, loop.element() a primary one.
    cv201 = fs.add(ControlValve(flow201.tag("CV"), fail="closed",
                                description="Propylene Oxide Control Valve"))
    hv202 = fs.add(Valve("HV-202", description="Process Water Block Valve"))
    # Both tees combine.
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
    hv209 = fs.add(Valve("HV-209",
                         description="Jacket Cooling Water Return Block Valve"))

    # --- Placement ----------------------------------------------------
    rx_x, rx_y = 640.0, 230.0
    rx.pin(x=rx_x, y=rx_y)
    charge_y = rx_y + port_offset(rx, "feed")[1]
    supply_y = rx_y + port_offset(rx, "jacket_in")[1]
    return_y = rx_y + port_offset(rx, "jacket_out")[1]
    vent_y = rx_y + port_offset(rx, "vent")[1]
    draw_x = rx_x + port_offset(rx, "outlet")[0]

    # Pin the pump by its discharge, on the charge line.
    pump.pin(x=150).pin(port="discharge", y=charge_y)
    po_feed.pin(port="outlet", x=80,
                y=pinned_y(pump, "suction"))
    # Leave room for the discharge's line number; turn the operator down.
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

    # The vent riser stands east of the reactor's balloons.
    vent_run_y = 120.0
    vent_riser_x = 1000.0
    cv204.pin(port="inlet", x=1150, y=vent_run_y)
    vent_gas.pin(port="inlet", x=1540, y=vent_run_y)

    # The jacket supply runs east to west, so its devices are mirrored.
    cws_jkt.pin(mirrored=True).pin(port="outlet", x=1540, y=supply_y)
    hv205.pin(mirrored=True).pin(port="inlet", x=1420, y=supply_y)
    fe205.pin(mirrored=True).pin(port="inlet", x=1300, y=supply_y)
    cv205.pin(mirrored=True).pin(port="inlet", x=1150, y=supply_y)
    hv209.pin(port="inlet", x=1420, y=return_y)
    cwr_jkt.pin(port="inlet", x=1540, y=return_y)

    product_y = 720.0
    cv203.pin(port="inlet", x=880, y=product_y)
    cooler.pin(x=1040).pin(port="tube_in", y=product_y)
    shell_in_x = pinned_x(cooler, "shell_in")
    shell_out_x = pinned_x(cooler, "shell_out")
    cws_cool.pin(port="outlet", x=shell_in_x, y=590)
    hv207.pin(orientation=90).pin(port="inlet", x=shell_in_x, y=640)
    cwr_cool.pin(port="inlet", x=shell_out_x, y=850)
    glycol.pin(port="inlet", x=1540, y=product_y)

    # --- Process lines ------------------------------------------------
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

    # The quench tees into the charge line.
    fs.connect(quench.outlet, xv206.inlet, size=80, service="QWS",
               sequence=205, spec="CS")
    fs.connect(xv206.outlet, dump.branch)

    # Fix the route of a line that carries a balloon with via().
    off_gas = fs.connect(rx.vent, cv204.inlet, size=100, service="VG",
                         sequence=206, spec="SS").via(
                             [(vent_riser_x, vent_y),
                              (vent_riser_x, vent_run_y)])
    fs.connect(cv204.outlet, vent_gas.inlet)

    fs.connect(cws_jkt.outlet, hv205.inlet, size=150, service="CWS",
               sequence=207, spec="CS")
    fs.connect(hv205.outlet, fe205.inlet)
    fs.connect(fe205.outlet, cv205.inlet)
    fs.connect(cv205.outlet, rx.jacket_in)
    fs.connect(rx.jacket_out, hv209.inlet, size=150, service="CWR",
               sequence=212, spec="CS")
    fs.connect(hv209.outlet, cwr_jkt.inlet)

    draw = fs.connect(rx.outlet, cv203.inlet, size=100, service="PG",
                      sequence=208, spec="SS").via([(draw_x, product_y)])
    fs.connect(cv203.outlet, cooler.tube_in)
    fs.connect(cooler.tube_out, glycol.inlet, size=100, service="PG",
               sequence=211, spec="SS")
    fs.connect(cws_cool.outlet, hv207.inlet, size=100, service="CWS",
               sequence=209, spec="CS")
    fs.connect(hv207.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, cwr_cool.inlet, size=100, service="CWR",
               sequence=210, spec="CS")

    # --- Loop 201: the oxide charge -----------------------------------
    # Move the element's tag into a balloon; FT-201 stacks on it.
    fe201_b = fs.add_balloon(fe201, face="N", offset=38)
    ft201 = fs.add_instrument("FT", flow201, near=fe201_b, face="N", offset=23)
    fic201 = fs.add_instrument("FIC", flow201, near=ft201, face="N", offset=60,
                               variant="shared")
    fic201.nozzle("sig_out", "E")
    fs.connect(ft201.sig_out, fic201.pv, kind="electric")
    fs.connect(fic201.sig_out, cv201.actuator, kind="pneumatic")

    # --- Loops 202/205: reactor temperature onto the jacket water -----
    # TIC-202 sets FIC-205's setpoint.
    tt202 = fs.add_instrument("TT", temp202, sensing=rx, face="E", offset=80)
    # South of its transmitter, clear of the off-gas riser.
    tic202 = fs.add_instrument("TIC", temp202, near=tt202, face="S", offset=130,
                               variant="shared")
    tic202.nozzle("sig_out", "E")
    tic202.annotate(high="TAH", low="TAL")
    fs.connect(tt202.sig_out, tic202.sig_in, kind="electric")

    fe205_b = fs.add_balloon(fe205, face="N", offset=38)
    ft205 = fs.add_instrument("FT", flow205, near=fe205_b, face="N", offset=23)
    fic205 = fs.add_instrument("FIC", flow205, near=ft205, face="W", offset=90,
                               variant="shared")
    fic205.nozzle("sig_out", "S")
    # The measurement lands on pv, the master's setpoint on sig_in.
    fs.connect(ft205.sig_out, fic205.pv, kind="electric")
    fs.connect(tic202.sig_out, fic205.sig_in, kind="software")
    fs.connect(fic205.sig_out, cv205.actuator, kind="pneumatic")

    # --- Loop 203: reactor level on the product draw ------------------
    lt203 = fs.add_instrument("LT", level203, sensing=rx, face="W", offset=90)
    lic203 = fs.add_instrument("LIC", level203, near=lt203, face="N", offset=90,
                               variant="shared")
    lic203.nozzle("sig_out", "E")
    lic203.annotate(high="LAH", low="LAL")
    fs.connect(lt203.sig_out, lic203.sig_in, kind="electric")
    fs.connect(lic203.sig_out, cv203.actuator, kind="pneumatic")

    # --- Loop 204: reactor pressure on the vent -----------------------
    pt204 = fs.add_instrument("PT", press204, sensing=off_gas, at=0.6,
                              offset=70, angle=-90)
    pic204 = fs.add_instrument("PIC", press204, near=pt204, face="E", offset=90,
                               variant="shared")
    pic204.nozzle("sig_out", "E")   # the valve it strokes stands above and right
    pic204.annotate(high="PAH")
    fs.connect(pt204.sig_out, pic204.sig_in, kind="electric")
    fs.connect(pic204.sig_out, cv204.actuator, kind="pneumatic")

    # --- The runaway trip, on measurements of its own -----------------
    # Z-1 reads the draw temperature and the agitator speed.
    tt207 = fs.add_instrument("TT", 207, sensing=draw, at=0.12, offset=90)
    si208 = fs.add_instrument("ST", 208, sensing=rx, face="N", offset=70)
    fs.add_instrument("Z", 1, sensing=tt207, face="E", offset=44, variant="sis")
    fs.add_instrument("Z", 1, sensing=si208, face="N", offset=40, variant="sis")
    # The same "sis" square again over each valve it strokes.
    fs.add_instrument("Z", 1, acting_on=xv201, face="N", offset=34, variant="sis")
    fs.add_instrument("Z", 1, acting_on=xv206, face="N", offset=34, variant="sis")

    # --- Sheet furniture ----------------------------------------------
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
    fs.add_annotation(equipment_table(fs, align="top-right", include=[
        "R-101", "P-201A/B", "E-201",
    ]))
    fs.add_annotation(notes([
        "Z-1: reactor runaway trip. TT-207 and ST-208 are its own "
        "measurements, independent of TIC-202.",
        "Z-1 shuts XV-201 and opens XV-206 together; the quench is sized "
        "for the full reactor inventory.",
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

