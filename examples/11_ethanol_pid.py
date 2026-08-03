"""
Example 11: Ethanol Purification A300, the P&ID of example 10's unit

The same beer column, condenser, reflux drum, kettle reboiler and bottoms
cooler as ``10_ethanol_pfd.py``, on the same fixed ``page_size="A3"`` sheet,
drawn as the piping and instrumentation diagram rather than the flow diagram.
It is modelled on ``professional_examples/P&ID_301.pdf``, the course exemplar,
and is the densest sheet in the repo.

What a P&ID adds over the PFD of the same unit: no arrowheads
(``diagram="p&id"``); line numbers instead of stream numbers, one per valve
station rather than one per valve; the field devices, with four control valves
drawn as the **station** each is installed in (``fs.add_valve_station()``, see
:mod:`pandid.stations`); five loops closing on a real final control element,
with the tower-top temperature cascaded onto the reflux flow; and a repeated
trip square, ``Instrument(variant="sis")`` being the one symbol allowed to
carry its tag more than once.

Three places it departs from the exemplar, each on a citation:

- **the trips are lettered ``Z``**, not ``A``. ISO 15519-2 Table 2 note 9: "If
  control functions S and Z at time of action also trigger an alarm/message,
  then the A shall not be used in addition to the in front letter codes S or
  Z." The alarm balloons keep ``A``, because they annunciate and do not act;
- **the safety function has its own transmitter**, ``PT-318``. CHEE4001 p.20:
  "For potentially hazardous situations it is better practice to specify a
  separate trip system." The other three trips read the transmitter their own
  controller reads, as the exemplar's do, so both are on one sheet to compare;
- **high above low**. ISO 15519-2 §5.1.3 Figure 8 puts high functions in
  quadrant c and low in d, one over the other, so ``PAH``/``LAH`` stand above
  their controllers and ``PAL``/``LAL`` beside them.

Drawing the alarms as balloons at all is a **known deviation**: ISO 15519-2
§5.2.5 is a *shall* -- "Letter code combinations with modifiers H and L shall
be represented outside the PCI symbol" -- and ``pandid`` cannot yet annotate a
balloon with a letter code string, so the balloon form stands until #137 and
#169 land.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Column, Feed, Fitting, Flowsheet, HeatExchanger, Product, Tee, Valve, Vessel
from pandid.document import Annotation, Revision, TitleBlock, legend, notes
from pandid.portgeom import port_offset, resolve_size


def main():
    # A line number reads service-sequence-size-schedule-spec, so size and
    # schedule are two fields and nothing on the sheet reads as a second size.
    fs = Flowsheet(
        "Ethanol Purification A300",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
        line_number_start=301,
    )

    # --- Control loops ---------------------------------------------------
    # Each number is declared once here instead of typed on every balloon that
    # carries it. Members still type their own functional letters and the handle
    # checks the first of them at the call site, so a TT put on a flow loop
    # raises at the line that wrote it; a loop that *supplied* the letter would
    # make every balloon agree by construction and catch nothing.
    press301 = fs.add_loop("P", 301)    # tower overhead pressure
    temp302 = fs.add_loop("T", 302)     # tower top temperature, the cascade master
    flow303 = fs.add_loop("F", 303)     # reflux flow, its slave
    level304 = fs.add_loop("L", 304)    # reflux drum level
    level306 = fs.add_loop("L", 306)    # kettle level
    temp307 = fs.add_loop("T", 307)     # reboiler return temperature

    # --- Equipment -------------------------------------------------------
    # label_pos="center": the overhead leaves the top centre, so a tag written
    # above the tower would be written across that riser.
    col = fs.add(Column("T-301", label_pos="center", description="Beer Column"))
    cond = fs.add(HeatExchanger("C-301", variant="straight_tubes", width=130,
                                height=40, description="Overhead Condenser"))
    drum = fs.add(Vessel("D-301", variant="horizontal", width=130, height=42,
                         description="Reflux Drum"))
    reb = fs.add(HeatExchanger("RB-301", variant="kettle", width=140, height=50,
                               description="U-tube Kettle Reboiler"))
    cooler = fs.add(HeatExchanger("HX-301", variant="straight_tubes", width=130,
                                  height=40, description="Beer Bottoms Cooler"))

    # header=True is one service tapped wherever the sheet wants it, so both
    # cooling-water tie-ins carry CWSH and both returns CWRH -- one tag, drawn
    # twice, rather than two boundary flags named apart.
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
    xv = fs.add(Valve("XV-301", variant="solenoid",
                      description="Feed Trip Valve"))
    meter = fs.add(Fitting("FE-313", variant="rotameter",
                           description="Feed Flow Element"))
    # loop.tag() composes without checking the first letter and cannot: a final
    # element is not tagged from the measured variable. Its *number* does track
    # the loop, which is the half tag() supplies. The check valve behind it is
    # in no loop and types its own.
    cv306 = fs.add(Valve(level306.tag("CV"), variant="control",
                         description="Bottoms Control Valve"))
    nrv306 = fs.add(Valve("NRV-306", variant="check",
                          description="Bottoms Non-Return Valve"))
    hv311 = fs.add(Valve("HV-311", description="C-301 Cooling Water Block Valve"))
    hv315 = fs.add(Valve("HV-315", description="HX-301 Cooling Water Block Valve"))
    # label_pos="bottom" because FT-303 stands over this element, and an impulse
    # line drawn up through the tag would be knocked out by the tag's own halo.
    fe303 = fs.add(Fitting(flow303.tag("FE"), variant="venturi", label_pos="bottom",
                           description="Reflux Flow Element"))
    # The size steps down 100 -> 40 across it, so the run's number breaks here.
    t_draw = fs.add(Tee())
    t_draw.new_line_number = True

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner: each device is pinned with pin(port=...),
    # which asks the symbol where its own nozzle sits, so nothing here carries a
    # measured offset and no rescaling of the artwork can leave a valve off its
    # run. A boundary flag is pinned at the tip of its arrow.
    col_x, col_y = 470.0, 300.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + resolve_size(col)[0] / 2
    feed_y = col_y + port_offset(col, "feed")[1]
    boilup_y = col_y + port_offset(col, "boilup_in")[1]

    # mirrored="y" flips the trip valve so its solenoid faces the interlock
    # square underneath it.
    fb_feed.pin(port="outlet", x=200, y=feed_y)
    xv.pin(mirrored="y").pin(port="inlet", x=250, y=feed_y)
    meter.pin(port="inlet", x=350, y=feed_y)

    overhead_y = 130.0
    cond_x, cond_y = 1010.0, 210.0
    cond.pin(x=cond_x, y=cond_y)
    cond_shell_in_x = cond_x + port_offset(cond, "shell_in")[0]
    cw_cond_y = cond_y + port_offset(cond, "tube_in")[1]
    # bypass_over="reduction" stands the bypass valve over the station's reducer
    # rather than in the middle of its leg, which is where the controller's
    # output crosses on its way down to the actuator. number=301 makes the
    # station's members 301 and not 301-1: the suffix is the control valve's.
    st301 = fs.add_valve_station(
        "CV-301-1", x=677.5, y=overhead_y, number=301, bypass_over="reduction",
        description="Overhead", service="AE", sequence=302, size=300, schedule=80, spec="SS")
    cws_cond.pin(port="outlet", x=200, y=cw_cond_y)
    hv311.pin(port="inlet", x=320, y=cw_cond_y)
    cwr_cond.pin(port="inlet", x=1540, y=cw_cond_y)

    # The drum's inlet is authored on more than one face; naming the top one
    # here makes the nozzle the drum is positioned by the nozzle the condensate
    # arrives at, so the run from the condenser is a straight drop.
    drum.nozzle("inlet", "N")
    drum_x = cond_x + port_offset(cond, "shell_out")[0] - port_offset(drum, "inlet")[0]
    drum.pin(x=drum_x, y=280)
    drum_draw_x = drum_x + port_offset(drum, "outlet")[0]

    # The reflux station runs right to left, so it is mirrored end to end and
    # every device takes flow on its east face. The flow element is pinned last,
    # outside the bypass, so it reads the reflux whichever way the station is
    # lined up.
    reflux_run_y = 440.0
    st303 = fs.add_valve_station(
        flow303.tag("CV"), x=672.5, y=reflux_run_y, mirrored=True, bypass_over="reduction",
        description="Reflux", service="AE", sequence=303, size=80, schedule=80, spec="SS")
    fe303.pin(mirrored=True).pin(port="outlet", x=617.5, y=reflux_run_y)

    # The quarter turn puts the tee's run down the page and its branch out west,
    # so the reflux leaves level with the nozzle it returns to and the
    # distillate carries on down.
    t_draw.pin(orientation=90)
    t_draw.pin(port="inlet", x=drum_draw_x).pin(port="branch", y=reflux_run_y)

    # gap=26 tightens this station: it is the one with the drum's draw at one
    # end and the sheet edge at the other and no room to move either.
    dist_y = 510.0
    st305 = fs.add_valve_station(
        "CV-305", x=1147, y=dist_y, gap=26, bypass_over="reduction",
        description="Distillate", service="AE", sequence=305, size=40, schedule=80, spec="SS")
    ae_prod.pin(port="inlet", x=1540, y=dist_y)

    reb.pin(x=700, y=580)
    steam_y = 580 + port_offset(reb, "tube_in")[1]
    steam.pin(port="outlet", x=200, y=steam_y)
    # TIC-307's output crosses this station's leg on the way down, so the bypass
    # valve moves to the far end rather than sitting under the crossing.
    st308 = fs.add_valve_station(
        "CV-308", x=217.5, y=steam_y, bypass_over="downstream_isolation",
        description="Steam", service="HPS", sequence=308, size=100, schedule=80, spec="CS")
    condensate.pin(port="inlet", x=1540, y=580 + port_offset(reb, "tube_out")[1])

    # mirrored="y" again: the bottoms valve's operator faces the controller
    # standing below it.
    bottoms_y = 660.0
    cv306.pin(mirrored="y").pin(port="inlet", x=900, y=bottoms_y)
    nrv306.pin(port="inlet", x=1000, y=bottoms_y)
    cooler.pin(x=1100, y=720)
    cooler_shell_in_x = 1100 + port_offset(cooler, "shell_in")[0]
    cooler_shell_out_x = 1100 + port_offset(cooler, "shell_out")[0]
    cw_cool_y = 720 + port_offset(cooler, "tube_in")[1]
    cooled_y = 805.0
    cws_cool.pin(port="outlet", x=200, y=cw_cool_y)
    hv315.pin(port="inlet", x=320, y=cw_cool_y)
    cwr_cool.pin(port="inlet", x=1540, y=cw_cool_y)
    bottoms_prod.pin(port="inlet", x=1540, y=cooled_y)

    # --- Process lines ---------------------------------------------------
    # A station is one line, bypass and drains included, so it is given the
    # components its branches are numbered from and nothing is written against
    # a bypass or a drain.
    fs.connect(fb_feed.outlet, xv.inlet, service="FB", sequence=301, size=200,
               schedule=160, spec="SS")
    fs.connect(xv.outlet, meter.inlet)
    col_feed = fs.connect(meter.outlet, col.feed)

    # A line that carries a balloon is routed by hand with via(): an attached
    # instrument hangs off the *routed* path, so a line the router is free to
    # re-bend takes its instrumentation elsewhere with it. The horizontal is
    # kept the longer leg, since the number is drawn on the longest segment.
    vapour = fs.connect(col.distillate, st301.inlet, service="AE", sequence=302,
                        size=300, schedule=80, spec="SS").via([(col_axis, overhead_y)])
    fs.connect(st301.outlet, cond.shell_in).via([(cond_shell_in_x, overhead_y)])

    fs.connect(cond.shell_out, drum.inlet, service="AE", sequence=304, size=150,
               schedule=80, spec="SS")
    fs.connect(cws_cond.outlet, hv311.inlet, service="CWS", sequence=311, size=150,
               schedule=40, spec="CS")
    fs.connect(hv311.outlet, cond.tube_in)
    cw_return = fs.connect(cond.tube_out, cwr_cond.inlet, service="CWR",
                           sequence=312, size=150,
                           schedule=40, spec="CS").via([(1300, cw_cond_y)])

    fs.connect(drum.outlet, t_draw.inlet, service="AE", sequence=309, size=100,
               schedule=80, spec="SS")
    # The branch takes the reflux and the run carries on down to the distillate,
    # so the two lines leave the tee without crossing.
    fs.connect(t_draw.branch, st303.inlet, service="AE", sequence=303, size=80,
               schedule=80, spec="SS")
    fs.connect(st303.outlet, fe303.inlet)
    fs.connect(fe303.outlet, col.reflux_in, draw_as_recycle=True)

    fs.connect(t_draw.outlet, st305.inlet, service="AE", sequence=305, size=40,
               schedule=80, spec="SS")
    fs.connect(st305.outlet, ae_prod.inlet)

    sump_x = 700 + port_offset(reb, "shell_in")[0]
    boilup_x = 700 + port_offset(reb, "shell_out")[0]
    sump = fs.connect(col.bottoms, reb.shell_in, service="FB", sequence=307,
                      size=250, schedule=160, spec="SS").via([(col_axis, 655), (sump_x, 655)])
    boilup = fs.connect(reb.shell_out, col.boilup_in, service="FB", sequence=310,
                        size=300, schedule=160, spec="SS",
                        draw_as_recycle=True).via([(boilup_x, 535), (595, 535), (595, boilup_y)])
    fs.connect(steam.outlet, st308.inlet, service="HPS", sequence=308, size=100,
               schedule=80, spec="CS")
    fs.connect(st308.outlet, reb.tube_in)
    fs.connect(reb.tube_out, condensate.inlet, service="HPR", sequence=317, size=80,
               schedule=80, spec="CS")

    fs.connect(reb.bottoms, cv306.inlet, service="FB", sequence=306, size=100,
               schedule=160, spec="SS")
    fs.connect(cv306.outlet, nrv306.inlet)
    fs.connect(nrv306.outlet, cooler.shell_in).via([(cooler_shell_in_x, bottoms_y)])
    fs.connect(cooler.shell_out, bottoms_prod.inlet, service="FB", sequence=314,
               size=100, schedule=160, spec="SS").via([(cooler_shell_out_x, cooled_y)])
    fs.connect(cws_cool.outlet, hv315.inlet, service="CWS", sequence=315, size=100,
               schedule=40, spec="CS")
    fs.connect(hv315.outlet, cooler.tube_in)
    fs.connect(cooler.tube_out, cwr_cool.inlet, service="CWR", sequence=316, size=100,
               schedule=40, spec="CS")

    # --- Feed trip and local indication ----------------------------------
    # Literal numbers here and on the three indicators below, not loop handles:
    # a loop is a measured variable and a number, Z is what the function *does*,
    # and each indicator is one reading with nothing else in its group.
    fs.add_instrument("Z", 2, on=xv, at="S", offset=26, variant="sis")
    fs.add_instrument("FI", 314, on=meter, at="S", offset=36)
    # on=col_feed and not on=col: a unit host taps a face *midpoint*, and the
    # tower's feed nozzle is that midpoint, so the balloon could only be reached
    # by a 45 degree line -- which BS ISO 15519-1 §12.1 forbids.
    fs.add_instrument("PI", 315, on=col_feed, at=0.45, offset=58)
    fs.add_instrument("TI", 325, on=cw_return, at=0.3, offset=55)

    # --- Loop 301: tower overhead pressure -------------------------------
    # The faceplate is mounted on the valve it drives, so its output leaves the
    # bottom of the balloon and drops straight onto the actuator; both balloons
    # hang on one row above the overhead run, which is what makes the
    # measurement line straight too.
    balloon_row_y = 45.0
    cv3011_top = overhead_y - port_offset(st301.control, "inlet")[1]
    pt301 = fs.add_instrument("PT", press301, on=vapour, at=0.75,
                              offset=overhead_y - balloon_row_y)
    pic301 = fs.add_instrument("PIC", press301, on=st301.control, at="N", variant="shared",
                               offset=cv3011_top - balloon_row_y)
    pic301.nozzle("sig_out", "S")
    # A face each, not chained: ISO 15519-2 §6.2 makes signal lines for
    # functions inside and outside a PCI symbol "drawn separate between the PCI
    # symbols", and §7.2.4 adds that lines "for different types of control
    # functions should not be joined". Which face is Figure 8 -- high above low.
    fs.add_instrument("PAH", press301, on=pic301, at="N", offset=46, variant="shared")
    fs.add_instrument("PAL", press301, on=pic301, at="E", offset=46, variant="shared")
    fs.connect(pt301.sig_out, pic301.sig_in, kind="electric")
    fs.connect(pic301.sig_out, st301.control.actuator, kind="pneumatic")

    # --- The high pressure trip, on a measurement of its own ---------------
    # 318 is typed, and it is the one literal here that has to be argued: it is
    # a transmitter, and a transmitter usually has a loop around it. Nothing is
    # tagged PIC-318, PAH-318 or PV-318 -- what it drives is Z-2, which carries
    # the trip's number -- so declaring P-318 would put a loop of exactly one
    # balloon in fs.loops that the drawing does not contain.
    pt318 = fs.add_instrument("PT", 318, on=vapour, at=0.55,
                              offset=overhead_y - balloon_row_y)
    fs.add_instrument("Z", 2, on=pt318, at="N", offset=40, variant="sis")

    # --- Loops 302/303: tower top temperature cascaded onto reflux flow ---
    # Tapped low on the riser, below the cooling-water header that crosses it.
    tt302 = fs.add_instrument("TT", temp302, on=vapour, at=0.13, offset=80, angle=-90)
    tic302 = fs.add_instrument("TIC", temp302, on=tt302, at="E", offset=78, variant="shared")
    tic302.nozzle("sig_out", "S")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    # The transmitter reads the element sitting in the line, so it hangs off
    # that unit rather than off the pipe.
    ft303 = fs.add_instrument("FT", flow303, on=fe303, at="N", offset=90)
    fic303 = fs.add_instrument("FIC", flow303, on=ft303, at="E", offset=70, variant="shared")
    fic303.nozzle("sig_out", "E")   # the valve it strokes stands below and right
    # The measurement lands on pv and the master sets sig_in: a cascade sets a
    # setpoint, it does not stroke a valve. It is also two loops and never one,
    # so a single handle could not have taken both TIC-302 and FIC-303 and would
    # have raised on the second of them.
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, st303.control.actuator, kind="pneumatic")

    # --- Loop 304: reflux drum level on the distillate valve --------------
    # Four lines reach this controller and the transmitter's own row cannot give
    # four faces: the cooling-water return crosses 49 px above it and a balloon
    # is 44 of those. So the faceplate is mounted on the valve it drives. The
    # north face is spent on the high alarm per Figure 8, so sig_in is moved to
    # the west and the run reaches it by dropping short of the balloon.
    lt304 = fs.add_instrument("LT", level304, on=drum, at="E", offset=60)
    lic304_row_y = 403.0
    cv305_top = dist_y - port_offset(st305.control, "inlet")[1]
    lic304 = fs.add_instrument("LIC", level304, on=st305.control, at="N", variant="shared",
                               offset=cv305_top - lic304_row_y)
    lic304.nozzle("sig_in", "W")
    lic304.nozzle("sig_out", "S")
    fs.add_instrument("LAH", level304, on=lic304, at="N", offset=46, variant="shared")
    fs.add_instrument("LAL", level304, on=lic304, at="E", offset=46, variant="shared")
    # Teed off the measurement, which is where the issued sheet puts all five of
    # its own trips. angle=-90 branches west off the drop the run makes on its
    # way to the west face, into the band between LT-304's row and LIC-304's.
    level = fs.connect(lt304.sig_out, lic304.sig_in, kind="electric")
    fs.add_instrument("Z", 1, on=level, at=0.6, offset=40, angle=-90, variant="sis")
    # Straight onto the actuator: the issued sheet puts FIC-305 between the two,
    # and this sheet leaves loops 305 and 308 out, so the master is wired to the
    # valve and the valve keeps the number the issued sheet gives it. The same
    # shortening is taken on TIC-307/CV-308 below.
    fs.connect(lic304.sig_out, st305.control.actuator, kind="pneumatic")

    # --- Loop 307: reboiler return temperature on the steam valve ---------
    tt307 = fs.add_instrument("TT", temp307, on=sump, at=0.05, offset=85, angle=-90)
    tic307 = fs.add_instrument("TIC", temp307, on=tt307, at="W", offset=96,
                               variant="shared")
    tic307.nozzle("sig_out", "S")
    fs.add_instrument("TI", 321, on=boilup, at=0.05, offset=70, angle=-90)
    # on=tt307 and not on=tic307: a trip hung on the controller reads what the
    # controller last asked the valve for, so it stops working the moment the
    # loop is put on manual. North is the free face -- TIC-307 is west, the
    # impulse line leaves east, and TIC-307's output crosses to the south.
    fs.add_instrument("Z", 1, on=tt307, at="N", offset=40, variant="sis")
    fs.connect(tt307.sig_out, tic307.sig_in, kind="electric")
    fs.connect(tic307.sig_out, st308.control.actuator, kind="pneumatic")

    # --- Loop 306: kettle level on the bottoms draw -----------------------
    lt306 = fs.add_instrument("LT", level306, on=reb, at="S", offset=68)
    lic306 = fs.add_instrument("LIC", level306, on=lt306, at="E", offset=56, variant="shared")
    lic306.nozzle("sig_out", "E")
    fs.add_instrument("Z", 1, on=lt306, at="W", offset=44, variant="sis")
    fs.connect(lt306.sig_out, lic306.sig_in, kind="electric")
    fs.connect(lic306.sig_out, cv306.actuator, kind="pneumatic")

    # --- Sheet furniture -------------------------------------------------
    fs.title_block = TitleBlock(
        title="Ethanol Purification",
        subtitle="A300 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-301",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        # Stated rather than left blank, so the sheet renders the same today as
        # it did at issue. scale="NTS" is the same argument: blank, the cell
        # reports the ratio the renderer fitted the drawing at, and CHEE4001 p.2
        # is flat about that -- "Do not represent the real length of pipes on
        # P&IDs. P&ID is a 'Not to Scale' (NTS) drawing."
        scale="NTS",
        date="30/10/25",
        # Deliberately fictional, and worth saying on this sheet in particular:
        # it is modelled on professional_examples/P&ID_301.pdf, whose checker
        # and approver are real people. JS and RL are the initials 03 and 09 use;
        # AA is the repo's author.
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "11/10/25", "Issued for internal review", "AA"),
            Revision("B", "25/10/25", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # Written out rather than generated, so the rows keep the order the issued
    # sheet schedules them in.
    fs.add_annotation(Annotation(
        title="EQUIPMENT LIST",
        rows=[("D-301", "Reflux Drum"),
              ("T-301", "Beer Column"),
              ("HX-301", "Beer Bottoms Cooler"),
              ("C-301", "Overhead Condenser"),
              ("RB-301", "U-tube Kettle Reboiler")],
        align="top-right",
    ))
    # Unnumbered, because a number in a notes box is a *flag* note: CHEE4001 p.5
    # draws it as a boxed "NOTE X" on the line it applies to. There is no flag
    # primitive, so a numbered list here would be three references to nothing.
    # What is left is what the drawing itself cannot say -- a symbol key belongs
    # in the LEGEND box below, and that one trip is drawn at every point it acts
    # is visible in the squares.
    fs.add_annotation(notes([
        "Z-2: high pressure trip. PT-318 is its own measurement point.",
        "Z-1: process shutdown logic, reading three measurements.",
        "Alarms are lettered A and trips S or Z; H is drawn above L.",
    ], title="GENERAL NOTES", numbered=False, align="bottom-left"))
    # NC is declared because a darkened valve body is not an ISA-5.1 symbol:
    # clauses 2.8.1(b)(1) and 5.2.5 make declaring one mandatory.
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

    fs.render(out("ethanol_pid.svg"), page_size="A3", border="zone",
              diagram="p&id")
    # The same sheet and the same arguments, as an editable draw.io model rather
    # than a finished drawing. Every flowsheet exports; this is the densest one.
    fs.render(out("ethanol_pid.drawio"), page_size="A3", border="zone",
              diagram="p&id")
    print("Generated ethanol_pid.svg and ethanol_pid.drawio")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
