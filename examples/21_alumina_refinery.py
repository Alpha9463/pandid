"""
Example 21: Alumina Refinery A900, the Bayer process as a set of three PFDs

One ``Flowsheet`` per area, each rendered to its own file: grinding and
digestion (PFD-901), clarification (PFD-902), and precipitation and
calcination (PFD-903). The caustic liquor circuit closes across all
three. A line that crosses sheets ends at a ``Product`` and starts again
at a ``Feed`` with the same name and stream number, each flag's
``reference=`` naming the other sheet. Each item stands for its train.
"""

from _bootstrap import out  # runs from the repo root or from examples/

from pandid import (
    Conveyor,
    Cooler,
    Cyclone,
    FallingFilmEvaporator,
    Feed,
    FilterPress,
    Flowsheet,
    FluidizedBedCalciner,
    Furnace,
    JawCrusher,
    Mill,
    Product,
    Pump,
    Reactor,
    RotaryDrumFilter,
    Separator,
    ShellAndTubeExchanger,
    Tank,
    Tee,
    Thickener,
)
from pandid.document import Revision, TableBox, TitleBlock, equipment_list, notes
from pandid.portgeom import pinned_x, pinned_y

# --- Stream property table --------------------------------------------
# Compositions are mass fractions; an empty value renders as "-".
PROPERTY_ROWS = (
    "Temperature (C)", "Pressure (bara)", "Total Flow (t/h)", "Solids (% w/w)",
    "Water", "Caustic (Na2O)", "Dissolved Al2O3", "Bauxite / Residue",
    "Hydrate Al(OH)3", "Alumina Al2O3", "Flocculant", "Air / Flue Gas",
    "Fuel Gas",
)

