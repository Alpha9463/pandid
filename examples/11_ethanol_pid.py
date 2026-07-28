"""
Example 11: Ethanol Purification A300 — the P&ID of example 10's unit

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
- the field devices are drawn: each control valve as the station it is, with
  hand isolation valves either side of it and the reduction to its body
  between, a **bypass** over the top on its own normally closed valve and a
  **drain** off the underside either side of the control valve, the flow
  elements sitting *in* the line with their transmitters hung off them, block
  valves on the cooling-water tie-ins, a check valve on the bottoms and the
  solenoid trip on the feed;
- five control loops close on a real final control element, each drawn
  measurement -> controller -> actuator, with the tower-top temperature
  cascaded onto the reflux flow controller. Every controller and alarm is a
  shared-display balloon, a circle in a square, because they are functions of
  the DCS and not devices standing in the field;
- the interlock square repeats. ``Instrument(variant="sis")`` is the one
  symbol allowed to carry its tag more than once, because a trip is a single
  logic function drawn everywhere it acts.

Three kinds of item on this sheet are drawn more than once, and each says so in
its own way rather than being renamed apart:

- a **utility header** (``Feed("CWSH", header=True)``) is one service tapped
  wherever the sheet wants it, so both cooling-water tie-ins carry ``CWSH`` and
  both returns ``CWRH``, which is what the legend entry explaining them names;
- a **tee** carries no tag at all — it is bulk piping bought by the line — so
  the branches around the valve stations put nothing on the drawing and nothing
  in the equipment list;
- and the **interlock square**, as above.

Every in-line device is placed with :func:`on_run`, which asks the symbol
where its own nozzle sits rather than repeating a measured offset, so the runs
stay straight whatever size the valve artwork is drawn at.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Annotation, Revision, TitleBlock, legend, notes
from pandid.geometry import Frame, normalize_mirror
from pandid.portgeom import port_point, resolve_size

# Spacing along a run, edge of one device to edge of the next. The router needs
# about 25 units to leave a nozzle before it may turn, so a facing pair closer
# than that sends the run doubling back on itself; 30 is the tightest that stays
# clean at every station here. The issued sheet is denser than this.
GAP = 30.0
# How far a bypass stands off the run it goes round, and how far a drain drops
# below it. Both are measured from the run's centreline.
BYPASS_RISE = 45.0
DRAIN_DROP = 36.0


def nozzle_at(unit, port, mirrored: "bool | str" = False, orientation: float = 0):
    """Where ``port`` sits relative to the unit's own top-left corner.

    Asked of the symbol the unit is drawn with rather than written down as a
    pair of numbers. A hand-tuned offset is only true of the artwork it was
    measured off, so a run pinned against one drifts off its nozzles the moment
    that artwork is drawn at another size; asked, it cannot.
    """
    mirror_x, mirror_y = normalize_mirror(mirrored)
    width, height = resolve_size(unit)
    probe = Frame(x=0.0, y=0.0, w=width, h=height,
                  mirrored=mirror_x, mirror_y=mirror_y, orientation=orientation)
    return port_point(unit, probe, port)


def on_run(unit, x, run_y, port="inlet", mirrored: "bool | str" = False):
    """Pin an in-line device at ``x`` with ``port`` on its run's centreline."""
    return unit.pin(x=x, y=run_y - nozzle_at(unit, port, mirrored)[1],
                    mirrored=mirrored)


def lay_out(items, x, run_y, gap=GAP):
    """Pin a station's devices left to right, each one ``gap`` clear of the last.

    ``items`` is (unit, mirrored) in the order they are *drawn*, which is not
    the order they are piped: a station fed from the right is mirrored end to
    end and still lays out left to right. Widths come from the symbols, so
    inserting a tee between two valves moves everything downstream of it by the
    tee's own width and no measurement has to be revisited.
    """
    for unit, mirrored in items:
        on_run(unit, x, run_y, mirrored=mirrored)
        x += resolve_size(unit)[0] + gap
    return x - gap


