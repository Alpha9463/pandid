#!/usr/bin/env python3
"""Generate pandid/devices.py, one class per scheduled device.

Three tables hold the mapping:

``DEVICES``
    ``(kind, variant)`` to class name and docstring.
``OWNS``
    Other drawings a class answers for, as
    ``{class-local variant: registry variant}``.
``STAYS_ON_BASE``
    Every drawing without a class, with the reason.

:func:`claims` stops generation unless every registered
``(kind, variant)`` is claimed exactly once.

Run:  python scripts/gen_devices.py
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pandid import units  # noqa: E402
from pandid.render.symbols import default_registry  # noqa: E402

OUT = HERE.parent / "pandid" / "devices.py"

# Kinds that never get a class, with the reason.
REFUSED_KINDS = {
    "instrument": "its variants are functions, not devices; see Instrument.repeats",
    "feed": "_Boundary.repeats tests the exact type; a subclass defeats it silently",
    "product": "_Boundary.repeats tests the exact type; a subclass defeats it silently",
}


# (kind, variant) -> (class name, docstring). The class draws that
# variant by default.
DEVICES = {
    # --- Pumps --------------------------------------------------------
    ("pump", "default"): ("CentrifugalPump", """Centrifugal pump: an impeller in a volute casing."""),
    ("pump", "gear"): ("GearPump", """Gear pump: two meshing gears, positive displacement."""),
    ("pump", "screw"): ("ScrewPump", """Screw pump: screws in a barrel, positive displacement."""),
    ("pump", "peristaltic"): ("PeristalticPump", """Peristaltic pump: rollers squeeze a tube.

    Both nozzles are on top of the head.
"""),
    ("pump", "submersible"): ("SubmersiblePump", """Submersible (sump) pump: it stands in the liquid it pumps.

    ``suction`` is the strainer plate underneath; ``discharge`` is the
    riser.
"""),
    ("pump", "vacuum"): ("VacuumPump", """Vacuum pump: pulls a system below atmospheric pressure.

    For a liquid-ring machine, use :class:`LiquidRingCompressor`.
"""),

    # --- Compressors --------------------------------------------------
    ("compressor", "default"): ("CentrifugalCompressor", """Centrifugal compressor: dynamic compression for large gas flows."""),
    ("compressor", "reciprocating"): ("ReciprocatingCompressor", """Reciprocating compressor: a piston in a cylinder."""),
    ("compressor", "rotary"): ("RotaryCompressor", """Rotary compressor: screws or lobes."""),
    ("compressor", "liquid_ring"): ("LiquidRingCompressor", """Liquid-ring compressor: a rotating liquid seal does the work."""),

    # --- Fans ----------------------------------------------------------
    ("blower", "centrifugal"): ("CentrifugalFan", """Centrifugal fan: an impeller in a scroll casing.

    ``suction`` enters the eye from the west and ``discharge`` leaves
    the scroll's outlet on the east.
"""),
    ("blower", "axial"): ("AxialFan", """Axial fan: a propeller across the duct, gas straight through."""),

    # --- Heat exchangers ----------------------------------------------
    ("hex", "default"): ("ShellAndTubeExchanger", """Shell-and-tube exchanger: a tube bundle inside a shell."""),
    ("hex", "double_pipe"): ("DoublePipeExchanger", """Double-pipe exchanger: a pipe in a pipe, drawn as a hairpin.

    Both fluids enter at one end and turn round at the far one.
"""),
    ("hex", "kettle"): ("KettleReboiler", """Kettle reboiler: a bundle in an enlarged shell, with a weir.

    ``bottoms`` is the draw at the weir end. The tube side carries the
    heating medium; ``tube_out`` is on the far dished head.
"""),
    ("hex", "condenser"): ("Condenser", """Condenser: an exchanger taking an overhead vapour to liquid.

    For the single-stream utility symbol, use
    :class:`pandid.units.Cooler`.
"""),
    ("hex", "air_cooled"): ("AirCooledExchanger", """Air-cooled exchanger: a finned bundle with air blown over it.

    ``air_in`` and ``air_out`` mark the air path through the fan bay.
"""),
    ("hex", "plate"): ("PlateExchanger", """Plate exchanger: a pack of plates with two circuits."""),
    ("hex", "spiral"): ("SpiralExchanger", """Spiral exchanger: two channels coiled about a common centre."""),
    ("hex", "thin_film"): ("ThinFilmEvaporator", """Thin-film evaporator: a rotor spreads feed on a heated wall.

    Product runs top to bottom; the heating medium runs through the
    jacket.
