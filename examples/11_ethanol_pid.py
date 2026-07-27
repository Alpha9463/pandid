"""
Example 11: Ethanol Purification A300 — the P&ID of example 10's unit

The same beer column, condenser, reflux drum, kettle reboiler and bottoms
cooler as ``10_ethanol_pfd.py``, on the same fixed ``page_size="A3"`` sheet,
drawn as the piping and instrumentation diagram rather than the flow diagram.
The condenser, drum and reboiler carry the tags the P&ID gives them, which the
PFD leaves off.

What a P&ID adds over the PFD of the same unit:

- every line carries its **line number** rather than a stream number, and one
  number runs through the hand valves and the control valve of a station,
  because a valve station is one line and not four;
- the field devices are drawn: each control valve as the station it is, with
  hand isolation valves either side of it and the reduction to its body
  between, the flow elements sitting *in* the line with their transmitters
  hung off them, block valves on the cooling-water tie-ins, a check valve on
  the bottoms and the solenoid trip on the feed;
- five control loops close on a real final control element, each drawn
  measurement -> controller -> actuator, with the tower-top temperature
  cascaded onto the reflux flow controller. Every controller and alarm is a
  shared-display balloon, a circle in a square, because they are functions of
  the DCS and not devices standing in the field;
- the interlock square repeats. ``Instrument(variant="sis")`` is the one
  symbol allowed to carry its tag more than once, because a trip is a single
  logic function drawn everywhere it acts.

Every in-line device is placed with :func:`on_run`, which asks the symbol
where its own nozzle sits rather than repeating a measured offset, so the runs
stay straight whatever size the valve artwork is drawn at.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Annotation, Revision, TitleBlock, legend, notes
from pandid.geometry import Frame, normalize_mirror
from pandid.portgeom import port_point, resolve_size


def nozzle_at(unit, port, mirrored=False):
    """Where ``port`` sits relative to the unit's own top-left corner.

    Asked of the symbol the unit is drawn with rather than written down as a
    pair of numbers. A hand-tuned offset is only true of the artwork it was
    measured off, so a run pinned against one drifts off its nozzles the moment
    that artwork is drawn at another size; asked, it cannot.
    """
    mirror_x, mirror_y = normalize_mirror(mirrored)
    width, height = resolve_size(unit)
    probe = Frame(x=0.0, y=0.0, w=width, h=height,
                  mirrored=mirror_x, mirror_y=mirror_y)
    return port_point(unit, probe, port)


def on_run(unit, x, run_y, port="inlet", mirrored=False):
    """Pin an in-line device at ``x`` with ``port`` on its run's centreline."""
    return unit.pin(x=x, y=run_y - nozzle_at(unit, port, mirrored)[1],
                    mirrored=mirrored)


