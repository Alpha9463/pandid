#!/usr/bin/env python3
"""Generate pandid/devices.py: one class per piece of equipment the registry draws.

:mod:`pandid.units` models equipment as a ``kind`` and a ``variant``, which is
how the symbol registry is keyed. ``pandid/devices.py`` adds named classes, so
an engineer finds ``Cyclone`` rather than ``Separator(variant="cyclone")`` and
a type checker sees ``cyclone.underflow``.

The rule: **a class is what the equipment is; ``variant=`` is how it is
drawn.** A variant becomes a class when it names a distinct scheduled item (a
row of its own on an equipment list). It stays a variant when it names a
support, roof, cladding, attitude, drawn internal, certification rating or body
style. Outside ``pandid.document._MAJOR_EQUIPMENT``, a variant becomes a class
only where the ports or a declarable property differ.

A different port set with no drawing of its own also earns a class, but not
here: ``pandid.units.DistillationColumn``, ``Absorber`` and ``Stripper`` draw
the ``Column`` symbol and differ only in their return ports, so they are
written by hand in ``pandid/units.py``.

Three tables hold the mapping:

``DEVICES``       the (kind, variant) each class is named for, its class name
                  and its docstring. One entry per class.
``OWNS``          other drawings a class also answers for, as
                  ``{class-local variant: registry variant}``.
``STAYS_ON_BASE`` every drawing that gets no class, with the reason.

:func:`claims` refuses to generate unless every registered ``(kind, variant)``
key is claimed exactly once, so a newly vendored stencil must be classified
first. Keys are claimed individually even where two share one drawing (such as
``valve/default`` and ``valve/gate``), since each is a name a caller may write.

Run:  python scripts/gen_devices.py
"""
import ast
import functools
import inspect
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pandid import units  # noqa: E402
from pandid.render.symbols import default_registry  # noqa: E402

OUT = HERE.parent / "pandid" / "devices.py"

# Kinds that must never get a class, with the reason. A subclass of any of
# these would be silently wrong.
REFUSED_KINDS = {
    # Instrument variants name functions (a logic square may repeat; see
    # Instrument.repeats), its constructor takes type/number, and pandid.spec
    # keeps instruments in their own section.
    "instrument": "its variants are functions, not devices; see Instrument.repeats",
    # _Boundary.repeats tests the exact type, so a subclassed flag would stop
    # matching the flags it repeats with.
    "feed": "_Boundary.repeats tests the exact type; a subclass defeats it silently",
    "product": "_Boundary.repeats tests the exact type; a subclass defeats it silently",
}