def branch_x(tee, mirrored: "bool | str" = False):
    """Where a laid-out tee's branch leaves it."""
    return tee.pin_.x + nozzle_at(tee, "branch", mirrored=mirrored)[0]


def on_drain(valve, x, run_y):
    """Stand a drain valve in the vertical leg hanging under ``x``.

    The leg ends at the valve: a drain runs to a funnel on the floor, which is
    not on this sheet.
    """
    valve.pin(orientation=90)
    return valve.pin(x=x - nozzle_at(valve, "inlet", orientation=90)[0],
                     y=run_y + DRAIN_DROP)


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

    # Valve stations. Each control valve is drawn as the station it is: hand
    # isolation valves either side so the valve can be changed out under a line
    # break, the reduction down to its own smaller body between the upstream
    # isolation and the valve, a bypass over the top so the unit keeps running
    # while it is out, and a drain either side of it so the isolated section can
    # be emptied first. There is no expander in the package (issue #96), so each
    # station carries its upstream reducer and the issued sheet's matching
    # expander is left off.
    xv = fs.add(units.Valve("XV-301", variant="solenoid",
                            description="Feed Trip Valve"))
    meter = fs.add(units.Fitting("FE-313", variant="rotameter",
                                 description="Feed Flow Element"))

    hv301a = fs.add(units.Valve("HV-301A", description="Overhead Isolation Valve"))
    rd301 = fs.add(units.Reducer("RD-301", description="CV-301-1 Inlet Reducer"))
    cv3011 = fs.add(units.Valve("CV-301-1", variant="control",
                                description="Overhead Pressure Control Valve"))
    hv301b = fs.add(units.Valve("HV-301B", description="Overhead Isolation Valve"))
    hv301c = fs.add(units.Valve("HV-301C", normal_position="closed",
                                description="CV-301-1 Bypass Valve"))
    hv301d = fs.add(units.Valve("HV-301D", normal_position="closed",
                                description="CV-301-1 Upstream Drain Valve"))
    hv301e = fs.add(units.Valve("HV-301E", normal_position="closed",
                                description="CV-301-1 Downstream Drain Valve"))

    hv303a = fs.add(units.Valve("HV-303A", description="Reflux Isolation Valve"))
    rd303 = fs.add(units.Reducer("RD-303", description="CV-303 Inlet Reducer"))
    cv303 = fs.add(units.Valve("CV-303", variant="control",
                               description="Reflux Control Valve"))
    hv303b = fs.add(units.Valve("HV-303B", description="Reflux Isolation Valve"))
    hv303c = fs.add(units.Valve("HV-303C", normal_position="closed",
                                description="CV-303 Bypass Valve"))
    hv303d = fs.add(units.Valve("HV-303D", normal_position="closed",
                                description="CV-303 Upstream Drain Valve"))
    hv303e = fs.add(units.Valve("HV-303E", normal_position="closed",
                                description="CV-303 Downstream Drain Valve"))
    # The reflux flow element sits in the run itself: the balloon beside it
    # reads the element, it is not the element. Its tag is written under the run
    # because its transmitter stands over it, and an impulse line drawn up
    # through the tag would be knocked out by the tag's own halo.
    fe303 = fs.add(units.Fitting("FE-303", variant="venturi", label_pos="bottom",
                                 description="Reflux Flow Element"))

    hv305a = fs.add(units.Valve("HV-305A", description="Distillate Isolation Valve"))
    rd305 = fs.add(units.Reducer("RD-305", description="CV-305 Inlet Reducer"))
    cv305 = fs.add(units.Valve("CV-305", variant="control",
                               description="Distillate Control Valve"))
    hv305b = fs.add(units.Valve("HV-305B", description="Distillate Isolation Valve"))
    hv305c = fs.add(units.Valve("HV-305C", normal_position="closed",
                                description="CV-305 Bypass Valve"))
    hv305d = fs.add(units.Valve("HV-305D", normal_position="closed",
                                description="CV-305 Upstream Drain Valve"))
    hv305e = fs.add(units.Valve("HV-305E", normal_position="closed",
                                description="CV-305 Downstream Drain Valve"))

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
    hv308c = fs.add(units.Valve("HV-308C", normal_position="closed",
                                description="CV-308 Bypass Valve"))
    hv308d = fs.add(units.Valve("HV-308D", normal_position="closed",
                                description="CV-308 Upstream Drain Valve"))
    hv308e = fs.add(units.Valve("HV-308E", normal_position="closed",
                                description="CV-308 Downstream Drain Valve"))

    # The junctions. A tee is drawn as nothing at all — three lines meeting,
    # the run passing straight through — and carries no tag, so none of these
    # puts a symbol on the sheet or a row in the equipment list. Four of them
    # make a station's bypass and its two drains; the fifth is where the drum's
    # single liquid draw parts into reflux and distillate.
    t301_bya, t301_dra, t301_drb, t301_byb = (
        fs.add(units.Tee()), fs.add(units.Tee()),
        fs.add(units.Tee()), fs.add(units.Tee(branch="inlet")))
    t303_bya, t303_dra, t303_drb, t303_byb = (
        fs.add(units.Tee()), fs.add(units.Tee()),
        fs.add(units.Tee()), fs.add(units.Tee(branch="inlet")))
    t305_bya, t305_dra, t305_drb, t305_byb = (
        fs.add(units.Tee()), fs.add(units.Tee()),
        fs.add(units.Tee()), fs.add(units.Tee(branch="inlet")))
    t308_bya, t308_dra, t308_drb, t308_byb = (
        fs.add(units.Tee()), fs.add(units.Tee()),
        fs.add(units.Tee()), fs.add(units.Tee(branch="inlet")))
    # The size steps down 100 -> 40 across it, so the run's number breaks here.
    t_draw = fs.add(units.Tee())
    t_draw.significant = True

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
    # control valve throttles into the condenser, so its station stands at the
    # far end of the run rather than over the tower. A bypass tee takes its
    # branch north, so it is flipped top-to-bottom; a drain tee takes its branch
    # south and is not.
    overhead_y = 130.0
    cond_x, cond_y = 1010.0, 210.0
    cond.pin(x=cond_x, y=cond_y)
    cond_shell_in_x = cond_x + nozzle_at(cond, "shell_in")[0]
    cw_cond_y = cond_y + nozzle_at(cond, "tube_in")[1]
    lay_out([(t301_bya, "y"), (hv301a, False), (t301_dra, False), (rd301, False),
             (cv3011, False), (t301_drb, False), (hv301b, False), (t301_byb, "y")],
            720, overhead_y)
    cv3011_top = overhead_y - nozzle_at(cv3011, "inlet")[1]
    # The bypass valve stands over the station's reducer. The issued sheet puts
    # it over the control valve, which is where the controller's output crosses
    # the leg on its way down to the actuator, and a valve body drawn under that
    # crossing is a valve body with a signal line through it. Each station moves
    # its own valve along the leg to wherever nothing else is already crossing.
    on_run(hv301c, rd301.pin_.x, overhead_y - BYPASS_RISE)
    on_drain(hv301d, branch_x(t301_dra), overhead_y)
    on_drain(hv301e, branch_x(t301_drb), overhead_y)
    on_run(cws_cond, 150, cw_cond_y, port="outlet")
    on_run(hv311, 320, cw_cond_y)
    on_run(cwr_cond, 1540, cw_cond_y, port="inlet")

    # Drum hung so its top inlet sits under the condenser's drain, which makes
    # that run a straight drop. The inlet is authored on more than one face and
    # the top one is named here, so the nozzle the drum is positioned by is the
    # nozzle the condensate arrives at.
    drum.nozzle("inlet", "N")
    drum_x = cond_x + nozzle_at(cond, "shell_out")[0] - nozzle_at(drum, "inlet")[0]
    drum.pin(x=drum_x, y=280)
    drum_draw_x = drum_x + nozzle_at(drum, "outlet")[0]

    # Reflux station, running right to left, so it is mirrored end to end and
    # every device takes flow on its east face. The flow element is last, next
    # to the tower, where it reads the metered stream and not the leakage past
    # an isolation valve; it stands outside the bypass, so it reads the reflux
    # whether the station is in service or bypassed.
    reflux_run_y = 440.0
    lay_out([(fe303, True), (t303_byb, "xy"), (hv303b, True), (t303_drb, True),
             (cv303, True), (rd303, True), (t303_dra, True), (hv303a, True),
             (t303_bya, "xy")],
            670, reflux_run_y)
    on_run(hv303c, rd303.pin_.x, reflux_run_y - BYPASS_RISE, mirrored=True)
    on_drain(hv303d, branch_x(t303_dra, True), reflux_run_y)
    on_drain(hv303e, branch_x(t303_drb, True), reflux_run_y)

    # The drum's draw parts into reflux and distillate below the vessel. That
    # junction is a tee and not a piece of plant: it carries no tag on the
    # issued sheet and nothing in its equipment list. The run drops on past it
    # to the distillate station and the branch leaves west onto the reflux run,
    # which is the way the issued sheet draws it.
    t_draw.pin(orientation=90)
    t_draw.pin(x=drum_draw_x - nozzle_at(t_draw, "inlet", orientation=90)[0],
               y=reflux_run_y - nozzle_at(t_draw, "branch", orientation=90)[1])

    # Distillate station, left to right, and well below the reflux run: the two
    # legs of the same tee read as two lines rather than as one.
    dist_y = 510.0
    lay_out([(t305_bya, "y"), (hv305a, False), (t305_dra, False), (rd305, False),
             (cv305, False), (t305_drb, False), (hv305b, False), (t305_byb, "y")],
            1147, dist_y)
    on_run(hv305c, rd305.pin_.x, dist_y - BYPASS_RISE)
    on_drain(hv305d, branch_x(t305_dra), dist_y)
    on_drain(hv305e, branch_x(t305_drb), dist_y)
    on_run(ae_prod, 1540, dist_y, port="inlet")

    # Reboiler off the tower sump; steam spine on its tube inlet, which is the
    # channel head the heating medium enters.
    reb.pin(x=700, y=580)
    steam_y = 580 + nozzle_at(reb, "tube_in")[1]
    on_run(steam, 150, steam_y, port="outlet")
    lay_out([(t308_bya, "y"), (hv308a, False), (t308_dra, False), (rd308, False),
             (cv308, False), (t308_drb, False), (hv308b, False), (t308_byb, "y")],
            260, steam_y)
    # TIC-307's balloons stand over this station's reducer and its output crosses
    # the leg on the way down, so this bypass valve moves along to the far end.
    on_run(hv308c, hv308b.pin_.x, steam_y - BYPASS_RISE)
    on_drain(hv308d, branch_x(t308_dra), steam_y)
    on_drain(hv308e, branch_x(t308_drb), steam_y)
    on_run(condensate, 1540, 580 + nozzle_at(reb, "tube_out")[1], port="inlet")

    # Bottoms over the weir, cooled and sent off the sheet. The bottoms valve
    # is flipped so its operator faces the controller standing below it.
    bottoms_y = 660.0
    on_run(cv306, 900, bottoms_y, mirrored="y")
    on_run(nrv306, 1000, bottoms_y)
    cooler.pin(x=1100, y=720)
    cooler_shell_in_x = 1100 + nozzle_at(cooler, "shell_in")[0]
    cooler_shell_out_x = 1100 + nozzle_at(cooler, "shell_out")[0]
    cw_cool_y = 720 + nozzle_at(cooler, "tube_in")[1]
    cooled_y = 805.0
    on_run(cws_cool, 150, cw_cool_y, port="outlet")
    on_run(hv315, 320, cw_cool_y)
    on_run(cwr_cool, 1540, cw_cool_y, port="inlet")
    on_run(bottoms_prod, 1540, cooled_y, port="inlet")

    # --- Process lines ---------------------------------------------------
    # A station is one line, and that goes for what hangs off it. The bypass is
    # the same service, size and spec as the run it goes round, and a drain small
    # enough to be governed by the piping class is part of the line it drains
    # rather than a line of its own: the size field of a line number is the
    # line's size and not the size of every branch on it. So all three branches
    # take the station's number, which is why the issued sheet writes that number
    # once and writes nothing at all against a bypass or a drain.
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
    vapour = fs.connect(col.distillate, t301_bya.inlet, service="AE", sequence=302,
                        size=300, spec="80-SS").via([(col_axis, overhead_y)])
    fs.connect(t301_bya.outlet, hv301a.inlet)
    fs.connect(hv301a.outlet, t301_dra.inlet)
    fs.connect(t301_dra.outlet, rd301.inlet)
    fs.connect(rd301.outlet, cv3011.inlet)
    fs.connect(cv3011.outlet, t301_drb.inlet)
    fs.connect(t301_drb.outlet, hv301b.inlet)
    fs.connect(hv301b.outlet, t301_byb.inlet)
    fs.connect(t301_byb.outlet, cond.shell_in).via([(cond_shell_in_x, overhead_y)])
    fs.connect(t301_bya.branch, hv301c.inlet, service="AE", sequence=302, size=300,
               spec="80-SS")
    fs.connect(hv301c.outlet, t301_byb.branch)
    fs.connect(t301_dra.branch, hv301d.inlet, service="AE", sequence=302, size=300,
               spec="80-SS")
    fs.connect(t301_drb.branch, hv301e.inlet, service="AE", sequence=302, size=300,
               spec="80-SS")

    fs.connect(cond.shell_out, drum.inlet, service="AE", sequence=304, size=150,
               spec="80-SS")
    fs.connect(cws_cond.outlet, hv311.inlet, service="CWS", sequence=311, size=150,
               spec="150-CS")
    fs.connect(hv311.outlet, cond.tube_in)
    cw_return = fs.connect(cond.tube_out, cwr_cond.inlet, service="CWR",
                           sequence=312, size=150,
                           spec="150-CS").via([(1300, cw_cond_y)])

    fs.connect(drum.outlet, t_draw.inlet, service="AE", sequence=309, size=100,
               spec="80-SS")
    # The branch takes the reflux and the run carries on down to the distillate,
    # so the two lines leave the tee without crossing.
    fs.connect(t_draw.branch, t303_bya.inlet, service="AE", sequence=303, size=80,
               spec="80-SS")
    fs.connect(t303_bya.outlet, hv303a.inlet)
    fs.connect(hv303a.outlet, t303_dra.inlet)
    fs.connect(t303_dra.outlet, rd303.inlet)
    fs.connect(rd303.outlet, cv303.inlet)
    fs.connect(cv303.outlet, t303_drb.inlet)
    fs.connect(t303_drb.outlet, hv303b.inlet)
    fs.connect(hv303b.outlet, t303_byb.inlet)
    fs.connect(t303_byb.outlet, fe303.inlet)
    fs.connect(fe303.outlet, col.reflux_in, tear_hint=True)
    fs.connect(t303_bya.branch, hv303c.inlet, service="AE", sequence=303, size=80,
               spec="80-SS")
    fs.connect(hv303c.outlet, t303_byb.branch)
    fs.connect(t303_dra.branch, hv303d.inlet, service="AE", sequence=303, size=80,
               spec="80-SS")
    fs.connect(t303_drb.branch, hv303e.inlet, service="AE", sequence=303, size=80,
               spec="80-SS")

    fs.connect(t_draw.outlet, t305_bya.inlet, service="AE", sequence=305, size=40,
               spec="80-SS")
    fs.connect(t305_bya.outlet, hv305a.inlet)
    fs.connect(hv305a.outlet, t305_dra.inlet)
    fs.connect(t305_dra.outlet, rd305.inlet)
    fs.connect(rd305.outlet, cv305.inlet)
    fs.connect(cv305.outlet, t305_drb.inlet)
    fs.connect(t305_drb.outlet, hv305b.inlet)
    fs.connect(hv305b.outlet, t305_byb.inlet)
    fs.connect(t305_byb.outlet, ae_prod.inlet)
    fs.connect(t305_bya.branch, hv305c.inlet, service="AE", sequence=305, size=40,
               spec="80-SS")
    fs.connect(hv305c.outlet, t305_byb.branch)
    fs.connect(t305_dra.branch, hv305d.inlet, service="AE", sequence=305, size=40,
               spec="80-SS")
    fs.connect(t305_drb.branch, hv305e.inlet, service="AE", sequence=305, size=40,
               spec="80-SS")

    sump_x = 700 + nozzle_at(reb, "shell_in")[0]
    boilup_x = 700 + nozzle_at(reb, "shell_out")[0]
    sump = fs.connect(col.bottoms, reb.shell_in, service="FB", sequence=307,
                      size=250, spec="160-SS").via([(col_axis, 655), (sump_x, 655)])
    boilup = fs.connect(reb.shell_out, col.boilup_in, service="FB", sequence=310,
                        size=300, spec="160-SS",
                        tear_hint=True).via([(boilup_x, 535), (595, 535), (595, boilup_y)])
    fs.connect(steam.outlet, t308_bya.inlet, service="HPS", sequence=308, size=100,
               spec="300-CS")
    fs.connect(t308_bya.outlet, hv308a.inlet)
    fs.connect(hv308a.outlet, t308_dra.inlet)
    fs.connect(t308_dra.outlet, rd308.inlet)
    fs.connect(rd308.outlet, cv308.inlet)
    fs.connect(cv308.outlet, t308_drb.inlet)
    fs.connect(t308_drb.outlet, hv308b.inlet)
    fs.connect(hv308b.outlet, t308_byb.inlet)
    fs.connect(t308_byb.outlet, reb.tube_in)
    fs.connect(t308_bya.branch, hv308c.inlet, service="HPS", sequence=308, size=100,
               spec="300-CS")
    fs.connect(hv308c.outlet, t308_byb.branch)
    fs.connect(t308_dra.branch, hv308d.inlet, service="HPS", sequence=308, size=100,
               spec="300-CS")
    fs.connect(t308_drb.branch, hv308e.inlet, service="HPS", sequence=308, size=100,
               spec="300-CS")
    fs.connect(reb.tube_out, condensate.inlet, service="HPR", sequence=317, size=80,
               spec="300-CS")

    fs.connect(reb.bottoms, cv306.inlet, service="FB", sequence=306, size=100,
               spec="160-SS")
    fs.connect(cv306.outlet, nrv306.inlet)
    fs.connect(nrv306.outlet, cooler.shell_in).via([(cooler_shell_in_x, bottoms_y)])
    fs.connect(cooler.shell_out, bottoms_prod.inlet, service="FB", sequence=314,
               size=100, spec="160-SS").via([(cooler_shell_out_x, cooled_y)])
    fs.connect(cws_cool.outlet, hv315.inlet, service="CWS", sequence=315, size=100,
               spec="150-CS")
    fs.connect(hv315.outlet, cooler.tube_in)
    fs.connect(cooler.tube_out, cwr_cool.inlet, service="CWR", sequence=316, size=100,
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
    fs.connect(fic303.sig_out, cv303.actuator, kind="pneumatic")

    # --- Loop 304: reflux drum level on the distillate valve --------------
    lt304 = fs.add_instrument("LT", 304, on=drum, at="E", offset=60)
    lic304 = fs.add_instrument("LIC", 304, on=lt304, at="E", offset=66, variant="shared")
    lic304.nozzle("sig_out", "S")
    lah = fs.add_instrument("LAH", 304, on=lic304, at="E", offset=46)
    lal = fs.add_instrument("LAL", 304, on=lah, at="E", offset=46)
    fs.add_instrument("I", 1, on=lal, at="E", offset=40, variant="sis")
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
    # A darkened valve body is not an ISA-5.1 symbol — the standard hands manual
    # valve depiction to the piping group — so clauses 2.8.1(b)(1) and 5.2.5 of
    # ISA-5.1 make declaring it here mandatory rather than optional.
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
