"""
Example 20: Gas Dehydration A500, two molecular sieve driers as a P&ID

Wet natural gas is dried over 4A molecular sieve before it goes to the
cold end of an NGL plant. One bed is on line and the other is being
regenerated, and every eight hours the sequence swaps them. Wet gas
flows down through the on-line bed and hot regeneration gas up through
the other, entering at ``reflux_in`` and ``boilup_in``.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    AirCooledExchanger,
    Compressor,
    ControlValve,
    DistillationColumn,
    Feed,
    Flowsheet,
    Furnace,
    KnockoutDrum,
    Product,
    SolenoidValve,
    Tee,
)
from pandid.document import Revision, TitleBlock, equipment_list, legend, notes
from pandid.portgeom import pinned_x, pinned_y, port_offset


def main():
    fs = Flowsheet("Gas Dehydration A500", line_number_start=501)

    # --- Control loops ------------------------------------------------
    temp503 = fs.add_loop("T", 503)     # regeneration gas outlet temperature
    level504 = fs.add_loop("L", 504)    # regeneration separator level

    # --- Equipment ----------------------------------------------------
    # Two identical packed beds.
    bed_a = fs.add(DistillationColumn("V-501A", internals="packing", trays=1, width=90,
                                      height=200,
                                      description="Molecular Sieve Drier A"))
    bed_b = fs.add(DistillationColumn("V-501B", internals="packing", trays=1, width=90,
                                      height=200,
                                      description="Molecular Sieve Drier B"))

    heater = fs.add(Furnace("H-501", description="Regeneration Gas Heater"))
    regen_cooler = fs.add(AirCooledExchanger(
        "E-501", description="Regeneration Gas Cooler"))
    regen_sep = fs.add(KnockoutDrum(
        "V-502", description="Regeneration Gas Separator"))
    regen_k = fs.add(Compressor("K-501",
                                description="Regeneration Gas Blower"))

    wet_gas = fs.add(Feed("Wet Feed Gas", reference="P&ID-401"))
    fuel = fs.add(Feed("FGSH", header=True))
    dry_gas = fs.add(Product("Dry Gas to NGL Recovery", reference="P&ID-601"))
    water = fs.add(Product("Free Water to Disposal", reference="P&ID-902"))

    # --- Switching valves ---------------------------------------------
    # Four per bed: two put it on line, two on regeneration.
    xv501a = fs.add(SolenoidValve("XV-501A", fail="closed",
                                  description="V-501A Wet Gas Inlet Valve"))
    xv501b = fs.add(SolenoidValve("XV-501B", fail="closed",
                                  description="V-501B Wet Gas Inlet Valve"))
    xv502a = fs.add(SolenoidValve("XV-502A", fail="closed",
                                  description="V-501A Dry Gas Outlet Valve"))
    xv502b = fs.add(SolenoidValve("XV-502B", fail="closed",
                                  description="V-501B Dry Gas Outlet Valve"))
    xv503a = fs.add(SolenoidValve("XV-503A", fail="closed",
                                  description="V-501A Regeneration Gas Inlet Valve"))
    xv503b = fs.add(SolenoidValve("XV-503B", fail="closed",
                                  description="V-501B Regeneration Gas Inlet Valve"))
    xv504a = fs.add(SolenoidValve("XV-504A", fail="closed",
                                  description="V-501A Regeneration Gas Outlet Valve"))
    xv504b = fs.add(SolenoidValve("XV-504B", fail="closed",
                                  description="V-501B Regeneration Gas Outlet Valve"))

    cv503 = fs.add(ControlValve(temp503.tag("CV"), fail="closed",
                                description="H-501 Fuel Gas Control Valve"))
    cv504 = fs.add(ControlValve(level504.tag("CV"), fail="closed",
                                description="V-502 Water Draw Control Valve"))

    # --- Header junctions ---------------------------------------------
    t_wet_in = fs.add(Tee(branch="inlet"))     # regeneration gas rejoins here
    t_wet_a = fs.add(Tee())                    # wet gas splits to bed A
    t_dry = fs.add(Tee(branch="inlet"))        # the two dry gas legs meet
    t_regen_out = fs.add(Tee(branch="inlet"))  # the two spent regen legs meet
    t_regen_in = fs.add(Tee())                 # hot regen gas splits to bed A
    t_slip = fs.add(Tee())                     # the regeneration slipstream

    # --- Placement ----------------------------------------------------
    # Four headers with the beds between them; bed A is mirrored so each
    # bed's side nozzles face its own half of the sheet.
    regen_out_y = 130.0
    wet_y = 220.0
    bed_y = 300.0
    regen_in_y = 590.0
    dry_y = 700.0
    regen_run_y = 900.0

    bed_a.pin(mirrored=True).pin(x=460, y=bed_y)
    bed_b.pin(x=940, y=bed_y)
    a_axis = 460 + port_offset(bed_a, "overhead")[0]
    b_axis = 940 + port_offset(bed_b, "overhead")[0]
    top_in_y = bed_y + port_offset(bed_a, "reflux_in")[1]
    bot_in_y = bed_y + port_offset(bed_a, "boilup_in")[1]
    a_leg_x, b_leg_x = 380.0, 1110.0

    wet_gas.pin(port="outlet", x=120, y=wet_y)
    # Branch north; the branch pins the riser's x, the outlet the header.
    t_wet_in.pin(mirrored="y").pin(port="branch", x=250).pin(
        port="outlet", y=wet_y)
    t_wet_a.pin(port="inlet", x=a_leg_x - 6, y=wet_y)
    xv501a.pin(port="inlet", x=400, y=top_in_y)
    xv501b.pin(mirrored=True).pin(port="inlet", x=1090, y=top_in_y)

    # orientation=90 puts the inlet on top, 270 underneath.
    xv502a.pin(orientation=90).pin(port="inlet", x=a_axis, y=640)
    xv502b.pin(orientation=90).pin(port="inlet", x=b_axis, y=640)
    xv504a.pin(orientation=270).pin(port="inlet", x=a_axis, y=190)
    xv504b.pin(orientation=270).pin(port="inlet", x=b_axis, y=190)
    xv503a.pin(port="inlet", x=400, y=bot_in_y)
    xv503b.pin(mirrored=True).pin(port="inlet", x=1090, y=bot_in_y)

    t_dry.pin(mirrored="y").pin(port="branch", x=b_axis).pin(
        port="outlet", y=dry_y)
    t_regen_out.pin(port="branch", x=b_axis).pin(port="outlet", y=regen_out_y)
    # Branch north, towards bed A's lower nozzle.
    t_regen_in.pin(mirrored="y").pin(port="branch", x=a_leg_x).pin(
        port="outlet", y=regen_in_y)
    t_slip.pin(port="inlet", x=1250, y=dry_y)
    dry_gas.pin(port="inlet", x=1560, y=dry_y)

    # Mirrored so the coil inlet faces the slipstream from the east.
    heater.pin(mirrored=True).pin(port="inlet", x=420, y=regen_run_y)
    heater_out_y = pinned_y(heater, "outlet")
    fuel_x = pinned_x(heater, "fuel")
    fuel.pin(port="outlet", x=140, y=1030)
    cv503.pin(port="inlet", x=250, y=1030)

    regen_cooler.pin(port="tube_in", x=1250, y=regen_out_y)
    regen_sep.pin(port="feed", x=1440, y=regen_out_y)
    sep_vapor_x = pinned_x(regen_sep, "vapor")
    sep_liquid_x = pinned_x(regen_sep, "liquid")
    regen_k.pin(port="suction", x=1620, y=60)
    cv504.pin(port="inlet", x=1520, y=310)
    water.pin(port="inlet", x=1700, y=310)

    # --- The wet gas header -------------------------------------------
    fs.connect(wet_gas.outlet, t_wet_in.inlet, size=400, service="WG",
               sequence=501, spec="CS")
    fs.connect(t_wet_in.outlet, t_wet_a.inlet, size=400, service="WG",
               sequence=502, spec="CS")
    # Each leg off a header takes its own line number.
    fs.connect(t_wet_a.branch, xv501a.inlet, size=400, service="WG",
               sequence=516, spec="CS").via(
                   [(a_leg_x, wet_y), (a_leg_x, top_in_y)])
    fs.connect(xv501a.outlet, bed_a.reflux_in)
    fs.connect(t_wet_a.outlet, xv501b.inlet, size=400, service="WG",
               sequence=517, spec="CS").via(
                   [(b_leg_x, wet_y), (b_leg_x, top_in_y)])
    fs.connect(xv501b.outlet, bed_b.reflux_in)

    # --- The dry gas header -------------------------------------------
    fs.connect(bed_a.bottoms, xv502a.inlet, size=400, service="DG",
               sequence=503, spec="CS")
    fs.connect(xv502a.outlet, t_dry.inlet).via([(a_axis, dry_y)])
    fs.connect(bed_b.bottoms, xv502b.inlet, size=400, service="DG",
               sequence=504, spec="CS")
    fs.connect(xv502b.outlet, t_dry.branch)
    dry_header = fs.connect(t_dry.outlet, t_slip.inlet, size=400,
                            service="DG", sequence=505, spec="CS")
    fs.connect(t_slip.outlet, dry_gas.inlet, size=400, service="DG",
               sequence=520, spec="CS")

    # --- The regeneration circuit -------------------------------------
    # A slipstream of dry gas regenerates the off-line bed.
    fs.connect(t_slip.branch, heater.inlet, size=200, service="RG",
               sequence=506, spec="CS").via(
                   [(1256, regen_run_y), (420, regen_run_y)])
    fs.connect(fuel.outlet, cv503.inlet, size=50, service="FG", sequence=507,
               spec="CS")
    fs.connect(cv503.outlet, heater.fuel).via([(fuel_x, 1030)])

    hot_regen = fs.connect(heater.outlet, t_regen_in.inlet, size=200,
                           service="RG", sequence=508, spec="LT").via(
                               [(200, heater_out_y), (200, regen_in_y)])
    fs.connect(t_regen_in.branch, xv503a.inlet, size=200, service="RG",
               sequence=518, spec="LT").via([(a_leg_x, bot_in_y)])
    fs.connect(xv503a.outlet, bed_a.boilup_in)
    fs.connect(t_regen_in.outlet, xv503b.inlet, size=200, service="RG",
               sequence=519, spec="LT").via(
                   [(b_leg_x, regen_in_y), (b_leg_x, bot_in_y)])
    fs.connect(xv503b.outlet, bed_b.boilup_in)

    # Spent regeneration gas leaves through the crown.
    fs.connect(bed_a.overhead, xv504a.inlet, size=200, service="RG",
               sequence=509, spec="LT")
    fs.connect(xv504a.outlet, t_regen_out.inlet).via([(a_axis, regen_out_y)])
    fs.connect(bed_b.overhead, xv504b.inlet, size=200, service="RG",
               sequence=510, spec="LT")
    fs.connect(xv504b.outlet, t_regen_out.branch)
    fs.connect(t_regen_out.outlet, regen_cooler.tube_in, size=200,
               service="RG", sequence=511, spec="LT")

    fs.connect(regen_cooler.tube_out, regen_sep.feed, size=200, service="RG",
               sequence=512, spec="CS")
    fs.connect(regen_sep.liquid, cv504.inlet, size=50, service="PW",
               sequence=513, spec="CS").via([(sep_liquid_x, 310)])
    fs.connect(cv504.outlet, water.inlet)
    fs.connect(regen_sep.vapor, regen_k.suction, size=200, service="RG",
               sequence=514, spec="CS").via([(sep_vapor_x, 60)])
    # The regeneration gas rejoins the wet gas ahead of the beds.
    fs.connect(regen_k.discharge, t_wet_in.branch, size=200, service="RG",
               sequence=515, spec="CS", draw_as_recycle=True).via(
                   [(1690, 20), (250, 20)])

    # --- The drier switching sequence ---------------------------------
    # KC-501 is the sequence; one KY-501 logic square at each valve.
    kc501 = fs.add_instrument("KC", 501, near=bed_a, face="W", offset=170,
                              variant="shared",
                              description="Drier Switching Sequence")
    kc501.annotate(high="KAH")
    # Each square's face keeps it off its valve's FC mark.
    for valve, face in ((xv501a, "N"), (xv501b, "N"),
                        (xv502a, "W"), (xv502b, "W"),
                        (xv503a, "N"), (xv503b, "N"),
                        (xv504a, "W"), (xv504b, "W")):
        fs.add_instrument("KY", 501, acting_on=valve, face=face, offset=34,
                          variant="logic")

    # --- Loop 503: the regeneration gas temperature -------------------
    # Tap the riser out of the heater.
    tt503 = fs.add_instrument("TT", temp503, sensing=hot_regen, at=0.5,
                              offset=70)
    tic503 = fs.add_instrument("TIC", temp503, near=tt503, face="S", offset=70,
                               variant="shared")
    tic503.annotate(high="TAH")
    fs.connect(tt503.sig_out, tic503.sig_in, kind="electric")
    fs.connect(tic503.sig_out, cv503.actuator, kind="pneumatic")

    # --- Loop 504: the separator level --------------------------------
    lt504 = fs.add_instrument("LT", level504, sensing=regen_sep, face="E",
                              offset=60)
    lic504 = fs.add_instrument("LIC", level504, near=lt504, face="S", offset=70,
                               variant="shared")
    lic504.annotate(high="LAH", low="LAL")
    fs.connect(lt504.sig_out, lic504.sig_in, kind="electric")
    fs.connect(lic504.sig_out, cv504.actuator, kind="pneumatic")

    # --- The outlet moisture analyser ---------------------------------
    # angle=-90 hangs the tap under its run, clear of the regen header.
    at502 = fs.add_instrument("AT", 502, sensing=dry_header, at=0.4, offset=60,
                              angle=-90)
    ai502 = fs.add_instrument("AI", 502, near=at502, face="S", offset=60,
                              variant="shared",
                              description="Dry Gas Moisture Analyser")
    ai502.annotate(high="AAH")
    fs.connect(at502.sig_out, ai502.sig_in, kind="electric")

    # --- Sheet furniture ----------------------------------------------
    fs.title_block = TitleBlock(
        title="Gas Dehydration",
        subtitle="A500 Process & Instrumentation Diagram 1",
        drawing_number="P&ID-501",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1", scale="NTS",
        date="24/03/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "05/03/26", "Issued for internal review", "AA"),
            Revision("B", "24/03/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )
    fs.add_annotation(equipment_list(fs, align="top-right", include=[
        "V-501A", "V-501B", "H-501", "E-501", "V-502", "K-501",
    ]))
    fs.add_annotation(notes([
        "KY-501 is one logic function drawn at each valve it strokes; "
        "the sequence is KC-501.",
        "Cycle: 8 h adsorption, 5 h heating, 2 h cooling, 1 h standby. "
        "AAH-502 shortens the adsorption step.",
        "V-501A and V-501B are identical vessels. Neither drawing says "
        "which is on line; the sequence does.",
    ], title="GENERAL NOTES", numbered=False, align="bottom-left"))
    fs.add_annotation(legend({
        "CS": "Carbon Steel A106-B",
        "LT": "Low Temperature Carbon Steel A333-6",
        "WG": "Wet Feed Gas",
        "DG": "Dry Gas",
        "RG": "Regeneration Gas",
        "FG": "Fuel Gas",
        "PW": "Produced Water",
        "FGSH": "Fuel Gas Supply Header",
    }, align="top-left"))

    fs.render(out("molecular_sieve_dryer.svg"), border="zone", diagram="p&id")
    print("Generated molecular_sieve_dryer.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