PROPERTIES = {
    "S-901": ("25", "1.0", "212", "100.0", "", "", "", "1.000", "", "", "", "", ""),
    "S-902": ("25", "1.0", "212", "100.0", "", "", "", "1.000", "", "", "", "", ""),
    "S-903": ("60", "4.0", "2300", "0.0", "0.834", "0.123", "0.043", "", "", "", "", "", ""),
    "S-904": ("57", "1.5", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-905": ("60", "1.3", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-906": ("80", "1.2", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-907": ("100", "1.1", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-908": ("100", "1.0", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-909": ("101", "6.5", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-910": ("145", "5.5", "2512", "8.4", "0.764", "0.113", "0.039", "0.084", "", "", "", "", ""),
    "S-911": ("145", "5.0", "2512", "2.2", "0.785", "0.113", "0.080", "0.022", "", "", "", "", ""),
    "S-912": ("125", "2.4", "78.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-913": ("125", "2.4", "2434", "2.3", "0.779", "0.116", "0.082", "0.023", "", "", "", "", ""),
    "S-914": ("105", "1.2", "74.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-915": ("105", "1.2", "2360", "2.4", "0.772", "0.120", "0.085", "0.024", "", "", "", "", ""),
    "S-916": ("170", "8.0", "185", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-917": ("170", "7.8", "185", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-918": ("125", "2.3", "78.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-919": ("105", "1.1", "74.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-920": ("73", "1.0", "444", "0.0", "0.955", "0.026", "0.019", "", "", "", "", "", ""),
    "S-921": ("100", "1.0", "1.0", "10.0", "0.735", "0.096", "0.068", "0.100", "", "", "", "", ""),
    "S-922": ("100", "1.0", "2805", "2.0", "0.801", "0.105", "0.074", "0.020", "", "", "", "", ""),
    "S-923": ("25", "1.0", "2.0", "", "0.995", "", "", "", "", "", "0.005", "", ""),
    "S-924": ("100", "1.0", "2807", "2.0", "0.801", "0.105", "0.074", "0.020", "", "", "trace", "", ""),
    "S-925": ("100", "1.0", "2620", "0.0", "0.817", "0.107", "0.076", "3.8E-05", "", "", "", "", ""),
    "S-926": ("90", "4.0", "20.0", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-927": ("100", "3.5", "2639", "0.0", "0.818", "0.106", "0.075", "", "", "", "", "", ""),
    "S-928": ("100", "1.0", "187", "30.0", "0.572", "0.075", "0.053", "0.299", "", "", "", "", ""),
    "S-929": ("60", "2.0", "400", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-930": ("73", "1.0", "587", "9.5", "0.864", "0.024", "0.017", "0.095", "", "", "", "", ""),
    "S-931": ("73", "1.0", "143", "39.2", "0.581", "0.016", "0.011", "0.392", "", "", "", "", ""),
    "S-932": ("75", "3.0", "2639", "0.0", "0.818", "0.106", "0.075", "", "", "", "", "", ""),
    "S-933": ("62", "1.0", "400", "30.0", "0.593", "0.079", "0.028", "", "0.300", "", "", "", ""),
    "S-934": ("73", "1.0", "3039", "3.9", "0.789", "0.103", "0.069", "", "0.039", "", "", "", ""),
    "S-935": ("68", "1.0", "3039", "7.0", "0.778", "0.103", "0.049", "", "0.070", "", "", "", ""),
    "S-936": ("62", "1.0", "3039", "9.0", "0.771", "0.103", "0.036", "", "0.090", "", "", "", ""),
    "S-937": ("62", "1.0", "340", "45.0", "0.466", "0.062", "0.022", "", "0.450", "", "", "", ""),
    "S-938": ("62", "1.0", "2699", "4.4", "0.810", "0.108", "0.038", "", "0.044", "", "", "", ""),
    "S-939": ("62", "1.0", "2299", "0.0", "0.848", "0.113", "0.040", "", "", "", "", "", ""),
    "S-940": ("80", "3.0", "150", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-941": ("66", "1.0", "325", "0.0", "0.912", "0.065", "0.023", "", "", "", "", "", ""),
    "S-942": ("70", "1.0", "165", "92.7", "0.073", "", "", "", "0.927", "", "", "", ""),
    "S-943": ("25", "1.0", "5.0", "", "0.600", "0.400", "", "", "", "", "", "", ""),
    "S-944": ("63", "1.0", "2629", "0.0", "0.855", "0.108", "0.037", "", "", "", "", "", ""),
    "S-945": ("150", "4.7", "100", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-946": ("150", "4.5", "100", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-947": ("60", "0.20", "329", "", "1.000", "", "", "", "", "", "", "", ""),
    "S-948": ("60", "0.20", "2300", "0.0", "0.834", "0.123", "0.043", "", "", "", "", "", ""),
    "S-949": ("25", "1.0", "120", "", "", "", "", "", "", "", "", "1.000", ""),
    "S-950": ("15", "3.0", "6.0", "", "", "", "", "", "", "", "", "", "1.000"),
    "S-951": ("1050", "1.0", "126", "", "", "", "", "", "", "", "", "1.000", ""),
    "S-952": ("1000", "1.0", "98.0", "100.0", "", "", "", "", "", "1.000", "", "", ""),
    "S-953": ("1000", "1.0", "193", "1.0", "0.337", "", "", "", "", "0.010", "", "0.653", ""),
    "S-954": ("1000", "1.0", "191", "0.0", "0.340", "", "", "", "", "", "", "0.660", ""),
    "S-955": ("1000", "1.0", "2.0", "100.0", "", "", "", "", "", "1.000", "", "", ""),
    "S-956": ("1000", "1.0", "100", "100.0", "", "", "", "", "", "1.000", "", "", ""),
}


# --- The drawing set --------------------------------------------------
# Drawing numbers, and the names of the lines that cross sheets.
DIGESTION = "PFD-901"
CLARIFICATION = "PFD-902"
PRECIPITATION = "PFD-903"
BLOW_OFF = "Blow-off Slurry"
PREGNANT_LIQUOR = "Pregnant Liquor"
SPENT_LIQUOR = "Spent Liquor"

TEE_W = 12.0  # a tee is a 12-unit square

NOT_DRAWN = ("Lime burning, causticisation, oxalate removal, residue disposal "
             "and product cooling are not in this set of drawings.")


def digestion():
    """Build PFD-901: grinding, digestion and the flash train."""
    fs = Flowsheet("Alumina Refinery A900 Grinding and Digestion")

    # --- Grinding -----------------------------------------------------
    bauxite = fs.add(Feed("ROM Bauxite", reference="PFD-101"))
    crusher = fs.add(JawCrusher("CR-901",
                                description="Bauxite Jaw Crusher"))
    # Ore drops onto the belt, so its feed is on the top face.
    ore_belt = fs.add(Conveyor("CV-901", length=200,
                               description="Crushed Bauxite Conveyor"))
    ore_belt.nozzle("feed", "N")
    # Spent liquor from PFD-903 joins the ore at the mill feed.
    spent_liquor = fs.add(Feed(SPENT_LIQUOR, reference=PRECIPITATION))
    mill_tee = fs.add(Tee(branch="inlet"))
    mill = fs.add(Mill("ML-901", description="Bauxite Ball Mill"))

    # --- Digestion ----------------------------------------------------
    interchanger_1 = fs.add(ShellAndTubeExchanger(
        "E-901", variant="straight_tubes", width=150, height=45,
        description="Digestion Heat Interchanger No. 1"))
    interchanger_2 = fs.add(ShellAndTubeExchanger(
        "E-902", variant="straight_tubes", width=150, height=45,
        description="Digestion Heat Interchanger No. 2"))
    # A ``Reactor`` draws the stirred tank's agitator.
    desilication = fs.add(Reactor(
        "TK-901", agitator="turbine", width=80, height=170,
        description="Desilication Tank"))
    charge_pump = fs.add(Pump("P-901", description="Digester Charge Pump"))
    steam_heater = fs.add(ShellAndTubeExchanger(
        "E-903", variant="straight_tubes", width=150, height=45,
        description="Live Steam Digestion Heater"))
    digester = fs.add(Reactor(
        "D-901", variant="jacketed", agitator="turbine", width=90,
        height=210, description="Digester"))

    # --- Flash train --------------------------------------------------
    # Counter-current: the hotter flash heats the feed nearer the digester.
    flash_1 = fs.add(Separator("V-901", width=70, height=130,
                               description="First Flash Tank"))
    flash_2 = fs.add(Separator("V-902", width=70, height=130,
                               description="Second Flash Tank"))
    mp_steam = fs.add(Feed("MP Steam", reference="PCD-903"))
    # header=True lets several flags name the same header.
    steam_condensate = fs.add(Product("Steam Condensate", header=True,
                                      reference="PCD-903"))
    flash_condensate_1 = fs.add(Product("Process Condensate", header=True,
                                        reference="PCD-902"))
    flash_condensate_2 = fs.add(Product("Process Condensate", header=True,
                                        reference="PCD-902"))
    # The flashed slurry leaves for the dilution tank on PFD-902.
    blow_off = fs.add(Product(BLOW_OFF, reference=CLARIFICATION))

    # --- Placement ----------------------------------------------------
    slurry_y = 480.0        # the two interchangers' elevation
    digest_y = 600.0        # the live steam heater and the digester
    # Lanes for the flash vapours, the spent liquor and the blow-off.
    lane_vapour_1, lane_vapour_2 = 300.0, 250.0
    lane_return_y = 340.0
    lane_blowoff_y = 1000.0

    bauxite.pin(port="outlet", x=180, y=110)
    spent_liquor.pin(port="outlet", x=180, y=lane_return_y)
    crusher.pin(port="feed", x=210, y=150)
    ore_belt.pin(port="feed", x=210, y=280)
    # The run out of the belt is on its discharge's elevation.
    ore_run_y = pinned_y(ore_belt, "discharge")
    mill_tee.pin(port="inlet", x=460, y=ore_run_y)
    mill.pin(port="feed", x=570, y=340)

    interchanger_1.pin(port="tube_in", x=760, y=slurry_y)
    interchanger_2.pin(port="tube_in", x=1010, y=slurry_y)
    desilication.pin(port="feed", x=1260, y=slurry_y)
    charge_pump.pin(port="suction", x=1400, y=620)
    steam_heater.pin(port="tube_in", x=1580, y=digest_y)
    digester.pin(port="feed", x=1860, y=digest_y)
    flash_1.pin(port="feed", x=2080, y=740)
    flash_2.pin(port="feed", x=2320, y=880)
    blow_off.pin(port="inlet", x=2440, y=lane_blowoff_y)

    hx1_shell_in_x = pinned_x(interchanger_1, "shell_in")
    hx2_shell_in_x = pinned_x(interchanger_2, "shell_in")
    hx1_drain_x = pinned_x(interchanger_1, "shell_out")
    hx2_drain_x = pinned_x(interchanger_2, "shell_out")
    heater_steam_x = pinned_x(steam_heater, "shell_in")
    heater_drain_x = pinned_x(steam_heater, "shell_out")
    desil_draw_x = pinned_x(desilication, "outlet")
    digester_draw_x = pinned_x(digester, "outlet")
    flash_1_axis_x = pinned_x(flash_1, "vapor")
    flash_2_axis_x = pinned_x(flash_2, "vapor")

    mp_steam.pin(port="outlet", x=1560, y=400)
    steam_condensate.pin(port="inlet", x=1760, y=790)
    flash_condensate_1.pin(port="inlet", x=1180, y=700)
    flash_condensate_2.pin(port="inlet", x=920, y=790)

    # --- Grinding and digestion ---------------------------------------
    # A number is drawn once, on the first segment declared with it.
    fs.connect(bauxite.outlet, crusher.feed, name="S-901")
    fs.connect(crusher.discharge, ore_belt.feed, name="S-902")
    fs.connect(ore_belt.discharge, mill_tee.inlet, name="S-902")
    # Under the belt and up into the mill feed chute from underneath.
    fs.connect(spent_liquor.outlet, mill_tee.branch, name="S-903").via(
        [(pinned_x(mill_tee) + TEE_W / 2, lane_return_y)])
    fs.connect(mill_tee.outlet, mill.feed, name="S-904").via([(570, ore_run_y)])
    fs.connect(mill.discharge, interchanger_1.tube_in, name="S-905").via(
        [(570, slurry_y)])
    fs.connect(interchanger_1.tube_out, interchanger_2.tube_in, name="S-906")
    fs.connect(interchanger_2.tube_out, desilication.feed, name="S-907")
    fs.connect(desilication.outlet, charge_pump.suction, name="S-908").via(
        [(desil_draw_x, 620)])
    fs.connect(charge_pump.discharge, steam_heater.tube_in, name="S-909")
    fs.connect(steam_heater.tube_out, digester.feed, name="S-910")

    # --- The flash train and the interchange --------------------------
    fs.connect(digester.outlet, flash_1.feed, name="S-911").via(
        [(digester_draw_x, 740)])
    # Route each flash vapour by hand, over the digester to its heater.
    fs.connect(flash_1.vapor, interchanger_2.port("shell_in"),
               name="S-912").via([(flash_1_axis_x, lane_vapour_1),
                                  (hx2_shell_in_x, lane_vapour_1)])
    fs.connect(flash_1.liquid, flash_2.feed, name="S-913").via(
        [(flash_1_axis_x, 880)])
    fs.connect(flash_2.vapor, interchanger_1.port("shell_in"),
               name="S-914").via([(flash_2_axis_x, lane_vapour_2),
                                  (hx1_shell_in_x, lane_vapour_2)])
    fs.connect(flash_2.liquid, blow_off.inlet, name="S-915").via(
        [(flash_2_axis_x, lane_blowoff_y)])

    fs.connect(mp_steam.outlet, steam_heater.port("shell_in"),
               name="S-916").via([(heater_steam_x, 400)])
    fs.connect(steam_heater.port("shell_out"), steam_condensate.inlet,
               name="S-917").via([(heater_drain_x, 790)])
    fs.connect(interchanger_2.port("shell_out"), flash_condensate_1.inlet,
               name="S-918").via([(hx2_drain_x, 700)])
    fs.connect(interchanger_1.port("shell_out"), flash_condensate_2.inlet,
               name="S-919").via([(hx1_drain_x, 790)])

    _furnish(
        fs, DIGESTION, 1, "Grinding and Digestion",
        equipment=["CR-901", "CV-901", "ML-901", "E-901", "E-902", "TK-901",
                   "P-901", "E-903", "D-901", "V-901", "V-902"],
        utilities=[["MP Steam", "E-903", "106800", "51.4", "170 C", "170 C"]],
        general_notes=[
            "Each item stands for the train it belongs to: one digester for "
            "six to ten, two flash stages for eight to twelve.",
            NOT_DRAWN,
        ],
    )
    return fs


def clarification():
    """Build PFD-902: dilution, settling, mud washing and security filtration."""
    fs = Flowsheet("Alumina Refinery A900 Clarification")

    # --- Dilution, settling and mud washing ---------------------------
    # The flashed slurry arrives from PFD-901.
    blow_off = fs.add(Feed(BLOW_OFF, reference=DIGESTION))
    # The blow-off, washer overflow and filter residue meet in M-901.
    dilution = fs.add(Tank("M-901", inputs=3, width=70, height=90,
                           description="Blow-off Dilution Tank"))
    floc_tee = fs.add(Tee(branch="inlet"))
    flocculant = fs.add(Feed("Flocculant", reference="PCD-904"))
    # Thickeners drawn large, in the symbol's own 5:4.
    settler = fs.add(Thickener("TH-901", width=150, height=120,
                               description="Red Mud Settler"))
    wash_tee = fs.add(Tee(branch="inlet"))
    wash_water = fs.add(Feed("Mud Wash Water", reference="PCD-902"))
    washer = fs.add(Thickener("TH-902", width=150, height=120,
                              description="Red Mud Washer"))
    residue = fs.add(Product("Washed Residue to Storage",
                             reference="PFD-905"))

    # --- Security filtration ------------------------------------------
    # The cake returns to M-901; ``wash_in`` takes a displacement wash.
    security_filter = fs.add(FilterPress(
        "F-901", width=140, height=70,
        description="Security Filter"))
    filter_wash = fs.add(Feed("Hot Condensate", reference="PCD-902"))
    liquor_cooler = fs.add(Cooler("E-904",
                                  description="Pregnant Liquor Cooler"))
    # The cooled liquor leaves for precipitation on PFD-903.
    pregnant_liquor = fs.add(Product(PREGNANT_LIQUOR, reference=PRECIPITATION))

    # --- Placement ----------------------------------------------------
    settle_y = 1130.0       # dilution to the liquor cooler, one elevation
    # Lanes to M-901's three inlets.
    lane_blowoff, lane_dilution, lane_residue = 140.0, 110.0, 170.0
    lane_blowoff_y = 965.0
    lane_dilution_y, lane_residue_y = 1350.0, 1330.0

    blow_off.pin(port="outlet", x=lane_blowoff - 50, y=lane_blowoff_y)
    dilution.pin(port="in_2", x=200, y=settle_y)
    floc_tee.pin(port="inlet", x=400, y=settle_y)
    # East of the lanes, so they clear the flag's lettering.
    flocculant.pin(port="outlet", x=330, y=1250)
    settler.pin(port="feed", x=460, y=settle_y)
    security_filter.pin(port="inlet", x=700, y=settle_y)
    filter_wash.pin(port="outlet", x=640, y=880)
    liquor_cooler.pin(port="inlet", x=980, y=settle_y)
    pregnant_liquor.pin(port="inlet", x=1120, y=settle_y)

    wash_tee.pin(port="inlet", x=560, y=1430)
    washer.pin(port="feed", x=640, y=1430)
    wash_water.pin(port="outlet", x=470, y=1520)
    residue.pin(port="inlet", x=880, y=1660)

    cake_x = pinned_x(security_filter, "cake")
    mud_draw_x = pinned_x(settler, "underflow")

    # --- Dilution and settling ----------------------------------------
    fs.connect(blow_off.outlet, dilution.port("in_1"), name="S-915").via(
        [(lane_blowoff, lane_blowoff_y),
         (lane_blowoff, pinned_y(dilution, "in_1"))])
    fs.connect(washer.port("overflow"), dilution.port("in_2"),
               name="S-920").via([(810, 1430), (810, lane_dilution_y),
                                  (lane_dilution, lane_dilution_y),
                                  (lane_dilution, settle_y)])
    fs.connect(security_filter.port("cake"), dilution.port("in_3"),
               name="S-921").via(
                   [(cake_x, lane_residue_y), (lane_residue, lane_residue_y),
                    (lane_residue,
                     pinned_y(dilution, "in_3"))])
    fs.connect(dilution.outlet, floc_tee.inlet, name="S-922")
    # East along the flag's elevation, then up the riser.
    fs.connect(flocculant.outlet, floc_tee.branch, name="S-923").via(
        [(pinned_x(floc_tee) + TEE_W / 2, 1250)])
    fs.connect(floc_tee.outlet, settler.feed, name="S-924")

    fs.connect(settler.port("overflow"), security_filter.inlet, name="S-925")
    fs.connect(filter_wash.outlet, security_filter.port("wash_in"),
               name="S-926").via(
                   [(pinned_x(security_filter, "wash_in"), 880)])
    fs.connect(security_filter.outlet, liquor_cooler.inlet, name="S-927")

    # --- Mud washing --------------------------------------------------
    fs.connect(settler.port("underflow"), wash_tee.inlet, name="S-928").via(
        [(mud_draw_x, 1430)])
    fs.connect(wash_water.outlet, wash_tee.branch, name="S-929").via(
        [(pinned_x(wash_tee) + TEE_W / 2, 1520)])
    fs.connect(wash_tee.outlet, washer.feed, name="S-930")
    fs.connect(washer.port("underflow"), residue.inlet, name="S-931").via(
        [(pinned_x(washer, "underflow"), 1660)])

    fs.connect(liquor_cooler.outlet, pregnant_liquor.inlet, name="S-932")

    _furnish(
        fs, CLARIFICATION, 2, "Clarification",
        equipment=["M-901", "TH-901", "TH-902", "F-901", "E-904"],
        utilities=[
            ["Cooling Water", "E-904", "-57300", "685", "25 C", "45 C"],
            ["Mud Wash Water", "TH-902", "-", "111", "60 C", "-"],
        ],
        general_notes=[
            "Each item stands for the train it belongs to: one settler and "
            "one washer for a six-stage decantation circuit.",
            "TH-901 and TH-902 are drawn with the ISO 10628-2 item 28.4 "
            "C2021 cross-beam on the rake shaft. The drive above it is not "
            "drawn: it is a tagged item of its own.",
            NOT_DRAWN,
        ],
    )
    return fs


def precipitation():
    """Build PFD-903: precipitation, calcination and spent liquor."""
    fs = Flowsheet("Alumina Refinery A900 Precipitation and Calcination")

    # --- Precipitation ------------------------------------------------
    # The pregnant liquor arrives from PFD-902.
    pregnant_liquor = fs.add(Feed(PREGNANT_LIQUOR, reference=CLARIFICATION))
    seed_tee = fs.add(Tee(branch="inlet"))
    # Sized in the symbol's proportions so the drive motor stays round.
    precipitator_1 = fs.add(Reactor(
        "PR-901", agitator="turbine", width=85, height=180,
        description="Precipitator No. 1"))
    precipitator_2 = fs.add(Reactor(
        "PR-902", agitator="turbine", width=85, height=180,
        description="Precipitator No. 2"))

    # --- Classification -----------------------------------------------
    # The primary takes out the product hydrate, the secondary the seed.
    classifier_1 = fs.add(Cyclone(
        "CY-901", width=90, height=140,
        description="Primary Classifying Cyclone"))
    classifier_2 = fs.add(Cyclone(
        "CY-902", width=90, height=140,
        description="Secondary Classifying Cyclone"))

    # --- Hydrate filtration and calcination ---------------------------
    hydrate_filter = fs.add(RotaryDrumFilter(
        "F-902", width=140, height=80,
        description="Hydrate Filter"))
    hydrate_wash = fs.add(Feed("Hydrate Wash Water", reference="PCD-902"))
    hydrate_belt = fs.add(Conveyor("CV-902", length=200,
                                   description="Washed Hydrate Conveyor"))
    hydrate_belt.nozzle("feed", "N")
    # FH-901 burns the fuel; its hot gas enters the calciner's ``air``.
    combustion = fs.add(Furnace("FH-901", width=100, height=120,
                                description="Calciner Combustion Chamber"))
    air = fs.add(Feed("Combustion Air"))
    fuel = fs.add(Feed("Fuel Gas", reference="PCD-905"))
    # ``CA-901.fuel`` is left unpiped.
    calciner = fs.add(FluidizedBedCalciner(
        "CA-901", width=120, height=200, description="Alumina Calciner"))
    product_cyclone = fs.add(Cyclone(
        "CY-903", width=90, height=140,
        description="Calciner Product Cyclone"))
    # The cyclone's catch rejoins the product line.
    product_tee = fs.add(Tee(branch="inlet"))
    offgas = fs.add(Product("Calciner Off-Gas to Gas Cleaning",
                            reference="PFD-904"))
    alumina = fs.add(Product("Alumina to Cooling and Storage",
                             reference="PFD-904"))

    # --- Spent liquor -------------------------------------------------
    # The circuit closes here: overflow, filtrate and make-up meet in
    # M-902 and the evaporator takes off the wash water.
    spent_tank = fs.add(Tank("M-902", inputs=3, width=70, height=90,
                              description="Spent Liquor Tank"))
    caustic = fs.add(Feed("Caustic Soda Make-up", reference="PCD-906"))
    evaporator = fs.add(FallingFilmEvaporator(
        "EV-901", width=100, height=200,
        description="Spent Liquor Evaporator"))
    lp_steam = fs.add(Feed("LP Steam", reference="PCD-903"))
    evap_condensate = fs.add(Product("Steam Condensate", header=True,
                                     reference="PCD-903"))
    evap_vapour = fs.add(Product("Evaporator Vapour", reference="PCD-902"))
    liquor_pump = fs.add(Pump("P-902", description="Spent Liquor Pump"))
    # The concentrated liquor returns to the mill on PFD-901.
    spent_liquor = fs.add(Product(SPENT_LIQUOR, reference=DIGESTION))

    # --- Placement ----------------------------------------------------
    settle_y = 1130.0       # the pregnant liquor and the first precipitator
    calcine_y = 1840.0      # the calcination train
    # Lanes for the lines that run back: spent liquor, seed, filtrate and
    # the return to PFD-901.
    lane_spent_y, lane_spent_x = 940.0, 1215.0
    lane_seed_y = 1560.0
    lane_filtrate_y, lane_filtrate_x = 1620.0, 1290.0
    lane_home_y = 2260.0

    pregnant_liquor.pin(port="outlet", x=1100, y=settle_y)
    seed_tee.pin(port="inlet", x=1180, y=settle_y)
    precipitator_1.pin(port="feed", x=1280, y=settle_y)
    precipitator_2.pin(port="feed", x=1460, y=1270)
    classifier_1.pin(port="feed", x=1660, y=1400)
    classifier_2.pin(port="feed", x=1920, y=1180)

    hydrate_filter.pin(port="inlet", x=2150, y=1700)
    hydrate_wash.pin(port="outlet", x=2200, y=1500)
    hydrate_belt.pin(port="feed", x=2220, y=calcine_y)
    hydrate_run_y = pinned_y(hydrate_belt, "discharge")
    calciner.pin(port="feed", x=2520, y=hydrate_run_y)
    product_cyclone.pin(port="feed", x=2790, y=1720)
    # Under the cyclone's apex, on the product run, branch north.
    product_tee.pin(port="inlet",
                    x=pinned_x(product_cyclone, "underflow") - TEE_W / 2,
                    y=pinned_y(calciner, "product"), mirrored="y")
    combustion.pin(port="inlet", x=2260, y=2060)
    air.pin(port="outlet", x=2160, y=2000)
    fuel.pin(port="outlet", x=2180, y=2230)
    combustion_gas_y = pinned_y(combustion, "outlet")
    offgas.pin(port="inlet", x=2960, y=1680)
    alumina.pin(port="inlet", x=2980, y=pinned_y(calciner, "product"))

    spent_tank.pin(port="in_1", x=1350, y=1800)
    # Level with the inlet it feeds.
    caustic.pin(port="outlet", x=1230, y=pinned_y(spent_tank, "in_3"))
    evaporator.pin(port="feed", x=1550, y=1980)
    lp_steam.pin(port="outlet", x=1330,
                 y=pinned_y(evaporator, "heating_in"))
    evap_condensate.pin(
        port="inlet", x=1820,
        y=pinned_y(evaporator, "condensate"))
    evap_vapour.pin(port="inlet", x=1700, y=1830)
    liquor_pump.pin(port="suction", x=1800, y=2220)
    # ``mirrored=True`` points the flag west, the way the liquor goes.
    spent_liquor.pin(mirrored=True).pin(port="inlet", x=1150, y=lane_home_y)

    classifier_1_axis_x = pinned_x(classifier_1, "overflow")
    classifier_2_axis_x = pinned_x(classifier_2, "overflow")
    product_axis_x = pinned_x(product_cyclone, "overflow")
    evap_bottoms_x = pinned_x(evaporator, "concentrate")
    evap_vapour_x = pinned_x(evaporator, "vapor")
    spent_in_2_y = pinned_y(spent_tank, "in_2")
    spent_draw_x = pinned_x(spent_tank, "outlet")

    # --- Precipitation and classification -----------------------------
    # Declare the return to PFD-901 first, so the table reads in order.
    fs.connect(liquor_pump.discharge, spent_liquor.inlet, name="S-903").via(
        [(pinned_x(liquor_pump, "discharge"), lane_home_y)])
    fs.connect(pregnant_liquor.outlet, seed_tee.inlet, name="S-932")
    fs.connect(classifier_2.port("underflow"), seed_tee.branch,
               name="S-933").via([(classifier_2_axis_x, lane_seed_y),
                                  (pinned_x(seed_tee) + TEE_W / 2, lane_seed_y)])
    fs.connect(seed_tee.outlet, precipitator_1.feed, name="S-934")
    fs.connect(precipitator_1.outlet, precipitator_2.feed, name="S-935").via(
        [(pinned_x(precipitator_1, "outlet"),
          1270)])
    fs.connect(precipitator_2.outlet, classifier_1.feed, name="S-936").via(
        [(pinned_x(precipitator_2, "outlet"),
          1400)])
    fs.connect(classifier_1.port("underflow"), hydrate_filter.inlet,
               name="S-937").via([(classifier_1_axis_x, 1700)])
    fs.connect(classifier_1.port("overflow"), classifier_2.feed,
               name="S-938").via([(classifier_1_axis_x, 1180)])
    # Up over the precipitators and down to M-902.
    fs.connect(classifier_2.port("overflow"), spent_tank.port("in_1"),
               name="S-939").via([(classifier_2_axis_x, lane_spent_y),
                                  (lane_spent_x, lane_spent_y),
                                  (lane_spent_x, 1800)])

    # --- Hydrate filtration and calcination ---------------------------
    fs.connect(hydrate_wash.outlet, hydrate_filter.port("wash_in"),
               name="S-940").via(
                   [(pinned_x(hydrate_filter, "wash_in"), 1500)])
    fs.connect(hydrate_filter.outlet, spent_tank.port("in_2"),
               name="S-941").via(
                   [(2340, 1700), (2340, lane_filtrate_y),
                    (lane_filtrate_x, lane_filtrate_y),
                    (lane_filtrate_x, spent_in_2_y)])
    fs.connect(hydrate_filter.port("cake"), hydrate_belt.feed, name="S-942")
    fs.connect(hydrate_belt.discharge, calciner.feed, name="S-942")

    # --- Spent liquor -------------------------------------------------
    fs.connect(caustic.outlet, spent_tank.port("in_3"), name="S-943")
    fs.connect(spent_tank.outlet, evaporator.feed,
               name="S-944").via([(spent_draw_x, 1980)])
    fs.connect(lp_steam.outlet, evaporator.heating_in, name="S-945")
    fs.connect(evaporator.condensate, evap_condensate.inlet, name="S-946")
    fs.connect(evaporator.vapor, evap_vapour.inlet,
               name="S-947").via([(evap_vapour_x, 1830)])
    fs.connect(evaporator.concentrate, liquor_pump.suction,
               name="S-948").via([(evap_bottoms_x, 2220)])

    # --- Calcination --------------------------------------------------
    fs.connect(air.outlet, combustion.inlet, name="S-949")
    fs.connect(fuel.outlet, combustion.fuel, name="S-950").via(
        [(pinned_x(combustion, "fuel"), 2230)])
    # Into the windbox from below.
    fs.connect(combustion.outlet, calciner.air, name="S-951").via(
        [(pinned_x(calciner, "air"), combustion_gas_y)])
    fs.connect(calciner.product, product_tee.inlet, name="S-952")
    fs.connect(calciner.offgas, product_cyclone.feed, name="S-953")
    fs.connect(product_cyclone.port("overflow"), offgas.inlet,
               name="S-954").via([(product_axis_x, 1680)])
    fs.connect(product_cyclone.port("underflow"), product_tee.branch,
               name="S-955")
    fs.connect(product_tee.outlet, alumina.inlet, name="S-956")

    _furnish(
        fs, PRECIPITATION, 3, "Precipitation and Calcination",
        equipment=["PR-901", "PR-902", "CY-901", "CY-902", "F-902", "CV-902",
                   "M-902", "EV-901", "P-902", "FH-901", "CA-901", "CY-903"],
        utilities=[
            ["LP Steam", "EV-901", "61100", "27.8", "150 C", "150 C"],
            ["Fuel Gas", "FH-901", "83300", "1.67", "15 C", "-"],
            ["Combustion Air", "FH-901", "-", "33.3", "25 C", "1050 C"],
            ["Hydrate Wash Water", "F-902", "-", "41.7", "80 C", "-"],
        ],
        general_notes=[
            "Each item stands for the train it belongs to: two "
            "precipitators for a tank farm of twelve.",
            "Soda leaving chemically bound in the residue is replaced by the "
            "make-up on S-943. Soda dissolved in the residue's entrained "
            "liquor is what the washing on TH-902 recovers.",
            NOT_DRAWN,
        ],
    )
    return fs


def _furnish(fs, number, sheet, area, equipment, utilities, general_notes):
    """Tabulate a sheet's streams and add its title block and furniture."""
    for s in fs.streams:
        values = PROPERTIES.get(s.name)
        if values is not None:
            s.properties = dict(zip(PROPERTY_ROWS, values))
    fs.stream_table_sections = [("Water", "Mass Fraction")]

    # --- Title strip --------------------------------------------------
    fs.title_block = TitleBlock(
        title="Alumina Refinery",
        subtitle=f"A900 {area}",
        drawing_number=number,
        project="Bayer Process Alumina Refinery",
        company="PANDID",
        status="ISSUED FOR REVIEW",
        sheet=str(sheet), of_sheets="3",
        date="14/08/26",
        drawn_by="AA", checked_by="JS", approved_by="RL",
        revisions=[
            Revision("A", "26/06/26", "Issued for internal review", "AA"),
            Revision("B", "24/07/26", "Second flash stage added", "AA"),
            Revision("C", "14/08/26", "Issued For Review", "AA", "JS", "RL"),
        ],
    )

    # --- Sheet furniture ----------------------------------------------
    fs.add_annotation(equipment_list(fs, align="top-right", include=equipment))
    fs.add_annotation(TableBox(
        title="UTILITIES SUMMARY",
        headers=["Utility", "Unit No.", "Duty (kW)", "Flow (kg/s)", "T_in",
                 "T_out"],
        rows=utilities,
        col_align=["l", "l", "r", "r", "c", "c"],
        align="bottom-right",
    ))
    fs.add_annotation(notes(general_notes, title="GENERAL NOTES",
                            numbered=True, align="top-left"))


def main():
    for fs in (digestion(), clarification(), precipitation()):
        assert fs.title_block is not None
        name = f"{fs.title_block.drawing_number}.svg"
        fs.render(out(name), border="zone", show_stream_table=True)
        print(f"Generated {name}")
        for issue in fs.validate():
            print(f"  {issue}")


if __name__ == "__main__":
    main()
