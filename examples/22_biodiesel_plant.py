"""
Example 22: Biodiesel Production A400, a batch transesterification P&ID

Canola oil and methanol, alkali-catalysed, one batch at a time. KOH is
dissolved into fresh (and recovered) methanol in MT-401 to make
potassium methoxide, which is charged into R-401 alongside the oil.
R-401 is a jacketed, agitated stirred tank -- exactly the ISO item 1.27
X8006 body example 17's continuous reactor is drawn from, batch or not,
because ISO 10628-2 has no separate reactor symbol and no separate
batch/continuous distinction either. Held at temperature and agitated
for the reaction time, the batch is dumped to S-401, a settling vessel
that splits by density alone once agitation stops: crude ester rises,
crude glycerol falls.

The crude ester still carries the methanol excess the reaction needs to
run to completion, so it is stripped in C-401 before anything else is
done to it -- unstripped, that methanol would flash in the wash water
and would end up costed as an effluent rather than recovered as a
feedstock. The stripped ester is washed once in M-401/S-402 to pull the
soap and residual catalyst into the water phase, then dried under
vacuum in S-403 before it is fit to store as fuel. The crude glycerol is
neutralised in N-401 and stored as-is: a saleable by-product at this
scale, not a refined one.

**What this sheet is not.** A merchant biodiesel plant recovers
methanol from *both* phases and refines its glycerol to pharma grade in
a plant of its own; this one strips the ester phase only and stores the
glycerol crude, which is what a single-train batch skid at this scale
actually ships. Neither omission is drawn as anything -- there is no
second stripper half-finished on the paper -- it is simply not here,
exactly as example 21 leaves lime burning and causticisation off the
Bayer refinery. A real design also washes more than once; this sheet
draws the one stage that makes the point.

**S-401's gravity settler is item 8.3 X8031**, the same composed
separating vessel example 21's red mud thickener is drawn from --
``characteristic="gravity"`` is the mark, not a shape ISO gives a
liquid-liquid decanter of its own. S-402 draws the wash separation the
same way for the same reason.

Eight loop numbers and a trip. Two are cascades -- reactor temperature
onto the jacket hot-water flow, column top temperature onto the reflux
-- and the other four close the inventory everywhere the process holds
one: the settler interface, the reflux drum, the reboiler sump, the wash
separator. The trip shuts the jacket on a runaway the temperature
controller cannot be trusted to catch once it is the thing that has
failed.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Column,
    Ejector,
    Feed,
    Fitting,
    Flowsheet,
    Funnel,
    HeatExchanger,
    KettleReboiler,
    Mixer,
    Product,
    Pump,
    Reactor,
    Separator,
    Tank,
    Tee,
    Valve,
    Vent,
    Vessel,
)
from pandid.document import Revision, TitleBlock, equipment_list, legend, notes
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet("Biodiesel Production A400", line_number_start=401)

    # --- Control loops ------------------------------------------------
    # Each number is declared once here instead of typed on every balloon
    # that carries it. Members still type their own functional letters
    # and the handle checks the first of them, so an LIC put on a
    # temperature loop raises at the line that wrote it.
    temp401 = fs.add_loop("T", 401)     # reactor batch temperature, a cascade master
    flow402 = fs.add_loop("F", 402)     # jacket hot-water flow, its slave
    level403 = fs.add_loop("L", 403)    # settler interface level
    temp404 = fs.add_loop("T", 404)     # column top temperature, a cascade master
    flow405 = fs.add_loop("F", 405)     # reflux flow, its slave
    level406 = fs.add_loop("L", 406)    # reflux drum level, onto the methanol draw
    level407 = fs.add_loop("L", 407)    # reboiler level, onto the ester draw
    level408 = fs.add_loop("L", 408)    # wash separator interface level

    # --- Boundary conditions ----------------------------------------------
    # Declared ahead of the equipment, methanol ahead of everything else
    # here: the layout engine's cycle-breaking walks the sheet from
    # whichever unit with no upstream it meets first, and the methanol
    # recycle (CV-406 back to this feed) is only found as the loop it
    # actually is if that walk starts here. Left for the engine to
    # discover from the oil or the KOH charge instead, it finds the loop
    # from the far side and calls MT-401's own charge line the recycle,
    # which is what drags TK-402 and P-402 to the far right of the case.
    meoh_feed = fs.add(Feed("Methanol", reference="PFD-002"))
    oil_feed = fs.add(Feed("Canola Oil", reference="PFD-001"))
    acid_feed = fs.add(Feed("Phosphoric Acid", reference="PFD-004"))
    ww_feed = fs.add(Feed("Wash Water", reference="PFD-005"))
    hw_supply = fs.add(Feed("HWSH", header=True))
    steam_reb = fs.add(Feed("LPSSH", header=True))
    steam_ej = fs.add(Feed("LPSSH", header=True))
    steam_condensate = fs.add(Product("LPSRH", header=True))
    cws = fs.add(Feed("CWSH", header=True))
    cwr = fs.add(Product("CWRH", header=True))
    reactor_vent = fs.add(Product("Reactor Vent to Vapour Recovery",
                                  reference="P&ID-701"))
    wastewater = fs.add(Product("Wash Water to Wastewater Treatment",
                                reference="P&ID-702"))
    vacuum_vent = fs.add(Product("Vacuum System Discharge", reference="P&ID-703"))
    biodiesel_prod = fs.add(Product("Biodiesel (FAME) to Loading",
                                    reference="P&ID-801"))
    glycerol_prod = fs.add(Product("Crude Glycerol to Loading",
                                   reference="P&ID-802"))

    # --- Equipment ------------------------------------------------------
    # Oil receipt and storage.
    tk401 = fs.add(Tank("TK-401", description="Canola Oil Storage Tank"))
    p401 = fs.add(Pump("P-401", description="Oil Charge Pump"))

    # Methanol storage and methoxide preparation. MT-401 is not jacketed:
    # dissolving KOH in methanol is exothermic enough on its own and runs
    # at ambient temperature, which is also why it draws the general
    # agitator (28.1) rather than the turbine R-401 needs to keep a
    # two-phase oil charge in suspension.
    tk402 = fs.add(Tank("TK-402", description="Methanol Storage Tank"))
    p402 = fs.add(Pump("P-402", description="Methanol Charge Pump"))
    bv401 = fs.add(Vent("BV-401", variant="breather",
                        description="Methanol Tank Conservation Vent"))
    mt401 = fs.add(Reactor("MT-401", n_feeds=2, width=71.04, height=151,
                           description="Methoxide Mixing Tank"))
    fn401 = fs.add(Funnel("FN-401", description="KOH Catalyst Charging Funnel"))

    # The reaction and the phase split. agitator="turbine" and not the
    # default "agitator": a two-phase oil/methoxide charge needs the
    # higher shear a turbine gives to stay dispersed, where MT-401 is
    # mixing one liquid phase into another and the general stirrer is
    # enough.
    r401 = fs.add(Reactor("R-401", variant="jacketed", agitator="turbine",
                          n_feeds=2, width=59.45, height=141,
                          description="Batch Transesterification Reactor"))
    p403 = fs.add(Pump("P-403", description="Reactor Discharge Pump"))
    s401 = fs.add(Separator("S-401", characteristic="gravity",
                            description="Glycerol Gravity Settler"))

    # Methanol recovery, stripped from the ester phase. internals="packing"
    # and trays=2 draws the same two-bed shell example 18's converter and
    # docs/api.md's absorber example are built from -- a stripping column
    # is this shell furnished with a bed, not a symbol of its own.
    c401 = fs.add(Column("C-401", internals="packing", trays=2,
                         description="Methanol Stripping Column"))
    e401 = fs.add(HeatExchanger("E-401", variant="straight_tubes",
                                description="Methanol Overhead Condenser"))
    d401 = fs.add(Vessel("D-401", variant="horizontal",
                         description="Methanol Reflux Drum"))
    e402 = fs.add(KettleReboiler("E-402", description="Ester Reboiler"))

    # Washing, vacuum drying and product storage.
    m401 = fs.add(Mixer("M-401", n_inlets=2, description="Wash Water Mixer"))
    s402 = fs.add(Separator("S-402", characteristic="gravity",
                            description="Wash Water Separator"))
    s403 = fs.add(Separator("S-403", description="Vacuum Flash Dryer"))
    ej401 = fs.add(Ejector("EJ-401", description="Dryer Vacuum Ejector"))
    p404 = fs.add(Pump("P-404", description="Biodiesel Loading Pump"))
    tk403 = fs.add(Tank("TK-403", description="Biodiesel Product Storage Tank"))

    # Glycerol neutralisation and by-product storage.
    n401 = fs.add(Reactor("N-401", n_feeds=2, width=71.04, height=151,
                          description="Glycerol Neutralisation Tank"))
    p405 = fs.add(Pump("P-405", description="Glycerol Transfer Pump"))
    tk404 = fs.add(Tank("TK-404", description="Crude Glycerol Storage Tank"))

    # --- In-line devices -------------------------------------------------
    hv402 = fs.add(Valve("HV-402", description="Jacket Hot Water Block Valve"))
    fe402 = fs.add(Fitting(flow402.element("FE"), variant="venturi",
                           description="Jacket Hot Water Flow Element"))
    cv402 = fs.add(Valve(flow402.tag("CV"), variant="control", fail="closed",
                         description="Jacket Hot Water Control Valve"))
    cv403 = fs.add(Valve(level403.tag("CV"), variant="control",
                         description="Glycerol Draw Control Valve"))
    hv403 = fs.add(Valve("HV-403", description="Condenser Cooling Water Block Valve"))
    fe405 = fs.add(Fitting(flow405.element("FE"), variant="venturi",
                           description="Reflux Flow Element"))
    cv405 = fs.add(Valve(flow405.tag("CV"), variant="control",
                         description="Reflux Control Valve"))
    t_meoh_in = fs.add(Tee(branch="inlet"))      # recovered methanol rejoins the fresh feed
    t_reflux = fs.add(Tee())                     # the reflux splits off the drum draw
    cv406 = fs.add(Valve(level406.tag("CV"), variant="control",
                         description="Recovered Methanol Draw Control Valve"))
    hv404 = fs.add(Valve("HV-404", description="Reboiler Steam Block Valve"))
    cv407 = fs.add(Valve(level407.tag("CV"), variant="control",
                         description="Stripped Ester Draw Control Valve"))
    cv408 = fs.add(Valve(level408.tag("CV"), variant="control",
                         description="Wash Water Draw Control Valve"))

    # --- Process lines ------------------------------------------------
    # Oil receipt and charge.
    fs.connect(oil_feed.outlet, tk401.inlet, service="CO", sequence=401,
               size=150, schedule=40, spec="CS")
    fs.connect(tk401.outlet, p401.suction, service="CO", sequence=402,
               size=100, schedule=40, spec="CS")
    fs.connect(p401.discharge, r401.feeds[0], service="CO", sequence=403,
               size=80, schedule=40, spec="CS")
    # Left to the engine, P-401's discharge and R-401's feed_1 nozzle
    # sit 34.6px apart in elevation -- too close to read as a change of
    # level, so the line steps sideways into R-401 and back out rather
    # than rising cleanly. Pinned a clean step below the nozzle instead
    # of level with it: level puts the line through TT-409, R-401's own
    # west-side tap.
    p401.pin(port="discharge", y=2150.0)

    # Methanol receipt, storage and the methoxide charge. The recovered
    # methanol recycle rejoins the fresh feed at t_meoh_in, ahead of the
    # tank's one inlet nozzle.
    fs.connect(meoh_feed.outlet, t_meoh_in.inlet, service="MEOH", sequence=404,
               size=80, schedule=40, spec="SS")
    fs.connect(t_meoh_in.outlet, tk402.inlet)
    fs.connect(tk402.vent, bv401.inlet)
    # Left to the engine, this line's own jog right (on its way down to
    # P-402) lands 6px under the canola oil charge line into TK-401,
    # the two then running side by side for 135px before this one turns
    # down -- close enough to read as one doubled line rather than two
    # streams. Routed clear of it instead: down well past that height
    # before turning, so the two lines simply cross once, the way BS
    # ISO 15519-1 draws a hop.
    fs.connect(tk402.outlet, p402.suction, service="MEOH", sequence=405,
               size=80, schedule=40, spec="SS"
               ).via([(474.0, 2200.0), (609.0, 2200.0), (609.0, 2283.0)])
    fs.connect(p402.discharge, mt401.feeds[0], service="MEOH", sequence=406,
               size=50, schedule=40, spec="SS")
    fs.connect(fn401.outlet, mt401.feeds[1], service="KOH", sequence=407,
               size=25, schedule=40, spec="SS")
    fs.connect(mt401.outlet, r401.feeds[1], service="MX", sequence=408,
               size=50, schedule=40, spec="SS")

    # The batch reaction and the phase split.
    fs.connect(r401.vent, reactor_vent.inlet, service="RV", sequence=409,
               size=50, schedule=40, spec="SS")
    fs.connect(r401.outlet, p403.suction, service="RM", sequence=410,
               size=80, schedule=40, spec="SS")
    fs.connect(p403.discharge, s401.feed, service="RM", sequence=411,
               size=80, schedule=40, spec="SS")

    # The settler's two draws: the light phase to methanol stripping, the
    # heavy phase to neutralisation.
    fs.connect(s401.port("overflow"), c401.feed, service="CE", sequence=412,
               size=80, schedule=40, spec="SS")
    fs.connect(s401.port("underflow"), cv403.inlet, service="CG", sequence=413,
               size=50, schedule=40, spec="SS")
    fs.connect(cv403.outlet, n401.feeds[0])
    fs.connect(acid_feed.outlet, n401.feeds[1], service="PA", sequence=414,
               size=25, schedule=40, spec="SS")

    # Methanol stripping: the overhead condenses, splits to reflux and
    # recovered methanol, and the sump reboils and draws stripped ester.
    #
    # C-401's two heat exchangers rank in the same column of the sheet
    # and neither is a Block, so neither carries the north/south face a
    # stacked constraint reads (see pandid.layout.stacking) -- the
    # engine has nothing that says a condenser belongs over the vapour
    # draw and a reboiler under the liquid one, which is why the two
    # came out swapped. Laid out by hand instead, the way
    # examples/06_column_reflux.py and examples/11_ethanol_pid.py draw
    # every column/condenser/reboiler group in this corpus: each
    # exchanger pinned by its own nozzle, so no rescaling of the
    # artwork can leave a run off its port, and the vapour and sump
    # lines routed through an explicit waypoint rather than left to
    # find their own way past the column and each other.
    #
    # C-401 is left for the engine to place -- pinning it would pull its
    # own 200px height out of row 13's band, collapsing every row below
    # it by that much (see the E-401/E-402/D-401 pins just below for the
    # same effect at smaller scale). col_x/col_y instead just name where
    # the engine already stands it, so the numbers derived from them
    # hold without constraining the column itself.
    col_x, col_y = 1722.49, 1730.0
    col_axis = col_x + port_offset(c401, "distillate")[0]

    overhead_y = 1560.0  # the vapour header's height, clear above the column
    cond_x, cond_y = 1972.49, 1640.0
    e401.pin(x=cond_x, y=cond_y)                 # condenser, over C-401's vapour draw
    cond_shell_in_x = cond_x + port_offset(e401, "shell_in")[0]
    cw_cond_y = cond_y + port_offset(e401, "tube_in")[1]

    vapour = fs.connect(
        c401.distillate, e401.shell_in, service="MV", sequence=415,
        size=80, schedule=40, spec="SS",
    ).via([(col_axis, overhead_y), (cond_shell_in_x, overhead_y)])
    hv403.pin(port="inlet", x=1722.49, y=cw_cond_y)   # condenser cooling water, with E-401
    fs.connect(cws.outlet, hv403.inlet, service="CWS", sequence=417,
               size=80, schedule=40, spec="CS")
    fs.connect(hv403.outlet, e401.tube_in)
    cwr.pin(port="inlet", x=2372.49, y=cw_cond_y)
    fs.connect(e401.tube_out, cwr.inlet, service="CWR", sequence=418,
               size=80, schedule=40, spec="CS")

    # D-401's inlet is authored on three faces; naming the top one and
    # pinning off E-401's own drain makes the run a straight drop, no
    # waypoint needed.
    d401.nozzle("inlet", "N")
    drum_x = cond_x + port_offset(e401, "shell_out")[0] - port_offset(d401, "inlet")[0]
    d401.pin(x=drum_x, y=1790.0)                 # reflux drum, straight under the condenser
    fs.connect(e401.shell_out, d401.inlet, service="RCM", sequence=416,
               size=80, schedule=40, spec="SS")

    fs.connect(d401.outlet, t_reflux.inlet, service="RCM", sequence=419,
               size=50, schedule=40, spec="SS")
    fs.connect(t_reflux.branch, cv406.inlet, service="RCM", sequence=420,
               size=40, schedule=40, spec="SS")
    # Pinned rather than left to the engine's barycentre: unpinned, this
    # tee's only rank-ordering neighbour is D-401, now up beside the
    # condenser, and the coordinate pass's spine-straightening would
    # carry the tee up to match it -- and cv405, fe405 and the reflux
    # flow loop off it in turn -- into the wash and vacuum train's own
    # corner of the sheet. Held at the height this split kept before
    # D-401 moved.
    t_reflux.pin(y=2094.5)
    fs.connect(t_reflux.outlet, cv405.inlet, service="RCM", sequence=421,
               size=40, schedule=40, spec="SS")
    fs.connect(cv405.outlet, fe405.inlet)
    # Left to the engine, this recycle rises to C-401's own reflux tap
    # height as soon as it leaves FE-405, and travels the width of the
    # sheet at it -- straight through the gap E-401 and D-401 stand in,
    # which is where RCM-416's own line number then has nowhere to sit
    # without a leader that cuts this line. Routed clear instead: a
    # short step off FE-405's own column (the FIC-405 loop stacks
    # straight up off it), a rise through the gap that loop's own
    # instruments leave between FT-405 and FIC-405, and a run in above
    # the condenser and the drum, only dropping onto the tap in the
    # clear run beside the column.
    reflux_y = col_y + port_offset(c401, "reflux_in")[1]
    fs.connect(fe405.outlet, c401.reflux_in, draw_as_recycle=True
               ).via([(2870.0, 2100.5), (2870.0, 1920.0), (1850.0, 1920.0), (1850.0, reflux_y)])
    fs.connect(cv406.outlet, t_meoh_in.branch, draw_as_recycle=True)
    # Pinned clear of CV-405: both valves draw off T-reflux one hop
    # apart, and left to the engine they stack directly on top of each
    # other -- not just close, touching -- with nowhere for either
    # valve's own signal line to run.
    cv406.pin(port="inlet", x=2432.5, y=2318.0)

    reb_x, reb_y = 1972.49, 2060.0
    e402.pin(x=reb_x, y=reb_y)                   # reboiler, under C-401's liquid draw
    sump_x = reb_x + port_offset(e402, "shell_in")[0]
    boilup_x = reb_x + port_offset(e402, "shell_out")[0]
    boilup_y = col_y + port_offset(c401, "boilup_in")[1]
    steam_y = reb_y + port_offset(e402, "tube_in")[1]

    # shell_in is E-402's own underside, so the sump line is routed
    # under the reboiler's own floor and back up into it, the same
    # shape 06 and 11 draw their kettle's sump line in.
    fs.connect(c401.bottoms, e402.shell_in, service="CE", sequence=422,
               size=80, schedule=40, spec="SS"
               ).via([(col_axis, reb_y + 63.0), (sump_x, reb_y + 63.0)])
    # shell_out is the reboiler's own crown, so the boilup line rises
    # off it, crosses at a height clear of both nozzles, and drops back
    # onto C-401's own side tap -- three waypoints, not one, so this
    # line and the sump line above don't run on top of each other
    # between the two shells.
    fs.connect(e402.shell_out, c401.boilup_in, service="CE", sequence=423,
               size=80, schedule=40, spec="SS", draw_as_recycle=True
               ).via([(boilup_x, reb_y - 40.0), (1870.0, reb_y - 40.0), (1870.0, boilup_y)])
    hv404.pin(port="inlet", x=1722.49, y=steam_y)     # reboiler steam, with E-402
    fs.connect(steam_reb.outlet, hv404.inlet, service="LPS", sequence=424,
               size=50, schedule=40, spec="CS")
    fs.connect(hv404.outlet, e402.tube_in)
    condensate_y = reb_y + port_offset(e402, "tube_out")[1]
    steam_condensate.pin(port="inlet", x=2472.49, y=condensate_y)
    fs.connect(e402.tube_out, steam_condensate.inlet, service="LPC",
               sequence=425, size=50, schedule=40, spec="CS")
    # E-402's bottoms draw is its own underside, like shell_in above, so
    # CV-407 is pinned close under it -- left automatic it ranks against
    # a much later column and drifts far from the nozzle it drains,
    # reading as a valve on a line of its own rather than E-402's draw.
    cv407.pin(port="inlet", x=reb_x + port_offset(e402, "bottoms")[0], y=2180.0)
    fs.connect(e402.bottoms, cv407.inlet, service="SE", sequence=426,
               size=50, schedule=40, spec="SS")
    fs.connect(cv407.outlet, m401.in_1)

    # Washing, vacuum drying and the biodiesel draw.
    fs.connect(ww_feed.outlet, m401.in_2, service="WW", sequence=427,
               size=40, schedule=40, spec="CS")
    fs.connect(m401.outlet, s402.feed, service="WM", sequence=428,
               size=50, schedule=40, spec="SS")
    fs.connect(s402.port("overflow"), s403.feed, service="WE", sequence=429,
               size=50, schedule=40, spec="SS")
    fs.connect(s402.port("underflow"), cv408.inlet, service="SW", sequence=430,
               size=40, schedule=40, spec="CS")
    fs.connect(cv408.outlet, wastewater.inlet)
    fs.connect(s403.vapor, ej401.suction, service="WV", sequence=431,
               size=50, schedule=40, spec="CS")
    fs.connect(steam_ej.outlet, ej401.motive, service="LPS", sequence=432,
               size=25, schedule=40, spec="CS")
    fs.connect(ej401.discharge, vacuum_vent.inlet, service="WV", sequence=433,
               size=50, schedule=40, spec="CS")
    fs.connect(s403.liquid, p404.suction, service="BD", sequence=434,
               size=50, schedule=40, spec="SS")
    fs.connect(p404.discharge, tk403.inlet, service="BD", sequence=435,
               size=50, schedule=40, spec="SS")
    fs.connect(tk403.outlet, biodiesel_prod.inlet, service="BD", sequence=436,
               size=80, schedule=40, spec="SS")

    # Glycerol neutralisation and storage.
    fs.connect(n401.outlet, p405.suction, service="NG", sequence=437,
               size=50, schedule=40, spec="SS")
    fs.connect(p405.discharge, tk404.inlet, service="NG", sequence=438,
               size=50, schedule=40, spec="SS")
    fs.connect(tk404.outlet, glycerol_prod.inlet, service="CGP", sequence=439,
               size=80, schedule=40, spec="SS")

    # The jacket's hot water, feeding the temperature/flow cascade.
    fs.connect(hw_supply.outlet, hv402.inlet, service="HWS", sequence=440,
               size=50, schedule=40, spec="CS")
    fs.connect(hv402.outlet, fe402.inlet)
    fs.connect(fe402.outlet, cv402.inlet)
    fs.connect(cv402.outlet, r401.duty)

    # --- Loops 401/402: reactor temperature onto the jacket hot water ---
    # The measurement the sheet exists for. TIC-401 sets FIC-402's
    # setpoint rather than stroking a valve, which is what a cascade is:
    # the slave holds the water flow the master asks for, so a swing in
    # hot-water header pressure is corrected before the batch temperature
    # has moved at all.
    # at="W", not "E": the batch temperature this sheet exists to hold
    # reads better standing over the feed side of the reactor than
    # sharing the discharge side with the trip that backs it up.
    tt401 = fs.add_instrument("TT", temp401, sensing=r401, at="W", offset=70)
    tic401 = fs.add_instrument("TIC", temp401, near=tt401, at="N", offset=90,
                               variant="shared")
    tic401.nozzle("sig_out", "W")
    tic401.annotate(high="TAH", low="TAL")
    fs.connect(tt401.sig_out, tic401.sig_in, kind="electric")

    fe402_b = fs.add_balloon(fe402, at="N", offset=38)
    ft402 = fs.add_instrument("FT", flow402, near=fe402_b, at="N", offset=23)
    # at="E", not "W": the signal flows transmitter to controller, and a
    # sheet reads that the same direction the loop does.
    fic402 = fs.add_instrument("FIC", flow402, near=ft402, at="E", offset=70,
                               variant="shared")
    fic402.nozzle("sig_out", "S")
    fs.connect(ft402.sig_out, fic402.pv, kind="electric")
    fs.connect(tic401.sig_out, fic402.sig_in, kind="software")
    fs.connect(fic402.sig_out, cv402.actuator, kind="pneumatic")

    # --- Loop 403: settler interface level onto the glycerol draw -------
    lt403 = fs.add_instrument("LT", level403, sensing=s401, at="E", offset=60)
    # at="N", not "S" or "W": north of CV-403 stands the faceplate over
    # the valve it strokes and east of LT-403, which reads better than
    # either of the sides it was tried on. "W" lands back in LT-403's
    # own pocket, S-401 and CV-403 standing close enough together for
    # that; "S" reads as if the valve fed the loop rather than the loop
    # the valve.
    lic403 = fs.add_instrument("LIC", level403, near=cv403, at="N", offset=100,
                               variant="shared")
    lic403.annotate(high="LAH", low="LAL")
    fs.connect(lt403.sig_out, lic403.sig_in, kind="electric")
    fs.connect(lic403.sig_out, cv403.actuator, kind="pneumatic")

    # --- Loops 404/405: column top temperature onto the reflux ----------
    # at=0.2, not the midpoint: E-402 sits close enough to this line's
    # far half that a tap taken there lands on the reboiler shell.
    # Reading the vapour closer to the column it leaves is truer to what
    # "column top temperature" means in any case.
    tt404 = fs.add_instrument("TT", temp404, sensing=vapour, at=0.2, offset=60)
    tic404 = fs.add_instrument("TIC", temp404, near=tt404, at="N", offset=70,
                               variant="shared")
    tic404.annotate(high="TAH")
    fs.connect(tt404.sig_out, tic404.sig_in, kind="electric")
    # West, clear of TAH: left on the default face, software leaves
    # from the same corner the annotation is written in.
    tic404.nozzle("sig_out", "W")

    fe405_b = fs.add_balloon(fe405, at="N", offset=38)
    ft405 = fs.add_instrument("FT", flow405, near=fe405_b, at="N", offset=23)
    fic405 = fs.add_instrument("FIC", flow405, near=ft405, at="N", offset=150,
                               variant="shared")
    fs.connect(ft405.sig_out, fic405.pv, kind="electric")
    fs.connect(tic404.sig_out, fic405.sig_in, kind="software")
    fs.connect(fic405.sig_out, cv405.actuator, kind="pneumatic")

    # --- Loop 406: reflux drum level onto the recovered methanol draw ---
    lt406 = fs.add_instrument("LT", level406, sensing=d401, at="E", offset=60)
    # at="N", not "W": west of CV-406 is the tee's own drop from T-reflux,
    # and a balloon parked in it is what bent that line wide around it.
    lic406 = fs.add_instrument("LIC", level406, near=cv406, at="N", offset=52,
                               variant="shared")
    lic406.annotate(high="LAH", low="LAL")
    fs.connect(lt406.sig_out, lic406.sig_in, kind="electric")
    fs.connect(lic406.sig_out, cv406.actuator, kind="pneumatic")

    # --- Loop 407: reboiler level onto the stripped ester draw -----------
    lt407 = fs.add_instrument("LT", level407, sensing=e402, at="S", offset=110)
    # at="W", offset widened from 52: E-402 sits close enough west of
    # CV-407 that a balloon left at the smaller offset lands on the
    # reboiler shell.
    lic407 = fs.add_instrument("LIC", level407, near=cv407, at="W", offset=115,
                               variant="shared")
    lic407.annotate(high="LAH", low="LAL")
    fs.connect(lt407.sig_out, lic407.sig_in, kind="electric")
    fs.connect(lic407.sig_out, cv407.actuator, kind="pneumatic")

    # --- Loop 408: wash separator interface level -------------------------
    lt408 = fs.add_instrument("LT", level408, sensing=s402, at="E", offset=60)
    # at="E", not "S": CV-408's own tag sits close under the valve, in
    # the way of a balloon hung there.
    lic408 = fs.add_instrument("LIC", level408, near=cv408, at="E", offset=70,
                               variant="shared")
    lic408.annotate(high="LAH", low="LAL")
    fs.connect(lt408.sig_out, lic408.sig_in, kind="electric")
    fs.connect(lic408.sig_out, cv408.actuator, kind="pneumatic")

    # --- The runaway trip, on a measurement of its own --------------------
    # 1 is a typed literal rather than a declared loop: nothing else on
    # the sheet is tagged Z-1, so a loop here would be a balloon the
    # drawing does not have. The transmitter and not TIC-401: a trip
    # reading the controller reads what it last asked the valve for, and
    # stops working the moment that loop is put on manual.
    # at="E", not "W": the trip stands over the discharge side now, out
    # from under the batch temperature loop it backs up.
    tt409 = fs.add_instrument("TT", 409, sensing=r401, at="E", offset=70)
    # at="N", not "S": P-403 takes R-401's discharge immediately south
    # of TT-409, and a square dropped there sits on the pump's own line.
    fs.add_instrument("Z", 1, sensing=tt409, at="N", offset=44, variant="sis")
    # at="N" and stood off further than the loop above: south is where
    # the tap carrying this square's own trip signal down from the
    # actuator runs; west is the jacket hot-water header's own line in
    # from HV-402; and close north still catches FIC-402's signal down
    # to the actuator, which offset=60 clears.
    fs.add_instrument("Z", 1, acting_on=cv402, at="N", offset=60, variant="sis")

    # A local reading only: the vacuum is watched, not held on a loop of
    # its own, which is ordinary for a batch dryer run to a fixed time
    # rather than to a measured dryness.
    fs.add_instrument("PI", 410, sensing=s403, at="E", offset=60)

    # --- Sheet furniture ----------------------------------------------
    fs.title_block = TitleBlock(
        title="Biodiesel Production",
        subtitle="A400 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-401",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        scale="NTS",
        date="18/08/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "04/08/26", "Issued for internal review", "AA"),
            Revision("B", "18/08/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(equipment_list(fs, align="top-right", include=[
        "TK-401", "P-401", "TK-402", "P-402", "MT-401", "R-401", "P-403",
        "S-401", "C-401", "E-401", "D-401", "E-402", "M-401", "S-402",
        "S-403", "EJ-401", "P-404", "TK-403", "N-401", "P-405", "TK-404",
    ]))
    fs.add_annotation(notes([
        "Z-1: reactor runaway trip, closing CV-402 on high batch "
        "temperature. TT-409 is its own measurement, independent of "
        "TIC-401.",
        "R-401 and MT-401 jacket/coil returns are on P&ID-402: each "
        "reactor draws a single duty nozzle, so the hot-water return is "
        "not on this sheet.",
        "Methanol is recovered from the ester phase only; the smaller "
        "quantity carried by the glycerol phase is stripped in the "
        "glycerine refining train, off this sheet.",
        "Crude glycerol is stored and sold as-is at this scale. Salt "
        "removal and vacuum refining to technical or pharmaceutical "
        "grade are a plant of their own.",
        "One wash stage is drawn; a production design washes the ester "
        "two to three times.",
    ], title="GENERAL NOTES", numbered=False, align="bottom-left"))
    fs.add_annotation(legend({
        "SS": "Stainless Steel 316L",
        "CS": "Carbon Steel A106-B",
        "CO": "Canola Oil",
        "MEOH": "Methanol",
        "KOH": "Potassium Hydroxide Catalyst",
        "MX": "Methoxide Charge",
        "RM": "Reactor Mix",
        "RV": "Reactor Vent Gas",
        "CE": "Crude Ester",
        "CG": "Crude Glycerol",
        "PA": "Phosphoric Acid",
        "MV": "Methanol Vapour",
        "RCM": "Recovered Methanol",
        "SE": "Stripped Ester",
        "WW": "Wash Water",
        "WM": "Wash Mix",
        "WE": "Washed Ester",
        "SW": "Spent Wash Water",
        "WV": "Water Vapour",
        "BD": "Biodiesel (FAME)",
        "NG": "Neutralised Glycerol",
        "CGP": "Crude Glycerol Product",
        "HWSH": "Hot Water Supply Header",
        "LPSSH": "Low Pressure Steam Supply Header",
        "LPSRH": "Low Pressure Steam Return Header",
        "CWSH": "Cooling Water Supply Header",
        "CWRH": "Cooling Water Return Header",
    }, align="top-left"))

    fs.render(out("biodiesel_plant.svg"), border="zone", diagram="p&id")
    print("Generated biodiesel_plant.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