"""),

    # --- Evaporators --------------------------------------------------
    ("evaporator", "calandria"): ("CalandriaEvaporator", """Calandria evaporator: short tubes round a central downcomer."""),
    ("evaporator", "falling_film"): ("FallingFilmEvaporator", """Falling-film evaporator: liquor flows down long heated tubes."""),
    ("evaporator", "climbing_film"): ("ClimbingFilmEvaporator", """Climbing-film evaporator: liquor fed into the foot of the tubes."""),
    ("evaporator", "plate"): ("PlateEvaporator", """Plate evaporator: a plate pack in place of a tube bundle."""),

    # --- Furnaces -----------------------------------------------------
    ("furnace", "combustion_chamber"): ("CombustionChamber", """Combustion chamber: fuel burned to make hot gas for another unit.

    ``inlet`` takes the combustion air on the west wall, ``fuel`` enters
    the burner from below and ``outlet`` sends the hot gas out of the
    top. ISO 10628-2 item 4.5 X8106.
"""),

    # --- Silos -------------------------------------------------------
    ("silo", "bunker"): ("Bunker", """Bunker: an open bin for bulk solids over a conical bottom.

    ISO 10628-2 item 1.8, 2064. Solids enter over the west wall at
    ``feed`` and leave the cone at ``discharge``.
"""),

    # --- Kilns and calciners ------------------------------------------
    ("kiln", "default"): ("RotaryKiln", """Rotary kiln: a sloping, turning shell fired down its length."""),
    ("kiln", "fluidized_bed"): ("FluidizedBedCalciner", """Fluidised-bed calciner: solids held up in the firing gas.

    ``product`` leaves over a weir and ``offgas`` from the freeboard.
"""),
    ("kiln", "shaft"): ("ShaftKiln", """Vertical shaft kiln: a column of burden fired at its middle."""),

    # --- Separators ---------------------------------------------------
    ("separator", "cyclone"): ("Cyclone", """Cyclone separator: a vortex throws the heavy phase down.

    ISO 15519-1 X 2618. The draws are ``overflow`` (gas) and
    ``underflow`` (solids).
"""),
    ("separator", "gravity"): ("GravitySeparator", """Gravity separator: the gas slows and the heavy phase falls."""),
    ("separator", "electrostatic"): ("ElectrostaticPrecipitator", """Electrostatic precipitator: charged dust collects on plates."""),
    ("separator", "sifter"): ("Screen", """Screen: a deck sorting by size, oversize over and fines through."""),
    ("separator", "impact"): ("ImpactSeparator", """Impact separator: a baffle the stream is thrown against."""),
    ("separator", "permanent_magnet"): ("MagneticSeparator", """Magnetic separator: pulls tramp metal out of a solids stream.

    ``default`` is a permanent magnet; ``electromagnetic`` is an
    electromagnet.
"""),
    ("separator", "scrubber"): ("Scrubber", """Wet scrubber: a wash liquid cleans a gas."""),
    ("separator", "venturi_scrubber"): ("VenturiScrubber", """Venturi scrubber: wash injected into an accelerating throat."""),
    ("separator", "knockout"): ("KnockoutDrum", """Knock-out drum: an upright drum with a demister pad."""),

    # --- Filters ------------------------------------------------------
    ("filter", "gas"): ("DustCollector", """Dust collector: a gas filter with a hopper under the medium.

    The variants are elements (``default``), a granular bed
    (``fixed_bed``) and a cloth on rollers (``belt``).
"""),
    ("filter", "rotary"): ("RotaryDrumFilter", """Rotary drum filter: a drum turning through slurry under vacuum.

    ``outlet`` is the filtrate, ``cake`` the solids lifted off and
    ``wash_in`` the wash sprays. ``scraper`` draws the knife.
"""),
    ("filter", "press"): ("FilterPress", """Filter press: a batch filter of clamped plates.

    ``outlet`` is the filtrate, ``cake`` the solids and ``wash_in`` the
    displacement wash.
"""),
    ("filter", "ion_exchange"): ("IonExchanger", """Ion exchanger: a resin bed between two retention screens.

    ``regenerant_in`` enters above the bed; ``spent_regenerant`` leaves
    the underdrain.
"""),

    # --- Dryers -------------------------------------------------------
    ("dryer", "default"): ("RotaryDryer", """Rotary drum dryer: a turning drum with hot gas through it."""),
    ("dryer", "fluidized_bed"): ("FluidizedBedDryer", """Fluidised-bed dryer: gas through a distributor holds up the bed."""),
    ("dryer", "spray"): ("SprayDryer", """Spray dryer: feed atomised into hot gas, powder off the floor."""),
    ("dryer", "shelf"): ("ShelfDryer", """Shelf (tray) dryer: trays of product in a heated chamber.

    ISO 10628-2 item 10.2.
"""),
    ("dryer", "turbo"): ("TurboDryer", """Turbo dryer: a stack of rotating discs on one shaft.

    ISO 10628-2 item 10.3.
"""),
    ("dryer", "belt"): ("BeltDryer", """Belt dryer: product carried through on a moving belt.

    ISO 10628-2 item 10.6.
