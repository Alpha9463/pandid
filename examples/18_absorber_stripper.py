"""
Example 18: Amine Sweetening A400, an absorber and its regenerator

Sour natural gas is contacted counter-currently with lean MDEA in
T-401, leaves the top on specification, and the acid gas it gave up
leaves the plant as the regenerator's overhead. The solvent is the
circuit: rich amine off the contactor's bottom is let down to near
atmospheric pressure, picks up heat from the returning lean amine in
E-401, is stripped in T-402 over the reboiler E-403, and is pumped back
up to contactor pressure through the trim cooler E-404.

T-401 is an ``Absorber`` with valve trays; T-402 is a packed
``DistillationColumn`` with its condenser E-402 and reflux drum V-401.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Absorber,
    Condenser,
    ControlValve,
    DistillationColumn,
    Feed,
    Flowsheet,
    KettleReboiler,
    Product,
    Pump,
    ShellAndTubeExchanger,
    Vessel,
)
from pandid.document import Revision, TableBox, TitleBlock, equipment_list
from pandid.portgeom import pinned_x, pinned_y, port_offset

# --- Stream property table --------------------------------------------
# An empty value renders as "-".
PROPERTY_ROWS = (
    "Temperature (C)", "Pressure (bara)", "Vapour Fraction", "Total Flow (kg/s)",
    "Methane", "Ethane", "CO2", "H2S", "MDEA", "Water",
)

PROPERTIES = {
    "S-401": ("40", "66.0", "1.000", "30.00", "0.900", "0.040", "0.050",
              "0.010", "", ""),
    "S-402": ("46", "65.4", "1.000", "28.31", "0.953", "0.042", "0.003",
              "2.0E-06", "", "0.002"),
    "S-403": ("45", "68.0", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04",
              "0.449", "0.550"),
    "S-404": ("62", "65.8", "0.000", "121.7", "", "", "0.0136", "2.55E-03",
              "0.443", "0.542"),
    "S-405": ("97", "1.90", "0.012", "121.7", "", "", "0.0136", "2.55E-03",
              "0.443", "0.542"),
    "S-406": ("104", "1.85", "1.000", "6.02", "", "", "0.276", "0.052", "",
              "0.672"),
    "S-407": ("50", "1.80", "0.286", "6.02", "", "", "0.276", "0.052", "",
              "0.672"),
    "S-408": ("50", "1.75", "1.000", "1.72", "", "", "0.850", "0.110", "",
              "0.040"),
    "S-409": ("50", "1.80", "0.000", "4.30", "", "", "0.047", "0.029", "",
              "0.924"),
    "S-410": ("122", "2.00", "0.000", "148.5", "", "", "1.42E-03", "1.2E-04",
              "0.363", "0.636"),
    "S-411": ("124", "2.02", "1.000", "28.5", "", "", "5.0E-03", "4.0E-04",
              "", "0.995"),
    "S-412": ("122", "2.00", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04",
              "0.449", "0.550"),
    "S-413": ("75", "1.60", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04",
              "0.449", "0.550"),
    "S-414": ("76", "70.0", "0.000", "120.0", "", "", "1.20E-03", "1.0E-04",
              "0.449", "0.550"),
    "S-415": ("152", "5.00", "1.000", "11.30", "", "", "", "", "", "1.000"),
    "S-416": ("151", "4.90", "0.000", "11.30", "", "", "", "", "", "1.000"),
    "S-417": ("25", "4.00", "0.000", "72.4", "", "", "", "", "", "1.000"),
    "S-418": ("40", "3.40", "0.000", "72.4", "", "", "", "", "", "1.000"),
    "S-419": ("25", "4.00", "0.000", "196.3", "", "", "", "", "", "1.000"),
    "S-420": ("40", "3.40", "0.000", "196.3", "", "", "", "", "", "1.000"),
}


def main():
    fs = Flowsheet("Amine Sweetening A400")

    # --- Equipment ----------------------------------------------------
    # Lean amine enters over stage 1 (feed_1), sour gas under stage 20.
    contactor = fs.add(Absorber("T-401", internals="valve_tray", trays=20,
                                n_feeds=2, feed_stages=[1, 20],
                                width=110, height=340,
                                description="Amine Contactor"))
    regen = fs.add(DistillationColumn("T-402", internals="packing", trays=2,
                                      width=110, height=300,
                                      description="Amine Regenerator"))

    # Rich amine tube side, lean amine shell side.
    cross = fs.add(ShellAndTubeExchanger("E-401", variant="straight_tubes", width=140,
                                         height=44,
                                         description="Lean / Rich Exchanger"))
    ovhd = fs.add(Condenser("E-402", width=70,
                            height=70,
                            description="Regenerator Overhead Condenser"))
    drum = fs.add(Vessel("V-401", variant="horizontal", width=120, height=40,
                         description="Reflux Drum"))
    reboiler = fs.add(KettleReboiler("E-403", width=130,
                                     height=46,
                                     description="Regenerator Reboiler"))
    trim = fs.add(ShellAndTubeExchanger("E-404", variant="straight_tubes", width=130,
                                        height=40, description="Lean Amine Cooler"))
    lean_pump = fs.add(Pump("P-401A/B", description="Lean Solvent Pump"))
    reflux_pump = fs.add(Pump("P-402A/B", description="Reflux Pump"))

    # The let-down from contactor to regenerator pressure.
    letdown = fs.add(ControlValve("LV-401",
                                  description="Rich Amine Level Control Valve"))

    sour = fs.add(Feed("Sour Gas", reference="PFD-301"))
    steam = fs.add(Feed("LP Steam", reference="PFD-901"))
    # header=True lets several flags name the same header.
    cws_ovhd = fs.add(Feed("CWS", header=True))
    cws_trim = fs.add(Feed("CWS", header=True))
    sweet = fs.add(Product("Sweet Gas", reference="PFD-501"))
    acid = fs.add(Product("Acid Gas to SRU", reference="PFD-601"))
    condensate = fs.add(Product("Steam Condensate", reference="PFD-901"))
    cwr_ovhd = fs.add(Product("CWR", header=True))
    cwr_trim = fs.add(Product("CWR", header=True))

    # --- Placement ----------------------------------------------------
    contactor.pin(x=300, y=250)
    lean_in_y = 250 + port_offset(contactor, "feed_1")[1]
    gas_in_y = 250 + port_offset(contactor, "feed_2")[1]
    contactor_axis = 300 + port_offset(contactor, "overhead")[0]
    sour.pin(port="outlet", x=120, y=gas_in_y)
    sweet.pin(port="inlet", x=contactor_axis, y=140)

    # The rich amine runs along the foot of the sheet.
    rich_y = 822.0
    letdown.pin(port="inlet", x=460, y=rich_y)
    cross.pin(x=620).pin(port="tube_in", y=rich_y)
    cross_shell_in_x = pinned_x(cross, "shell_in")
    cross_shell_out_x = pinned_x(cross, "shell_out")
    rich_riser_x = 880.0

    regen.pin(x=980, y=290)
    regen_axis = 980 + port_offset(regen, "overhead")[0]
    regen_feed_y = 290 + port_offset(regen, "feed")[1]
    reflux_in_y = 290 + port_offset(regen, "reflux_in")[1]
    boilup_in_y = 290 + port_offset(regen, "boilup_in")[1]

    # mirrored="y" puts the condenser's shell inlet underneath.
    ovhd.pin(mirrored="y").pin(port="shell_in", x=regen_axis, y=201)
    ovhd_drain_y = pinned_y(ovhd, "shell_out")
    cw_ovhd_y = pinned_y(ovhd, "tube_in")
    drum.pin(port="inlet", x=1200, y=ovhd_drain_y)
    drum_draw_x = pinned_x(drum, "outlet")
    drum_vent_x = pinned_x(drum, "vent")
    reflux_run_y = 240.0
    reflux_pump.pin(x=1350).pin(port="suction", y=reflux_run_y)
    reflux_riser_x = 1480.0

    reboiler.pin(x=1400, y=640)
    sump_x = 1400 + port_offset(reboiler, "shell_in")[0]
    boilup_x = 1400 + port_offset(reboiler, "shell_out")[0]
    lean_draw_x = 1400 + port_offset(reboiler, "bottoms")[0]
    steam_y = 640 + port_offset(reboiler, "tube_in")[1]
    condensate_y = 640 + port_offset(reboiler, "tube_out")[1]
    sump_run_y = 730.0
    lean_run_y = 770.0

    steam.pin(port="outlet", x=1230, y=steam_y)
    condensate.pin(port="inlet", x=1700, y=condensate_y)
    cws_ovhd.pin(port="outlet", x=880, y=cw_ovhd_y)
    # The cooling water return drops below the reflux drum and pump.
    cw_return_x, cw_return_y = 1130.0, 310.0
    cwr_ovhd.pin(port="inlet", x=1700, y=cw_return_y)
    acid.pin(port="inlet", x=1700, y=60)

    # The solvent return runs east to west, so the pump is mirrored.
    return_y = 900.0
    lean_pump.pin(mirrored=True).pin(port="suction", x=600, y=return_y)
    pump_out_y = pinned_y(lean_pump, "discharge")
    trim.pin(x=370, y=960)
    trim_shell_in_x = pinned_x(trim, "shell_in")
    trim_shell_out_x = pinned_x(trim, "shell_out")
    cw_trim_y = pinned_y(trim, "tube_in")
    cws_trim.pin(port="outlet", x=250, y=cw_trim_y)
    cwr_trim.pin(port="inlet", x=760, y=cw_trim_y)
    lean_riser_x = 150.0
    lean_return_y = 1040.0

    # --- Connections --------------------------------------------------
    # A number is drawn once, on the first segment declared with it.
    fs.connect(sour.outlet, contactor.feed_2, name="S-401")
    fs.connect(contactor.overhead, sweet.inlet, name="S-402")

    fs.connect(contactor.bottoms, letdown.inlet, name="S-404").via(
        [(contactor_axis, rich_y)])
    fs.connect(letdown.outlet, cross.tube_in, name="S-404")
    fs.connect(cross.tube_out, regen.feed, name="S-405").via(
        [(rich_riser_x, rich_y), (rich_riser_x, regen_feed_y)])

    fs.connect(regen.overhead, ovhd.shell_in, name="S-406")
    fs.connect(ovhd.shell_out, drum.inlet, name="S-407").via(
        [(regen_axis, ovhd_drain_y)])
    fs.connect(drum.vent, acid.inlet, name="S-408").via([(drum_vent_x, 60)])
    fs.connect(drum.outlet, reflux_pump.suction, name="S-409").via(
        [(drum_draw_x, reflux_run_y)])
    fs.connect(reflux_pump.discharge, regen.reflux_in, name="S-409",
               draw_as_recycle=True).via(
                   [(reflux_riser_x, pinned_y(reflux_pump, "discharge")),
                    (reflux_riser_x, reflux_in_y)])

    fs.connect(regen.bottoms, reboiler.shell_in, name="S-410").via(
        [(regen_axis, sump_run_y), (sump_x, sump_run_y)])
    fs.connect(reboiler.shell_out, regen.boilup_in, name="S-411",
               draw_as_recycle=True).via([(boilup_x, boilup_in_y)])

    # Lean amine leaves over the kettle's weir.
    fs.connect(reboiler.bottoms, cross.shell_in, name="S-412").via(
        [(lean_draw_x, lean_run_y), (cross_shell_in_x, lean_run_y)])
    fs.connect(cross.shell_out, lean_pump.suction, name="S-413").via(
        [(cross_shell_out_x, return_y)])
    fs.connect(lean_pump.discharge, trim.shell_in, name="S-414").via(
        [(trim_shell_in_x, pump_out_y)])
    fs.connect(trim.shell_out, contactor.feed_1, name="S-403",
               draw_as_recycle=True).via(
                   [(trim_shell_out_x, lean_return_y),
                    (lean_riser_x, lean_return_y),
                    (lean_riser_x, lean_in_y)])

    fs.connect(steam.outlet, reboiler.tube_in, name="S-415")
    fs.connect(reboiler.tube_out, condensate.inlet, name="S-416")
    fs.connect(cws_ovhd.outlet, ovhd.tube_in, name="S-417")
    fs.connect(ovhd.tube_out, cwr_ovhd.inlet, name="S-418").via(
        [(cw_return_x, cw_ovhd_y), (cw_return_x, cw_return_y)])
    fs.connect(cws_trim.outlet, trim.tube_in, name="S-419")
    fs.connect(trim.tube_out, cwr_trim.inlet, name="S-420")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Methane", "Mass Fraction")]

    # --- Title strip --------------------------------------------------
    fs.title_block = TitleBlock(
        title="Amine Sweetening",
        subtitle="A400 Process Flow Diagram 1",
        drawing_number="PFD-401",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet="1", of_sheets="1", scale="NTS",
        date="03/03/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "12/02/26", "Issued for internal review", "AA"),
            Revision("B", "03/03/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # --- Sheet furniture ----------------------------------------------
    # List every item but LV-401, in process order.
    fs.add_annotation(equipment_list(fs, align="top", include=[
        "T-401", "E-401", "T-402", "E-402", "V-401", "P-402A/B", "E-403",
        "P-401A/B", "E-404",
    ]))
    fs.add_annotation(TableBox(
        title="UTILITIES SUMMARY",
        headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in",
                 "T_out"],
        rows=[
            ["LP Steam", "E-403", "24700", "11.30", "152 C", "151 C"],
            ["Cooling Water", "E-402", "-4540", "72.4", "25 C", "40 C"],
            ["Cooling Water", "E-404", "-12310", "196.3", "25 C", "40 C"],
        ],
        col_align=["l", "l", "r", "r", "c", "c"],
        align="bottom-right",
    ))

    fs.render(out("absorber_stripper.svg"), border="zone",
              show_stream_table=True)
    print("Generated absorber_stripper.svg")
    for issue in fs.validate():
        print(f"  {issue}")


if __name__ == "__main__":
    main()