def main():
    # The sheet spells a line number service-sequence-size-spec, and its spec
    # field carries the flange class and the material together.
    fs = Flowsheet(
        "Ethanol Purification A300",
        line_numbering_scheme="{service}-{sequence}-{size}-{spec}",
        line_number_start=301,
    )

    # --- Equipment -------------------------------------------------------
    # The tag is set inside the shell, since the overhead leaves the top centre
    # and a tag written above the tower would be written across that riser.
    col = fs.add(units.Column("T-301", label_pos="center", description="Beer Column"))
    cond = fs.add(units.HeatExchanger("C-301", variant="straight_tubes", width=130,
                                      height=40, description="Overhead Condenser"))
    drum = fs.add(units.Vessel("D-301", variant="horizontal", width=130, height=42,
                               description="Reflux Drum"))
    reb = fs.add(units.HeatExchanger("RB-301", variant="kettle", width=140, height=50,
                                     description="U-tube Kettle Reboiler"))
    cooler = fs.add(units.HeatExchanger("HX-301", variant="straight_tubes", width=130,
                                        height=40, description="Beer Bottoms Cooler"))
    split_w = 40.0
    split = fs.add(units.Splitter("SP-301", n_outlets=2, width=split_w, height=split_w,
                                  description="Reflux Split"))

    # Boundary flags. The two cooling-water tie-ins serve one header but are
    # numbered apart, because a tag names one item on the sheet.
    fb_feed = fs.add(units.Feed("Fermentation Broth", reference="P&ID-201"))
    cws_cond = fs.add(units.Feed("CWSH-1"))
    cwr_cond = fs.add(units.Product("CWRH-1"))
    cws_cool = fs.add(units.Feed("CWSH-2"))
    cwr_cool = fs.add(units.Product("CWRH-2"))
    steam = fs.add(units.Feed("HPSSH"))
    condensate = fs.add(units.Product("HPSRH"))
    ae_prod = fs.add(units.Product("Azeotropic Ethanol", reference="PFD-302"))
    bottoms_prod = fs.add(units.Product("Cooled Bottoms", reference="F-301"))

    # Valve stations. The reflux, distillate and steam control valves are each
    # drawn as the station they are: hand isolation valves either side so the
    # valve can be changed out under a line break, and between the upstream
    # isolation and the valve the reduction down to its own smaller body.
    xv = fs.add(units.Valve("XV-301", variant="solenoid",
                            description="Feed Trip Valve"))
    meter = fs.add(units.Fitting("FE-313", variant="rotameter",
                                 description="Feed Flow Element"))
    cv3011 = fs.add(units.Valve("CV-301-1", variant="control",
                                description="Overhead Pressure Control Valve"))
    hv303a = fs.add(units.Valve("HV-303A", description="Reflux Isolation Valve"))
    rd303 = fs.add(units.Reducer("RD-303", description="CV-303 Inlet Reducer"))
    cv303 = fs.add(units.Valve("CV-303", variant="control",
                               description="Reflux Control Valve"))
    hv303b = fs.add(units.Valve("HV-303B", description="Reflux Isolation Valve"))
    # The reflux flow element sits in the run itself: the balloon beside it
    # reads the element, it is not the element.
    fe303 = fs.add(units.Fitting("FE-303", variant="orifice",
                                 description="Reflux Flow Element"))
    hv305a = fs.add(units.Valve("HV-305A", description="Distillate Isolation Valve"))
    rd305 = fs.add(units.Reducer("RD-305", description="CV-305 Inlet Reducer"))
    cv305 = fs.add(units.Valve("CV-305", variant="control",
                               description="Distillate Control Valve"))
    hv305b = fs.add(units.Valve("HV-305B", description="Distillate Isolation Valve"))
    cv306 = fs.add(units.Valve("CV-306", variant="control",
                               description="Bottoms Control Valve"))
    nrv306 = fs.add(units.Valve("NRV-306", variant="check",
                                description="Bottoms Non-Return Valve"))
    # Block valves at the two cooling-water tie-ins, so either exchanger can be
    # isolated from the header without shutting the header down.
    hv311 = fs.add(units.Valve("HV-311", description="C-301 Cooling Water Block Valve"))
    hv315 = fs.add(units.Valve("HV-315", description="HX-301 Cooling Water Block Valve"))
    hv308a = fs.add(units.Valve("HV-308A", description="Steam Isolation Valve"))
    rd308 = fs.add(units.Reducer("RD-308", description="CV-308 Inlet Reducer"))
    cv308 = fs.add(units.Valve("CV-308", variant="control",
                               description="Steam Control Valve"))
    hv308b = fs.add(units.Valve("HV-308B", description="Steam Isolation Valve"))

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner. Every run is named by the elevation of
    # the nozzle it serves, and each device on it is pinned with on_run(), which
    # asks the symbol where its own nozzle sits. Nothing here carries a measured
    # offset, so no rescaling of the artwork can leave a valve off its run.
    col_x, col_y = 470.0, 300.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + resolve_size(col)[0] / 2
    feed_y = col_y + nozzle_at(col, "feed")[1]
    boilup_y = col_y + nozzle_at(col, "boilup_in")[1]

    # Feed spine on the tower's feed nozzle. The trip valve is flipped
    # top-to-bottom so its solenoid faces the interlock square underneath it.
    on_run(fb_feed, 150, feed_y, port="outlet")
    on_run(xv, 250, feed_y, mirrored="y")
    on_run(meter, 350, feed_y)

    # Overhead spine, clear above the tower and the condenser. The pressure
    # control valve throttles into the condenser, so it stands at the far end of
    # the run rather than over the tower.
    overhead_y = 140.0
    cond.pin(x=880, y=180)
    cond_hot_in_x = 880 + nozzle_at(cond, "hot_in")[0]
    cw_cond_y = 180 + nozzle_at(cond, "cold_in")[1]
    on_run(cv3011, 800, overhead_y)
    cv3011_top = overhead_y - nozzle_at(cv3011, "inlet")[1]
    on_run(cws_cond, 150, cw_cond_y, port="outlet")
    on_run(hv311, 320, cw_cond_y)
    on_run(cwr_cond, 1480, cw_cond_y, port="inlet")

    # Drum hung so its top inlet sits under the condenser's drain, which makes
    # that run a straight drop. The inlet is authored on more than one face and
    # the top one is named here, so the nozzle the drum is positioned by is the
    # nozzle the condensate arrives at.
    drum.nozzle("inlet", "N")
    drum_x = 880 + nozzle_at(cond, "hot_out")[0] - nozzle_at(drum, "inlet")[0]
    drum.pin(x=drum_x, y=270)
    drum_draw_x = drum_x + nozzle_at(drum, "outlet")[0]
    split.pin(x=drum_draw_x - split_w / 2, y=350, orientation=90)  # inlet up, outlets down

    # Reflux station, running right to left, so it is mirrored end to end and
    # every device takes flow on its east face. The flow element is last, next
    # to the tower, where it reads the metered stream and not the leakage past
    # an isolation valve.
    reflux_run_y = 440.0
    on_run(hv303a, 910, reflux_run_y, mirrored=True)
    on_run(rd303, 855, reflux_run_y, mirrored=True)
    on_run(cv303, 785, reflux_run_y, mirrored=True)
    on_run(hv303b, 715, reflux_run_y, mirrored=True)
    on_run(fe303, 655, reflux_run_y, mirrored=True)

    # Distillate station, left to right, and well below the reflux run: the two
    # legs of the same tee read as two lines rather than as one. The station is
    # far enough along the run for the line number to be drawn on its
    # horizontal, since a number is drawn on the longest segment it has.
    dist_y = 510.0
    on_run(hv305a, 1110, dist_y)
    on_run(rd305, 1170, dist_y)
    on_run(cv305, 1225, dist_y)
    on_run(hv305b, 1295, dist_y)
    on_run(ae_prod, 1480, dist_y, port="inlet")

    # Reboiler off the tower sump; steam spine on its shell inlet.
    reb.pin(x=700, y=580)
    steam_y = 580 + nozzle_at(reb, "hot_in")[1]
    on_run(steam, 150, steam_y, port="outlet")
    on_run(hv308a, 240, steam_y)
    on_run(rd308, 300, steam_y)
    on_run(cv308, 350, steam_y)
    on_run(hv308b, 420, steam_y)
    on_run(condensate, 1480, 580 + nozzle_at(reb, "hot_out")[1], port="inlet")

    # Bottoms over the weir, cooled and sent off the sheet. The bottoms valve
    # is flipped so its operator faces the controller standing below it.
    bottoms_y = 660.0
    on_run(cv306, 900, bottoms_y, mirrored="y")
    on_run(nrv306, 1000, bottoms_y)
    cooler.pin(x=1100, y=720)
    cooler_hot_in_x = 1100 + nozzle_at(cooler, "hot_in")[0]
    cooler_hot_out_x = 1100 + nozzle_at(cooler, "hot_out")[0]
    cw_cool_y = 720 + nozzle_at(cooler, "cold_in")[1]
    cooled_y = 805.0
    on_run(cws_cool, 150, cw_cool_y, port="outlet")
    on_run(hv315, 320, cw_cool_y)
    on_run(cwr_cool, 1480, cw_cool_y, port="inlet")
    on_run(bottoms_prod, 1480, cooled_y, port="inlet")

    # --- Process lines ---------------------------------------------------
    fs.connect(fb_feed.outlet, xv.inlet, service="FB", sequence=301, size=200,
               spec="160-SS")
    fs.connect(xv.outlet, meter.inlet)
    fs.connect(meter.outlet, col.feed)

    # A line that carries a balloon is routed by hand with via(). An attached
    # instrument hangs off the *routed* path, so a line the router is free to
    # re-bend carries its instrumentation somewhere else with it.
    #
    # A line number is drawn on the longest segment of its run, and the
    # cooling-water header crosses this one's riser, so the run's horizontal is
    # kept the longer of the two and the number is read clear of the crossing.
    vapour = fs.connect(col.distillate, cv3011.inlet, service="AE", sequence=302,
                        size=300, spec="80-SS").via([(col_axis, overhead_y)])
    fs.connect(cv3011.outlet, cond.hot_in).via([(cond_hot_in_x, overhead_y)])
    fs.connect(cond.hot_out, drum.inlet, service="AE", sequence=304, size=150,
               spec="80-SS")
    fs.connect(cws_cond.outlet, hv311.inlet, service="CWS", sequence=311, size=150,
               spec="150-CS")
    fs.connect(hv311.outlet, cond.cold_in)
    cw_return = fs.connect(cond.cold_out, cwr_cond.inlet, service="CWR",
                           sequence=312, size=150,
                           spec="150-CS").via([(1200, cw_cond_y)])

    fs.connect(drum.outlet, split.inlet, service="AE", sequence=309, size=100,
               spec="80-SS")
    # The left-hand outlet takes the reflux and the right-hand one the
    # distillate, so the two lines leave the tee without crossing.
    fs.connect(split.out_2, hv303a.inlet, service="AE", sequence=303, size=80,
               spec="80-SS")
    fs.connect(hv303a.outlet, rd303.inlet)
    fs.connect(rd303.outlet, cv303.inlet)
    fs.connect(cv303.outlet, hv303b.inlet)
    fs.connect(hv303b.outlet, fe303.inlet)
    fs.connect(fe303.outlet, col.reflux_in, tear_hint=True)
    fs.connect(split.out_1, hv305a.inlet, service="AE", sequence=305, size=40,
               spec="80-SS")
    fs.connect(hv305a.outlet, rd305.inlet)
    fs.connect(rd305.outlet, cv305.inlet)
    fs.connect(cv305.outlet, hv305b.inlet)
    fs.connect(hv305b.outlet, ae_prod.inlet)

    sump_x = 700 + nozzle_at(reb, "cold_in")[0]
    boilup_x = 700 + nozzle_at(reb, "cold_out")[0]
    sump = fs.connect(col.bottoms, reb.cold_in, service="FB", sequence=307,
                      size=250, spec="160-SS").via([(col_axis, 655), (sump_x, 655)])
    boilup = fs.connect(reb.cold_out, col.boilup_in, service="FB", sequence=310,
                        size=300, spec="160-SS",
                        tear_hint=True).via([(boilup_x, 535), (595, 535), (595, boilup_y)])
    fs.connect(steam.outlet, hv308a.inlet, service="HPS", sequence=308, size=100,
               spec="300-CS")
    fs.connect(hv308a.outlet, rd308.inlet)
    fs.connect(rd308.outlet, cv308.inlet)
    fs.connect(cv308.outlet, hv308b.inlet)
    fs.connect(hv308b.outlet, reb.hot_in)
    fs.connect(reb.hot_out, condensate.inlet, service="HPR", sequence=317, size=80,
               spec="300-CS")

    fs.connect(reb.bottoms, cv306.inlet, service="FB", sequence=306, size=100,
               spec="160-SS")
    fs.connect(cv306.outlet, nrv306.inlet)
    fs.connect(nrv306.outlet, cooler.hot_in).via([(cooler_hot_in_x, bottoms_y)])
    fs.connect(cooler.hot_out, bottoms_prod.inlet, service="FB", sequence=314,
               size=100, spec="160-SS").via([(cooler_hot_out_x, cooled_y)])
    fs.connect(cws_cool.outlet, hv315.inlet, service="CWS", sequence=315, size=100,
               spec="150-CS")
    fs.connect(hv315.outlet, cooler.cold_in)
    fs.connect(cooler.cold_out, cwr_cool.inlet, service="CWR", sequence=316, size=100,
               spec="150-CS")

    # --- Feed trip and local indication ----------------------------------
    # The square is the trip logic rather than a device, so it is drawn at each
    # place the trip acts and carries the same tag every time. It is the
    # diamond-in-square of ANSI/ISA-5.1-2009 Table 5.1.1 column B, named
    # outright rather than through the ``logic`` spelling of it, because a plain
    # diamond is the different symbol this sheet does not draw.
    fs.add_instrument("I", 2, on=xv, at="S", offset=26, variant="sis")
    fs.add_instrument("FI", 314, on=meter, at="S", offset=36)
    fs.add_instrument("PI", 315, on=col, at="W", offset=52)
    fs.add_instrument("TI", 325, on=cw_return, at=0.3, offset=55)

    # --- Loop 301: tower overhead pressure -------------------------------
    # The faceplate is mounted on the valve it drives rather than beside the
    # transmitter, so its output leaves the bottom of the balloon and drops
    # straight onto the actuator; both balloons are hung on one row above the
    # overhead run, which is what makes the measurement line straight too.
    balloon_row_y = 45.0
    pt301 = fs.add_instrument("PT", 301, on=vapour, at=0.75,
                              offset=overhead_y - balloon_row_y)
    pic301 = fs.add_instrument("PIC", 301, on=cv3011, at="N", variant="shared",
                               offset=cv3011_top - balloon_row_y)
    pic301.nozzle("sig_out", "S")
    pah = fs.add_instrument("PAH", 301, on=pic301, at="E", offset=46)
    pal = fs.add_instrument("PAL", 301, on=pah, at="E", offset=46)
    fs.add_instrument("I", 1, on=pal, at="E", offset=40, variant="sis")
    fs.connect(pt301.sig_out, pic301.sig_in, kind="electric")
    fs.connect(pic301.sig_out, cv3011.actuator, kind="pneumatic")

    # --- Loops 302/303: tower top temperature cascaded onto reflux flow ---
    # Tapped low on the riser, below the cooling-water header that crosses it.
    tt302 = fs.add_instrument("TT", 302, on=vapour, at=0.13, offset=80, angle=-90)
    tic302 = fs.add_instrument("TIC", 302, on=tt302, at="E", offset=78, variant="shared")
    tic302.nozzle("sig_out", "S")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    # The transmitter reads the element sitting in the line, so it hangs off
    # that unit rather than off the pipe. Both balloons sit in the gap between
    # the reflux run and the boilup.
    ft303 = fs.add_instrument("FT", 303, on=fe303, at="S", offset=45)
    fic303 = fs.add_instrument("FIC", 303, on=ft303, at="E", offset=70, variant="shared")
    fic303.nozzle("sig_out", "E")   # the valve it strokes stands above and right
    # The measurement lands on the flow controller's pv and the temperature
    # controller sets it: a cascade sets a setpoint, it does not stroke a valve.
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, cv303.actuator, kind="pneumatic")

    # --- Loop 304: reflux drum level on the distillate valve --------------
    lt304 = fs.add_instrument("LT", 304, on=drum, at="E", offset=60)
    lic304 = fs.add_instrument("LIC", 304, on=lt304, at="E", offset=66, variant="shared")
    lic304.nozzle("sig_out", "S")
    lah = fs.add_instrument("LAH", 304, on=lic304, at="E", offset=46)
    fs.add_instrument("LAL", 304, on=lah, at="E", offset=46)
    fs.add_instrument("I", 1, on=lic304, at="N", offset=40, variant="sis")
    fs.connect(lt304.sig_out, lic304.sig_in, kind="electric")
    fs.connect(lic304.sig_out, cv305.actuator, kind="pneumatic")

    # --- Loop 307: reboiler return temperature on the steam valve ---------
    tt307 = fs.add_instrument("TT", 307, on=sump, at=0.05, offset=85, angle=-90)
    tic307 = fs.add_instrument("TIC", 307, on=tt307, at="W", offset=96,
                               variant="shared")
    tic307.nozzle("sig_out", "S")
    fs.add_instrument("I", 1, on=tic307, at="W", offset=40, variant="sis")
    fs.add_instrument("TI", 321, on=boilup, at=0.05, offset=70, angle=-90)
    fs.connect(tt307.sig_out, tic307.sig_in, kind="electric")
    fs.connect(tic307.sig_out, cv308.actuator, kind="pneumatic")

    # --- Loop 306: kettle level on the bottoms draw -----------------------
    lt306 = fs.add_instrument("LT", 306, on=reb, at="S", offset=68)
    lic306 = fs.add_instrument("LIC", 306, on=lt306, at="E", offset=56, variant="shared")
    lic306.nozzle("sig_out", "E")
    fs.add_instrument("I", 1, on=lt306, at="W", offset=44, variant="sis")
    fs.connect(lt306.sig_out, lic306.sig_in, kind="electric")
    fs.connect(lic306.sig_out, cv306.actuator, kind="pneumatic")

    # --- Sheet furniture -------------------------------------------------
    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-301",
        company="THE UNIVERSITY OF QUEENSLAND",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        # Stated rather than left blank, so the sheet renders the same today as
        # it did at issue.
        date="30/10/25",
        drawn_by="AA", checked_by="RG", approved_by="HVL",
        revisions=[
            Revision("A", "11/10/25", "Issued for internal review", "AA"),
            Revision("B", "25/10/25", "Issued For Review", "AA", "RG", "HVL"),
        ],
    )

    # The equipment list is written out rather than generated, so the rows keep
    # the order the issued sheet schedules them in.
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
        "Sampling Point",
        "Electromagnetic Flow Meter",
        "Reflux Drum Startup Fill Point",
        "Vent",
        "Distillation Tower Flush Line",
    ], align="bottom-left"))
    fs.add_annotation(legend({
        "SS": "Stainless Steel 316L",
        "CS": "Carbon Steel A106-B",
        "AE": "Azeotropic Ethanol",
        "FB": "Fermentation Broth",
        "CWSH": "Cooling Water Supply Header",
        "CWRH": "Cooling Water Return Header",
        "HPSSH": "High Pressure Steam Supply Header",
        "HPSRH": "High Pressure Steam Return Header",
    }, align="top-left"))

    fs.render(out("ethanol_pid.svg"), page_size="A3", border="zone")
    print("Generated ethanol_pid.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
