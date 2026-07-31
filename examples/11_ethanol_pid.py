"""
Example 11: Ethanol Purification A300, the P&ID of example 10's unit

The same beer column, condenser, reflux drum, kettle reboiler and bottoms
cooler as ``10_ethanol_pfd.py``, on the same fixed ``page_size="A3"`` sheet,
drawn as the piping and instrumentation diagram rather than the flow diagram.
The condenser, drum and reboiler carry the tags the P&ID gives them, which the
PFD leaves off.

What a P&ID adds over the PFD of the same unit:

- it is drawn as one, ``diagram="p&id"``, so **no process line carries an
  arrowhead**: direction on a P&ID is read off the equipment and the line list,
  and the arrow at the end of every run is the PFD's convention, not this
  drawing's;
- every line carries its **line number** rather than a stream number, and one
  number runs through the hand valves and the control valve of a station,
  because a valve station is one line and not four;
- the field devices are drawn: each control valve as the station it is, the
  flow elements sitting *in* the line with their transmitters hung off them,
  block valves on the cooling-water tie-ins, a check valve on the bottoms and
  the solenoid trip on the feed;
- five control loops close on a real final control element, each drawn
  measurement -> controller -> actuator, with the tower-top temperature
  cascaded onto the reflux flow controller. Every controller and alarm is a
  shared-display balloon, a circle in a square, because they are functions of
  the DCS and not devices standing in the field;
- the interlock square repeats. ``Instrument(variant="sis")`` is the one
  symbol allowed to carry its tag more than once, because a trip is a single
  logic function drawn everywhere it acts.

Four of the control valves are drawn as the **station** each one is installed
in, and each station is one call: ``fs.add_valve_station()`` builds the two
isolation valves, the two drains, the bypass and its normally closed throttling
valve, and the size change at each end, tags them from the control valve's own
tag, pins them along the run and wires them together. See
:mod:`pandid.stations` for the arrangement and the source it comes from.

Three kinds of item on this sheet are drawn more than once, and each says so in
its own way rather than being renamed apart:

- a **utility header** (``Feed("CWSH", header=True)``) is one service tapped
  wherever the sheet wants it, so both cooling-water tie-ins carry ``CWSH`` and
  both returns ``CWRH``, which is what the legend entry explaining them names;
- a **tee** carries no tag at all, being bulk piping bought by the line, so
  the branches around the valve stations put nothing on the drawing and nothing
  in the equipment list;
- and the **interlock square**, as above.

Every in-line device is placed with ``pin(port=...)``, which asks the symbol
where its own nozzle sits rather than repeating a measured offset, so the runs
stay straight whatever size the valve artwork is drawn at.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Annotation, Revision, TitleBlock, legend, notes
from pandid.portgeom import port_offset, resolve_size


def main():
    # The sheet spells a line number service-sequence-size-schedule-spec:
    # FB-301-200-160-SS is fermentation broth, line 301, DN 200 bore, schedule
    # 160 wall, in the stainless the legend names. Size and schedule are two
    # facts and get two fields, so nothing on the sheet reads as a second size.
    fs = Flowsheet(
        "Ethanol Purification A300",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
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

    # Boundary flags. The cooling water and the steam are utility headers, not
    # lines leaving the sheet once: a header is available all over the plant and
    # is drawn and labelled the same way at every tap, so both tie-ins on each
    # of them carry the one tag the legend explains.
    fb_feed = fs.add(units.Feed("Fermentation Broth", reference="P&ID-201"))
    cws_cond = fs.add(units.Feed("CWSH", header=True))
    cwr_cond = fs.add(units.Product("CWRH", header=True))
    cws_cool = fs.add(units.Feed("CWSH", header=True))
    cwr_cool = fs.add(units.Product("CWRH", header=True))
    steam = fs.add(units.Feed("HPSSH", header=True))
    condensate = fs.add(units.Product("HPSRH", header=True))
    ae_prod = fs.add(units.Product("Azeotropic Ethanol", reference="PFD-302"))
    bottoms_prod = fs.add(units.Product("Cooled Bottoms", reference="F-301"))

    # The in-line devices that stand on their own, outside a station.
    xv = fs.add(units.Valve("XV-301", variant="solenoid",
                            description="Feed Trip Valve"))
    meter = fs.add(units.Fitting("FE-313", variant="rotameter",
                                 description="Feed Flow Element"))
    cv306 = fs.add(units.Valve("CV-306", variant="control",
                               description="Bottoms Control Valve"))
    nrv306 = fs.add(units.Valve("NRV-306", variant="check",
                                description="Bottoms Non-Return Valve"))
    # Block valves at the two cooling-water tie-ins, so either exchanger can be
    # isolated from the header without shutting the header down.
    hv311 = fs.add(units.Valve("HV-311", description="C-301 Cooling Water Block Valve"))
    hv315 = fs.add(units.Valve("HV-315", description="HX-301 Cooling Water Block Valve"))
    # The reflux flow element sits in the run itself: the balloon beside it
    # reads the element, it is not the element. Its tag is written under the run
    # because its transmitter stands over it, and an impulse line drawn up
    # through the tag would be knocked out by the tag's own halo.
    fe303 = fs.add(units.Fitting("FE-303", variant="venturi", label_pos="bottom",
                                 description="Reflux Flow Element"))
    # The size steps down 100 -> 40 across it, so the run's number breaks here.
    t_draw = fs.add(units.Tee())
    t_draw.new_line_number = True

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner. Every run is named by the elevation of
    # the nozzle it serves, and each device on it is pinned with pin(port=...),
    # which asks the symbol where its own nozzle sits. Nothing here carries a
    # measured offset, so no rescaling of the artwork can leave a valve off its
    # run. A boundary flag is pinned at the tip of its arrow, which is where its
    # line reaches it.
    col_x, col_y = 470.0, 300.0
    col.pin(x=col_x, y=col_y)
    col_axis = col_x + resolve_size(col)[0] / 2
    feed_y = col_y + port_offset(col, "feed")[1]
    boilup_y = col_y + port_offset(col, "boilup_in")[1]

    # Feed spine on the tower's feed nozzle. The trip valve is flipped
    # top-to-bottom so its solenoid faces the interlock square underneath it.
    fb_feed.pin(port="outlet", x=200, y=feed_y)
    xv.pin(mirrored="y").pin(port="inlet", x=250, y=feed_y)
    meter.pin(port="inlet", x=350, y=feed_y)

    # Overhead spine, clear above the tower and the condenser. The pressure
    # control valve throttles into the condenser, so its station stands at the
    # far end of the run rather than over the tower. The station's members are
    # numbered 301, not 301-1: the control valve carries a suffix its hand
    # valves do not.
    overhead_y = 130.0
    cond_x, cond_y = 1010.0, 210.0
    cond.pin(x=cond_x, y=cond_y)
    cond_shell_in_x = cond_x + port_offset(cond, "shell_in")[0]
    cw_cond_y = cond_y + port_offset(cond, "tube_in")[1]
    # The bypass valve stands over the station's reducer rather than in the
    # middle of its leg, which is where the controller's output crosses on its
    # way down to the actuator; a valve body drawn under that crossing is a
    # valve body with a signal line through it.
    st301 = fs.add_valve_station(
        "CV-301-1", x=677.5, y=overhead_y, number=301, bypass_over="reduction",
        description="Overhead", service="AE", sequence=302, size=300, schedule=80, spec="SS")
    cws_cond.pin(port="outlet", x=200, y=cw_cond_y)
    hv311.pin(port="inlet", x=320, y=cw_cond_y)
    cwr_cond.pin(port="inlet", x=1540, y=cw_cond_y)

    # Drum hung so its top inlet sits under the condenser's drain, which makes
    # that run a straight drop. The inlet is authored on more than one face and
    # the top one is named here, so the nozzle the drum is positioned by is the
    # nozzle the condensate arrives at.
    drum.nozzle("inlet", "N")
    drum_x = cond_x + port_offset(cond, "shell_out")[0] - port_offset(drum, "inlet")[0]
    drum.pin(x=drum_x, y=280)
    drum_draw_x = drum_x + port_offset(drum, "outlet")[0]

    # Reflux station, running right to left, so it is mirrored end to end and
    # every device takes flow on its east face. The flow element is last, next
    # to the tower, where it reads the metered stream and not the leakage past
    # an isolation valve; it stands outside the bypass, so it reads the reflux
    # whether the station is in service or bypassed.
    reflux_run_y = 440.0
    st303 = fs.add_valve_station(
        "CV-303", x=672.5, y=reflux_run_y, mirrored=True, bypass_over="reduction",
        description="Reflux", service="AE", sequence=303, size=80, schedule=80, spec="SS")
    fe303.pin(mirrored=True).pin(port="outlet", x=617.5, y=reflux_run_y)

    # The drum's draw parts into reflux and distillate below the vessel. That
    # junction is a tee and not a piece of plant: it carries no tag on the
    # issued sheet and nothing in its equipment list. The run drops on past it
    # to the distillate station and the branch leaves west onto the reflux run,
    # which is the way the issued sheet draws it.
    t_draw.pin(orientation=90)
    t_draw.pin(port="inlet", x=drum_draw_x).pin(port="branch", y=reflux_run_y)

    # Distillate station, left to right, and well below the reflux run: the two
    # legs of the same tee read as two lines rather than as one. It is drawn a
    # little tighter than the other three, because it is the one station with
    # the drum's draw at one end and the sheet edge at the other and no room to
    # move either.
    dist_y = 510.0
    st305 = fs.add_valve_station(
        "CV-305", x=1147, y=dist_y, gap=26, bypass_over="reduction",
        description="Distillate", service="AE", sequence=305, size=40, schedule=80, spec="SS")
    ae_prod.pin(port="inlet", x=1540, y=dist_y)

    # Reboiler off the tower sump; steam spine on its tube inlet, which is the
    # channel head the heating medium enters.
    reb.pin(x=700, y=580)
    steam_y = 580 + port_offset(reb, "tube_in")[1]
    steam.pin(port="outlet", x=200, y=steam_y)
    # TIC-307's balloons stand over the middle of this station and its output
    # crosses the leg on the way down, so this bypass valve moves along to the
    # far end rather than sitting in the middle of its own leg.
    st308 = fs.add_valve_station(
        "CV-308", x=217.5, y=steam_y, bypass_over="downstream_isolation",
        description="Steam", service="HPS", sequence=308, size=100, schedule=80, spec="CS")
    condensate.pin(port="inlet", x=1540, y=580 + port_offset(reb, "tube_out")[1])

    # Bottoms over the weir, cooled and sent off the sheet. The bottoms valve
    # is flipped so its operator faces the controller standing below it.
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
    # A station is one line, and that goes for what hangs off it. The bypass is
    # the same service, size and spec as the run it goes round, and a drain small
    # enough to be governed by the piping class is part of the line it drains
    # rather than a line of its own: the size field of a line number is the
    # line's size and not the size of every branch on it. So all three branches
    # take the station's number, which is why the issued sheet writes that number
    # once and writes nothing at all against a bypass or a drain, and why the
    # station is given the components its own branches are numbered from.
    fs.connect(fb_feed.outlet, xv.inlet, service="FB", sequence=301, size=200,
               schedule=160, spec="SS")
    fs.connect(xv.outlet, meter.inlet)
    col_feed = fs.connect(meter.outlet, col.feed)

    # A line that carries a balloon is routed by hand with via(). An attached
    # instrument hangs off the *routed* path, so a line the router is free to
    # re-bend carries its instrumentation somewhere else with it.
    #
    # A line number is drawn on the longest segment of its run, and the
    # cooling-water header crosses this one's riser, so the run's horizontal is
    # kept the longer of the two and the number is read clear of the crossing.
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
    # The square is the trip logic rather than a device, so it is drawn at each
    # place the trip acts and carries the same tag every time. It is the
    # diamond-in-square of ANSI/ISA-5.1-2009 Table 5.1.1 column B, named
    # outright rather than through the ``logic`` spelling of it, because a plain
    # diamond is the different symbol this sheet does not draw.
    fs.add_instrument("I", 2, on=xv, at="S", offset=26, variant="sis")
    fs.add_instrument("FI", 314, on=meter, at="S", offset=36)
    # The gauge reads the tower's feed nozzle, but it is hung on the run rather
    # than on the wall. A unit host taps a *face midpoint*, and the tower's feed
    # enters the middle of its west wall, so that midpoint is the nozzle itself:
    # every orthogonal branch off it either runs down the feed line (west) or
    # straddles the shell (north/south), and the sheet used to reach the clear
    # space above the run with a 45 degree line instead. BS ISO 15519-1 §12.1
    # does not allow that for a functional connection, so the tap moves the few
    # pixels back onto the run it measures and stands the balloon over it.
    fs.add_instrument("PI", 315, on=col_feed, at=0.45, offset=58)
    fs.add_instrument("TI", 325, on=cw_return, at=0.3, offset=55)

    # --- Loop 301: tower overhead pressure -------------------------------
    # The faceplate is mounted on the valve it drives rather than beside the
    # transmitter, so its output leaves the bottom of the balloon and drops
    # straight onto the actuator; both balloons are hung on one row above the
    # overhead run, which is what makes the measurement line straight too.
    balloon_row_y = 45.0
    cv3011_top = overhead_y - port_offset(st301.control, "inlet")[1]
    pt301 = fs.add_instrument("PT", 301, on=vapour, at=0.75,
                              offset=overhead_y - balloon_row_y)
    pic301 = fs.add_instrument("PIC", 301, on=st301.control, at="N", variant="shared",
                               offset=cv3011_top - balloon_row_y)
    pic301.nozzle("sig_out", "S")
    # Both alarms read the controller, so both hang off it, each on a face of
    # its own and each a dead end. Chained one behind the other they would state
    # that PIC-301 feeds PAH-301 and PAH-301 feeds PAL-301: one run of line
    # carrying a control function and two alarm functions between three symbols.
    # ISO 15519-2 §6.2 is the rule against it -- "Signal lines representing
    # functions inside the PCI symbol ... and signal lines representing
    # functions outside the PCI symbol ... shall be drawn separate between the
    # PCI symbols" -- and §7.2.4 says the same from the junction's side:
    # "Signal lines for different types of control functions should not be
    # joined." Figure 17 b) draws it: every function's line leaves the balloon
    # on its own. Both faces here are forced, since the measurement arrives from
    # PT-301 in the west and the output leaves south onto the valve stem, so
    # what is left is the east and the clear sheet above the row.
    fs.add_instrument("PAH", 301, on=pic301, at="E", offset=46, variant="shared")
    fs.add_instrument("PAL", 301, on=pic301, at="N", offset=46, variant="shared")
    # The trip is teed off the *measurement*, which is where the issued sheet
    # takes all four of its own and where ISO 15519-2 Figure 17 b) puts one: the
    # SLL line leaves the measurement point, not the controller's output. An
    # alarm is the wrong host twice over, since it would draw the alarm as
    # driving the trip, and an alarm that acts is lettered S or Z and not A
    # (Table 2 note 9). It branches *above* the row, which is the one side free:
    # the station's bypass leg runs 40 px below the row and HV-301C's body
    # starts 32 px below it, so a square hung downward lands on both.
    measured = fs.connect(pt301.sig_out, pic301.sig_in, kind="electric")
    fs.add_instrument("I", 1, on=measured, at=0.35, offset=40, angle=90, variant="sis")
    fs.connect(pic301.sig_out, st301.control.actuator, kind="pneumatic")

    # --- Loops 302/303: tower top temperature cascaded onto reflux flow ---
    # Tapped low on the riser, below the cooling-water header that crosses it.
    tt302 = fs.add_instrument("TT", 302, on=vapour, at=0.13, offset=80, angle=-90)
    tic302 = fs.add_instrument("TIC", 302, on=tt302, at="E", offset=78, variant="shared")
    tic302.nozzle("sig_out", "S")
    fs.connect(tt302.sig_out, tic302.sig_in, kind="electric")

    # The transmitter reads the element sitting in the line, so it hangs off
    # that unit rather than off the pipe. Both balloons stand over the reflux
    # run, clear of the bypass leg crossing beneath them, on the side the two
    # lines that reach them come from: CV-303's actuator is on the crown of the
    # valve, so the output drops onto it, and the cascade comes down from
    # TIC-302 without having to cross the run to find them.
    ft303 = fs.add_instrument("FT", 303, on=fe303, at="N", offset=90)
    fic303 = fs.add_instrument("FIC", 303, on=ft303, at="E", offset=70, variant="shared")
    fic303.nozzle("sig_out", "E")   # the valve it strokes stands below and right
    # The measurement lands on the flow controller's pv and the temperature
    # controller sets it: a cascade sets a setpoint, it does not stroke a valve.
    fs.connect(ft303.sig_out, fic303.pv, kind="electric")
    fs.connect(tic302.sig_out, fic303.sig_in, kind="software")
    fs.connect(fic303.sig_out, st303.control.actuator, kind="pneumatic")

    # --- Loop 304: reflux drum level on the distillate valve --------------
    # Four lines reach this controller -- the measurement, the output and the
    # two alarms -- so it needs four faces, and the transmitter's own row cannot
    # give four: the cooling-water return crosses 49 px above it, and a balloon
    # is 44 of those, leaving 5 px for the stub that would have to reach it. So
    # the faceplate comes off the row and is mounted on the valve it drives, the
    # way PIC-301 is and the way the issued sheet mounts FIC-305 over this very
    # station, in the clear band between that header and CV-305's bypass leg.
    # The measurement then arrives from the north, the output drops south onto
    # the actuator, and the two alarms fan east and west.
    lt304 = fs.add_instrument("LT", 304, on=drum, at="E", offset=60)
    lic304_row_y = 403.0
    cv305_top = dist_y - port_offset(st305.control, "inlet")[1]
    lic304 = fs.add_instrument("LIC", 304, on=st305.control, at="N", variant="shared",
                               offset=cv305_top - lic304_row_y)
    lic304.nozzle("sig_in", "N")
    lic304.nozzle("sig_out", "S")
    fs.add_instrument("LAH", 304, on=lic304, at="W", offset=46, variant="shared")
    fs.add_instrument("LAL", 304, on=lic304, at="E", offset=46, variant="shared")
    # Teed off the measurement, as in loop 301 above. angle=-90 branches south
    # off the run east from LT-304, into the gap the alarm row leaves.
    level = fs.connect(lt304.sig_out, lic304.sig_in, kind="electric")
    fs.add_instrument("I", 1, on=level, at=0.3, offset=40, angle=-90, variant="sis")
    fs.connect(lic304.sig_out, st305.control.actuator, kind="pneumatic")

    # --- Loop 307: reboiler return temperature on the steam valve ---------
    tt307 = fs.add_instrument("TT", 307, on=sump, at=0.05, offset=85, angle=-90)
    tic307 = fs.add_instrument("TIC", 307, on=tt307, at="W", offset=96,
                               variant="shared")
    tic307.nozzle("sig_out", "S")
    fs.add_instrument("I", 1, on=tic307, at="W", offset=40, variant="sis")
    fs.add_instrument("TI", 321, on=boilup, at=0.05, offset=70, angle=-90)
    fs.connect(tt307.sig_out, tic307.sig_in, kind="electric")
    fs.connect(tic307.sig_out, st308.control.actuator, kind="pneumatic")

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
        company="PANDID",
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
    # A darkened valve body is not an ISA-5.1 symbol, since the standard hands
    # manual valve depiction to the piping group, so clauses 2.8.1(b)(1) and
    # 5.2.5 of ISA-5.1 make declaring it here mandatory rather than optional.
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
    print("Generated ethanol_pid.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
