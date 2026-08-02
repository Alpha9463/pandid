"""
Example 14: Product Storage and Road Loading A600, a bulk liquid tank farm

Three storage vessels, the transfer system that draws them down, the rack that
loads road tankers off it, and the vapour system that takes back what the
loading displaces. Nothing is heated, cooled, reacted or separated: a terminal
is a plant whose whole content is containment and piping, which is why this
sheet is dense in symbols the reactor-and-column examples never reach for.

**It is a P&ID, and it has to be.** Almost everything this sheet exists to draw
is line hardware, and ISO 15519-2 puts line hardware on one diagram type and
not the other. Its Table 4, the process flow diagram, allows "general graphical
symbols for process equipment, valve actuators, PCI symbols" and never names a
valve *body*, a reducer or a fitting in either of its columns -- all three of
its mentions of the word are of an actuator. Its Table 5, the
process and instrumentation diagram, opens its *basic* information with
"specific graphical symbols for process equipment incl. prime movers ...,
valves incl. actuators, connections, etc." and its additional information with
"pipe reducers for change of dimensions, compensators, flow straighteners,
mixing paths, etc." (pp. 17 and 19). A root valve, a strainer, a compensator
and a flame arrestor drawn on a PFD would be four items that diagram is not
for; drawn here they are what the diagram is for. The same table is why P-602
is drawn as the gear pump it is rather than as a pump: "supplementary
information on graphical symbols, if needed, e.g. connections represent
equipment of specific function e.g. gear pump".

**The tanks are three different vessels because they hold three different
fluids**, and the sheet is meant to make the reason legible.

- ``TK-601`` is an **external floating roof**. Motor spirit's vapour pressure
  at ambient is high, and a fixed roof over it is a vapour space that is pushed
  out to atmosphere on every fill and drawn back in on every draw-down. A
  floating roof deletes the space rather than managing it: the deck rides on
  the liquid, so there is nothing to breathe and nothing to inert. That is why
  it has no vent, no breather and no blanket anywhere on this sheet, and why
  the two tanks beside it are not drawn the same way.
- ``TK-602`` is a **fixed dished roof** over denatured ethanol, and the choice
  is the product's and not the pressure's. Ethanol is water-miscible and
  hygroscopic, and an external floating roof's rim seal is open to weather: the
  rain that collects on the deck has one barrier between it and the product.
  Water in motor spirit separates and is drawn off the tank floor; water in
  ethanol is in the ethanol and the parcel is off specification. So the roof
  stays on, and the vapour space it keeps is what the vapour system below
  exists to handle.
- ``V-603`` is a **sphere** because butane at ambient is a liquid only under
  its own vapour pressure. A flat-bottomed atmospheric tank holds no pressure
  at all -- its floor-to-shell joint is a hinge, which is exactly why an
  atmospheric tank fails there first -- and a sphere carries pressure in pure
  membrane tension with no corner to concentrate it, so it needs the least
  metal per unit volume of any shape that will hold the duty. The line off it
  needs no pump for the same reason the sphere is a sphere: the stored liquid
  is already above the pressure the loading arm works at, so ``PCV-606``, a
  self-contained regulator, lets it down rather than a pump pushing it up.

**The vapour system is where the flammables are handled.** Every litre loaded
into a road tanker displaces a litre of saturated vapour out of it, and that
vapour is returned rather than vented at the rack. ``V-604`` knocks out what
condenses in the return line and passes the rest to the recovery unit; its
crown carries the sheet's one opening to atmosphere, and that opening is the
reason for both arrestors.

- ``VT-601`` is a **conservation vent**, not an open pipe. It is the relief
  that limits the pressure and the vacuum a thin drum can take when the
  recovery unit trips or the return is blocked, and it reseats; an open vent
  would make the drum breathe air in on every cycle and hold the header near
  the flammable range as a matter of routine rather than as a fault.
- ``FA-601`` is the **arrestor for that opening**, and it is mounted between
  the breather and the drum rather than on top of the breather. An arrestor
  quenches a flame by taking the heat out of it in a narrow passage, so it has
  to stand between the ignition source and the volume being protected. Put
  above the breather it would leave the whole vent nozzle full of flammable
  vapour on the wrong side of it.
- ``FA-602`` is **detonation-rated and the vent one is not**, which is a
  statement about the pipe rather than about the hazard. The vapour return runs
  the length of the rack; a deflagration started at a road tanker has that much
  pipe to accelerate in, and by the time it reaches the drum it can be a
  detonation, which an end-of-line element is not rated to stop. ``HV-607``
  sits outboard of it so the element can be drawn for cleaning without opening
  the drum.

None of that last group can be cited to the standards on disk: ISO 15519-1,
ISO 15519-2 and the CHEE4001 guidelines contain no mention of a flame arrestor,
a conservation vent, a floating roof or tank venting of any kind, so they are
argued here as engineering and attributed to nothing. What the guidelines do
give is permission to draw them at all -- CHEE4001 p.2 lists a P&ID's
"Miscellaneous: vents, drains, special fittings, sampling lines, reducers,
etc".

**Two reducers, and the difference between them is the whole point.**
``RD-601`` is eccentric and ``RD-602`` concentric, on the suction and the
discharge of one pump. :class:`pandid.units.Reducer` argues the suction half
already -- the eccentric body is drawn flat on top, so a concentric one there
"leaves a pocket for vapour to collect in against the roof of the line" -- and
this sheet is the first to draw the pair and let the two bodies be compared.
The discharge takes the concentric one because the argument does not apply: the
line is pumped and liquid-full, there is no vapour to collect, and a symmetric
body is the cheaper casting.

**The overfill trip is the tank farm's safety case**, and it is drawn as a
separate system rather than as an alarm on the gauge. Each tank carries a level
transmitter for the gauge loop and a *second*, independent high-high switch
that drives ``Z-1``; the trip closes the receipt valve on whichever tank
initiated it. CHEE4001 p.20 gives both halves of that: "high-high and low-low
levels are generally 'reserved' for SIS actions", and, of a safety-related
alarm, "where they are involved in protecting against mal-operation by the
control system they should be independent of the devices they are monitoring".
The same page states the practice outright -- "While a safety trip can be
incorporated into a control loop, the safe operation of such a system will be
dependent on the reliability of the control equipment. For potentially
hazardous situations it is better practice to specify a separate trip system"
-- which is the reason ``LSHH-611`` is not a tap off ``LT-601``. One trip, four
drawn squares: ``Z-1`` is a single logic function and appears at each point it
acts, which is the convention ``examples/11_ethanol_pid.py`` establishes.

**Every loop number is allocated, not typed.** ``fs.add_loop("L")`` with no
number takes the next from ``loop_number_start``, so the five loops come out
L-601, L-602, P-603, F-604, F-605 -- one series climbing through whichever
measured variable was declared next, in the order the file reads. That is the
draft-stage half of :mod:`pandid.loops`: the numbers are fixed at declaration
and nothing re-derives them, but nobody retypes the series when a loop is added
near the top. ``LSHH-611`` and ``LSHH-612`` keep literal numbers, because a
switch that initiates a trip and measures nothing for a controller is in no
group a loop number names -- CHEE4001 p.13, "A loop number is assigned to each
group of components required to perform the desired function of the monitor or
control scheme".

**Two things a real sheet carries that this one cannot yet.** Both are the same
gap: :class:`pandid.units.Tank` has a fill and a draw and no third nozzle.

- The conservation vent belongs on ``TK-602``'s own roof, not only on the
  vapour drum. A fixed roof over a flammable is the textbook place for a
  breather and an arrestor, and it is the one place here they cannot be hung.
- ``V-603`` should carry a fire-case relief. CHEE4001 p.8 names the duty
  exactly -- a rupture disc suits "protection against exposure of a pressure
  vessel to fire or other sources of heat provided that the vessel has no
  permanent supply connection. This is usually the case with storage vessels
  for non-refrigerated liquefied compressible gases at ambient temperatures" --
  and p.7 says where it goes: "directly on the system to be protected,
  vertically, upward, and at the top of the container". The sphere's top nozzle
  is spent on the receipt, so the one device this sheet has a quotable duty for
  is the one it cannot draw. It is left off rather than hung somewhere it does
  not belong.

**The layout is elevation-ordered so that nothing crosses.** ISO 15519-1 §12.1
asks for connecting lines "straight with a minimum of bends and crossovers",
and on a sheet with three receipts feeding three roofs and three draws feeding
one header that is a choice about which run gets which elevation, not luck: the
receipt to the *furthest* tank is the *highest* run, and the draw from the
*nearest* tank is the *lowest*. Each drop then falls through empty paper. The
same clause's §13.1 is why the tanks sit above the pumps at all -- "where the
gravity is an essential or important function, for example in a chemical
process, the vertical view principle should be used" -- and §11.4.2 is why none
of the three is turned: it names symbol 2061, *Open tank*, as one of the
symbols "where gravity is a functionality", which "must not be turned". Every
boundary flag is on the left or right edge, which is CHEE4001 p.2's preference
"to show off-page connectors horizontally and at the edge of a P&ID", and the
two at the east edge are mirrored so each pennant points the way its fluid
travels.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Annotation, Revision, TitleBlock, legend, notes
from pandid.portgeom import port_offset, resolve_size


def main():
    fs = Flowsheet(
        "Product Storage and Road Loading A600",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
        line_number_start=601,
        loop_number_start=601,
    )

    # --- Control loops ---------------------------------------------------
    # Five loops, and not one number typed. add_loop() with the number left out
    # takes the next from loop_number_start, so the series is L-601, L-602,
    # P-603, F-604, F-605: one counter running across measured variables, in the
    # order these five lines read. The alternative -- a literal at every
    # declaration -- is the churn a draft is made of, since adding a loop near
    # the top of a sheet whose series runs in reading order means retyping every
    # number below it by hand, on a drawing whose whole point is that a number is
    # typed once. Allocation happens *here*, at the declaration, so from this
    # line on the number is as fixed as a typed one; see pandid.loops for why
    # that is still "allocate once and never renumber".
    #
    # A loop is the variable and the number together, so nothing else on this
    # sheet numbered 601 -- TK-601, XV-601, line MS-601, HV-601 -- is loop L-601,
    # and no reader may recover a loop by grouping tags on the digits.
    ms_level = fs.add_loop("L")      # L-601, TK-601 level
    eth_level = fs.add_loop("L")     # L-602, TK-602 level
    lpg_press = fs.add_loop("P")     # P-603, V-603 pressure
    load_flow = fs.add_loop("F")     # F-604, loading rate
    blend_flow = fs.add_loop("F")    # F-605, ethanol blend ratio

    # --- Storage ---------------------------------------------------------
    # Floating roof, fixed roof, sphere: three roofs for three vapour pressures,
    # argued at the top of this file. The tag goes inside each shell
    # (label_pos="center") because the fill line arrives on the roof and a tag
    # written above the tank would be written across that drop.
    tk601 = fs.add(units.Tank("TK-601", variant="floating_roof", width=190, height=140,
                              label_pos="center", description="Motor Spirit Storage Tank"))
    tk602 = fs.add(units.Tank("TK-602", width=180, height=150, label_pos="center",
                              description="Denatured Ethanol Storage Tank"))
    v603 = fs.add(units.Tank("V-603", variant="sphere", width=140, height=185,
                             label_pos="center", description="Butane Storage Sphere"))
    v604 = fs.add(units.Vessel("V-604", variant="legs", width=60, height=120,
                               description="Loading Vapour Knock-Out Drum"))

    # --- Rotating --------------------------------------------------------
    # P-601 is a centrifugal pump moving the bulk of the blend and P-602 a gear
    # pump metering the ethanol into it, and the second is a gear pump because
    # the ratio has to hold whatever the rack does. A centrifugal pump sits on a
    # head-flow curve, so its delivery falls as the loading arm back-pressure
    # rises and the blend drifts with the tanker; a positive-displacement pump
    # delivers a volume per revolution and does not. What that buys is paid for
    # by PSV-602 below: a pump that ignores back-pressure will raise it until
    # something gives, so it cannot be throttled without a relief path.
    p601 = fs.add(units.Pump("P-601", description="Motor Spirit Transfer Pump"))
    p602 = fs.add(units.Pump("P-602", variant="gear", width=48, height=76,
                             description="Ethanol Blend Pump"))

    # --- Boundary --------------------------------------------------------
    ms_in = fs.add(units.Feed("Motor Spirit", reference="P&ID-501"))
    eth_in = fs.add(units.Feed("Denatured Ethanol", reference="PFD-302"))
    lpg_in = fs.add(units.Feed("Butane", reference="P&ID-503"))
    e10_out = fs.add(units.Product("E10 Road Tanker", reference="P&ID-611"))
    lpg_out = fs.add(units.Product("LPG Road Tanker", reference="P&ID-612"))
    vap_in = fs.add(units.Feed("Tanker Vapour Return", reference="P&ID-611"))
    vru_out = fs.add(units.Product("Vapour Recovery Unit", reference="P&ID-609"))

    # --- In-line: motor spirit -------------------------------------------
    # Both receipt valves fail closed, and both say so in the notes rather than
    # on the valve. fail="closed" is the drawn form and was tried first: it puts
    # an FC under the valve body, which is the same face the trip square hangs
    # on, and the mark's halo then deletes the impulse line joining the two. The
    # square is the more important of the pair -- it is the whole of what Z-1
    # claims -- so the mark comes off and the words go in the notes box, which is
    # what a notes box is for.
    xv601 = fs.add(units.Valve("XV-601", variant="solenoid",
                               description="MS Receipt Trip Valve"))
    xv602 = fs.add(units.Valve("XV-602", variant="solenoid",
                               description="Ethanol Receipt Trip Valve"))
    hv601 = fs.add(units.Valve("HV-601", variant="gate", description="TK-601 Root Valve"))
    # The compensator is there because the tank moves. A tank this size settles
    # into its pad over its first fills and rises and falls with every one after,
    # and the shell nozzle is the stiffest point in the system: with no flexible
    # element in the first few metres, that movement is taken by the
    # nozzle-to-shell weld. ISO 15519-2 Table 5 names it as P&ID content --
    # "pipe reducers for change of dimensions, compensators, flow straighteners,
    # mixing paths, etc." (p. 19) -- under the same bullet as the reducers.
    ej601 = fs.add(units.Fitting("EJ-601", variant="expansion_joint",
                                 description="TK-601 Nozzle Compensator"))
    # A basket on the big line and a Y on the small one, which is a choice about
    # dirt load rather than about taste. ST-601 takes the whole of a 250 bore
    # draw off a tank floor that has been settling water and scale since the tank
    # was commissioned, and a basket gives the most screen area per body and
    # comes out through its own lid. ST-602 protects gear teeth on an 80 bore
    # line of already-clean product, where a Y body element is enough and its
    # blowdown boss is the thing that actually gets used.
    st601 = fs.add(units.Fitting("ST-601", variant="strainer_basket",
                                 description="P-601 Suction Strainer"))
    # Eccentric into the pump, concentric out of it. The eccentric body is drawn
    # flat on top, so the two bores share a roof and nothing is left for vapour
    # to collect under; a concentric one on a suction leaves exactly that pocket
    # against the crown of the line, and a pocket at a pump suction breaks the
    # pump prime. units.Reducer argues this at length and the wording here is
    # deliberately its wording. The discharge takes the concentric body because
    # none of that is true of it: the line is pumped and liquid-full, so there is
    # no vapour to trap and no reason to pay for an offset casting.
    #
    # large_end="outlet" is what makes the second one an expansion. It is the
    # same fitting piped round the other way rather than a second symbol, so the
    # run still goes inlet to outlet through both.
    rd601 = fs.add(units.Reducer("RD-601", variant="eccentric",
                                 description="P-601 Suction Reducer"))
    rd602 = fs.add(units.Reducer("RD-602", variant="concentric", large_end="outlet",
                                 description="P-601 Discharge Expander"))
    nrv601 = fs.add(units.Valve("NRV-601", variant="check", description="P-601 Non-Return Valve"))

    # --- In-line: ethanol ------------------------------------------------
    hv603 = fs.add(units.Valve("HV-603", variant="gate", description="TK-602 Root Valve"))
    # A spectacle blind at the tank root, drawn in its open position: the ring is
    # in the line and the solid disc parked above it. It is the positive
    # isolation a tank needs before anyone opens it, and a closed valve is not
    # that -- a valve is a seat that may pass, a blind is a plate that cannot. It
    # goes immediately outside the root valve, because that is where the break
    # has to be to leave TK-602 isolated from a header the other tank is still
    # delivering into. normal_position is a change of *shape* on this fitting
    # rather than a mark added to one, so the sheet never shows a blind in a
    # position by inference.
    sb601 = fs.add(units.Fitting("SB-601", variant="blind", description="TK-602 Spectacle Blind"))
    t_rec = fs.add(units.Tee(branch="inlet"))
    st602 = fs.add(units.Fitting("ST-602", variant="strainer_y",
                                 description="P-602 Suction Strainer"))
    t_psv = fs.add(units.Tee())
    # The relief a positive-displacement pump has to have. CV-605 throttles the
    # blend, and throttling a gear pump does not slow it down: it raises the
    # discharge pressure until the weakest thing in the loop gives, which on a
    # blocked-in line is the casing or the pipe. So the discharge is teed back to
    # the suction through a relief set above the working pressure, and what the
    # ratio valve does not pass goes round again. It is drawn upright, which is
    # both how the stencil draws it and what CHEE4001 p.7 asks for: "The PSV
    # should be placed, whenever possible, directly on the system to be
    # protected, vertically, upward, and at the top of the container." The leg
    # rejoins upstream of ST-602, so anything the recycle picks up passes the
    # strainer before it reaches the gears again.
    psv602 = fs.add(units.Valve("PSV-602", variant="relief", description="P-602 Relief Valve"))
    fe605 = fs.add(units.Fitting(blend_flow.tag("FE"), variant="coriolis",
                                 description="Ethanol Blend Meter"))
    cv605 = fs.add(units.Valve(blend_flow.tag("CV"), variant="control",
                               description="Ethanol Blend Valve"))
    nrv602 = fs.add(units.Valve("NRV-602", variant="check", description="P-602 Non-Return Valve"))

    # --- In-line: butane -------------------------------------------------
    hv605 = fs.add(units.Valve("HV-605", variant="gate", description="V-603 Root Valve"))
    pcv606 = fs.add(units.Valve("PCV-606", variant="regulator",
                                description="Butane Let-Down Regulator"))
    hv608 = fs.add(units.Valve("HV-608", variant="ball", description="LPG Loading Arm Valve"))
    # Gate at the tank roots, ball at the arms, butterfly on the vapour header,
    # and each is the body that duty asks for rather than a tour of the
    # catalogue. A gate is full bore and drops almost no head, which is what a
    # gravity draw off a tank floor cannot spare; it is a poor throttle, and
    # nothing here throttles by hand. A ball is quarter-turn with a handle whose
    # position is readable across the rack, which is what an operator wants on a
    # line they are about to break. A butterfly is a disc in a large low-pressure
    # bore, the cheapest way to shut a 150 vapour line and the wrong way to shut
    # a 250 liquid one. Nothing here is a globe, a needle or a plug: a globe
    # throttles and the two duties that throttle are on control valves, and the
    # needle that would isolate a gauge is an instrument block valve, which
    # ISO 15519-2 7.3.4.2 says "should not be shown in PID".

    # --- In-line: the loading rack ---------------------------------------
    t_blend = fs.add(units.Tee(branch="inlet"))
    t_blend.new_line_number = True
    # Two meters, two technologies, because they measure for two different
    # reasons. FE-604 is the custody transfer meter -- what leaves here is
    # invoiced -- and a positive-displacement meter counts a fixed volume per
    # revolution, so its accuracy does not depend on the flow profile it is given
    # or on a straight run it will not get at a rack. FE-605 is the blend
    # measurement and is a Coriolis, which reads mass directly and so need not be
    # told the ethanol density as it warms through the day. Both are primary
    # elements sitting *in* the line with their transmitters hung off them: the
    # balloon beside one reads the element, it is not the element.
    fe604 = fs.add(units.Fitting(load_flow.tag("FE"), variant="positive_displacement",
                                 label_pos="bottom", description="Loading Meter"))
    cv604 = fs.add(units.Valve(load_flow.tag("CV"), variant="control",
                               description="Loading Rate Valve"))
    hv604 = fs.add(units.Valve("HV-604", variant="ball", description="E10 Loading Arm Valve"))
    # HOS and not HS. ISO 15519-2 Table 2 (p. 11) gives H as a process variable,
    # "Human observation", and S as a control function, "Switching (open loop)",
    # and §5.2.2/§5.2.3 say a letter code string is a process variable followed
    # by a control function -- so HS-601 was a well-formed instrument tag on a
    # length of rubber. HOS breaks the string at its second letter, which is
    # neither a control function nor a Table 3 modifier, so it cannot be read as
    # one. This is the ISA-5.1 "hand switch" by another name; those are not the
    # standard's words and the note above quotes the ones that are.
    hos601 = fs.add(units.Fitting("HOS-601", variant="hose", description="E10 Loading Hose"))

    # --- In-line: the vapour system --------------------------------------
    fa602 = fs.add(units.Fitting("FA-602", variant="flame_arrestor_detonation_proof",
                                 description="Vapour Return Flame Arrestor"))
    hv607 = fs.add(units.Valve("HV-607", variant="butterfly", description="Vapour Header Valve"))
    fa601 = fs.add(units.Fitting("FA-601", variant="flame_arrestor",
                                 description="V-604 Vent Flame Arrestor"))
    vt601 = fs.add(units.Vent("VT-601", variant="breather", description="V-604 Conservation Vent"))

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner. Every run is named by the elevation of the
    # nozzle it serves and each device is placed with pin(port=...), which asks
    # the symbol where its own nozzle sits, so no rescaling of the artwork can
    # leave a valve off its run.
    #
    # The elevations are the sheet's one piece of real drafting. Three receipts
    # come in from the west and drop onto three roofs; three draws leave three
    # floors and run east. ISO 15519-1 12.1 wants lines "straight with a minimum
    # of bends and crossovers", and with six runs on one sheet that is decided
    # here or not at all: the receipt to the *furthest* tank takes the *highest*
    # run (butane, then ethanol, then motor spirit), and the draw from the
    # *nearest* tank takes the *lowest*. Each drop then falls past the end of
    # every run it might have crossed, and the sheet carries no process crossing
    # at all. Reverse either ordering and there are four.
    tk601.pin(x=360, y=215)
    tk602.pin(x=680, y=205)
    v603.pin(x=1090, y=180)

    ms_fill_x = 360 + port_offset(tk601, "inlet")[0]
    ms_draw_x = 360 + port_offset(tk601, "outlet")[0]
    eth_fill_x = 680 + port_offset(tk602, "inlet")[0]
    eth_draw_x = 680 + port_offset(tk602, "outlet")[0]
    lpg_fill_x = 1090 + port_offset(v603, "inlet")[0]
    lpg_draw_x = 1090 + port_offset(v603, "outlet")[0]

    ms_recv_y, eth_recv_y, lpg_recv_y = 170.0, 110.0, 50.0
    ms_in.pin(port="outlet", x=200, y=ms_recv_y)
    xv601.pin(port="inlet", x=250, y=ms_recv_y)
    eth_in.pin(port="outlet", x=200, y=eth_recv_y)
    xv602.pin(port="inlet", x=500, y=eth_recv_y)
    lpg_in.pin(port="outlet", x=200, y=lpg_recv_y)

    lpg_run_y, eth_run_y, ms_run_y = 390.0, 510.0, 665.0
    balloon_row_y, low_row_y, psv_run_y = 462.0, 570.0, 600.0
    cascade_y = 422.0

    hv601.pin(port="inlet", x=495, y=ms_run_y)
    ej601.pin(port="inlet", x=560, y=ms_run_y)
    st601.pin(port="inlet", x=605, y=ms_run_y)
    rd601.pin(port="inlet", x=665, y=ms_run_y)
    # RD-601 is the eccentric body, so its two nozzles are not on one centreline:
    # flat on top puts the small end's axis half the bore difference above the
    # large end's. Pinning the pump on ms_run_y therefore put a step in the line
    # immediately downstream of the one fitting whose whole point is that there
    # is no step in the crown of the run. The pump is pinned at the reducer's
    # *outlet* elevation instead, asked of the symbol rather than measured off
    # the drawing, and the suction is straight from the strainer to the nozzle.
    ms_suction_y = ms_run_y + port_offset(rd601, "outlet")[1] - port_offset(rd601, "inlet")[1]
    p601.pin(port="suction", x=705, y=ms_suction_y)
    ms_disch_y = ms_suction_y + port_offset(p601, "discharge")[1] - port_offset(p601, "suction")[1]
    rd602.pin(port="inlet", x=795, y=ms_disch_y)
    nrv601.pin(port="inlet", x=875, y=ms_disch_y)

    hv603.pin(port="inlet", x=785, y=eth_run_y)
    sb601.pin(port="inlet", x=845, y=eth_run_y)
    t_rec.pin(port="inlet", x=870, y=eth_run_y)
    st602.pin(port="inlet", x=896, y=eth_run_y)
    p602.pin(port="suction", x=940, y=eth_run_y)
    t_psv.pin(port="inlet", x=1060, y=eth_run_y)
    fe605.pin(port="inlet", x=1080, y=eth_run_y)
    cv605.pin(port="inlet", x=1140, y=eth_run_y)
    nrv602.pin(port="inlet", x=1180, y=eth_run_y)
    psv_branch_x = t_psv.pin_.x + port_offset(t_psv, "branch")[0]
    rec_branch_x = t_rec.pin_.x + port_offset(t_rec, "branch")[0]
    psv602.pin(port="inlet", x=rec_branch_x, y=psv_run_y)

    hv605.pin(port="inlet", x=1250, y=lpg_run_y)
    pcv606.pin(port="inlet", x=1310, y=lpg_run_y)
    hv608.pin(port="inlet", x=1390, y=lpg_run_y)
    lpg_out.pin(port="inlet", x=1560, y=lpg_run_y)

    blend_y = ms_disch_y
    t_blend.pin(mirrored="y").pin(port="inlet", x=1220, y=blend_y)
    blend_branch_x = t_blend.pin_.x + port_offset(t_blend, "branch")[0]
    fe604.pin(port="inlet", x=1340, y=blend_y)
    cv604.pin(port="inlet", x=1400, y=blend_y)
    hv604.pin(port="inlet", x=1460, y=blend_y)
    hos601.pin(port="inlet", x=1505, y=blend_y)
    e10_out.pin(port="inlet", x=1560, y=blend_y)

    # The vapour system stands at the rack it serves and both of its off-page
    # flags are on the east edge, beside the tanker flags whose traffic makes
    # the vapour: the return comes in on one row, turns round in V-604 and
    # leaves for the recovery unit on the row below. It used to run the full
    # width of the sheet from the east edge to the west, which is a return
    # stream counterflowing for 1200 units against ISO 15519-1 §13.2 (p. 28),
    # "the direction of the main flow should be from left to right or from top
    # to bottom". Both flags stay at a sheet edge, which is CHEE4001 p.2's
    # preference for an off-page connector, so the fix is where the run ends and
    # not whether it is drawn at an edge at all.
    #
    # The two rows are 120 apart and low on the sheet because the drum's vent
    # riser rises between them: VT-601 tops out at vap_y - 130, and the E10 rack
    # run at blend_y is what it has to clear.
    vap_y, vru_y = 830.0, 935.0
    vap_in.pin(mirrored=True).pin(port="outlet", x=1560, y=vap_y)
    hv607.pin(mirrored=True).pin(port="inlet", x=1470, y=vap_y)
    fa602.pin(mirrored=True).pin(port="inlet", x=1390, y=vap_y)
    v604.pin(mirrored=True).pin(port="inlet", x=1315, y=vap_y)
    vent_x = v604.pin_.x + port_offset(v604, "vent")[0]
    vent_y = v604.pin_.y + port_offset(v604, "vent")[1]
    vru_x = v604.pin_.x + port_offset(v604, "outlet")[0]
    fa601.pin(orientation=270).pin(port="inlet", x=vent_x, y=vent_y - 22)
    vt601.pin(port="inlet", x=vent_x, y=vent_y - 68)
    vru_out.pin(port="inlet", x=1560, y=vru_y)

    # --- Process lines ---------------------------------------------------
    fs.connect(ms_in.outlet, xv601.inlet, service="MS", sequence=601, size=200,
               schedule=40, spec="CS")
    fs.connect(xv601.outlet, tk601.inlet).via([(ms_fill_x, ms_recv_y)])
    fs.connect(eth_in.outlet, xv602.inlet, service="ETH", sequence=602, size=150,
               schedule=40, spec="SS")
    fs.connect(xv602.outlet, tk602.inlet).via([(eth_fill_x, eth_recv_y)])
    fs.connect(lpg_in.outlet, v603.inlet, service="LPG", sequence=603, size=100,
               schedule=80, spec="CS").via([(lpg_fill_x, lpg_recv_y)])

    fs.connect(tk601.outlet, hv601.inlet, service="MS", sequence=604, size=250,
               schedule=40, spec="CS").via([(ms_draw_x, ms_run_y)])
    fs.connect(hv601.outlet, ej601.inlet)
    fs.connect(ej601.outlet, st601.inlet)
    fs.connect(st601.outlet, rd601.inlet)
    fs.connect(rd601.outlet, p601.suction)
    fs.connect(p601.discharge, rd602.inlet, service="MS", sequence=605, size=200,
               schedule=40, spec="CS")
    fs.connect(rd602.outlet, nrv601.inlet)
    fs.connect(nrv601.outlet, t_blend.inlet)

    fs.connect(tk602.outlet, hv603.inlet, service="ETH", sequence=606, size=100,
               schedule=40, spec="SS").via([(eth_draw_x, eth_run_y)])
    fs.connect(hv603.outlet, sb601.inlet)
    fs.connect(sb601.outlet, t_rec.inlet)
    fs.connect(t_rec.outlet, st602.inlet)
    fs.connect(st602.outlet, p602.suction)
    fs.connect(p602.discharge, t_psv.inlet, service="ETH", sequence=607, size=80,
               schedule=40, spec="SS")
    fs.connect(t_psv.outlet, fe605.inlet)
    fs.connect(fe605.outlet, cv605.inlet)
    fs.connect(cv605.outlet, nrv602.inlet)
    fs.connect(nrv602.outlet, t_blend.branch).via([(blend_branch_x, eth_run_y)])
    fs.connect(t_psv.branch, psv602.inlet, service="ETH", sequence=613, size=40,
               schedule=40, spec="SS").via([(psv_branch_x, psv_run_y)])
    fs.connect(psv602.outlet, t_rec.branch)

    fs.connect(v603.outlet, hv605.inlet, service="LPG", sequence=608, size=80,
               schedule=80, spec="CS").via([(lpg_draw_x, lpg_run_y)])
    fs.connect(hv605.outlet, pcv606.inlet)
    fs.connect(pcv606.outlet, hv608.inlet)
    fs.connect(hv608.outlet, lpg_out.inlet)

    fs.connect(t_blend.outlet, fe604.inlet, service="E10", sequence=609, size=200,
               schedule=40, spec="CS")
    fs.connect(fe604.outlet, cv604.inlet)
    fs.connect(cv604.outlet, hv604.inlet)
    fs.connect(hv604.outlet, hos601.inlet)
    fs.connect(hos601.outlet, e10_out.inlet)

    fs.connect(vap_in.outlet, hv607.inlet, service="VAP", sequence=610, size=150,
               schedule=40, spec="CS")
    fs.connect(hv607.outlet, fa602.inlet)
    fs.connect(fa602.outlet, v604.inlet)
    # Routed by hand: the drum's outlet faces west and the recovery unit is
    # east, so the drop is put on the drum's own face rather than wherever the
    # router would have turned it.
    fs.connect(v604.outlet, vru_out.inlet, service="VAP", sequence=612, size=150,
               schedule=40, spec="CS").via([(vru_x, vru_y)])
    fs.connect(v604.vent, fa601.inlet, service="VAP", sequence=611, size=150,
               schedule=40, spec="CS")
    fs.connect(fa601.outlet, vt601.inlet)

    # --- Instruments -----------------------------------------------------
    # Gauging first: one transmitter per tank feeding one shared-display
    # indicator, which is what a terminal reads a tank with. Neither closes on a
    # valve -- a storage tank is filled to a target and stopped, not level
    # controlled -- so each loop is a measurement and its display and nothing
    # else, which CHEE4001 p.13 still calls a loop: "a group of components
    # required to perform the desired function of the monitor or control scheme".
    #
    # The alarms those indicators carry are not drawn. ISO 15519-2 5.2.5 is a
    # shall -- "Letter code combinations with modifiers H and L shall be
    # represented outside the PCI symbol" -- and pandid cannot yet write a code
    # string beside a balloon, which is what that asks for; the
    # same deviation is argued at length in examples/11_ethanol_pid.py, and this
    # sheet takes the other branch of it -- leaving them off rather than drawing
    # them as balloons -- because the protection that matters here is the trip
    # below and a row of alarm balloons would read as competing with it.
    lt601 = fs.add_instrument("LT", ms_level, on=tk601, at="W", offset=40)
    fs.add_instrument("LI", ms_level, on=lt601, at="S", offset=50, variant="shared")
    lt602 = fs.add_instrument("LT", eth_level, on=tk602, at="W", offset=32)
    fs.add_instrument("LI", eth_level, on=lt602, at="S", offset=50, variant="shared")

    # The overfill trip, and it is a second measurement rather than a tap off the
    # first. LSHH-611 and LSHH-612 are their own instruments on their own tank
    # connections, driving Z-1 and nothing else, so the protection does not
    # depend on the gauge it exists to back up: CHEE4001 p.20, "For potentially
    # hazardous situations it is better practice to specify a separate trip
    # system", and on the same page, of a safety related alarm, "where they are
    # involved in protecting against mal-operation by the control system they
    # should be independent of the devices they are monitoring".
    #
    # HH and not H. The same page: "the high-high and low-low levels are
    # generally 'reserved' for SIS actions" -- so a switch that acts is lettered
    # for the action, and the high *alarm* would be a different device.
    #
    # Both keep literal numbers. A loop is a measured variable and a number, and
    # what these two initiate is Z-1, which carries the trip's number and not
    # theirs; declaring L-611 would put a loop of exactly one balloon in fs.loops
    # that the drawing does not contain.
    lsh611 = fs.add_instrument("LSHH", 611, on=tk601, at="E", offset=32)
    lsh612 = fs.add_instrument("LSHH", 612, on=tk602, at="E", offset=40)
    # One trip, four squares. Z-1 is a single logic function -- receipt shutdown
    # on high-high level -- and it is drawn at each of the four points it
    # touches: the two switches that initiate it and the two valves it closes.
    # Instrument(variant="sis") is the one symbol allowed to carry its tag more
    # than once, for exactly this reason; see examples/11_ethanol_pid.py, which
    # draws its own Z-1 four times on the same argument. The alternative, a
    # signal line from each switch across the sheet to each valve, would be four
    # runs of dashed line stating that the trip is four different things.
    #
    # Z and not A: a function that acts is lettered S or Z and never A, and I,
    # which a square is sometimes given, is *indicating*, which is the one thing
    # a trip does not do.
    fs.add_instrument("Z", 1, on=lsh611, at="N", offset=40, variant="sis")
    fs.add_instrument("Z", 1, on=lsh612, at="N", offset=40, variant="sis")
    fs.add_instrument("Z", 1, on=xv601, at="S", offset=26, variant="sis")
    fs.add_instrument("Z", 1, on=xv602, at="S", offset=26, variant="sis")

    pt603 = fs.add_instrument("PT", lpg_press, on=v603, at="E", offset=30)
    fs.add_instrument("PI", lpg_press, on=pt603, at="N", offset=40, variant="shared")

    # The balloon over a valve is centred on the valve's own face, so the axis the
    # cascade is routed down is half the valve wide -- not the actuator's offset,
    # which is a hair off centre and would put a 0.05 px slope in a signal line.
    cv604_axis = 1400 + resolve_size(cv604)[0] / 2
    cv605_axis = 1140 + resolve_size(cv605)[0] / 2
    fe604_top = blend_y - port_offset(fe604, "inlet")[1]
    cv604_top = blend_y - port_offset(cv604, "inlet")[1]
    fe605_top = eth_run_y - port_offset(fe605, "inlet")[1]
    cv605_top = eth_run_y - port_offset(cv605, "inlet")[1]

    ft604 = fs.add_instrument("FT", load_flow, on=fe604, at="N", offset=fe604_top - low_row_y)
    fic604 = fs.add_instrument("FIC", load_flow, on=cv604, at="N", variant="shared",
                               offset=cv604_top - balloon_row_y)
    fic604.nozzle("sig_out", "S")
    fs.connect(ft604.sig_out, fic604.sig_in, kind="electric")
    fs.connect(fic604.sig_out, cv604.actuator, kind="pneumatic")

    # The blend is ratio control, so FIC-605 takes its setpoint from FIC-604
    # rather than from an operator: what the ethanol should be doing is a
    # fraction of what the rack is doing, and a fixed setpoint would hold the
    # ratio at exactly one loading rate. That is a cascade and therefore two
    # loops and never one -- the master measures the total and the slave the
    # ethanol -- so a single handle could not have taken both and would have
    # raised on the second of them.
    #
    # The link is kind="software", not a wire: both faceplates are functions of
    # the same DCS and nothing runs between them in the field. Its route is
    # given by hand, because a setpoint is the one signal on this sheet with two
    # equally good paths and the router picks the one that leaves FIC-604 through
    # its last free face.
    ft605 = fs.add_instrument("FT", blend_flow, on=fe605, at="N", offset=fe605_top - balloon_row_y)
    fic605 = fs.add_instrument("FIC", blend_flow, on=cv605, at="N", variant="shared",
                               offset=cv605_top - balloon_row_y)
    fic605.nozzle("sig_out", "S")
    fic605.nozzle("sig_in", "N")
    fs.connect(ft605.sig_out, fic605.pv, kind="electric")
    fs.connect(fic604.sig_out, fic605.sig_in, kind="software").via(
        [(cv604_axis, cascade_y), (cv605_axis, cascade_y)])
    fs.connect(fic605.sig_out, cv605.actuator, kind="pneumatic")

    # --- Sheet furniture -------------------------------------------------
    fs.title_block = TitleBlock(
        title="Tank Farm and Loading",
        subtitle="A600 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-601",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1",
        date="12/12/25",
        drawn_by="AA", checked_by="RG", approved_by="HVL",
        revisions=[
            Revision("A", "28/11/25", "Issued for internal review", "AA"),
            Revision("B", "12/12/25", "Issued For Review", "AA", "RG", "HVL"),
        ],
    )
    fs.add_annotation(Annotation(
        title="EQUIPMENT LIST",
        rows=[("TK-601", "Motor Spirit Storage Tank"),
              ("TK-602", "Denatured Ethanol Storage Tank"),
              ("V-603", "Butane Storage Sphere"),
              ("V-604", "Loading Vapour Knock-Out Drum"),
              ("P-601", "Motor Spirit Transfer Pump"),
              ("P-602", "Ethanol Blend Pump")],
        align="top-right",
    ))
    # General, and general is why they are not numbered: a number in a notes box
    # is a flag note, drawn on the line it applies to, and nothing here puts a
    # reference on a line. What is left is what a general note is for -- what
    # the drawing itself cannot say. A symbol key belongs in the LEGEND box
    # below, and where the trip squares are is visible in the trip squares.
    fs.add_annotation(notes([
        "Z-1: receipt shutdown on tank high-high level.",
        "LSHH-611/612 are independent of the gauging transmitters they back up.",
        "FA-601 is deflagration rated; FA-602, on the rack return, is detonation",
        "rated. VT-601 is the vapour system's only opening to atmosphere.",
        "SB-601 gives TK-602 positive isolation from the blend header.",
        # This one is not a fact about the plant: it stands in for a mark the
        # sheet cannot yet draw, since fail="closed" puts an FC mark whose halo
        # deletes the trip square's impulse line (#223). Delete the note when
        # #223 lands and the mark goes back on XV-601 and XV-602.
        "XV-601 and XV-602 fail closed.",
    ], title="GENERAL NOTES", numbered=False, align="bottom-left"))
    fs.add_annotation(legend({
        "MS": "Motor Spirit",
        "ETH": "Denatured Ethanol",
        "LPG": "Liquefied Petroleum Gas",
        "E10": "Ethanol Blended Motor Spirit",
        "VAP": "Loading Vapour",
        "CS": "Carbon Steel A106-B",
        "SS": "Stainless Steel 316L",
    }, align="top-left"))

    fs.render(out("tank_farm.svg"), page_size="A3", border="zone", diagram="p&id")
    print("Generated tank_farm.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
