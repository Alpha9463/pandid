"""
Example 19: Amine Sweetening A400, an absorber and its regenerator

Sour natural gas is contacted counter-currently with lean MDEA in
T-401, leaves the top on specification, and the acid gas it gave up
leaves the plant as the regenerator's overhead. The solvent is the
circuit: rich amine off the contactor's bottom is let down to near
atmospheric pressure, picks up heat from the returning lean amine in
E-401, is stripped in T-402 over the reboiler E-403, and is pumped back
up to contactor pressure through the trim cooler E-404.

Two columns on one sheet, and they are **not the same tower**. ISO
10628-2 gives an absorber and a regenerator no symbols of their own:
each is the one dished-end shell of group 2 carrying whichever group-27
internal it really contains, so what tells them apart here is
``internals=``.

- T-401 is ``internals="valve_tray"``. The contactor runs at 66 bara,
  where a deck's pressure drop costs nothing worth having, and it has to
  turn down with the gas rate and tolerate the compressor oil and iron
  sulphide that arrive with the feed. A valve deck does both, and can be
  washed.
- T-402 is ``internals="packing"``. The regenerator runs just above
  atmospheric, where pressure drop *is* the design: every millibar
  across the tower raises the reboiler's bubble point, and MDEA degrades
  thermally above about 130 C. Packing buys the low drop, and the two
  beds are the wash section over the stripping section.

Drawn as a PFD -- an arrowhead on every process line, an equipment
list, a utilities summary and a stream table sectioned into a mass
fraction block, with one control valve on the sheet and no instrument
balloon anywhere.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Column,
    Condenser,
    ControlValve,
    Feed,
    Flowsheet,
    KettleReboiler,
    Product,
    Pump,
    ShellAndTubeExchanger,
    Vessel,
)
from pandid.document import Revision, TableBox, TitleBlock, equipment_list
from pandid.portgeom import port_offset

# --- Stream property table --------------------------------------------
# Rows render in first-seen key order, so every stream carries the same
# keys; values are drawn verbatim and an empty one renders as "-".
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
    # mirrored=True turns the contactor end for end so that the two
    # nozzles a column takes its returns on -- reflux_in at the top and
    # boilup_in at the bottom -- face the sheet's west edge. On an
    # absorber those two are the *process* inlets: the solvent enters
    # over the top deck and the gas under the bottom one, and the tower
    # is counter-current between them.
    #
    # No label_pos: a tag written in the middle of a tower is written
    # across the decks, and a tag is not haloed the way a line number is.
    # Left unset the engine takes the first face no nozzle's stream runs
    # through -- top, bottom, right, left in that order -- which is the
    # wall beside each of these two.
    contactor = fs.add(Column("T-401", internals="valve_tray", trays=20,
                              width=110, height=340,
                              description="Amine Contactor")).pin(mirrored=True)
    regen = fs.add(Column("T-402", internals="packing", trays=2, width=110,
                          height=300,
                          description="Amine Regenerator"))

    # The rich amine goes tube side and the returning lean amine shell
    # side. Nozzles are named for the side of the equipment, never for
    # the duty, and the choice is a real one: the rich stream flashes
    # across E-401, carries the iron sulphide the contactor washed out of
    # the gas, and is the corrosive half of the circuit -- so it goes in
    # the half that can be pulled and cleaned. The shell also runs east
    # to west against the tubes, which is the counter-current the
    # exchanger is sized on.
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

    # The one valve on the sheet. A PFD draws the plant that sets the
    # process conditions, and this is the 64 bar break between a
    # contactor at 66 bara and a regenerator at 1.9: without it the
    # pressures in the table either side of E-401 have nothing to happen
    # across.
    letdown = fs.add(ControlValve("LV-401",
                                  description="Rich Amine Level Control Valve"))

    sour = fs.add(Feed("Sour Gas", reference="PFD-301"))
    steam = fs.add(Feed("LP Steam", reference="PFD-901"))
    # header=True is one service tapped wherever the sheet wants it, so
    # both cooling-water tie-ins carry CWS and both returns CWR. Without
    # it a second flag with the same name is refused: a tag names one
    # item, and a header is the exception because it is one service drawn
    # at each place it is tapped.
    cws_ovhd = fs.add(Feed("CWS", header=True))
    cws_trim = fs.add(Feed("CWS", header=True))
    sweet = fs.add(Product("Sweet Gas", reference="PFD-501"))
    acid = fs.add(Product("Acid Gas to SRU", reference="PFD-601"))
    condensate = fs.add(Product("Steam Condensate", reference="PFD-901"))
    cwr_ovhd = fs.add(Product("CWR", header=True))
    cwr_trim = fs.add(Product("CWR", header=True))

    # --- Placement ----------------------------------------------------
    # Pinned by nozzle, not by corner: pin(port=...) asks the symbol
    # where its own nozzle sits, so no rescaling of the artwork can leave
    # a flag off its run. A boundary flag is pinned at the tip of its
    # arrow.
    contactor.pin(x=300, y=250)
    lean_in_y = 250 + port_offset(contactor, "reflux_in")[1]
    gas_in_y = 250 + port_offset(contactor, "boilup_in")[1]
    contactor_axis = 300 + port_offset(contactor, "distillate")[0]
    sour.pin(port="outlet", x=120, y=gas_in_y)
    sweet.pin(port="inlet", x=contactor_axis, y=140)

    # The rich amine runs along the foot of the sheet and the heated
    # rich rises to the regenerator's feed: one elevation each, which is
    # what keeps the two halves of E-401 from having to be read as a
    # single line through it.
    rich_y = 822.0
    letdown.pin(port="inlet", x=460, y=rich_y)
    cross.pin(x=620).pin(port="tube_in", y=rich_y)
    cross_shell_in_x = cross.pin_.x + port_offset(cross, "shell_in")[0]
    cross_shell_out_x = cross.pin_.x + port_offset(cross, "shell_out")[0]
    rich_riser_x = 880.0

    regen.pin(x=980, y=290)
    regen_axis = 980 + port_offset(regen, "distillate")[0]
    regen_feed_y = 290 + port_offset(regen, "feed")[1]
    reflux_in_y = 290 + port_offset(regen, "reflux_in")[1]
    boilup_in_y = 290 + port_offset(regen, "boilup_in")[1]

    # mirrored="y" puts the condenser's shell inlet underneath, so the
    # overhead rises into it straight.
    ovhd.pin(mirrored="y").pin(port="shell_in", x=regen_axis, y=201)
    ovhd_drain_y = ovhd.pin_.y + port_offset(ovhd, "shell_out")[1]
    cw_ovhd_y = ovhd.pin_.y + port_offset(ovhd, "tube_in")[1]
    drum.pin(port="inlet", x=1200, y=ovhd_drain_y)
    drum_draw_x = drum.pin_.x + port_offset(drum, "outlet")[0]
    drum_vent_x = drum.pin_.x + port_offset(drum, "vent")[0]
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
    cwr_ovhd.pin(port="inlet", x=1700, y=cw_ovhd_y)
    acid.pin(port="inlet", x=1700, y=60)

    # The solvent return runs east to west, so the pump is mirrored end
    # to end and the riser back up to the contactor is the westmost line
    # on the sheet. The trim cooler is not mirrored: the amine is on its
    # shell, which is the side whose nozzles run east to west, and the
    # cooling water on its tubes, which is the side whose two are on the
    # walls where a boundary flag can reach them without doubling back.
    return_y = 900.0
    lean_pump.pin(mirrored=True).pin(port="suction", x=600, y=return_y)
    pump_out_y = lean_pump.pin_.y + port_offset(lean_pump, "discharge")[1]
    trim.pin(x=370, y=960)
    trim_shell_in_x = trim.pin_.x + port_offset(trim, "shell_in")[0]
    trim_shell_out_x = trim.pin_.x + port_offset(trim, "shell_out")[0]
    cw_trim_y = trim.pin_.y + port_offset(trim, "tube_in")[1]
    cws_trim.pin(port="outlet", x=250, y=cw_trim_y)
    cwr_trim.pin(port="inlet", x=760, y=cw_trim_y)
    lean_riser_x = 150.0
    lean_return_y = 1040.0

    # --- Connections --------------------------------------------------
    # Declared in stream-number order, which is the order the table
    # reads. A number is drawn once, on the first segment declared, so
    # each group starts with the run it belongs on.
    fs.connect(sour.outlet, contactor.boilup_in, name="S-401")
    fs.connect(contactor.distillate, sweet.inlet, name="S-402")

    fs.connect(contactor.bottoms, letdown.inlet, name="S-404").via(
        [(contactor_axis, rich_y)])
    fs.connect(letdown.outlet, cross.tube_in, name="S-404")
    fs.connect(cross.tube_out, regen.feed, name="S-405").via(
        [(rich_riser_x, rich_y), (rich_riser_x, regen_feed_y)])

    fs.connect(regen.distillate, ovhd.shell_in, name="S-406")
    fs.connect(ovhd.shell_out, drum.inlet, name="S-407").via(
        [(regen_axis, ovhd_drain_y)])
    fs.connect(drum.vent, acid.inlet, name="S-408").via([(drum_vent_x, 60)])
    fs.connect(drum.outlet, reflux_pump.suction, name="S-409").via(
        [(drum_draw_x, reflux_run_y)])
    fs.connect(reflux_pump.discharge, regen.reflux_in, name="S-409",
               draw_as_recycle=True).via(
                   [(reflux_riser_x, reflux_pump.pin_.y
                     + port_offset(reflux_pump, "discharge")[1]),
                    (reflux_riser_x, reflux_in_y)])

    fs.connect(regen.bottoms, reboiler.shell_in, name="S-410").via(
        [(regen_axis, sump_run_y), (sump_x, sump_run_y)])
    fs.connect(reboiler.shell_out, regen.boilup_in, name="S-411",
               draw_as_recycle=True).via([(boilup_x, boilup_in_y)])

    # The kettle's weir draw is the lean amine: everything that does not
    # boil off leaves over it, which is where a stripping column's
    # bottoms product physically comes from.
    fs.connect(reboiler.bottoms, cross.shell_in, name="S-412").via(
        [(lean_draw_x, lean_run_y), (cross_shell_in_x, lean_run_y)])
    fs.connect(cross.shell_out, lean_pump.suction, name="S-413").via(
        [(cross_shell_out_x, return_y)])
    # The trim cooler is on the pump's discharge and not its suction: the
    # lean amine leaves E-401 at 75 C and its bubble point at 1.6 bara is
    # 113 C, so the pump has 38 C of subcooling to work with. Cooling it
    # first would only add the cooler's pressure drop to the tightest
    # suction on the sheet.
    fs.connect(lean_pump.discharge, trim.shell_in, name="S-414").via(
        [(trim_shell_in_x, pump_out_y)])
    fs.connect(trim.shell_out, contactor.reflux_in, name="S-403",
               draw_as_recycle=True).via(
                   [(trim_shell_out_x, lean_return_y),
                    (lean_riser_x, lean_return_y),
                    (lean_riser_x, lean_in_y)])

    fs.connect(steam.outlet, reboiler.tube_in, name="S-415")
    fs.connect(reboiler.tube_out, condensate.inlet, name="S-416")
    fs.connect(cws_ovhd.outlet, ovhd.tube_in, name="S-417")
    fs.connect(ovhd.tube_out, cwr_ovhd.inlet, name="S-418")
    fs.connect(cws_trim.outlet, trim.tube_in, name="S-419")
    fs.connect(trim.tube_out, cwr_trim.inlet, name="S-420")

    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Methane", "Mass Fraction")]

    # --- Title strip --------------------------------------------------
    # date= and scale= are stated rather than left blank: left blank, the
    # renderer fills in today's date and the ratio it fitted the sheet at.
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
    # include= names the rows in process order; LV-401 is a bulk item
    # bought by the line and takes no equipment-list row.
    fs.add_annotation(equipment_list(fs, align="top", include=[
        "T-401", "E-401", "T-402", "E-402", "V-401", "P-402A/B", "E-403",
        "P-401A/B", "E-404",
    ]))
    # The unit is written in the two temperature headers rather than on
    # every value under them, which is a column narrower and a reading
    # clearer. It also keeps those two columns off a width the renderer
    # cannot round the same way twice: a column is as wide as its widest
    # cell plus a fixed pad, at five characters that comes to a width
    # whose half is an exact rounding tie, and which way a tie falls
    # depends on the last bit of a float sum -- which CPython 3.12
    # changed. Five-character cells there draw this sheet 0,1 unit apart
    # on 3.11 and on 3.12. The fix belongs in the renderer.
    fs.add_annotation(TableBox(
        title="UTILITIES SUMMARY",
        headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in (C)",
                 "T_out (C)"],
        rows=[
            ["LP Steam", "E-403", "24700", "11.30", "152", "151"],
            ["Cooling Water", "E-402", "-4540", "72.4", "25", "40"],
            ["Cooling Water", "E-404", "-12310", "196.3", "25", "40"],
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
