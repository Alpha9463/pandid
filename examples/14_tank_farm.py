"""
Example 14: Product Storage and Road Loading A600 (draft docstring)
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import Flowsheet, units
from pandid.document import Annotation, Revision, TitleBlock, legend, notes
from pandid.portgeom import port_offset


def main():
    fs = Flowsheet(
        "Product Storage and Road Loading A600",
        line_numbering_scheme="{service}-{sequence}-{size}-{schedule}-{spec}",
        line_number_start=601,
        loop_number_start=601,
    )

    # --- Control loops ---------------------------------------------------
    ms_level = fs.add_loop("L")      # L-601, TK-601 level
    eth_level = fs.add_loop("L")     # L-602, TK-602 level
    lpg_press = fs.add_loop("P")     # P-603, V-603 pressure
    load_flow = fs.add_loop("F")     # F-604, loading rate
    blend_flow = fs.add_loop("F")    # F-605, ethanol blend ratio

    # --- Storage ---------------------------------------------------------
    tk601 = fs.add(units.Tank("TK-601", variant="floating_roof", width=190, height=140,
                              label_pos="center", description="Motor Spirit Storage Tank"))
    tk602 = fs.add(units.Tank("TK-602", width=180, height=150, label_pos="center",
                              description="Denatured Ethanol Storage Tank"))
    v603 = fs.add(units.Tank("V-603", variant="sphere", width=140, height=185,
                             label_pos="center", description="Butane Storage Sphere"))
    v604 = fs.add(units.Vessel("V-604", variant="legs", width=60, height=120,
                               description="Loading Vapour Knock-Out Drum"))

    # --- Rotating --------------------------------------------------------
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
    xv601 = fs.add(units.Valve("XV-601", variant="solenoid", description="MS Receipt Trip Valve"))
    hv601 = fs.add(units.Valve("HV-601", variant="gate", description="TK-601 Root Valve"))
    ej601 = fs.add(units.Fitting("EJ-601", variant="expansion_joint",
                                 description="TK-601 Nozzle Compensator"))
    st601 = fs.add(units.Fitting("ST-601", variant="strainer_basket",
                                 description="P-601 Suction Strainer"))
    rd601 = fs.add(units.Reducer("RD-601", variant="eccentric",
                                 description="P-601 Suction Reducer"))
    rd602 = fs.add(units.Reducer("RD-602", variant="concentric", large_end="outlet",
                                 description="P-601 Discharge Expander"))
    nrv601 = fs.add(units.Valve("NRV-601", variant="check", description="P-601 Non-Return Valve"))

    # --- In-line: ethanol ------------------------------------------------
    hv603 = fs.add(units.Valve("HV-603", variant="gate", description="TK-602 Root Valve"))
    sb601 = fs.add(units.Fitting("SB-601", variant="blind", description="TK-602 Spectacle Blind"))
    t_rec = fs.add(units.Tee(branch="inlet"))
    st602 = fs.add(units.Fitting("ST-602", variant="strainer_y",
                                 description="P-602 Suction Strainer"))
    t_psv = fs.add(units.Tee())
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

    # --- In-line: the loading rack ---------------------------------------
    t_blend = fs.add(units.Tee(branch="inlet"))
    fe604 = fs.add(units.Fitting(load_flow.tag("FE"), variant="positive_displacement",
                                 label_pos="bottom", description="Loading Meter"))
    cv604 = fs.add(units.Valve(load_flow.tag("CV"), variant="control",
                               description="Loading Rate Valve"))
    hv604 = fs.add(units.Valve("HV-604", variant="ball", description="E10 Loading Arm Valve"))
    hs601 = fs.add(units.Fitting("HS-601", variant="hose", description="E10 Loading Hose"))

    # --- In-line: the vapour system --------------------------------------
    fa602 = fs.add(units.Fitting("FA-602", variant="flame_arrestor_detonation_proof",
                                 description="Vapour Return Flame Arrestor"))
    hv607 = fs.add(units.Valve("HV-607", variant="butterfly", description="Vapour Header Valve"))
    fa601 = fs.add(units.Fitting("FA-601", variant="flame_arrestor",
                                 description="V-604 Vent Flame Arrestor"))
    vt601 = fs.add(units.Vent("VT-601", variant="breather", description="V-604 Conservation Vent"))

    # --- Placement -------------------------------------------------------
    tk601.pin(x=360, y=215)
    tk602.pin(x=680, y=205)
    v603.pin(x=1090, y=180)

    ms_fill_x = 360 + port_offset(tk601, "inlet")[0]
    ms_draw_x = 360 + port_offset(tk601, "outlet")[0]
    eth_fill_x = 680 + port_offset(tk602, "inlet")[0]
    eth_draw_x = 680 + port_offset(tk602, "outlet")[0]
    lpg_fill_x = 1090 + port_offset(v603, "inlet")[0]
    lpg_draw_x = 1090 + port_offset(v603, "outlet")[0]

    ms_recv_y, eth_recv_y, lpg_recv_y = 175.0, 115.0, 55.0
    ms_in.pin(port="outlet", x=200, y=ms_recv_y)
    xv601.pin(port="inlet", x=250, y=ms_recv_y)
    eth_in.pin(port="outlet", x=200, y=eth_recv_y)
    lpg_in.pin(port="outlet", x=200, y=lpg_recv_y)

    lpg_run_y, eth_run_y, ms_run_y = 390.0, 510.0, 665.0
    balloon_row_y, low_row_y, psv_run_y = 445.0, 570.0, 600.0

    hv601.pin(port="inlet", x=495, y=ms_run_y)
    ej601.pin(port="inlet", x=560, y=ms_run_y)
    st601.pin(port="inlet", x=605, y=ms_run_y)
    rd601.pin(port="inlet", x=665, y=ms_run_y)
    p601.pin(port="suction", x=705, y=ms_run_y)
    ms_disch_y = ms_run_y + port_offset(p601, "discharge")[1] - port_offset(p601, "suction")[1]
    rd602.pin(port="inlet", x=795, y=ms_disch_y)
    nrv601.pin(port="inlet", x=875, y=ms_disch_y)

    hv603.pin(port="inlet", x=800, y=eth_run_y)
    sb601.pin(port="inlet", x=850, y=eth_run_y)
    t_rec.pin(port="inlet", x=890, y=eth_run_y)
    st602.pin(port="inlet", x=918, y=eth_run_y)
    p602.pin(port="suction", x=965, y=eth_run_y)
    t_psv.pin(port="inlet", x=1025, y=eth_run_y)
    fe605.pin(port="inlet", x=1045, y=eth_run_y)
    cv605.pin(port="inlet", x=1105, y=eth_run_y)
    nrv602.pin(port="inlet", x=1148, y=eth_run_y)
    psv_branch_x = t_psv.pin_.x + port_offset(t_psv, "branch")[0]
    rec_branch_x = t_rec.pin_.x + port_offset(t_rec, "branch")[0]
    psv602.pin(port="inlet", x=rec_branch_x, y=psv_run_y)

    hv605.pin(port="inlet", x=1190, y=lpg_run_y)
    pcv606.pin(port="inlet", x=1255, y=lpg_run_y)
    hv608.pin(port="inlet", x=1340, y=lpg_run_y)
    lpg_out.pin(port="inlet", x=1540, y=lpg_run_y)

    blend_y = ms_disch_y
    t_blend.pin(mirrored="y").pin(port="inlet", x=1180, y=blend_y)
    blend_branch_x = t_blend.pin_.x + port_offset(t_blend, "branch")[0]
    fe604.pin(port="inlet", x=1215, y=blend_y)
    cv604.pin(port="inlet", x=1275, y=blend_y)
    hv604.pin(port="inlet", x=1340, y=blend_y)
    hs601.pin(port="inlet", x=1420, y=blend_y)
    e10_out.pin(port="inlet", x=1540, y=blend_y)

    vap_y = 775.0
    vap_in.pin(mirrored=True).pin(port="outlet", x=1540, y=vap_y)
    hv607.pin(mirrored=True).pin(port="inlet", x=590, y=vap_y)
    fa602.pin(mirrored=True).pin(port="inlet", x=490, y=vap_y)
    v604.pin(mirrored=True).pin(port="inlet", x=405, y=vap_y)
    vent_x = v604.pin_.x + port_offset(v604, "vent")[0]
    vent_y = v604.pin_.y + port_offset(v604, "vent")[1]
    fa601.pin(orientation=270).pin(port="inlet", x=vent_x, y=vent_y - 22)
    vt601.pin(port="inlet", x=vent_x, y=vent_y - 68)
    vru_out.pin(mirrored=True).pin(port="inlet", x=335, y=vap_y)

    # --- Process lines ---------------------------------------------------
    fs.connect(ms_in.outlet, xv601.inlet, service="MS", sequence=601, size=200,
               schedule=40, spec="CS")
    fs.connect(xv601.outlet, tk601.inlet).via([(ms_fill_x, ms_recv_y)])
    fs.connect(eth_in.outlet, tk602.inlet, service="ETH", sequence=602, size=150,
               schedule=40, spec="SS").via([(eth_fill_x, eth_recv_y)])
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
    fs.connect(hv604.outlet, hs601.inlet)
    fs.connect(hs601.outlet, e10_out.inlet)

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
    lt601 = fs.add_instrument("LT", ms_level, on=tk601, at="W", offset=40)
    fs.add_instrument("LI", ms_level, on=lt601, at="S", offset=50, variant="shared")
    lsh611 = fs.add_instrument("LSHH", 611, on=tk601, at="E", offset=40)
    fs.add_instrument("Z", 1, on=lsh611, at="N", offset=40, variant="sis")
    fs.add_instrument("Z", 1, on=xv601, at="S", offset=26, variant="sis")

    lt602 = fs.add_instrument("LT", eth_level, on=tk602, at="E", offset=40)
    fs.add_instrument("LI", eth_level, on=lt602, at="S", offset=50, variant="shared")

    pt603 = fs.add_instrument("PT", lpg_press, on=v603, at="E", offset=30)
    fs.add_instrument("PI", lpg_press, on=pt603, at="N", offset=40, variant="shared")

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

    ft605 = fs.add_instrument("FT", blend_flow, on=fe605, at="N", offset=fe605_top - balloon_row_y)
    fic605 = fs.add_instrument("FIC", blend_flow, on=cv605, at="N", variant="shared",
                               offset=cv605_top - balloon_row_y)
    fic605.nozzle("sig_out", "S")
    fs.connect(ft605.sig_out, fic605.pv, kind="electric")
    fs.connect(fic604.sig_out, fic605.sig_in, kind="software").via([(1200, balloon_row_y)])
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
    fs.add_annotation(notes([
        "Placeholder note.",
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