# (kind, variant) -> (class name, docstring): the drawing each class is named
# for, and the one it draws with no variant= argument.
DEVICES = {
    # --- Pumps -------------------------------------------------------------
    #
    # Each pump type is a separate machine and equipment-list row, though all
    # have suction and discharge.
    ("pump", "default"): ("CentrifugalPump", """Centrifugal pump: the volute-and-impeller workhorse.

    What ``Pump`` draws when it is asked for by name, under the name a
    schedule calls it. Head falls as flow rises, so it throttles on a
    control valve rather than on a relief; contrast :class:`GearPump`
    and :class:`ScrewPump`, which are positive displacement and do not.
"""),
    ("pump", "gear"): ("GearPump", """Gear pump: positive displacement, for viscous or metered duty.

    Two meshing gears carry fluid round the casing, so flow is set by
    speed and is very nearly independent of discharge pressure. That is
    why a positive displacement pump is protected by a relief valve and
    a centrifugal is not: a closed discharge has nowhere to go.
"""),
    ("pump", "screw"): ("ScrewPump", """Screw pump: positive displacement, for viscous duty.

    One or more screws in a close-fitting barrel, moving a smooth,
    pulsation-free flow along the axis. The same relief-valve rule as
    :class:`GearPump`.
"""),
    ("pump", "peristaltic"): ("PeristalticPump", """Peristaltic pump: rollers squeeze a tube, wetting nothing.

    The metering pump for a slurry or a reagent that must not meet a
    seal or an impeller: the fluid touches the hose and nothing else.
    Both connections leave the top of the head, which is where the
    stencil draws the tube.
"""),
    ("pump", "submersible"): ("SubmersiblePump", """Submersible (sump) pump: it stands in the liquid it pumps.

    The suction is the strainer plate it sits on rather than a piped
    nozzle, so the drawing is piped from underneath; the discharge is
    the riser out of the casing.
"""),
    ("pump", "vacuum"): ("VacuumPump", """Vacuum pump: the machine that pulls a system below atmospheric.

    Drawn as a pump rather than as a compressor because that is the
    stencil the set files it under; a liquid-ring machine doing the same
    duty is :class:`LiquidRingCompressor`.
"""),

    # --- Compressors -------------------------------------------------------
    ("compressor", "default"): ("CentrifugalCompressor", """Centrifugal compressor: dynamic compression, for large gas flows.

    What ``Compressor`` draws when it is asked for by name. Its stable
    range is bounded by surge at low flow, which is what the anti-surge
    recycle round one is for; a reciprocating machine has no such limit
    and needs no such line.
"""),
    ("compressor", "reciprocating"): ("ReciprocatingCompressor", """Reciprocating compressor: for high ratio or low flow.

    A piston in a cylinder, so the discharge pulses and the ratio is set
    by geometry rather than by speed. Like every positive displacement
    machine it is protected by a relief valve on the discharge.
"""),
    ("compressor", "rotary"): ("RotaryCompressor", """Rotary compressor: screws or lobes, and oil-free duty.

    The plant-air and blower-service machine: steady flow, modest ratio,
    and no valves to pulse.
"""),
    ("compressor", "liquid_ring"): ("LiquidRingCompressor", """Liquid-ring compressor: a rotating liquid seal does the work.

    Wet, tolerant of carryover and inherently cool, which is why it is
    the machine on a vacuum system handling condensable or dirty vapour.
    It carries a service liquid, which the sheet draws as an ordinary
    connection to the machine rather than as a nozzle of its own.
"""),

    # --- Heat exchangers ---------------------------------------------------
    #
    # hex is major equipment, so each scheduled item is a class. Five also
    # differ in ports (HeatExchanger._VARIANT_PORTS).
    ("hex", "default"): ("ShellAndTubeExchanger", """Shell-and-tube exchanger: a tube bundle inside a shell.

    The default exchanger and the one most of the family's drawings are
    styles of: the ISO circle-and-zigzag (``default``, ``shell_tube``),
    the U-tube and hairpin bundles that turn round inside the shell
    (``u_tube``, ``hairpin``), the horizontal elevation a real sheet
    draws (``straight_tubes``) and the finned bundle in the same casing
    (``finned``).

    Nozzles are named for the **side of the equipment** they sit on,
    never for the duty the stream carries: which fluid runs in the shell
    and which in the tubes is a design decision worth recording, and hot
    and cold invert between operating cases while the nozzle stays where
    it is.
"""),
    ("hex", "double_pipe"): ("DoublePipeExchanger", """Double-pipe exchanger: a pipe in a pipe, drawn as a hairpin.

    The small-duty exchanger, and the one whose two sides really are a
    tube and an annulus. Both fluids enter at the same end and turn
    round at the far one, so neither side has an east nozzle.
"""),
    ("hex", "kettle"): ("KettleReboiler", """Kettle reboiler: a bundle in an enlarged shell, with a weir.

    The one exchanger with a nozzle more. ``bottoms`` is the draw at the
    weir end: what does not boil overflows the plate and leaves the
    bottom of the shell, which is where a tower's bottoms product
    physically gets off the sheet. The draw belongs on the exchanger,
    not on an invented splitter in the sump line.

    The heating medium is the **tube** side; the process boils in the
    shell. The stencil draws one channel-head opening, so ``tube_out``
    takes the shell's far dished head.
"""),
    ("hex", "condenser"): ("Condenser", """Condenser: the exchanger taking an overhead vapour to liquid.

    The circle-and-zigzag with the heat-removed arrow across it, so the
    sides read the same way as the rest of the shell-and-tube family.
    For the single-stream utility symbol, where the cooling medium is a
    connection rather than a side, reach for
    :class:`pandid.units.Cooler` instead.
"""),
    ("hex", "air_cooled"): ("AirCooledExchanger", """Air-cooled exchanger: a finned bundle with air blown over it.

    The only piped side is the tube bundle. There is no shell, so the
    nozzles say so: ``air_in`` and ``air_out`` are the induced-draft
    bay's own faces, under the bundle and out through the fan, and
    neither is a pipe. That is why this is a class and not a style -- an
    exchanger with no shell cannot carry ``shell_in``.
"""),
    ("hex", "plate"): ("PlateExchanger", """Plate exchanger: a pack of plates, two circuits through it.

    Neither circuit is a shell or a tube and the two are physically
    interchangeable, so they are **lettered** rather than named:
    ``side_a`` and ``side_b``, each following the diagonal the artwork
    actually draws.
"""),
    ("hex", "spiral"): ("SpiralExchanger", """Spiral exchanger: two channels coiled about a common centre.

    Lettered sides for :class:`PlateExchanger`'s reason: neither channel
    is a shell or a tube. The self-cleaning geometry is what puts one in
    fouling or slurry duty.
"""),
    ("hex", "thin_film"): ("ThinFilmEvaporator", """Thin-film evaporator: a rotor spreads feed on a heated wall.

    The one evaporator in the set, and the one exchanger whose two sides
    are a **jacket** and a **product** side. Product runs top to bottom
    -- onto the wiper at the top, concentrate out of the cone apex --
    and the heating medium goes through the jacket, which is why neither
    pair borrows the shell-and-tube names.
"""),

    # --- Evaporators -------------------------------------------------------
    #
    # Named for the heating element, which is what a design picks.
    # ThinFilmEvaporator above stays a hex: its artwork has no vapour port.
    ("evaporator", "calandria"): ("CalandriaEvaporator", """Calandria (short-tube) evaporator: a short bundle with a central downcomer.

    The sugar and salt workhorse, and the body most people picture when
    they hear "evaporator": liquor rises through a short heated bundle
    and falls back down the middle, so the machine circulates on its own
    heat with nothing turning in it.
"""),
    ("evaporator", "falling_film"): ("FallingFilmEvaporator", """Falling-film evaporator: liquor fed onto a distributor over long tubes.

    The low-holdup, low-temperature-rise effect a multiple-effect train
    is built from, and what heat-sensitive duties -- dairy, juice,
    caustic liquor -- reach for. The distributor over the top tubesheet
    is drawn because it is the machine's defining internal: a tube it
    fails to wet dries out and fouls.
"""),
    ("evaporator", "climbing_film"): ("ClimbingFilmEvaporator", """Climbing-film evaporator: liquor fed into the foot of the tubes.

    The same long-tube body as :class:`FallingFilmEvaporator` with the
    feed at the other end: the liquor's own vapour carries it up the
    tube wall as a film. Simpler, since there is no distributor to keep
    even, and it needs a temperature difference to get the film started.
"""),
    ("evaporator", "plate"): ("PlateEvaporator", """Plate evaporator: a gasketed or welded plate pack in place of a bundle.

    Compact, low holdup, and dismantled for cleaning, which is what puts
    it in food and pharmaceutical duty. No tubesheets: the plates are the
    heating surface and they are clamped in a frame of their own.
"""),

    # --- Kilns and calciners -----------------------------------------------
    ("kiln", "default"): ("RotaryKiln", """Rotary kiln: a sloping shell, turning, fired down its length.

    Cement, lime, alumina and every roasting duty there is, and what
    ``Kiln`` draws when it is asked for by name. The fall from feed end
    to discharge is what moves the charge, so the drawing may not be
    turned; the riding rings are what tell the shell from a pipe.
"""),
    ("kiln", "fluidized_bed"): ("FluidizedBedCalciner", """Fluidised-bed or gas-suspension calciner: solids held in the gas that fires them.

    What a refinery built this century calcines hydrate in, and what a
    roaster does its work in. Product is drawn over a weir out of the
    bed and the spent gas leaves the freeboard above it, which is the
    nozzle a :class:`FluidizedBedDryer` standing in for one did not
    have.
"""),
    ("kiln", "shaft"): ("ShaftKiln", """Vertical shaft kiln: a column of burden, fired at its middle.

    The lime kiln, and the counter-current machine every fuel argument
    about calcination starts from: the charge preheats against the gas
    leaving, calcines at the burners, and cools against the air entering
    under it.
"""),

    # --- Separators --------------------------------------------------------
    #
    # Mechanical separators and dust collectors draw ``overflow`` and
    # ``underflow``; see the generated module docstring.
    ("separator", "cyclone"): ("Cyclone", """Cyclone separator: a vortex throws the heavy phase down.

    The gas-solid workhorse -- off a spray dryer, a fluidised bed, a
    mill -- and the hydrocyclone in a classifying duty. ISO 15519-1
    symbol X 2618, and one of the two the standard names as symbols
    gravity fixes the attitude of: the apex points down and the drawing
    says nothing true turned.

    The draws are ``overflow`` and ``underflow``, not ``vapor`` and
    ``liquid``, because the apex discharges a solid catch.
    ``Separator(variant="cyclone")`` draws the same pair.
"""),
    ("separator", "gravity"): ("GravitySeparator", """Gravity separator: velocity drops and the heavy phase falls.

    The crudest gas-solid separator there is, and usually the first
    stage ahead of a cyclone or a filter. ``overflow`` and ``underflow``
    for :class:`Cyclone`'s reason.
"""),
    ("separator", "electrostatic"): ("ElectrostaticPrecipitator", """Electrostatic precipitator: charged particles migrate to a plate.

    The high-efficiency dust collector on a flue-gas or a kiln duty,
    rapped clear into the hopper below. ``overflow`` and ``underflow``
    for :class:`Cyclone`'s reason.
"""),
    ("separator", "sifter"): ("Screen", """Screen: a deck sorting by size, oversize over and fines through.

    Named ``Screen`` rather than ``Sifter`` because that is the word a
    specification uses. One drawing covers scalping and sizing; the ports
    name positions because either draw may be the product.
"""),
    ("separator", "impact"): ("ImpactSeparator", """Impact separator: a baffle to throw the stream at.

    The knock-out on a pneumatic conveying line or a vent, where the
    heavy fraction cannot follow the gas round the baffle.
"""),
    ("separator", "permanent_magnet"): ("MagneticSeparator", """Magnetic separator: tramp metal pulled out of a solids stream.

    One class over both drawings: a **permanent** magnet (``default``)
    and an **electromagnet** (``electromagnetic``) differ only in how the
    field is made, with the same body and draws.
"""),
    ("separator", "scrubber"): ("Scrubber", """Wet scrubber: a wash liquid takes the contaminant out of a gas.

    Cleaned gas leaves the side and dirty liquid the hopper, a true
    vapour and liquid, so unlike the dust collectors it keeps ``vapor``
    and ``liquid``.
"""),
    ("separator", "venturi_scrubber"): ("VenturiScrubber", """Venturi scrubber: the wash is injected into an accelerating throat.

    A different mechanism from :class:`Scrubber`, so its own class: the
    gas is accelerated through a throat, which buys collection
    efficiency at the cost of pressure drop. The throat runs downward, so
    the feed is on the top.
"""),
    ("separator", "knockout"): ("KnockoutDrum", """Knock-out drum: an upright drum with a demister pad.

    A class despite the rule (drawn internals are variants) because
    "knock-out drum" is the term P&IDs, datasheets and searches use.

    The level gauge is drawn, not declared, so a level instrument added
    with :meth:`~pandid.flowsheet.Flowsheet.add_instrument` draws its own
    balloon beside it.
"""),

    # --- Filters -----------------------------------------------------------
    ("filter", "gas"): ("DustCollector", """Dust collector: a gas filter with a hopper under the medium.

    One class over the three gas casings, since the choice is the
    medium and all are piped alike: bag, candle or cartridge elements
    (``default``), a granular bed (``fixed_bed``) and a cloth on rollers
    (``belt``). Also known as a baghouse.
"""),
    ("filter", "rotary"): ("RotaryDrumFilter", """Rotary drum filter: a drum turns through slurry under vacuum.

    Cake builds on the submerged face and is lifted off at the top. The
    ``scraper`` variant draws the knife that lifts it.

    ``inlet`` is the slurry, ``outlet`` the filtrate, ``cake`` what is
    lifted off, and ``wash_in`` the sprays that displace mother liquor
    first. Both variants have the same ports in the same places.
"""),
    ("filter", "press"): ("FilterPress", """Filter press: plates squeezed together, slurry in, two products out.

    A batch machine on a continuous sheet. ``outlet`` is the filtrate and
    ``cake`` what the plates hold, often the product. ``wash_in`` is the
    displacement wash applied before the press opens.
"""),
    ("filter", "ion_exchange"): ("IonExchanger", """Ion exchanger: a resin bed between two retention screens.

    The vessel of a demineraliser or softener train; it removes
    dissolved rather than suspended matter. ``regenerant_in`` (acid,
    caustic or brine, above the bed) and ``spent_regenerant`` (out of the
    underdrain) replace the cake filters' wash and cake.
"""),

    # --- Dryers ------------------------------------------------------------
    ("dryer", "default"): ("RotaryDryer", """Rotary drum dryer: a turning drum with hot gas through it.

    The bulk-solids dryer, and what ``Dryer`` draws when it is asked for
    by name.
"""),
    ("dryer", "fluidized_bed"): ("FluidizedBedDryer", """Fluidised-bed dryer: gas up through a distributor holds the bed.

    Even temperature and a high transfer rate, at the price of a bed
    that has to stay fluidised. The bed is a layer on its plate, so the
    symbol is one gravity fixes the attitude of.
"""),
    ("dryer", "spray"): ("SprayDryer", """Spray dryer: feed atomised into hot gas, powder off the floor.

    Fed through the atomiser in its roof and drawn top to bottom rather
    than across, which is why the artwork must not be turned. The
    cyclone downstream of one is where the product is usually recovered;
    see :class:`Cyclone`.
"""),
    ("dryer", "shelf"): ("ShelfDryer", """Shelf (tray) dryer: trays of product in a heated oven or chamber.

    ISO 10628-2 item 10.2, X8083: the general drier's own casing
    carrying three shelf lines. Batch duty -- the trays are loaded and
    struck by hand -- next to the continuous machines the rest of the
    group draws.
"""),
    ("dryer", "turbo"): ("TurboDryer", """Turbo (disc, moving-shelf) dryer: a stack of rotating discs on one shaft.

    ISO 10628-2 item 10.3, X8040. The product moves down the stack from
    disc to disc as each one turns under it, which is what tells this
    from :class:`ShelfDryer`'s fixed trays -- the artwork's own shaft
    reaching to the casing's crown is the drive that turns them.
"""),
    ("dryer", "belt"): ("BeltDryer", """Belt (roller-conveyor) dryer: product carried through on a moving bed.

    ISO 10628-2 item 10.6, X8043. Continuous duty, drawn as the two
    rollers a belt runs on -- the same construction
    :class:`~pandid.units.Conveyor`'s belt variant draws, here inside a
    heated casing rather than in the open.
"""),

    # --- Crushers and mills -------------------------------------------------
    #
    # Each is a body carrying one ISO group-29 characteristic, and each is a
    # separate purchase. crusher/default and mill/default stay on their bases.
    ("crusher", "jaw"): ("JawCrusher", """Jaw crusher: a swing jaw worked by an eccentric.

    The primary crusher of a hard-rock circuit -- run-of-mine ore in at
    the top, one product size out of the bottom. ISO 10628-2 item 11.5
    X8047: the crusher body carrying item 29.9 C2036.
"""),
    ("crusher", "cone"): ("ConeCrusher", """Cone crusher: a gyrating head inside a fixed bowl.

    Secondary and tertiary duty behind a jaw, and where a gyratory
    crusher is drawn too. ISO 10628-2 item 11.7 X8049: the crusher body
    carrying item 29.12 C2038.
"""),
    ("crusher", "hammer"): ("HammerCrusher", """Hammer crusher: swing hammers on a rotor, against a breaker plate.

    For friable and medium-hard feed -- limestone, gypsum, coal. ISO
    10628-2 item 11.3 X8045: the crusher body carrying item 29.7 C2034.
"""),
    ("crusher", "impact"): ("ImpactCrusher", """Impact crusher: blow bars on a rotor throwing feed at aprons.

    Breaks on impact rather than by compression, so it makes a cubical
    product and more fines than a jaw. ISO 10628-2 item 11.4 X8046: the
    crusher body carrying item 29.8 C2035.
"""),
    ("crusher", "roller"): ("RollerCrusher", """Roll crusher: two counter-rotating rolls with a nip between them.

    A closely sized product from a friable feed, and the sizer of a coal
    or bauxite circuit. ISO 10628-2 item 11.6 X8048: the crusher body
    carrying item 29.11 C2037.
"""),
    ("mill", "hammer"): ("HammerMill", """Hammer mill: swing hammers against a screen.

    The same hammers as a hammer crusher in a machine ground for a
    finer product, which is the whole difference ISO draws between the
    two bodies. Item 11.9 X8050: the mill body carrying item 29.7 C2034.
"""),
    ("mill", "impact"): ("ImpactMill", """Impact mill, pin mill: a rotor throwing feed at a liner.

    Fine grinding of soft and friable solids. ISO 10628-2 item 11.10
    X8051: the mill body carrying item 29.8 C2035.
"""),
    ("mill", "roller"): ("RollerMill", """Roller mill: rolls running on a table or against a ring.

    The horizontal-rotation roller mill of a cement or coal circuit.
    ISO 10628-2 item 11.11 X8053: the mill body carrying item 29.11
    C2037.
"""),
    ("mill", "vibration"): ("VibratingMill", """Vibrating mill: a charged drum shaken rather than tumbled.

    Fine and ultrafine grinding in a small footprint. ISO 10628-2 item
    11.12 X8054, and the one group-11 row that is not a body and a mark
    alone: the drawing puts the two arrows of item 29.14 (3831) inside a
    drum the standard gives no number of its own, so the drum is drawn
    as part of the body. See
    ``pandid.render.symbols._VIBRATION_DRUM``.
"""),

    # --- Solids conveying ---------------------------------------------------
    #
    # A screw conveyor is a different purchase from a belt. The two bucket
    # elevator arrangements are one purchase and stay on Elevator.
    ("conveyor", "screw"): ("ScrewConveyor", """Screw conveyor: a flighted shaft turning in a closed trough.

    Short runs of dusty, hot or hazardous solids, where the enclosure
    is the point. Fed through a spout on top near the tail and
    discharged through one underneath near the head, which is where
    ISO 10628-2 item 18.5 X8063 draws its two connections.

    Sized by ``length=``, as every conveyor is; a longer trough gets
    more turns of the flight rather than a longer one.
"""),

    # --- Feeders -------------------------------------------------------------
    #
    # ISO 10628-2 group 19: three purchases, three classes. feeder/general
    # stays on the base.
    ("feeder", "rotary_valve"): ("RotaryValveFeeder", """Rotary valve feeder: a close-fitting rotor metering solids through a housing.

    The standard way solids enter a pressurised system, one pocket of
    the rotor at a time -- a purge lock as much as a feeder. ISO
    10628-2 item 19.2 X8067.
"""),
    ("feeder", "rotary_table"): ("RotaryTableFeeder", """Rotary table feeder: solids dropped onto a turning table and ploughed off its edge.

    A steady, low-headroom feed off a hopper -- ISO 10628-2 item 19.3
    C0074 -- drawn as the table, its shaft and the rotation it turns
    on.
"""),
    ("feeder", "metering"): ("MeteringFeeder", """Metering (weigh) feeder: solids let through in proportion to a measured weight.

    Drawn as a balance -- ISO 10628-2 item 19.4 C0035 -- because that
    is the principle: what leaves is metered against what the pans
    weigh, not against a timer or a gate position.
"""),

    # --- Screens -------------------------------------------------------------
    #
    # ISO 10628-2 group 7: six purchases, six classes. screen/general (item
    # 7.1) stays on the base.
    ("screening_device", "coarse_rake"): ("CoarseRakeScreen", """Rake screen, coarse type: a mesh cleared by a coarse-toothed rake.

    ISO 10628-2 item 7.2 X8026.
"""),
    ("screening_device", "fine_rake"): ("FineRakeScreen", """Rake screen, fine type: the same rake at a finer tooth pitch.

    ISO 10628-2 item 7.3 X8027.
"""),
    ("screening_device", "coarse_and_fine"): ("CoarseAndFineScreen", """Double-deck screen: a coarse deck over a fine one in one casing.

    ISO 10628-2 item 7.4 X8028: the two mesh lines Table 2 draws are
    the two decks, one screening pass each.
"""),
    ("screening_device", "vibrating"): ("VibratingScreen", """Vibrating screen: the deck itself is shaken to work material across it.

    The screener a sizing or dewatering duty reaches for first. ISO
    10628-2 item 7.5 X2605, the same double-arrow oscillation mark
    :class:`VibratingMill` carries on its own drum.
"""),
    ("screening_device", "rotating_drum"): ("RotaryDrumScreen", """Rotary drum screen, trommel: a slowly turning perforated cylinder.

    Coarse scalping ahead of a crusher, or dewatering off a wash
    circuit. ISO 10628-2 item 7.6 X8029.
"""),
    ("screening_device", "basket_reel"): ("ReelScreen", """Reel screen: a wire basket strung between two rollers and turned.

    ISO 10628-2 item 7.7 X8030, drawn in a taller outline than the
    other six rows to hold the reel's own rollers.
"""),

    # --- Valves ------------------------------------------------------------
    #
    # Split on behaviour, not body. Gate, ball and globe are body styles of one
    # block valve and stay variants; control, relief and check valves do
    # different jobs. three_way has a third port, so it is a class.
    ("valve", "three_way"): ("ThreeWayValve", """Three-way valve: a third leg the run is switched between.

    The ISO three-port mark, with the third connection anchored as
    ``branch`` -- see :class:`~pandid.units.Valve` for what it is
    declared as and why.
    """),
    ("valve", "control"): ("ControlValve", """Control valve: the final element a loop's output lands on.

    The valve a controller modulates. ISO 15519-2 Table A.3.20 is the
    general control valve with a general actuator; this draws the general
    body with A.3.41's diaphragm, the specific symbol Table 5 asks for on a
    P&ID (a PFD, per Table 4, would use the general one). The stencil set
    has no separate general actuator. ``butterfly_pneumatic`` is the same
    actuator on a butterfly disc, also reached as
    ``ControlValve(variant="butterfly", actuator="diaphragm")``.

    It usually declares ``fail=``. It may not be shown normally closed
    (PIP PIC001 4.2.2.10), since a darkened control valve reads as a closed
    block valve; use ``fail="closed"``.
"""),
    ("valve", "solenoid"): ("SolenoidValve", """Solenoid valve: an electrically operated on/off valve.

    The valve a trip acts through, and the pilot on a larger actuator.
    On/off rather than modulating, so it takes a ``fail`` position and
    it may be shown normally closed, which is how a dump or a purge
    valve is drawn.
"""),
    ("valve", "relief"): ("ReliefValve", """Pressure relief valve: it opens itself at the set pressure.

    The PSV/PRV a protected system is drawn with, in either of the two
    bodies the stencil set draws (``default`` is the bonnet-on-a-stem
    relief; ``psv`` is the spring-loaded angle body a real sheet draws).
    Worked by the process itself, so it has no actuating energy to lose
    and declares no ``fail``, and PIP PIC001 4.2.2.10 forbids showing it
    normally closed.
"""),
    ("valve", "regulator"): ("PressureRegulator", """Self-acting regulator: the process works its own diaphragm.

    A back-pressure or a reducing regulator, holding a pressure with no
    controller and no signal. Its "actuator" connection is the external
    pilot line rather than a signal terminus. No ``fail`` position for
    :class:`ReliefValve`'s reason, and no NC mark for the same clause.
"""),
    ("valve", "motor"): ("MotorOperatedValve", """Motor-operated valve: a block valve on an electric actuator.

    Stroked open or shut from the control system rather than modulated,
    which is why it takes a ``fail`` position and, unlike a control
    valve, may be shown normally closed.
"""),
    ("valve", "check"): ("CheckValve", """Check valve: it passes flow one way and shuts against the other.

    Worked by the flow itself, so it has no ``actuator`` port and a
    signal line cannot be connected to it; that missing port is why it is
    a class.

    The arrow inside the outline would be hidden by a darkened body, so a
    normally closed one is marked ``NC`` beside it (PIP PIC001 4.2.2.8).
"""),

    # --- In-line fittings --------------------------------------------------
    #
    # Fittings are not major equipment, so a class needs different ports or a
    # declarable property. The other fitting variants stay styles.
    ("fitting", "blind"): ("SpectacleBlind", """Spectacle blind: two discs on a tie, one bored and one solid.

    The fitting with a declarable property, which makes it a class. The
    stencil set draws both states:

    - ``normal_position="open"`` (the default) puts the **ring** in the
      line, with the solid disc parked above it: the line is through.
    - ``normal_position="closed"`` puts the **solid** disc in the line:
      blanked.
"""),
    ("fitting", "steam_trap"): ("SteamTrap", """Steam trap: drains condensate from a steam line and holds the steam.

    ISO 10628-2 Table 2 item 24.15, registered 2181. Drawn as the row
    draws it: a body with a diameter across it at 45 degrees and the
    discharge half below that filled.

    A class rather than a :class:`~pandid.units.Fitting` style because a
    trap is scheduled and bought as its own item. Fitted at each low point
    and drip leg of a steam main; condensate passes to the return header or
    drain.
"""),
    ("fitting", "venturi"): ("FlowElement", """Primary flow element: the device in the run an FE balloon reads.

    One class over the twelve the stencil set draws, because to the
    flowsheet they are the same thing -- a pair of faces on a line --
    and the choice between them is the metering principle: a
    differential-pressure profile (``default``/``venturi``,
    ``flow_nozzle``, ``v_cone``, ``wedge``, ``target``, ``pitot``,
    ``averaging_pitot``) or a meter body (``coriolis``, ``vortex``,
    ``ultrasonic``, ``turbine_meter``, ``positive_displacement``).

    A class rather than a ``Fitting`` style because it is listed on the
    instrument schedule. Attach the balloon with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument`. The restriction
    orifice (which restricts rather than measures) and the rotameter
    (which indicates itself) stay ``Fitting`` variants.
"""),

    # --- Reactors ----------------------------------------------------------
    ("reactor", "default"): ("StirredTankReactor", """Stirred-tank reactor: a charge vessel with a top agitator.

    A class despite the rule (an agitator is a drawn internal) because
    "stirred tank reactor" and "CSTR" are the terms engineers search for.

    ``n_feeds`` adds feed ports as on :class:`pandid.units.Reactor`.
"""),

    # --- Storage -----------------------------------------------------------
    ("tank", "gas_holder"): ("GasHolder", """Gas holder: a bell floating in a water seal.

    The only tank drawing with a class: other tank variants are roofs,
    floors or shells of one atmospheric liquid tank, while a gas holder
    stores gas at constant pressure and variable volume, with a moving
    bell and a water seal.

    ``inlet`` and ``outlet`` are the gas main, on the seal tank, since the
    bell moves. ``vent`` and ``relief`` are the crown valves on the bell,
    discharging to atmosphere. ``drain`` is the seal water.
"""),
}


