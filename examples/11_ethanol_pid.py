"""
Example 11: Ethanol Purification A300, the P&ID of example 10's unit

The unit of ``10_ethanol_pfd.py`` drawn as a P&ID on the same A3 sheet:
flanged connections, line numbers, four control valve stations
(``fs.add_valve_station()``), eight loops with three cascades, alarms
lettered in their controllers, and repeated ``variant="sis"`` trips.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    CheckValve,
    ControlValve,
    DistillationColumn,
    Feed,
    Fitting,
    FlowElement,
    Flowsheet,
    KettleReboiler,
    Product,
    ShellAndTubeExchanger,
    SolenoidValve,
    Tee,
    Valve,
    Vessel,
)
from pandid.document import Annotation, Revision, TitleBlock, legend, notes
from pandid.portgeom import port_offset, resolve_size


def main():
    """Build and render the ethanol purification P&ID."""
    fs = Flowsheet(
        "Ethanol Purification A300",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
        line_number_start=301,
    )

    # --- Control loops ------------------------------------------------
    press301 = fs.add_loop("P", 301)    # tower overhead pressure
    temp302 = fs.add_loop("T", 302)     # tower top temperature, a cascade master
    flow303 = fs.add_loop("F", 303)     # reflux flow, its slave
    level304 = fs.add_loop("L", 304)    # reflux drum level, a cascade master
    flow305 = fs.add_loop("F", 305)     # distillate flow, its slave
    level306 = fs.add_loop("L", 306)    # kettle level
    temp307 = fs.add_loop("T", 307)     # reboiler return temperature, a master
    flow308 = fs.add_loop("F", 308)     # steam flow, its slave

    # --- Equipment ----------------------------------------------------
    # label_pos="center" keeps the tag off the overhead riser.
    col = fs.add(DistillationColumn("T-301", internals="sieve_tray", trays=18,
                                    label_pos="center", description="Beer Column"))
    cond = fs.add(ShellAndTubeExchanger("C-301", variant="straight_tubes", width=130,
                                        height=40, description="Overhead Condenser"))
    drum = fs.add(Vessel("D-301", variant="horizontal", width=130, height=42,
                         description="Reflux Drum"))
    reb = fs.add(KettleReboiler("RB-301", width=140, height=50,
                                description="U-tube Kettle Reboiler"))
    cooler = fs.add(ShellAndTubeExchanger("HX-301", variant="straight_tubes", width=130,
                                          height=40, description="Beer Bottoms Cooler"))

    # header=True lets several flags name the same header.
    fb_feed = fs.add(Feed("Fermentation Broth", reference="P&ID-201"))
    cws_cond = fs.add(Feed("CWSH", header=True))
    cwr_cond = fs.add(Product("CWRH", header=True))
    cws_cool = fs.add(Feed("CWSH", header=True))
    cwr_cool = fs.add(Product("CWRH", header=True))
    steam = fs.add(Feed("HPSSH", header=True))
    condensate = fs.add(Product("HPSRH", header=True))
    ae_prod = fs.add(Product("Azeotropic Ethanol", reference="PFD-302"))
    bottoms_prod = fs.add(Product("Cooled Bottoms", reference="F-301"))

    # The in-line devices that stand on their own, outside a station.
    xv = fs.add(SolenoidValve("XV-301",
                              description="Feed Trip Valve"))
    meter = fs.add(Fitting("FE-313", variant="rotameter",
                           description="Feed Flow Element"))
    # loop.tag() names a final element, loop.element() a primary one.
    cv306 = fs.add(ControlValve(level306.tag("CV"),
                                description="Bottoms Control Valve"))
    nrv306 = fs.add(CheckValve("NRV-306",
                               description="Bottoms Non-Return Valve"))
    hv311 = fs.add(Valve("HV-311", description="C-301 Cooling Water Block Valve"))
    hv315 = fs.add(Valve("HV-315", description="HX-301 Cooling Water Block Valve"))
    # Each element's tag goes in a balloon; see add_balloon() below.
    fe303 = fs.add(FlowElement(flow303.element("FE"),
                               description="Reflux Flow Element"))
    fe305 = fs.add(FlowElement(flow305.element("FE"),
                               description="Distillate Flow Element"))
    fe308 = fs.add(FlowElement(flow308.element("FE"),
                               description="Steam Flow Element"))
    # The size steps down 100 -> 40, so the number breaks here.
    t_draw = fs.add(Tee())
    t_draw.new_line_number = True

    # --- Placement ----------------------------------------------------
    col_x, col_y = 470.0, 300.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + resolve_size(col)[0] / 2
    feed_y = col_y + port_offset(col, "feed")[1]
    boilup_y = col_y + port_offset(col, "boilup_in")[1]

    # mirrored="y" faces the solenoid at the interlock square.
    fb_feed.pin(port="outlet", x=200, y=feed_y)
    xv.pin(mirrored="y").pin(port="inlet", x=250, y=feed_y)
    meter.pin(port="inlet", x=350, y=feed_y)

    overhead_y = 130.0
    cond_x, cond_y = 1010.0, 210.0
    cond.pin(x=cond_x, y=cond_y)
    cond_shell_in_x = cond_x + port_offset(cond, "shell_in")[0]
    cw_cond_y = cond_y + port_offset(cond, "tube_in")[1]
    # bypass_over="reduction" stands the bypass valve over the reducer;
    # number=301 numbers the members 301 rather than 301-1.
    st301 = fs.add_valve_station(
        "CV-301-1", x=677.5, y=overhead_y, number=301, bypass_over="reduction",
        description="Overhead", service="AE", sequence=302, size=300, schedule=80, spec="SS")
    cws_cond.pin(port="outlet", x=200, y=cw_cond_y)
    hv311.pin(port="inlet", x=320, y=cw_cond_y)
    cwr_cond.pin(port="inlet", x=1540, y=cw_cond_y)

    # Move the drum's inlet to its top face, under the condenser.
    drum.nozzle("inlet", "N")
    drum_x = cond_x + port_offset(cond, "shell_out")[0] - port_offset(drum, "inlet")[0]
    drum.pin(x=drum_x, y=280)
    drum_draw_x = drum_x + port_offset(drum, "outlet")[0]

    # The reflux station runs right to left; its element sits outside it.
    reflux_run_y = 440.0
    st303 = fs.add_valve_station(
        flow303.tag("CV"), x=672.5, y=reflux_run_y, mirrored=True, bypass_over="reduction",
        description="Reflux", service="AE", sequence=303, size=80, schedule=80, spec="SS")
    fe303.pin(mirrored=True).pin(port="outlet", x=617.5, y=reflux_run_y)

    # orientation=90 puts the run down the page, the branch west.
    t_draw.pin(orientation=90)
    t_draw.pin(port="inlet", x=drum_draw_x).pin(port="branch", y=reflux_run_y)

    # gap=22 tightens this station.
    dist_y = 510.0
    st305 = fs.add_valve_station(
        flow305.tag("CV"), x=1147, y=dist_y, gap=22, bypass_over="reduction",
        description="Distillate", service="AE", sequence=305, size=40, schedule=80, spec="SS")
    fe305.pin(port="inlet", x=1495, y=dist_y)
    ae_prod.pin(port="inlet", x=1540, y=dist_y)

    reb.pin(x=700, y=580)
    steam_y = 580 + port_offset(reb, "tube_in")[1]
    # The steam flag stands west of the others to fit FE-308.
    steam.pin(port="outlet", x=130, y=steam_y)
    fe308.pin(port="inlet", x=150, y=steam_y)
    # Bypass valve at the far end, clear of FIC-308's output.
    st308 = fs.add_valve_station(
        flow308.tag("CV"), x=217.5, y=steam_y, bypass_over="downstream_isolation",
        description="Steam", service="HPS", sequence=308, size=100, schedule=80, spec="CS")
    condensate.pin(port="inlet", x=1540, y=580 + port_offset(reb, "tube_out")[1])

    # mirrored="y" faces the operator at the controller below.
    bottoms_y = 660.0
    cv306.pin(mirrored="y").pin(port="inlet", x=900, y=bottoms_y)
    nrv306.pin(port="inlet", x=1000, y=bottoms_y)
    cooler.pin(x=1100, y=720)
    cw_cool_y = 720 + port_offset(cooler, "tube_in")[1]
    cooled_y = 805.0
    cws_cool.pin(port="outlet", x=200, y=cw_cool_y)
    hv315.pin(port="inlet", x=320, y=cw_cool_y)
    cwr_cool.pin(port="inlet", x=1540, y=cw_cool_y)
    bottoms_prod.pin(port="inlet", x=1540, y=cooled_y)

    # --- Process lines ------------------------------------------------
    fs.connect(fb_feed.outlet, xv.inlet, service="FB", sequence=301, size=200,
               schedule=160, spec="SS")
    fs.connect(xv.outlet, meter.inlet)
    col_feed = fs.connect(meter.outlet, col.feed)

    # Fix the route of lines that carry balloons with via().
    vapour = fs.connect(col.overhead, st301.inlet, service="AE", sequence=302,
                        size=300, schedule=80, spec="SS").via([(col_axis, overhead_y)])
    fs.connect(st301.outlet, cond.shell_in).via([(cond_shell_in_x, overhead_y)])

    fs.connect(cond.shell_out, drum.inlet, service="AE", sequence=304, size=150,
               schedule=80, spec="SS")
    fs.connect(cws_cond.outlet, hv311.inlet, service="CWS", sequence=311, size=150,
               schedule=40, spec="CS")
    fs.connect(hv311.outlet, cond.tube_in)
    cw_return = fs.connect(cond.tube_out, cwr_cond.inlet, service="CWR",
                           sequence=312, size=150,
                           schedule=40, spec="CS")

    fs.connect(drum.outlet, t_draw.inlet, service="AE", sequence=309, size=100,
               schedule=80, spec="SS")
    # Reflux off the branch, distillate down the run.
    fs.connect(t_draw.branch, st303.inlet, service="AE", sequence=303, size=80,
               schedule=80, spec="SS")
    fs.connect(st303.outlet, fe303.inlet)
    fs.connect(fe303.outlet, col.reflux_in, draw_as_recycle=True)

    fs.connect(t_draw.outlet, st305.inlet, service="AE", sequence=305, size=40,
               schedule=80, spec="SS")
    fs.connect(st305.outlet, fe305.inlet)
    fs.connect(fe305.outlet, ae_prod.inlet)

    sump_x = 700 + port_offset(reb, "shell_in")[0]
    boilup_x = 700 + port_offset(reb, "shell_out")[0]
    sump = fs.connect(col.bottoms, reb.shell_in, service="FB", sequence=307,
                      size=250, schedule=160, spec="SS").via([(col_axis, 655), (sump_x, 655)])
    boilup = fs.connect(reb.shell_out, col.boilup_in, service="FB", sequence=310,
                        size=300, schedule=160, spec="SS",
                        draw_as_recycle=True).via([(boilup_x, 535), (595, 535), (595, boilup_y)])
    fs.connect(steam.outlet, fe308.inlet, service="HPS", sequence=308, size=100,
               schedule=80, spec="CS")
    fs.connect(fe308.outlet, st308.inlet)
    fs.connect(st308.outlet, reb.tube_in)
    fs.connect(reb.tube_out, condensate.inlet, service="HPR", sequence=317, size=80,
               schedule=80, spec="CS")

    fs.connect(reb.bottoms, cv306.inlet, service="FB", sequence=306, size=100,
               schedule=160, spec="SS")
    fs.connect(cv306.outlet, nrv306.inlet)
    fs.connect(nrv306.outlet, cooler.shell_in)
    fs.connect(cooler.shell_out, bottoms_prod.inlet, service="FB", sequence=314,
               size=100, schedule=160, spec="SS")
    fs.connect(cws_cool.outlet, hv315.inlet, service="CWS", sequence=315, size=100,
               schedule=40, spec="CS")
    fs.connect(hv315.outlet, cooler.tube_in)
    fs.connect(cooler.tube_out, cwr_cool.inlet, service="CWR", sequence=316, size=100,
               schedule=40, spec="CS")

    # --- Feed trip and local indication -------------------------------
    fs.add_instrument("Z", 2, acting_on=xv, face="S", offset=26, variant="sis")
    fs.add_instrument("FI", 314, sensing=meter, face="S", offset=36)
    fs.add_instrument("PI", 315, sensing=col_feed, at=0.45, offset=58)
    fs.add_instrument("TI", 325, sensing=cw_return, at=0.3, offset=55)

    # --- Loop 301: tower overhead pressure ----------------------------
    # Transmitter and controller on one row, the controller over its valve.
    balloon_row_y = 45.0
    cv3011_top = overhead_y - port_offset(st301.control, "inlet")[1]
    pt301 = fs.add_instrument("PT", press301, sensing=vapour, at=0.75,
                              offset=overhead_y - balloon_row_y)
    pic301 = fs.add_instrument("PIC", press301, near=st301.control, face="N",
                               variant="shared", offset=cv3011_top - balloon_row_y)
    pic301.nozzle("sig_out", "S")
    pic301.annotate(high="PAH", low="PAL")
    fs.connect(pt301.sig_out, pic301.sig_in, kind="electric")
    fs.connect(pic301.sig_out, st301.control.actuator, kind="pneumatic")

    # --- The high pressure trip, on a measurement of its own ----------
    pt318 = fs.add_instrument("PT", 318, sensing=vapour, at=0.55,
                              offset=overhead_y - balloon_row_y)
    fs.add_instrument("Z", 2, sensing=pt318, face="N", offset=40, variant="sis")

    # --- Loops 302/303: tower top temperature onto reflux flow -------
    # Tapped low on the riser, below the header that crosses it.
    tt302 = fs.add_instrument("TT", temp302, sensing=vapour, at=0.13, offset=80,
                              angle=-90)
    tic302 = fs.add_instrument("TIC", temp302, near=tt302, face="E", offset=78,
                               variant="shared")
    tic302.nozzle("sig_out", "S")
    tic302.annotate(high="TAH", low="TAL")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    # Move the element's tag into a balloon; FT-303 stacks on it.
    fe303_b = fs.add_balloon(fe303, face="N", offset=38)
    ft303 = fs.add_instrument("FT", flow303, near=fe303_b, face="N", offset=23)
    fic303 = fs.add_instrument("FIC", flow303, near=ft303, face="E", offset=70,
                               variant="shared")
    fic303.nozzle("sig_out", "E")   # the valve it strokes stands below and right
    # The measurement lands on pv, the master's setpoint on sig_in.
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, st303.control.actuator, kind="pneumatic")

    # --- Loops 304/305: reflux drum level onto the distillate flow ----
    # Both controllers stand over the valve, master above slave.
    lt304 = fs.add_instrument("LT", level304, sensing=drum, face="E", offset=60)
    lic304_row_y = 325.0
    fic305_row_y = 417.0        # FT-305's row, so the measurement is straight
    cv305_top = dist_y - port_offset(st305.control, "inlet")[1]
    fic305 = fs.add_instrument("FIC", flow305, near=st305.control, face="N",
                               variant="shared", offset=cv305_top - fic305_row_y)
    lic304 = fs.add_instrument("LIC", level304, near=st305.control, face="N",
                               variant="shared", offset=cv305_top - lic304_row_y)
    lic304.nozzle("sig_out", "S")
    lic304.annotate(high="LAH", low="LAL")
    fic305.nozzle("pv", "E")     # the element stands east, down the run
    fic305.nozzle("sig_out", "S")
    fs.connect(lt304.sig_out, lic304.sig_in, kind="electric")
    fs.add_instrument("Z", 1, sensing=lt304, face="S", offset=44, variant="sis")
    fe305_b = fs.add_balloon(fe305, face="N", offset=38)
    ft305 = fs.add_instrument("FT", flow305, near=fe305_b, face="N", offset=23)
    fs.connect(ft305.sig_out, fic305.pv, kind="electric")
    fs.connect(lic304.sig_out, fic305.sig_in, kind="software")
    fs.connect(fic305.sig_out, st305.control.actuator, kind="pneumatic")

    # --- Loops 307/308: reboiler return temperature onto the steam ----
    tt307 = fs.add_instrument("TT", temp307, sensing=sump, at=0.05, offset=85,
                              angle=-90)
    tic307 = fs.add_instrument("TIC", temp307, near=tt307, face="W", offset=96,
                               variant="shared")
    tic307.nozzle("sig_out", "W")   # the slave it sets stands beside it
    fs.add_instrument("TI", 321, sensing=boilup, at=0.05, offset=70, angle=-90)
    fs.add_instrument("Z", 1, sensing=tt307, face="N", offset=40, variant="sis")
    fs.connect(tt307.sig_out, tic307.sig_in, kind="electric")

    fe308_b = fs.add_balloon(fe308, face="N", offset=38)
    ft308 = fs.add_instrument("FT", flow308, near=fe308_b, face="N", offset=23)
    fic308 = fs.add_instrument("FIC", flow308, near=ft308, face="E", offset=60,
                               variant="shared")
    fic308.nozzle("sig_out", "S")   # the valve it strokes stands below and right
    fs.connect(ft308.sig_out, fic308.pv, kind="electric")
    fs.connect(tic307.sig_out, fic308.sig_in, kind="software")
    fs.connect(fic308.sig_out, st308.control.actuator, kind="pneumatic")

    # --- Loop 306: kettle level on the bottoms draw -------------------
    lt306 = fs.add_instrument("LT", level306, sensing=reb, face="S", offset=68)
    lic306 = fs.add_instrument("LIC", level306, near=lt306, face="E", offset=56,
                               variant="shared")
    lic306.nozzle("sig_out", "E")
    fs.add_instrument("Z", 1, sensing=lt306, face="W", offset=44, variant="sis")
    fs.connect(lt306.sig_out, lic306.sig_in, kind="electric")
    fs.connect(lic306.sig_out, cv306.actuator, kind="pneumatic")

    # --- Sheet furniture ----------------------------------------------
    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-301",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        scale="NTS",
        date="30/10/25",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "11/10/25", "Issued for internal review", "AA"),
            Revision("B", "25/10/25", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # Equipment list written out by hand, in the issued sheet's order.
    fs.add_annotation(Annotation(
        title="EQUIPMENT LIST",
        rows=[("D-301", "Reflux Drum"),
              ("T-301", "Beer Column"),
              ("HX-301", "Beer Bottoms Cooler"),
              ("C-301", "Overhead Condenser"),
              ("RB-301", "U-tube Kettle Reboiler")],
        align="top-right",
    ))
    fs.add_annotation(notes([
        "Z-2: high pressure trip. PT-318 is its own measurement point.",
        "Z-1: process shutdown logic, reading three measurements.",
        "Alarms are lettered A and trips S or Z; H is drawn above L.",
    ], title="GENERAL NOTES", numbered=False, align="bottom-left"))
    fs.add_annotation(legend({
        "SS": "Stainless Steel 316L",
        "CS": "Carbon Steel A106-B",
        "AE": "Azeotropic Ethanol",
        "FB": "Fermentation Broth",
        "CWSH": "Cooling Water Supply Header",
        "CWRH": "Cooling Water Return Header",
        "HPSSH": "High Pressure Steam Supply Header",
        "HPSRH": "High Pressure Steam Return Header",
        "NC": "Normally Closed (darkened valve body)",
    }, align="top-left"))

    # connections="flanged" marks a flange pair at every nozzle and valve.
    fs.render(out("ethanol_pid.svg"), page_size="A3", border="zone",
              diagram="p&id", connections="flanged")
    # The same sheet as an editable draw.io model.
    fs.render(out("ethanol_pid.drawio"), page_size="A3", border="zone",
              diagram="p&id", connections="flanged")
    print("Generated ethanol_pid.svg and ethanol_pid.drawio")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