"""),

    # --- Crushers and mills -------------------------------------------
    ("crusher", "jaw"): ("JawCrusher", """Jaw crusher: a swing jaw worked by an eccentric.

    ISO 10628-2 item 11.5.
"""),
    ("crusher", "cone"): ("ConeCrusher", """Cone crusher: a gyrating head inside a fixed bowl.

    ISO 10628-2 item 11.7.
"""),
    ("crusher", "hammer"): ("HammerCrusher", """Hammer crusher: swing hammers on a rotor against a breaker plate.

    ISO 10628-2 item 11.3.
"""),
    ("crusher", "impact"): ("ImpactCrusher", """Impact crusher: blow bars on a rotor throw feed at aprons.

    ISO 10628-2 item 11.4.
"""),
    ("crusher", "roller"): ("RollerCrusher", """Roll crusher: two counter-rotating rolls with a nip between.

    ISO 10628-2 item 11.6.
"""),
    ("mill", "hammer"): ("HammerMill", """Hammer mill: swing hammers against a screen.

    ISO 10628-2 item 11.9.
"""),
    ("mill", "impact"): ("ImpactMill", """Impact mill or pin mill: a rotor throws feed at a liner.

    ISO 10628-2 item 11.10.
"""),
    ("mill", "roller"): ("RollerMill", """Roller mill: rolls running on a table or against a ring.

    ISO 10628-2 item 11.11.
"""),
    ("mill", "vibration"): ("VibratingMill", """Vibrating mill: a charged drum shaken rather than tumbled.

    ISO 10628-2 item 11.12.
"""),

    # --- Solids conveying ---------------------------------------------
    ("conveyor", "screw"): ("ScrewConveyor", """Screw conveyor: a flighted shaft turning in a closed trough.

    ISO 10628-2 item 18.5. ``feed`` is on top near the tail and
    ``discharge`` underneath near the head. ``length=`` sets the trough
    length.
"""),

    # --- Feeders ------------------------------------------------------
    ("feeder", "rotary_valve"): ("RotaryValveFeeder", """Rotary valve feeder: a rotor metering solids through a housing.

    ISO 10628-2 item 19.2.
"""),
    ("feeder", "rotary_table"): ("RotaryTableFeeder", """Rotary table feeder: solids ploughed off a turning table.

    ISO 10628-2 item 19.3.
"""),
    ("feeder", "metering"): ("MeteringFeeder", """Metering (weigh) feeder: solids let through by measured weight.

    ISO 10628-2 item 19.4, drawn as a balance.
"""),

    # --- Screens ------------------------------------------------------
    ("screening_device", "coarse_rake"): ("CoarseRakeScreen", """Rake screen, coarse type: a mesh cleared by a coarse rake.

    ISO 10628-2 item 7.2.
"""),
    ("screening_device", "fine_rake"): ("FineRakeScreen", """Rake screen, fine type: a mesh cleared by a fine rake.

    ISO 10628-2 item 7.3.
"""),
    ("screening_device", "coarse_and_fine"): ("CoarseAndFineScreen", """Double-deck screen: a coarse deck over a fine one.

    ISO 10628-2 item 7.4.
"""),
    ("screening_device", "vibrating"): ("VibratingScreen", """Vibrating screen: a deck shaken to move material across it.

    ISO 10628-2 item 7.5.
"""),
    ("screening_device", "rotating_drum"): ("RotaryDrumScreen", """Rotary drum screen (trommel): a turning perforated cylinder.

    ISO 10628-2 item 7.6.
"""),
    ("screening_device", "basket_reel"): ("ReelScreen", """Reel screen: a wire basket turned between two rollers.

    ISO 10628-2 item 7.7.
"""),

    # --- Valves -------------------------------------------------------
    ("valve", "three_way"): ("ThreeWayValve", """Three-way valve: the run switches to a third leg, ``branch``."""),
    ("valve", "control"): ("ControlValve", """Control valve: the valve a controller modulates.

    Drawn as the general body with a diaphragm actuator (ISO 15519-2
    A.3.41); ``butterfly_pneumatic`` draws a butterfly body. The
    ``default`` body raises on ``normal_position="closed"``; use
    ``fail="closed"``.
"""),
    ("valve", "solenoid"): ("SolenoidValve", """Solenoid valve: an electrically operated on/off valve.

    It takes a ``fail`` position and may be shown normally closed.
"""),
    ("valve", "relief"): ("ReliefValve", """Pressure relief valve: opens itself at the set pressure.

    ``default`` draws the bonnet-on-a-stem body and ``psv`` the
    spring-loaded angle body. A ``fail`` position or
    ``normal_position="closed"`` raises.