# class -> {class-local variant: registry variant}, for classes that answer for
# more than one drawing. Generated VARIANTS lists both spellings, class-local
# first, because to_dict writes the registry name and it must read back.
OWNS = {
    # Shell-and-tube styles: one item with one port set.
    "ShellAndTubeExchanger": {
        "default": "default", "shell_tube": "shell_tube", "u_tube": "u_tube",
        "straight_tubes": "straight_tubes", "finned": "finned", "hairpin": "hairpin",
    },
    # Both ways of making the field. See the class docstring.
    "MagneticSeparator": {
        "default": "permanent_magnet", "electromagnetic": "electromagnetic",
    },
    # The three gas casings, without the registry's gas_ prefix.
    "DustCollector": {
        "default": "gas", "fixed_bed": "gas_fixed_bed", "belt": "gas_belt",
    },
    "RotaryDrumFilter": {"default": "rotary", "scraper": "rotary_scraper"},
    # Diaphragm-actuated bodies; butterfly_pneumatic may declare fail= too.
    "ControlValve": {
        "default": "control", "butterfly_pneumatic": "butterfly_pneumatic",
    },
    # Two body styles: the bonnet-on-a-stem PRV and the angle PSV.
    "ReliefValve": {"default": "relief", "psv": "psv"},
    # The twelve primary elements from flow_sensors.xml; the metering
    # principle is the variant.
    "FlowElement": {
        "default": "venturi", "venturi": "venturi", "flow_nozzle": "flow_nozzle",
        "coriolis": "coriolis", "vortex": "vortex", "ultrasonic": "ultrasonic",
        "turbine_meter": "turbine_meter",
        "positive_displacement": "positive_displacement",
        "v_cone": "v_cone", "wedge": "wedge", "target": "target",
        "pitot": "pitot", "averaging_pitot": "averaging_pitot",
    },
}


