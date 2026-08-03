"""
Example 14: Product Storage and Road Loading A600, a bulk liquid tank farm

Three storage vessels, the transfer system that draws them down, the rack that
loads road tankers off it, and the vapour system that takes back what the
loading displaces. Nothing is heated, cooled, reacted or separated, so the
sheet is dense in line hardware the reactor-and-column examples never reach
for: two strainer bodies, a spectacle blind, a compensator, both reducer
bodies, two flame arrestors and a conservation vent.

Motor spirit sits under an external floating roof, denatured ethanol under a
fixed one and butane in a sphere -- three roofs for three vapour pressures.
The first two are pumped to the rack and blended to E10 on ratio control; the
third needs no pump, since the sphere's own pressure is above what the loading
arm works at and ``PCV-606`` lets it down. Every litre loaded displaces a litre
of vapour, which is returned to the knock-out drum ``V-604`` and passed to a
recovery unit rather than vented at the rack.

It is a P&ID because almost all of it is line hardware, and ISO 15519-2 puts
line hardware on one diagram type and not the other: its Table 4 (p. 17), the
PFD, names no valve body, reducer or fitting, while its Table 5 (p. 19), the
P&ID, opens with "specific graphical symbols for process equipment incl. prime
movers ..., valves incl. actuators, connections, etc." and adds "pipe reducers
for change of dimensions, compensators, flow straighteners, mixing paths,
etc.". The same table is why ``P-602`` is drawn as the gear pump it is:
"supplementary information on graphical symbols, if needed, e.g. connections
represent equipment of specific function e.g. gear pump". CHEE4001 p.2 gives
the rest -- "Miscellaneous: vents, drains, special fittings, sampling lines,
reducers, etc".

The overfill trip is the sheet's safety case and is drawn as a separate system
rather than as an alarm on the gauge. CHEE4001 p.20: "For potentially hazardous
situations it is better practice to specify a separate trip system", and, of a
safety-related alarm, "where they are involved in protecting against
mal-operation by the control system they should be independent of the devices
they are monitoring". The same page reserves high-high for SIS actions, which
is why the switches are ``LSHH`` and not ``LSH``.

**Layout.** ISO 15519-1 §12.1 is a *shall* -- connecting lines "straight with a
minimum of bends and crossovers" -- and §13.2 (p. 28) recommends that "the
direction of the main flow should be from left to right or from top to bottom".
Both are what the elevations are chosen for: the receipt to the *furthest* tank
takes the *highest* run and the draw from the *nearest* tank the *lowest*, so
every drop falls through empty paper and the sheet carries no process crossing.
All four feeds enter on the west edge and all three products leave on the east,
the vapour return included, so the main flow reads left to right everywhere.
§13.1's vertical view is why the tanks sit above the pumps and §11.4.2 is why
none of them is turned -- it names symbol 2061, *Open tank*, as a symbol "where
gravity is a functionality", which "must not be turned". Boundary flags sit on
the east or west edge, which is CHEE4001 p.2's preference "to show off-page
connectors horizontally and at the edge of a P&ID".

**How the three vessels are filled**, since each is filled differently and none
of it is a default. ``TK-601``'s roof floats on the liquid, so there is no fixed
roof to weld a nozzle to and the receipt lands on the shell. ``TK-602`` takes
its ethanol over the top through an internal downcomer carried to the floor,
which is what the crown nozzle is asked for by name and what the notes say.
``V-603`` fills low on the shell and draws from the nozzle drawn under its
belly, its crown left to the relief and the vapour connection.

Every vessel here carries five nozzles and none of them is piped for all five: a
declared nozzle is offered rather than asserted, so ``TK-602``'s conservation
vent and ``V-603``'s fire-case relief are drawings this sheet does not make.
CHEE4001 p.8 names the second duty exactly, for "protection against exposure of
a pressure vessel to fire ... usually the case with storage vessels for
non-refrigerated liquefied compressible gases at ambient temperatures".

Nothing in ISO 15519-1, ISO 15519-2 or the CHEE4001 guidelines covers flame
arrestors, conservation vents, floating roofs, tank venting or tank filling at
all, so those choices are engineering and are attributed to nothing.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Feed, Fitting, Flowsheet, Product, Pump, Reducer, Tank, Tee, Valve, Vent, Vessel
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
    # add_loop() with the number left out takes the next from loop_number_start,
    # so the series is L-601, L-602, P-603, F-604, F-605 in the order these five
    # lines read. Nothing re-derives them afterwards: from here on each number is
    # as fixed as a typed one.
    ms_level = fs.add_loop("L")      # L-601, TK-601 level
    eth_level = fs.add_loop("L")     # L-602, TK-602 level
    lpg_press = fs.add_loop("P")     # P-603, V-603 pressure
    load_flow = fs.add_loop("F")     # F-604, loading rate
    blend_flow = fs.add_loop("F")    # F-605, ethanol blend ratio

    # --- Storage ---------------------------------------------------------
    # label_pos="center" on all three: each carries a vent, a relief or a fill on
    # the crown, and a tag written above the tank would be written across them.
    tk601 = fs.add(Tank("TK-601", variant="floating_roof", width=190, height=140,
                        label_pos="center", description="Motor Spirit Storage Tank"))
    tk602 = fs.add(Tank("TK-602", width=180, height=150, label_pos="center",
                        description="Denatured Ethanol Storage Tank"))
    v603 = fs.add(Tank("V-603", variant="sphere", width=140, height=185,
                       label_pos="center", description="Butane Storage Sphere"))
    v604 = fs.add(Vessel("V-604", variant="legs", width=60, height=120,
                         description="Loading Vapour Knock-Out Drum"))

    # --- Rotating --------------------------------------------------------
    p601 = fs.add(Pump("P-601", description="Motor Spirit Transfer Pump"))
    p602 = fs.add(Pump("P-602", variant="gear", width=48, height=76,
                       description="Ethanol Blend Pump"))

    # --- Boundary --------------------------------------------------------
    ms_in = fs.add(Feed("Motor Spirit", reference="P&ID-501"))
    eth_in = fs.add(Feed("Denatured Ethanol", reference="PFD-302"))
    lpg_in = fs.add(Feed("Butane", reference="P&ID-503"))
    e10_out = fs.add(Product("E10 Road Tanker", reference="P&ID-611"))
    lpg_out = fs.add(Product("LPG Road Tanker", reference="P&ID-612"))
    vap_in = fs.add(Feed("Tanker Vapour Return", reference="P&ID-611"))
    vru_out = fs.add(Product("Vapour Recovery Unit", reference="P&ID-609"))

    # --- In-line: motor spirit -------------------------------------------
    # Both receipt valves fail closed on the trip, and say so on the valve.
    xv601 = fs.add(Valve("XV-601", variant="solenoid", fail="closed",
                         description="MS Receipt Trip Valve"))
    xv602 = fs.add(Valve("XV-602", variant="solenoid", fail="closed",
                         description="Ethanol Receipt Trip Valve"))
    hv601 = fs.add(Valve("HV-601", variant="gate", description="TK-601 Root Valve"))
    ej601 = fs.add(Fitting("EJ-601", variant="expansion_joint",
                           description="TK-601 Nozzle Compensator"))
    st601 = fs.add(Fitting("ST-601", variant="strainer_basket",
                           description="P-601 Suction Strainer"))
    # large_end="outlet" is what makes RD-602 an expansion: the same fitting
    # piped round the other way rather than a second symbol, so the run still
    # goes inlet to outlet through both.
    rd601 = fs.add(Reducer("RD-601", variant="eccentric",
                           description="P-601 Suction Reducer"))
    rd602 = fs.add(Reducer("RD-602", variant="concentric", large_end="outlet",
                           description="P-601 Discharge Expander"))
    nrv601 = fs.add(Valve("NRV-601", variant="check", description="P-601 Non-Return Valve"))

    # --- In-line: ethanol ------------------------------------------------
    hv603 = fs.add(Valve("HV-603", variant="gate", description="TK-602 Root Valve"))
    sb601 = fs.add(Fitting("SB-601", variant="blind", description="TK-602 Spectacle Blind"))
    t_rec = fs.add(Tee(branch="inlet"))
    st602 = fs.add(Fitting("ST-602", variant="strainer_y",
                           description="P-602 Suction Strainer"))
    t_psv = fs.add(Tee())
    psv602 = fs.add(Valve("PSV-602", variant="relief", description="P-602 Relief Valve"))
    fe605 = fs.add(Fitting(blend_flow.tag("FE"), variant="coriolis",
                           description="Ethanol Blend Meter"))
    cv605 = fs.add(Valve(blend_flow.tag("CV"), variant="control",
                         description="Ethanol Blend Valve"))
    nrv602 = fs.add(Valve("NRV-602", variant="check", description="P-602 Non-Return Valve"))

    # --- In-line: butane -------------------------------------------------
    hv605 = fs.add(Valve("HV-605", variant="gate", description="V-603 Root Valve"))
    pcv606 = fs.add(Valve("PCV-606", variant="regulator",
                          description="Butane Let-Down Regulator"))
    hv608 = fs.add(Valve("HV-608", variant="ball", description="LPG Loading Arm Valve"))

    # --- In-line: the loading rack ---------------------------------------
    t_blend = fs.add(Tee(branch="inlet"))
    t_blend.new_line_number = True
    # label_pos="bottom" keeps FE-604's tag clear of FT-604, which stands over it.
    fe604 = fs.add(Fitting(load_flow.tag("FE"), variant="positive_displacement",
                           label_pos="bottom", description="Loading Meter"))
    cv604 = fs.add(Valve(load_flow.tag("CV"), variant="control",
                         description="Loading Rate Valve"))
    hv604 = fs.add(Valve("HV-604", variant="ball", description="E10 Loading Arm Valve"))
    # HOS and not HS. ISO 15519-2 Table 2 (p. 11) gives H as a process variable,
    # "Human observation", and S as a control function, "Switching (open loop)",
    # so HS-601 is a well-formed letter code string and tagged this hose as an
    # instrument. HOS breaks at the second letter, which is neither.
    hos601 = fs.add(Fitting("HOS-601", variant="hose", description="E10 Loading Hose"))

    # --- In-line: the vapour system --------------------------------------
    fa602 = fs.add(Fitting("FA-602", variant="flame_arrestor_detonation_proof",
                           description="Vapour Return Flame Arrestor"))
    hv607 = fs.add(Valve("HV-607", variant="butterfly", description="Vapour Header Valve"))
    fa601 = fs.add(Fitting("FA-601", variant="flame_arrestor",
                           description="V-604 Vent Flame Arrestor"))
    vt601 = fs.add(Vent("VT-601", variant="breather", description="V-604 Conservation Vent"))

    # --- Placement -------------------------------------------------------
    # Pinned by nozzle, not by corner: every device is placed with pin(port=...),
    # which asks the symbol where its own nozzle sits, so no rescaling of the
    # artwork can leave a valve off its run.
    tk601.pin(x=360, y=215)
    tk602.pin(x=680, y=205)
    v603.pin(x=1090, y=180)

    # TK-602 is the only one of the three filled over the top, and it says so:
    # the crown is an alternate on a fixed-roof tank and the shell is the
    # default, so a sheet that wants the downcomer arrangement asks for it.
    tk602.nozzle("inlet", "N")

    ms_drop_x = 340.0
    ms_fill_y = 215 + port_offset(tk601, "inlet")[1]
    ms_draw_x = 360 + port_offset(tk601, "outlet")[0]
    eth_fill_x = 680 + port_offset(tk602, "inlet")[0]
    eth_draw_x = 680 + port_offset(tk602, "outlet")[0]
    # The sphere fills low on the west shell and draws from the nozzle under its
    # belly, so the receipt drops clear of the vessel and comes in level.
    lpg_fill_y = 180 + port_offset(v603, "inlet")[1]
    lpg_draw_x = 1090 + port_offset(v603, "outlet")[0]

    ms_recv_y, eth_recv_y, lpg_recv_y = 170.0, 110.0, 50.0
    ms_in.pin(port="outlet", x=200, y=ms_recv_y)
    xv601.pin(port="inlet", x=250, y=ms_recv_y)
    eth_in.pin(port="outlet", x=200, y=eth_recv_y)
    xv602.pin(port="inlet", x=500, y=eth_recv_y)
    lpg_in.pin(port="outlet", x=200, y=lpg_recv_y)

    lpg_run_y, eth_run_y, ms_run_y = 390.0, 510.0, 665.0
    lpg_drop_x = 1040.0
    balloon_row_y, low_row_y, psv_run_y = 462.0, 570.0, 600.0
    cascade_y = 422.0

    hv601.pin(port="inlet", x=495, y=ms_run_y)
    ej601.pin(port="inlet", x=560, y=ms_run_y)
    st601.pin(port="inlet", x=605, y=ms_run_y)
    rd601.pin(port="inlet", x=665, y=ms_run_y)
    # RD-601 is the eccentric body, so its two nozzles are not on one centreline
    # and pinning the pump on ms_run_y put a step in the line immediately
    # downstream of it. The pump is pinned at the *reducer's outlet* elevation
    # instead, asked of the symbol rather than measured off the drawing, so the
    # suction is straight from the strainer to the pump nozzle.
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

    # The return enters on the west edge with the other three feeds and reads
    # left to right into V-604, which un-mirrored puts the drum's inlet and
    # outlet on one centreline: both flags sit on vap_y and the run is straight
    # from edge to edge. HV-607 and FA-602 are walked back from the drum by
    # their own widths, so the two gaps hold whatever the artwork measures.
    vap_y = 830.0
    drum_x, vap_gap = 1255.0, 52.0
    fa602_x = drum_x - vap_gap - port_offset(fa602, "outlet")[0]
    hv607_x = fa602_x - vap_gap - port_offset(hv607, "outlet")[0]
    vap_in.pin(port="outlet", x=200, y=vap_y)
    hv607.pin(port="inlet", x=hv607_x, y=vap_y)
    fa602.pin(port="inlet", x=fa602_x, y=vap_y)
    v604.pin(port="inlet", x=drum_x, y=vap_y)
    vent_x = v604.pin_.x + port_offset(v604, "vent")[0]
    vent_y = v604.pin_.y + port_offset(v604, "vent")[1]
    fa601.pin(orientation=270).pin(port="inlet", x=vent_x, y=vent_y - 22)
    vt601.pin(port="inlet", x=vent_x, y=vent_y - 68)
    vru_out.pin(port="inlet", x=1560, y=vap_y)

    # --- Process lines ---------------------------------------------------
    fs.connect(ms_in.outlet, xv601.inlet, service="MS", sequence=601, size=200,
               schedule=40, spec="CS")
    fs.connect(xv601.outlet, tk601.inlet).via(
        [(ms_drop_x, ms_recv_y), (ms_drop_x, ms_fill_y)])
    fs.connect(eth_in.outlet, xv602.inlet, service="ETH", sequence=602, size=150,
               schedule=40, spec="SS")
    fs.connect(xv602.outlet, tk602.inlet).via([(eth_fill_x, eth_recv_y)])
    fs.connect(lpg_in.outlet, v603.inlet, service="LPG", sequence=603, size=100,
               schedule=80, spec="CS").via([(lpg_drop_x, lpg_recv_y),
                                            (lpg_drop_x, lpg_fill_y)])

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
    fs.connect(v604.outlet, vru_out.inlet, service="VAP", sequence=612, size=150,
               schedule=40, spec="CS")
    fs.connect(v604.vent, fa601.inlet, service="VAP", sequence=611, size=150,
               schedule=40, spec="CS")
    fs.connect(fa601.outlet, vt601.inlet)

    # --- Instruments -----------------------------------------------------
    # The alarms these indicators carry are not drawn. ISO 15519-2 5.2.5 is a
    # shall -- "Letter code combinations with modifiers H and L shall be
    # represented outside the PCI symbol" -- and pandid cannot yet write a code
    # string beside a balloon (#137, #169), so they are left off rather than
    # drawn as balloons that would compete with the trip below.
    lt601 = fs.add_instrument("LT", ms_level, on=tk601, at="W", offset=62)
    fs.add_instrument("LI", ms_level, on=lt601, at="S", offset=50, variant="shared")
    lt602 = fs.add_instrument("LT", eth_level, on=tk602, at="W", offset=32)
    fs.add_instrument("LI", eth_level, on=lt602, at="S", offset=50, variant="shared")

    # Both switches keep literal numbers. What they initiate is Z-1, which
    # carries the trip's number and not theirs, so declaring L-611 would put a
    # loop of exactly one balloon in fs.loops that the drawing does not contain.
    lsh611 = fs.add_instrument("LSHH", 611, on=tk601, at="E", offset=32)
    lsh612 = fs.add_instrument("LSHH", 612, on=tk602, at="E", offset=40)
    # Instrument(variant="sis") is the one symbol allowed to carry its tag more
    # than once, so Z-1 is drawn at each of the four points it acts on rather
    # than wired across the sheet from each switch to each valve.
    fs.add_instrument("Z", 1, on=lsh611, at="N", offset=40, variant="sis")
    fs.add_instrument("Z", 1, on=lsh612, at="N", offset=40, variant="sis")
    # 46 and not 26: FC is written directly below each valve (PIP PIC001
    # 4.2.4.6) and the square has to hang below the mark, not on it.
    fs.add_instrument("Z", 1, on=xv601, at="S", offset=46, variant="sis")
    fs.add_instrument("Z", 1, on=xv602, at="S", offset=46, variant="sis")

    pt603 = fs.add_instrument("PT", lpg_press, on=v603, at="E", offset=30)
    fs.add_instrument("PI", lpg_press, on=pt603, at="N", offset=40, variant="shared")

    # The balloon over a valve is centred on the valve's own face, so the axis
    # the cascade is routed down is half the valve wide -- not the actuator's
    # offset, which is a hair off centre and would put a 0.05 px slope in a
    # signal line.
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

    # The blend is ratio control, so FIC-605 takes its setpoint from FIC-604.
    # kind="software" and not a wire: both faceplates are functions of the same
    # DCS and nothing runs between them in the field. Its route is given by hand
    # because the router leaves FIC-604 through its last free face instead.
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
    # scale="NTS" rather than left blank: a blank cell makes the sheet report the
    # ratio it was fitted at, and CHEE4001 p.2 is flat about that -- "Do not
    # represent the real length of pipes on P&IDs. P&ID is a 'Not to Scale'
    # (NTS) drawing." The date is stated for the same reason a fixture pins one:
    # left blank the renderer fills in today's.
    #
    # All three sets of initials are fictional, as they are on 03 and 09. AA is
    # the repo's author.
    fs.title_block = TitleBlock(
        title="Tank Farm and Loading",
        subtitle="A600 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-601",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1", scale="NTS",
        date="12/12/25",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "28/11/25", "Issued for internal review", "AA"),
            Revision("B", "12/12/25", "Issued For Review", "AA", "JS", "RL"),
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
    # Unnumbered, because a number in a notes box is a flag note drawn on the
    # line it applies to and nothing here puts a reference on a line. Each note
    # states something the drawing cannot: a symbol key belongs in the LEGEND
    # box and where the trip squares are is visible.
    fs.add_annotation(notes([
        "Z-1: receipt shutdown on tank high-high level.",
        "LSHH-611/612 are independent of the gauging transmitters they back up.",
        "FA-601 is deflagration rated; FA-602, on the rack return, is detonation",
        "rated. VT-601 is the vapour system's only opening to atmosphere.",
        "SB-601 gives TK-602 positive isolation from the blend header.",
        "TK-602 is filled through an internal downcomer carried to the floor.",
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