"""),
    ("valve", "regulator"): ("PressureRegulator", """Self-acting regulator: the process works its own diaphragm.

    ``actuator`` is the external pilot line. A ``fail`` position or
    ``normal_position="closed"`` raises.
"""),
    ("valve", "motor"): ("MotorOperatedValve", """Motor-operated valve: a block valve on an electric actuator.

    It takes a ``fail`` position and may be shown normally closed.
"""),
    ("valve", "check"): ("CheckValve", """Check valve: passes flow one way and shuts against the other.

    Its ports are ``inlet`` and ``outlet``. A normally closed one is
    marked ``NC`` (PIP PIC001 4.2.2.8).
"""),

    # --- In-line fittings ---------------------------------------------
    ("fitting", "blind"): ("SpectacleBlind", """Spectacle blind: two discs on a tie, one bored and one solid.

    ``normal_position="open"`` puts the ring in the line;
    ``normal_position="closed"`` puts the solid disc in it.
"""),
    ("fitting", "steam_trap"): ("SteamTrap", """Steam trap: drains condensate from a steam line.

    ISO 10628-2 item 24.15.
"""),
    ("fitting", "venturi"): ("FlowElement", """Primary flow element: the device in the run an FE balloon reads.

    The variant is the metering principle. Attach the balloon with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument`.
"""),

    # --- Reactors -----------------------------------------------------
    ("reactor", "default"): ("StirredTankReactor", """Stirred-tank reactor: a charge vessel with a top agitator.

    ``n_feeds`` adds feed ports as on :class:`pandid.units.Reactor`.
"""),
    ("reactor", "jacketed"): ("JacketedReactor", """Jacketed reactor: a stirred tank inside a heating or cooling jacket.

    ``jacket_in`` is low on the jacket and ``jacket_out`` high on it.
    ``n_feeds`` adds feed ports as on :class:`pandid.units.Reactor`.
"""),

    # --- Storage ------------------------------------------------------
    ("tank", "gas_holder"): ("GasHolder", """Gas holder: a bell floating in a water seal.

    ``inlet`` and ``outlet`` are the gas main on the seal tank. ``vent``
    and ``relief`` are the crown valves on the bell; ``drain`` is the
    seal water.
"""),
}


# class -> {class-local variant: registry variant}, for a class that
# draws more than one registry variant.
OWNS = {
    "ShellAndTubeExchanger": {
        "default": "default", "shell_tube": "shell_tube", "u_tube": "u_tube",
        "straight_tubes": "straight_tubes", "finned": "finned", "hairpin": "hairpin",
    },
    "MagneticSeparator": {
        "default": "permanent_magnet", "electromagnetic": "electromagnetic",
    },
    "DustCollector": {
        "default": "gas", "fixed_bed": "gas_fixed_bed", "belt": "gas_belt",
    },
    "RotaryDrumFilter": {"default": "rotary", "scraper": "rotary_scraper"},
    "ControlValve": {
        "default": "control", "butterfly_pneumatic": "butterfly_pneumatic",
    },
    "ReliefValve": {"default": "relief", "psv": "psv"},
    "FlowElement": {
        "default": "venturi", "venturi": "venturi", "flow_nozzle": "flow_nozzle",
        "coriolis": "coriolis", "vortex": "vortex", "ultrasonic": "ultrasonic",
        "turbine_meter": "turbine_meter",
        "positive_displacement": "positive_displacement",
        "v_cone": "v_cone", "wedge": "wedge", "target": "target",
        "pitot": "pitot", "averaging_pitot": "averaging_pitot",
    },
}


# class -> complete port list, where it differs from the base's.
PORT_OVERRIDES = {
    "CheckValve": [("inlet", "inlet", "process"), ("outlet", "outlet", "process")],
}


# (kind, variant) -> why this drawing gets no class.
STAYS_ON_BASE = {
    ("block", "default"): "Block's own drawing",
    ("blower", "default"): "Blower's own drawing",
    ("blower", "general"): "ISO item 17.1: the general fan, no casing type drawn",
    ("boiler", "default"): "Boiler's own drawing",
    ("conveyor", "default"): "Conveyor's own drawing",
    ("cooler", "default"): "Cooler's own drawing",
    ("cooling_tower", "default"): "CoolingTower's own drawing (the fan on the stack)",
    ("cooling_tower", "induced_draft"):
        "fan arrangement, and the same drawing as the default",
    ("cooling_tower", "forced_draft"):
        "fan arrangement: the fan in a housing at the foot of each side",
    ("centrifuge", "default"): (
        "Centrifuge's own drawing (ISO item 9.6 X8082, the decanter) -- "
        "same drawing as decanter, below"
    ),
    ("centrifuge", "high_speed"): "mechanism: item 9.1 X2619, the open rotor",
    ("centrifuge", "perforated_shell"):
        "mechanism: item 9.2 X2614, a basket with broken walls",
    ("centrifuge", "solid_shell"): "mechanism: item 9.3 X8035, a basket with solid walls",
    ("centrifuge", "disc"): "mechanism: item 9.4 X8036, the disc stack",
    ("centrifuge", "screw_perforated"):
        "mechanism: item 9.5 X8037, a screw in a perforated shell",
    ("centrifuge", "decanter"): "mechanism: item 9.6 X8082, a screw in a solid shell",
    ("centrifuge", "pusher"): "mechanism: item 9.7 X8038, the pusher plate",
    ("centrifuge", "skimmer"): "mechanism: item 9.8 X8039, the skimmer tube",
    ("crushing_machine", "default"):
        "CrushingMachine's own drawing (ISO item 11.1, no characteristic)",
    ("cooling_tower", "general"): "ISO item 5.1: the bare outline, no fill or draught mark",
    ("cooling_tower", "dry_natural"): "fill + draught: dry fill, no fan (natural draught)",
    ("cooling_tower", "dry_forced"): "fill + draught: dry fill, fan low in the tower",
    ("cooling_tower", "dry_induced"): "fill + draught: dry fill, fan high in the tower",
    ("cooling_tower", "wet_natural"): "fill + draught: wet fill, no fan (natural draught)",
    ("cooling_tower", "wet_forced"): "fill + draught: wet fill, fan low in the tower",
    ("cooling_tower", "wet_induced"): "fill + draught: wet fill, fan high in the tower",
    ("cooling_tower", "wet_dry_natural"):
        "fill + draught: both fill marks, no fan (natural draught)",
    ("crusher", "default"): "Crusher's own drawing (ISO item 11.2, no characteristic)",
    ("mill", "default"): "Mill's own drawing (ISO item 11.8, no characteristic)",
    ("dryer", "general"): "ISO item 10.1: the bare casing, no characteristic drawn",
    ("feeder", "general"): "ISO item 19.1: the bare circle, no mechanism drawn",
    ("screening_device", "general"): "ISO item 7.1: the bare outline, no mechanism drawn",
    ("kneader", "default"): "Kneader's own drawing (ISO item 12.4 X8134)",
    ("evaporator", "default"):
        "the general row: two tubesheets around a boxed element, no element chosen",
    ("thickener", "default"): "Thickener's own drawing (draw.io's settling tank)",
    ("silo", "default"): "Silo's own drawing (ISO item 1.9 X2062, the closed silo)",
    ("crystallizer", "default"): "Crystallizer's own drawing (the draft-tube baffle body)",
    ("flotation_cell", "default"): "FlotationCell's own drawing (the mechanical cell)",
    ("mixer_settler", "default"): "MixerSettler's own drawing",
    ("deaerator", "default"): "Deaerator's own drawing",
    ("spray_nozzle", "default"): "SprayNozzle's own drawing (ISO item 19.5 2037)",
    ("fitting", "rotary_mixer"): "body style: a rotating mixing element in the run",
    ("fitting", "mixing_path"): "body style: three mixing elements in series in the run",
    ("elevator", "default"): "Elevator's own drawing (ISO item 18.7, the straight lift)",
    ("elevator", "z_form"): "body style: the same lift with a run at each end",
    ("ejector", "default"): "Ejector's own drawing",
    ("filter", "default"): "Filter's own drawing (bag, candle or cartridge elements)",
    ("flare", "default"): "Flare's own drawing",
    ("funnel", "default"): "Funnel's own drawing",
    ("furnace", "default"): "Furnace's own drawing",
    ("furnace", "general"): "ISO item 4.3: the general furnace, no tubes drawn",
    ("heater", "default"): "Heater's own drawing",
    ("mixer", "default"): "Mixer's own drawing",
    ("separator", "default"): "Separator's own drawing (the flash drum)",
    ("splitter", "default"): "Splitter's own drawing",
    ("stack", "default"): "Stack's own drawing",
    ("tank", "default"): "Tank's own drawing",
    ("tee", "default"): "Tee's own drawing",
    ("turbine", "default"): "Turbine's own drawing",
    ("vent", "default"): "Vent's own drawing",
    ("vessel", "default"): "Vessel's own drawing",
    ("column", "default"): "Column's own drawing",
    ("reactor", "tubular"): "body style: a horizontal shell with a tube pass",
    ("feed", "default"): "a boundary flag, not equipment",
    ("product", "default"): "a boundary flag, not equipment",
    ("instrument", "default"): "a function, not a device",
    ("instrument", "panel"): "a function, not a device",
    ("instrument", "aux"): "a function, not a device",
    ("instrument", "shared"): "a function, not a device",
    ("instrument", "computer"): "a function, not a device",
    ("instrument", "sis"): "a function, not a device",
    ("instrument", "logic"): "a function, not a device",
    ("instrument", "interlock"): "a function, not a device",
    ("vessel", "dished"): "head style, plus the brackets it stands on",
    ("vessel", "dome"): "head style: a raised manway dome",
    ("vessel", "horizontal"): "attitude: the same vessel lying down",
    ("vessel", "swaged"): "shell style: one vessel in two diameters",
    ("vessel", "jacketed"): "cladding: a heating/cooling jacket",
    ("vessel", "insulated"): "cladding: thermal insulation",
    ("vessel", "electrical_heating"): "a heating element hung on the shell wall",
    ("tank", "conical"): "roof: conical",
    ("tank", "floating_roof"): "roof: floating",
    ("tank", "sphere"): "shell style: a pressure sphere on legs",
    ("tank", "conical_bottom"): "floor: a discharge cone",
    ("tank", "conical_ends"): "roof and floor: a cone at each end",
    ("tank", "dished_roof_conical_bottom"): "roof and floor",
    ("column", "packed"): "drawn internal: beds of packing on their support grids",
    ("reducer", "default"): "Reducer's own drawing (the concentric body)",
    ("reducer", "concentric"): "body style, and the same drawing as the default",
    ("reducer", "eccentric"): "body style: flat along one side",
    ("vent", "exhaust_head"): "body style: a silencing hood",
    ("vent", "breather"): "body style: a conservation vent",
    ("filter", "belt"): "medium: a cloth on rollers, in a liquid casing",
    ("filter", "fixed_bed"): "medium: a granular bed, in a liquid casing",
    ("separator", "horizontal"): "attitude: the same separator lying down",
    ("valve", "default"): "Valve's own drawing (the gate body)",
    ("valve", "gate"): "body style, and the same drawing as the default",
    ("valve", "globe"): "body style",
    ("valve", "ball"): "body style",
    ("valve", "butterfly"): "body style",
    ("valve", "needle"): "body style",
    ("valve", "saunders"): "body style: a weir under a diaphragm, and no operator drawn",
    ("valve", "plug"): "body style",
    ("valve", "pinch"): "body style",
    ("valve", "knife"): "body style",
    ("valve", "angle"): "body style: the seat turns the flow a quarter",
    ("valve", "bleed"): "body style: the small drain valve tapped off a header",
    ("valve", "manual"): "operator style: a handwheel drawn on the body",
    ("valve", "hydraulic"): "operator style: a hydraulic cylinder drawn on the body",
    ("fitting", "default"): "Fitting's own drawing (a flanged joint)",
    ("fitting", "flange"): "body style, and the same drawing as the default",
    ("fitting", "strainer"): "body style",
    ("fitting", "strainer_cone"): "body style",
    ("fitting", "strainer_y"): "body style",
    ("fitting", "strainer_basket"): "body style",
    ("fitting", "strainer_duplex"): "body style",
    ("fitting", "orifice"): "body style: a restriction orifice, which restricts rather than measures",
    ("fitting", "rotameter"): "body style: a variable-area meter carrying its own indication",
    ("fitting", "rupture_disc"): "body style",
    ("fitting", "sight_glass"): "body style",
    ("fitting", "sight_glass_lit"): "body style: the same glass, lit",
    ("fitting", "silencer"): "body style",
    ("fitting", "expansion_joint"): "body style: a lens between two faces",
    ("fitting", "bellows"): "body style: four convolutions between two flanges",
    ("fitting", "damper"): "body style: a blade on a pivot",
    ("fitting", "spool"): "bulk piping: the length taken out to break a line",
    ("fitting", "hose"): "bulk piping",
    ("fitting", "coupling"): "bulk piping",
    ("fitting", "clamped_coupling"): "bulk piping",
    ("fitting", "static_mixer"): "body style: mixing elements in the run",
    ("fitting", "flame_arrestor"): "certification rating",
    ("fitting", "flame_arrestor_explosion_proof"): "certification rating",
    ("fitting", "flame_arrestor_detonation_proof"): "certification rating",
    ("fitting", "flame_arrestor_fire_resistant"): "certification rating",
}


# ----------------------------------------------------------------------
# The tables, held to the registry
# ----------------------------------------------------------------------


def variant_map(class_name: str, home: str) -> dict[str, str]:
    """Return a class's ``{class-local: registry}`` variant map.

    Parameters
    ----------
    class_name : str
        Generated class name.
    home : str
        Registry variant the class is named for.

    Returns
    -------
    dict[str, str]
        Class-local variant to registry variant.
    """
    if class_name in OWNS:
        return dict(OWNS[class_name])
    return {"default": home}


def declared_variants(mapping: dict[str, str]) -> tuple[str, ...]:
    """Return ``VARIANTS``: class-local names, then registry ones.

    Parameters
    ----------
    mapping : dict[str, str]
        Output of :func:`variant_map`.

    Returns
    -------
    tuple[str, ...]
        Accepted variant names.
    """
    return tuple(dict.fromkeys([*mapping, *mapping.values()]))


def base_of(kind: str) -> type:
    """Return the exported units class that owns ``kind``.

    Parameters
    ----------
    kind : str
        Unit kind.

    Returns
    -------
    type
        Base class for generated subclasses.

    Raises
    ------
    SystemExit
        If no exported class owns ``kind``.
    """
    for name in units.__all__:
        cls = getattr(units, name)
        if cls is not units.Unit and cls.kind == kind and not cls.VARIANTS:
            return cls
    raise SystemExit(f"no class in units.__all__ owns kind {kind!r}")


def ports_for(base: type, variant: str) -> list[tuple[str, str, str]]:
    """Return a base's declared ports plus those of ``variant``.

    Parameters
    ----------
    base : type
        Base unit class.
    variant : str
        Registry variant.

    Returns
    -------
    list[tuple[str, str, str]]
        ``(name, direction, role)`` port specs.
    """
    declared = base._declared_ports()
    variant_ports = base._variant_ports(variant)
    return [*declared, *variant_ports]


def claims() -> dict[tuple[str, str], str]:
    """Return each registered ``(kind, variant)`` and its claimant.

    Returns
    -------
    dict[tuple[str, str], str]
        Registry key to claiming class or reason.

    Raises
    ------
    SystemExit
        If a key is unclaimed, unknown, refused or claimed twice.
    """
    registered = set(default_registry._symbols)
    claimed: dict[tuple[str, str], str] = {}
    twice: list[str] = []

    def claim(key: tuple[str, str], by: str) -> None:
        """Record a claim, noting a second claim on one key.

        Parameters
        ----------
        key : tuple[str, str]
            Registry ``(kind, variant)``.
        by : str
            Claiming class or reason.
        """
        if key in claimed:
            twice.append(f"{key[0]}/{key[1]} (by {claimed[key]} and by {by})")
        claimed[key] = by

    for (kind, variant), (class_name, _doc) in DEVICES.items():
        if kind in REFUSED_KINDS:
            raise SystemExit(
                f"DEVICES names {class_name} for {kind}/{variant}, and a {kind} may "
                f"not have a class: {REFUSED_KINDS[kind]}"
            )
        for registry_variant in set(variant_map(class_name, variant).values()):
            claim((kind, registry_variant), class_name)
    for key, why in STAYS_ON_BASE.items():
        claim(key, f"STAYS_ON_BASE ({why})")

    if twice:
        raise SystemExit(
            "two claims on one drawing, and a drawing is one device: "
            + ", ".join(sorted(twice))
        )
    orphans = sorted(claimed.keys() - registered)
    if orphans:
        raise SystemExit(
            "the tables claim drawings the registry does not have: "
            + ", ".join(f"{kind}/{variant}" for kind, variant in orphans)
        )
    unclaimed = sorted(registered - claimed.keys())
    if unclaimed:
        raise SystemExit(
            "nothing says what these are: "
            + ", ".join(f"{kind}/{variant}" for kind, variant in unclaimed)
            + ".\nEvery registered symbol is claimed exactly once, by a DEVICES "
            "entry (it is its own device), by an OWNS value (another class draws "
            "it too) or by a STAYS_ON_BASE entry (it is a style of something that "
            "already has a class). Say which, in scripts/gen_devices.py."
        )
    return claimed


def spec_of(class_name: str, kind: str, home: str, doc: str) -> dict:
    """Return one generated class's spec, read from the live library.

    Parameters
    ----------
    class_name : str
        Generated class name.
    kind : str
        Unit kind.
    home : str
        Registry variant the class is named for.
    doc : str
        Class docstring.

    Returns
    -------
    dict
        Name, base, doc, variants, aliases and ports.

    Raises
    ------
    SystemExit
        If owned drawings differ in ports, or the base is unresolved.
    """
    base = base_of(kind)
    mapping = variant_map(class_name, home)
    variants = declared_variants(mapping)
    aliases = {local: registry for local, registry in mapping.items() if local != registry}
    ports = PORT_OVERRIDES.get(class_name) or ports_for(base, home)
    # Every owned drawing must share one port list.
    for registry_variant in set(mapping.values()):
        also = PORT_OVERRIDES.get(class_name) or ports_for(base, registry_variant)
        if also != ports:
            raise SystemExit(
                f"{class_name} owns {home!r} and {registry_variant!r}, which do not "
                f"have the same nozzles ({[p[0] for p in ports]} against "
                f"{[p[0] for p in also]}); a class is one set of nozzles, so those "
                f"are two classes"
            )
    return {
        "name": class_name, "base": base.__name__, "doc": doc,
        "variants": variants, "aliases": aliases, "ports": ports,
    }


HEADER = '''"""Named equipment classes, one per scheduled device.

GENERATED by scripts/gen_devices.py. Do not edit by hand.

Each class subclasses a :mod:`pandid.units` base and draws one of its
variants by default, so ``Cyclone("S-1")`` draws
``Separator("S-1", variant="cyclone")``.
"""

from pandid.ports import Port
from pandid.units import (
{imports})

__all__ = [
{exports}]
'''


def render() -> str:
    """Return the generated module source with LF line endings.

    Returns
    -------
    str
        Module source.

    Raises
    ------
    SystemExit
        If the tables disagree or a name is in ``units.__all__``.
    """
    claims()
    specs = [spec_of(class_name, kind, variant, doc)
             for (kind, variant), (class_name, doc) in DEVICES.items()]

    taken = set(units.__all__)
    clashes = sorted(spec["name"] for spec in specs if spec["name"] in taken)
    if clashes:
        raise SystemExit(
            "these class names are already in units.__all__, and the package "
            "re-exports both: " + ", ".join(clashes)
        )

    lines = [HEADER.format(
        imports="".join(f"    {base},\n" for base in sorted({s["base"] for s in specs})),
        exports="".join(f'    "{spec["name"]}",\n' for spec in specs),
    )]
    for spec in specs:
        lines.append(emit(spec))
    return "\n".join(lines)


def emit(spec: dict) -> str:
    """Return one generated class as source.

    Parameters
    ----------
    spec : dict
        Output of :func:`spec_of`.

    Returns
    -------
    str
        Class source.
    """
    body = [
        "",
        f"class {spec['name']}({spec['base']}):",
        f'    """{spec["doc"].rstrip()}\n\n'
        f'    Parameters are those of :class:`~pandid.units.{spec["base"]}`.\n    """',
        "",
        f"    VARIANTS = {_variants_source(spec['variants'])}",
    ]
    if spec["aliases"]:
        body.append(f"    VARIANT_ALIASES = {_dict(spec['aliases'])}")
    # Unit._declared_ports reads the nearest PORTS up the class tree.
    if spec["ports"] != getattr(units, spec["base"])._declared_ports():
        body.append(f"    PORTS = {_ports_source(spec['ports'])}")
    body.append("")
    body += [f"    {name}: Port" for name, _direction, _role in spec["ports"]]
    body.append("")
    return "\n".join(body)


def _q(text: str) -> str:
    """Return ``text`` double-quoted.

    Parameters
    ----------
    text : str
        Text to quote.

    Returns
    -------
    str
        ``"text"``.
    """
    return f'"{text}"'


def _variants_source(variants: tuple[str, ...]) -> str:
    """Return ``VARIANTS`` as source, wrapped if over one line.

    Parameters
    ----------
    variants : tuple[str, ...]
        Variant names.

    Returns
    -------
    str
        Tuple literal.
    """
    if len(variants) == 1:
        return f"({_q(variants[0])},)"
    flat = "(" + ", ".join(_q(v) for v in variants) + ")"
    if len(flat) + len("    VARIANTS = ") <= 99:
        return flat
    return _wrap("(", [_q(v) for v in variants], ")")


def _wrap(open_bracket: str, entries: list[str], close_bracket: str) -> str:
    """Return a literal with one entry per line, closed at indent 4.

    Parameters
    ----------
    open_bracket : str
        Opening bracket.
    entries : list[str]
        Entry sources.
    close_bracket : str
        Closing bracket.

    Returns
    -------
    str
        Wrapped literal.
    """
    return (open_bracket + "\n"
            + "".join(f"        {entry},\n" for entry in entries)
            + "    " + close_bracket)


def _dict(mapping: dict[str, str]) -> str:
    """Return a string mapping as a one-line dict literal.

    Parameters
    ----------
    mapping : dict[str, str]
        Mapping to write.

    Returns
    -------
    str
        Dict literal.
    """
    return "{" + ", ".join(f"{_q(k)}: {_q(v)}" for k, v in mapping.items()) + "}"


def _ports_source(ports: list[tuple[str, str, str]]) -> str:
    """Return ``PORTS`` as source, wrapped if over one line.

    Parameters
    ----------
    ports : list[tuple[str, str, str]]
        Port specs.

    Returns
    -------
    str
        List literal.
    """
    tuples = ["(" + ", ".join(_q(field) for field in port) + ")" for port in ports]
    flat = "[" + ", ".join(tuples) + "]"
    return flat if len(flat) + len("    PORTS = ") <= 99 else _wrap("[", tuples, "]")


def main() -> None:
    """Write ``pandid/devices.py`` and report the class count."""
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT} ({len(DEVICES)} classes over "
          f"{len(default_registry._symbols) - len(STAYS_ON_BASE)} of the "
          f"{len(default_registry._symbols)} registered symbols)")


if __name__ == "__main__":
    main()