# class -> complete port list, where it differs from the base's. Other port
# lists are computed from the live base class, so the committed file must be
# regenerated when a base's ports change.
PORT_OVERRIDES = {
    # A check valve has no actuator; see the class docstring.
    "CheckValve": [("inlet", "inlet", "process"), ("outlet", "outlet", "process")],
}


# class -> {port: artwork anchor name}, for a class whose artwork names a port
# differently. Empty: the dust collectors inherit
# pandid.units.Separator._VARIANT_ANCHORS.
PORT_ANCHORS: dict[str, dict[str, str]] = {}


# (kind, variant) -> why this drawing gets no class. :func:`claims` refuses to
# generate while any registered key is unclaimed.
STAYS_ON_BASE = {
    # The base classes' own drawings.
    ("block", "default"): "Block's own drawing",
    ("blower", "default"): "Blower's own drawing",
    ("boiler", "default"): "Boiler's own drawing",
    ("conveyor", "default"): "Conveyor's own drawing",
    ("cooler", "default"): "Cooler's own drawing",
    ("cooling_tower", "default"): "CoolingTower's own drawing (the fan on the stack)",
    # Fan position changes only the casing; the ports and the item are the same.
    ("cooling_tower", "induced_draft"):
        "fan arrangement, and the same drawing as the default",
    ("cooling_tower", "forced_draft"):
        "fan arrangement: the fan in a housing at the foot of each side",
    # Centrifuge's eight ISO group-9 rows share one port set; the mechanism
    # is a drawn internal.
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
    # ISO group 5 (symbols._register_cooling_towers): fill and draught marks on
    # one outline with one port set.
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
    # ISO item 10.1 C0046: a dryer whose type is not yet chosen.
    ("dryer", "general"): "ISO item 10.1: the bare casing, no characteristic drawn",
    ("feeder", "general"): "ISO item 19.1: the bare circle, no mechanism drawn",
    ("screening_device", "general"): "ISO item 7.1: the bare outline, no mechanism drawn",
    ("kneader", "default"): "Kneader's own drawing (ISO item 12.4 X8134)",
    ("evaporator", "default"):
        "the general row: two tubesheets around a boxed element, no element chosen",
    # Thickener and clarifier are one machine at two duties; the rake is
    # composed with Thickener(rake=).
    ("thickener", "default"): "Thickener's own drawing (draw.io's settling tank)",
    ("spray_nozzle", "default"): "SprayNozzle's own drawing (ISO item 19.5 2037)",
    # ISO group 12 in-line mixers, like fitting/static_mixer.
    ("fitting", "rotary_mixer"): "body style: a rotating mixing element in the run",
    ("fitting", "mixing_path"): "body style: three mixing elements in series in the run",
    ("elevator", "default"): "Elevator's own drawing (ISO item 18.7, the straight lift)",
    ("elevator", "z_form"): "body style: the same lift with a run at each end",
    ("ejector", "default"): "Ejector's own drawing",
    ("filter", "default"): "Filter's own drawing (bag, candle or cartridge elements)",
    ("flare", "default"): "Flare's own drawing",
    ("funnel", "default"): "Funnel's own drawing",
    ("furnace", "default"): "Furnace's own drawing",
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
    ("reactor", "plain"): "body style: the same charge vessel without the agitator",
    # Reactor type comes from agitator= and internals=, so these bodies are
    # styles.
    ("reactor", "jacketed"): "cladding: a heating/cooling jacket",
    ("reactor", "mixing"): "body style: a conical-bottomed mixing vessel",
    ("reactor", "tubular"): "body style: a horizontal shell with a tube pass",
    # Refused by name; see REFUSED_KINDS.
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
    # Vessels: supports, head styles, cladding and attitude.
    ("vessel", "dished"): "head style, plus the brackets it stands on",
    ("vessel", "dome"): "head style: a raised manway dome",
    ("vessel", "skirted"): "support: a skirt",
    ("vessel", "legs"): "support: legs",
    ("vessel", "horizontal"): "attitude: the same vessel lying down",
    ("vessel", "swaged"): "shell style: one vessel in two diameters",
    ("vessel", "jacketed"): "cladding: a heating/cooling jacket",
    ("vessel", "insulated"): "cladding: thermal insulation",
    ("vessel", "electrical_heating"): "a heating element hung on the shell wall",
    # Tanks: roofs, floors and shell styles.
    ("tank", "conical"): "roof: conical",
    ("tank", "floating_roof"): "roof: floating",
    ("tank", "sphere"): "shell style: a pressure sphere on legs",
    ("tank", "conical_bottom"): "floor: a discharge cone",
    ("tank", "conical_ends"): "roof and floor: a cone at each end",
    ("tank", "dished_roof_conical_bottom"): "roof and floor",
    # Columns: packing is a drawn internal.
    ("column", "packed"): "drawn internal: beds of packing on their support grids",
    # Reducers: body style, and the fitting is bulk piping bought by the line.
    ("reducer", "default"): "Reducer's own drawing (the concentric body)",
    ("reducer", "concentric"): "body style, and the same drawing as the default",
    ("reducer", "eccentric"): "body style: flat along one side",
    # Vents: what is on top of the stack.
    ("vent", "exhaust_head"): "body style: a silencing hood",
    ("vent", "breather"): "body style: a conservation vent",
    # Liquid filters whose gas counterparts DustCollector claims: the medium
    # is the variant.
    ("filter", "belt"): "medium: a cloth on rollers, in a liquid casing",
    ("filter", "fixed_bed"): "medium: a granular bed, in a liquid casing",
    # The horizontal flash drum: attitude, exactly as vessel/horizontal is.
    ("separator", "horizontal"): "attitude: the same separator lying down",
    # Valves: body and operator styles of one block valve.
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
    # Fittings: body styles, certification ratings and bulk piping.
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


# ---------------------------------------------------------------------------
# The tables, held to the registry
# ---------------------------------------------------------------------------


def variant_map(class_name: str, home: str) -> dict[str, str]:
    """Return ``{class-local variant: registry variant}`` for one class.

    A class in :data:`OWNS` states its own mapping; any other owns its named
    drawing, also under ``"default"`` since that is the default argument.

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
    return {"default": home} if home != "default" else {"default": "default"}


def declared_variants(mapping: dict[str, str]) -> tuple[str, ...]:
    """Return a generated class's ``VARIANTS``.

    Class-local names come first, then the registry spellings of renamed
    ones: :attr:`~pandid.units.Unit.VARIANT_ALIASES` stores the registry
    spelling, which ``to_dict`` writes and must read back.

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
    """Return the :mod:`pandid.units` class that owns ``kind``.

    Read from ``units.__all__`` so a renamed base cannot go stale here.

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
    """Return the ports a generated class declares, from the live base class.

    ``_declared_ports()`` plus ``_variant_ports(variant)``. Ports a base's
    ``__init__`` adds itself (a Reactor's feeds) are excluded, since a
    subclass restating them would add them twice.

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
    variant_ports = base._variant_ports(variant) if hasattr(base, "_variant_ports") else []
    return [*declared, *variant_ports]


# (keyword, member, default, max_n) for a variable-port family base: the count
# argument (n_feeds), the numbered port prefix (feed), the count's default, and
# the highest arity with a typed class.
_Family = tuple[str, str, int, int]

_ARITY_CLASS_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


@functools.lru_cache(maxsize=None)
def _arity_families() -> dict[str, dict[int, list[str]]]:
    """Return each base's per-arity type-checking classes, read from units.py.

    Read from the source because the ``BaseN`` classes exist only under
    ``TYPE_CHECKING``.

    Returns
    -------
    dict[str, dict[int, list[str]]]
        Base name to ``{arity: annotated port names}``, such as
        ``{"Reactor": {2: ["feed_1", "feed_2"], ...}}``.
    """
    tree = ast.parse((HERE.parent / "pandid" / "units.py").read_text(encoding="utf-8"))
    families: dict[str, dict[int, list[str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        m = _ARITY_CLASS_RE.match(node.name)
        if not m:
            continue
        base_name, n = m.group(1), int(m.group(2))
        members = [
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        ]
        families.setdefault(base_name, {})[n] = members
    return families


def arity_family(base: type) -> "_Family | None":
    """Return the arity family a generated subclass needs overloads for.

    Derived from the base: its per-arity classes (:func:`_arity_families`),
    their shared port prefix, and the count argument after ``name`` in its
    signature. A subclass needs its own overloads so that, for example,
    ``StirredTankReactor`` with a literal count returns
    ``StirredTankReactor2`` rather than ``Reactor2``, keeping it assignable
    to its own type.

    Parameters
    ----------
    base : type
        Base unit class.

    Returns
    -------
    tuple[str, str, int, int] or None
        ``(keyword, member, default, max_n)``, or ``None`` if ``base`` has
        no family.

    Raises
    ------
    SystemExit
        If the family cannot be derived from the base.
    """
    arities = _arity_families().get(base.__name__)
    if not arities:
        return None
    max_n = max(arities)
    sample = next((members for n, members in arities.items() if n >= 2 and members), None)
    if sample is None:
        raise SystemExit(
            f"{base.__name__} declares arity classes 1..{max_n} but none past "
            f"1 has a numbered nozzle; cannot tell what a device subclass's "
            f"own arity classes should be named"
        )
    prefixes = {name.rsplit("_", 1)[0] for name in sample}
    if len(prefixes) != 1:
        raise SystemExit(
            f"{base.__name__}'s numbered nozzles ({sorted(sample)}) do not "
            f"share one prefix; cannot derive the member name"
        )
    member = next(iter(prefixes))
    # Ask the class, not __init__: it omits self and type-checks soundly.
    params = list(inspect.signature(base).parameters.values())
    if not params or params[0].name != "name":
        raise SystemExit(f"{base.__name__}.__init__ does not take name first")
    if len(params) < 2:
        raise SystemExit(f"{base.__name__}.__init__ takes no count argument after name")
    keyword = params[1].name
    default = params[1].default
    if not isinstance(default, int) or isinstance(default, bool):
        raise SystemExit(
            f"{base.__name__}.__init__'s {keyword}= has no integer default; "
            f"cannot derive a fallback overload for it"
        )
    return keyword, member, default, max_n


def claims() -> dict[tuple[str, str], str]:
    """Return every registered ``(kind, variant)`` mapped to what claims it.

    The drift check between the class tables and the symbol registry: a
    registered drawing nobody claims, a claim on an unregistered drawing,
    or a double claim all stop generation.

    Returns
    -------
    dict[tuple[str, str], str]
        Registry key to claiming class or reason.

    Raises
    ------
    SystemExit
        If the tables and the registry disagree, or a refused kind is
        claimed.
    """
    registered = set(default_registry._symbols)
    claimed: dict[tuple[str, str], str] = {}
    twice: list[str] = []

    def claim(key: tuple[str, str], by: str) -> None:
        """Record a claim, noting a second claim on one key."""
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
    """Return everything one generated class needs, from the live library.

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
        Name, base, kind, doc, variants, aliases, anchors, ports and family.

    Raises
    ------
    SystemExit
        If two owned drawings have different ports.
    """
    base = base_of(kind)
    mapping = variant_map(class_name, home)
    variants = declared_variants(mapping)
    aliases = {local: registry for local, registry in mapping.items() if local != registry}
    ports = PORT_OVERRIDES.get(class_name) or ports_for(base, home)
    # Every owned drawing must share one port list, since PORTS is per class.
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
        "name": class_name, "base": base.__name__, "kind": kind, "doc": doc,
        "variants": variants, "aliases": aliases,
        "anchors": PORT_ANCHORS.get(class_name, {}), "ports": ports,
        "family": arity_family(base),
    }


HEADER = '''"""Equipment classes: named classes for what a piece of plant is.

GENERATED by scripts/gen_devices.py. Do not edit by hand.

:mod:`pandid.units` models equipment as a ``kind`` and a ``variant``, as
the symbol registry is keyed. This module adds one class per device, so

    * an engineer looking for a cyclone finds :class:`Cyclone` rather
      than ``Separator(variant="cyclone")``;
    * a type checker sees ``cyclone.underflow``, because the ports are
      declared on the class;
    * an equipment list reads as equipment.

A class is what the equipment is and ``variant=`` is how it is drawn:
a variant becomes a class when it names a distinct scheduled item, and
stays a variant for a support, roof, cladding, attitude, drawn internal,
certification rating or body style. A gate valve and a ball valve are
one class; a check valve, which has no actuator, is its own.

The base-class form, such as ``Separator(variant="cyclone")``, stays
supported and is the only way to reach drawings without a class;
``pandid.render.symbols.default_registry`` is the whole catalogue.

:class:`Cyclone`, :class:`GravitySeparator` and
:class:`ElectrostaticPrecipitator` collect dust, so their draws are
``overflow`` (gas) and ``underflow`` (catch), as in classification and
solid-liquid separation. ``Separator`` draws the same pair for those
variants; the artwork's ``vapor``/``liquid`` anchors are mapped in
:attr:`pandid.units.Separator._VARIANT_ANCHORS`.

This module imports its bases from :mod:`pandid.units`, so it is not
star-imported there. Use ``from pandid import devices`` or the package,
which re-exports every class.
"""
{typing_import}
from pandid.ports import Port
from pandid.units import (
{imports})

__all__ = [
{exports}]
'''

#: Typing import added to :data:`HEADER` only when a class needs arity
#: overloads, so the module has no unused imports otherwise.
_TYPING_IMPORT = "\nfrom typing import TYPE_CHECKING, Any, Literal, overload\n"


def render() -> str:
    """Return the generated module source without writing it.

    A test compares this with the committed ``pandid/devices.py``, which
    catches hand edits and stale output.

    Returns
    -------
    str
        Module source with LF line endings.

    Raises
    ------
    SystemExit
        If the tables are inconsistent or a class name clashes with
        ``units.__all__``.
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
        typing_import=_TYPING_IMPORT if any(s["family"] for s in specs) else "",
        imports="".join(f"    {base},\n" for base in sorted({s["base"] for s in specs})),
        exports="".join(f'    "{spec["name"]}",\n' for spec in specs),
    )]
    for spec in specs:
        lines.append(emit(spec))
    # Use LF, not os.linesep: the test reads the committed file in text mode.
    return "\n".join(lines)


def emit(spec: dict) -> str:
    """Return one generated class as source.

    Ports appear twice: as ``PORTS`` tuples that create them, and as bare
    annotations so type checkers and editors see them. An annotation binds
    nothing, so construction is unchanged.

    Parameters
    ----------
    spec : dict
        Output of :func:`spec_of`.

    Returns
    -------
    str
        Class source, plus its arity classes when it has a family.
    """
    body = [
        "",
        f"class {spec['name']}({spec['base']}):",
        f'    """{spec["doc"].rstrip()}\n\n'
        f'    Parameters are those of :class:`~pandid.units.{spec["base"]}`.\n    """',
        "",
        f'    kind = "{spec["kind"]}"',
        f"    VARIANTS = {_variants_source(spec['variants'])}",
    ]
    if spec["aliases"]:
        body.append(f"    VARIANT_ALIASES = {_dict(spec['aliases'])}")
    if spec["anchors"]:
        body.append(f"    PORT_ANCHORS = {_dict(spec['anchors'])}")
    body.append(f"    PORTS = {_ports_source(spec['ports'])}")
    body.append("")
    body += [f"    {name}: Port" for name, _direction, _role in spec["ports"]]
    body.append("")
    if spec["family"]:
        body += _family_overload_lines(spec["name"], spec["family"])
    out = "\n".join(body)
    if spec["family"]:
        # Two blank lines before the top-level block, as PEP 8 asks.
        out += "\n\n\n" + _family_class_block(spec["name"], spec["family"])
    return out


def _family_overload_lines(name: str, family: "_Family") -> list[str]:
    """Return the ``__new__`` overload lines for a family subclass.

    A literal count returns this class's own arity class, as in
    :class:`~pandid.units.Column`.

    Parameters
    ----------
    name : str
        Generated class name.
    family : tuple[str, str, int, int]
        Output of :func:`arity_family`.

    Returns
    -------
    list[str]
        Source lines, indented for the class body.
    """
    keyword, _member, default, max_n = family
    lines = ["    if TYPE_CHECKING:", ""]
    for n in range(1, max_n + 1):
        default_clause = f" = {default}" if n == default else ""
        lines.append("        @overload")
        lines.append(
            f"        def __new__(cls, name: str, {keyword}: Literal[{n}]{default_clause},"
        )
        lines.append(f'                    *args: Any, **kwargs: Any) -> "{name}{n}": ...')
        lines.append("")
    lines.append("        @overload")
    lines.append(f"        def __new__(cls, name: str, {keyword}: int,")
    lines.append(f'                    *args: Any, **kwargs: Any) -> "{name}": ...')
    lines.append(f"        def __new__(cls, name: str, {keyword}: int = {default},")
    lines.append(f'                    *args: Any, **kwargs: Any) -> "{name}": ...')
    return lines


def _family_class_block(name: str, family: "_Family") -> str:
    """Return the module-level arity classes the overloads refer to.

    Like :mod:`pandid.units`, each declares only its numbered ports, arity 1
    included; the base's alias (``Reactor.feed``) covers the singular name.

    Parameters
    ----------
    name : str
        Generated class name.
    family : tuple[str, str, int, int]
        Output of :func:`arity_family`.

    Returns
    -------
    str
        ``if TYPE_CHECKING:`` block declaring ``Name1`` to ``Name{max_n}``.
    """
    _keyword, member, _default, max_n = family
    lines = ["if TYPE_CHECKING:", ""]
    for n in range(1, max_n + 1):
        lines.append(f"    class {name}{n}({name}):")
        ports = f"``{member}_1``" if n == 1 else f"``{member}_1`` to ``{member}_{n}``"
        lines.append(f'        """{name} declaring {ports} for type checkers."""')
        lines.append("")
        lines += [f"        {member}_{i}: Port" for i in range(1, n + 1)]
        lines.append("")
    return "\n".join(lines)


def _q(text: str) -> str:
    """Return ``text`` double-quoted, as the package writes strings."""
    return f'"{text}"'


def _variants_source(variants: tuple[str, ...]) -> str:
    """Return ``VARIANTS`` as source, wrapped if longer than one line.

    A one-member tuple keeps its trailing comma; longer ones do not.

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
    """Return a literal with one entry per line, closed at indent 4."""
    return (open_bracket + "\n"
            + "".join(f"        {entry},\n" for entry in entries)
            + "    " + close_bracket)


def _dict(mapping: dict[str, str]) -> str:
    """Return a string mapping as a one-line dict literal."""
    return "{" + ", ".join(f"{_q(k)}: {_q(v)}" for k, v in mapping.items()) + "}"


def _ports_source(ports: list[tuple[str, str, str]]) -> str:
    """Return ``PORTS`` as source: one line if it fits in 100 columns.

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
