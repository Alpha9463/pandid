#!/usr/bin/env python3
"""Generate pandid/devices.py: one class per piece of equipment the registry draws.

The library models equipment as a ``kind`` and a ``variant``, which is what the
symbol registry is keyed by and what a sheet is drawn from. That is the right
model for *drawing* and the wrong one for *finding*: an engineer looking for a
cyclone searches for ``Cyclone``, not for ``Separator(variant="cyclone")``, and
a type checker asked about ``sep.underflow`` on the second form can only shrug,
because the nozzle depends on a string. This file is the mapping from the one to
the other, and ``pandid/devices.py`` is what it emits.

The rule, in one line: **a class is what the equipment is; ``variant=`` is how it
is drawn.** Precisely -- a variant becomes a class when it names a distinct
*scheduled item*, something with a row of its own on an equipment list. It stays
a variant when it names a support, a roof, a cladding, an attitude, a drawn
internal, a certification rating or a body style within one bought item. Outside
``pandid.document._MAJOR_EQUIPMENT``, which is already this library's own
definition of "bought as an item", a variant becomes a class only where the
**ports** or a **declarable property** differ. That line is what keeps this at
forty-odd classes instead of a hundred and twenty.

Three tables say it, and :func:`claims` holds them to the registry:

``DEVICES``       the (kind, variant) a class is *named for*, its class name and
                  its docstring. One entry per class.
``OWNS``          the other drawings a class also answers for, as
                  ``{class-local variant: registry variant}``. A class not named
                  here owns its ``DEVICES`` drawing and nothing else.
``STAYS_ON_BASE`` every drawing that gets no class, each with the word from the
                  rule that says why.

**The anti-drift check is the point.** :func:`claims` imports the live registry
and refuses to generate unless every registered ``(kind, variant)`` is claimed
exactly once, by one of those three. Vendor a new stencil and this script stops
until someone has said what the equipment *is*, which is the one question a
symbol table cannot answer for itself. It mirrors the ``SystemExit`` orphan
checks in ``scripts/vendor_symbols.py``, in the same voice and for the same
reason.

It claims every registry **key**, not every distinct drawing. ``valve/default``
and ``valve/gate`` are one shape under two keys, as are ``hex/default`` and
``hex/shell_tube``, ``fitting/default`` and ``fitting/flange``, and
``reducer/default`` and ``reducer/concentric``; ``instrument/sis`` and
``instrument/logic`` are the *same Symbol object* registered twice. Each key is
claimed on its own, because each is a name a caller may write.

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

# Kinds that must never get a class, and why. Refused by name rather than left
# out, so adding one is a deliberate act with the reason to read first.
#
# All three would be *silently* wrong rather than merely unhelpful, which is
# what puts them here and not in STAYS_ON_BASE:
REFUSED_KINDS = {
    # An Instrument's variants name a FUNCTION, not a device: "sis", "logic" and
    # "interlock" are the logic square a trip is drawn with, one thing acting in
    # several places, and Instrument.repeats() is what lets the sheet draw it in
    # each of them. Its __init__ signature is different too (type/number, not
    # name), and pandid.spec._resolve_kind already refuses it in `units:`
    # because its tag and its attachment live in the `instruments:` section.
    "instrument": "its variants are functions, not devices; see Instrument.repeats",
    # _Boundary.repeats tests `type(other) is type(self)`, so a subclass of Feed
    # or Product would quietly stop matching the flags it is meant to repeat
    # with, and a utility header tapped twice would be reported as two services
    # the reader cannot tell apart. A flag is where the sheet ends, and a sheet
    # ends one way.
    "feed": "_Boundary.repeats tests the exact type; a subclass defeats it silently",
    "product": "_Boundary.repeats tests the exact type; a subclass defeats it silently",
}


# (kind, variant) -> (class name, docstring). The drawing each class is *named
# for*: its own, and the one ``Cyclone("S-1")`` with no variant= asks for.
DEVICES = {
    # --- Pumps -------------------------------------------------------------
    #
    # Every pump variant is a distinct scheduled item: a gear pump and a
    # centrifugal are different machines with different curves, bought
    # separately and listed separately, even though the flowsheet sees the same
    # suction and discharge on all six.
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
    # ``hex`` is in _MAJOR_EQUIPMENT, so the test is "distinct scheduled item"
    # rather than "different ports" -- but five of these differ in ports as
    # well, because their two sides are not a shell and tubes and they refuse to
    # borrow the vocabulary. See HeatExchanger._VARIANT_PORTS.
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

    # --- Separators --------------------------------------------------------
    #
    # Four of these are the mechanical separators, which sort by size, inertia
    # or magnetism rather than into phases, and three more collect *dust*. See
    # the module docstring of pandid/devices.py for the port vocabulary that
    # follows from that, and for what it costs.
    ("separator", "cyclone"): ("Cyclone", """Cyclone separator: a vortex throws the heavy phase down.

    The gas-solid workhorse -- off a spray dryer, a fluidised bed, a
    mill -- and the hydrocyclone in a classifying duty. ISO 15519-1
    symbol X 2618, and one of the two the standard names as symbols
    gravity fixes the attitude of: the apex points down and the drawing
    says nothing true turned.

    The draws are ``overflow`` and ``underflow``, not ``vapor`` and
    ``liquid``: what leaves the apex is a catch, and calling a hopper
    full of dust a liquid is the bend this class exists to stop.
    ``Separator(variant="cyclone")`` draws the same pair as of 0.1.2;
    see the module docstring.
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
    specification uses and the word an engineer searches for, and
    because the one drawing stands for both duties a screen is bought
    for: **scalping**, taking a little oversize off a lot of product,
    and **sizing**, cutting a feed into fractions. Which of the two
    draws is the product is a fact about the service and not about the
    machine, which is why the nozzles name the two positions and not the
    contents.
"""),
    ("separator", "impact"): ("ImpactSeparator", """Impact separator: a baffle to throw the stream at.

    The knock-out on a pneumatic conveying line or a vent, where the
    heavy fraction cannot follow the gas round the baffle.
"""),
    ("separator", "permanent_magnet"): ("MagneticSeparator", """Magnetic separator: tramp metal pulled out of a solids stream.

    One class over both drawings, because the choice between a
    **permanent** magnet (``default``) and an **electromagnet**
    (``electromagnetic``) is a matter of how the field is made, not of
    what the machine does or of how it is piped: same body, same hopper,
    same two draws.
"""),
    ("separator", "scrubber"): ("Scrubber", """Wet scrubber: a wash liquid takes the contaminant out of a gas.

    Cleaned gas off the side, dirty scrubbing liquid out of the hopper,
    which really is a vapour and a liquid -- so unlike the collectors
    above this one keeps ``vapor`` and ``liquid``. A scrubber cleans a
    gas rather than classifying a solid.
"""),
    ("separator", "venturi_scrubber"): ("VenturiScrubber", """Venturi scrubber: the wash is injected into an accelerating throat.

    Its own class rather than a body style of :class:`Scrubber`, because
    the separating families in this table each get one per **mechanism**
    and this is a different mechanism: a spray tower washes a gas at the
    velocity it arrives at, and a venturi accelerates it through a throat
    first, which is what buys the collection efficiency and what costs
    the pressure drop. Two different machines with two different fans in
    front of them.

    So the feed is on the **top**: the throat runs downward, and the
    stencil draws it that way.
"""),
    ("separator", "knockout"): ("KnockoutDrum", """Knock-out drum: an upright drum with a demister pad.

    A mesh pad and a level gauge are both *drawn internals*, which the
    rule calls a variant -- and this is one of the two places the rule
    is deliberately overruled, because "knock-out drum" is the term a
    P&ID, a datasheet and a search box all use, and a class nobody can
    find is worth nothing. It is therefore near enough a duplicate of
    ``Separator``, and that is accepted.

    The gauge is *drawn*, not declared, so a level instrument added with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument` puts its own
    ISA-5.1 balloon beside it and the sheet says the level is measured
    twice.
"""),

    # --- Filters -----------------------------------------------------------
    ("filter", "gas"): ("DustCollector", """Dust collector: a gas filter with a hopper under the medium.

    One class over the three gas casings the stencil set draws -- bag,
    candle or cartridge elements (``default``), a granular bed
    (``fixed_bed``) and a cloth on rollers (``belt``) -- because
    choosing between them is a statement about the **medium**, which is
    what a variant is for, and all three are piped alike.

    Not called ``Baghouse``. That is the commonest member and the word
    most often reached for, but the same stencil stands for candle and
    cartridge filters, and a class named for one of the three would be
    wrong about the other two. The term is here in the docstring so a
    search finds it.
"""),
    ("filter", "rotary"): ("RotaryDrumFilter", """Rotary drum filter: a drum turns through slurry under vacuum.

    Cake builds on the submerged face and is lifted off at the top. The
    ``scraper`` variant is the same drum with the knife that lifts the
    cake drawn on it, which is the whole of the difference between the
    two shapes.

    Four connections, because the machine makes **two products**:
    ``inlet`` is the slurry, ``outlet`` the filtrate, ``cake`` what is
    lifted off the drum, and ``wash_in`` the sprays over the top of it
    that displace mother liquor before the knife reaches. Both drawings
    take them at the same points, so swapping one for the other moves no
    run.
"""),
    ("filter", "press"): ("FilterPress", """Filter press: plates squeezed together, slurry in, two products out.

    A batch machine on a continuous sheet, which is exactly why it is
    worth its own row on an equipment list.

    ``outlet`` is the filtrate and ``cake`` is what the plates hold,
    discharged downward when they part -- and it is usually the product
    the press was bought for, so it is a line of its own rather than
    something the filtrate has to stand in for. ``wash_in`` is the
    displacement wash that pushes mother liquor out of the cake before
    the press is opened.
"""),
    ("filter", "ion_exchange"): ("IonExchanger", """Ion exchanger: a resin bed between two retention screens.

    The vessel every demineraliser or softener train is drawn with. A
    filter by drawing and by piping; what it removes is dissolved rather
    than suspended.

    That is also why its extra pair is not the cake filters' one. A
    resin is restored by running acid, caustic or brine through it, so
    the connections are ``regenerant_in``, above the bed, and
    ``spent_regenerant``, out of the underdrain: the reagent loaded with
    what it has stripped. Calling either a wash would put the wrong
    fluid on the line list.
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
    # Nine classes over nine drawings, and every one of the nine is a body
    # carrying one ISO group-29 characteristic -- the same shape of row the
    # three composed separators are, and classed for the same reason. A jaw
    # crusher and a cone crusher are not one machine with two internals fitted:
    # they are two purchases, two datasheets and two rows on an equipment list,
    # and the mark inside the outline is what says which was bought.
    #
    # ``crusher/default`` and ``mill/default`` stay on their base classes, which
    # is where a machine whose type is not being stated belongs.
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
    # A screw conveyor is a different purchase from a belt -- different
    # supplier, different datasheet, different failure modes -- so it is a
    # class. The two bucket elevators are one purchase in two arrangements,
    # which is a body style, so both stay on ``Elevator``.
    ("conveyor", "screw"): ("ScrewConveyor", """Screw conveyor: a flighted shaft turning in a closed trough.

    Short runs of dusty, hot or hazardous solids, where the enclosure
    is the point. Fed through a spout on top near the tail and
    discharged through one underneath near the head, which is where
    ISO 10628-2 item 18.5 X8063 draws its two connections.

    Sized by ``length=``, as every conveyor is; a longer trough gets
    more turns of the flight rather than a longer one.
"""),

    # --- Valves ------------------------------------------------------------
    #
    # Six classes over twenty-three drawings, split on BEHAVIOUR rather than on
    # body. A gate, a ball and a globe valve are three ways of building the same
    # thing (a hand-operated block valve in a line) and the flowsheet cannot
    # tell them apart; a control valve, a relief valve and a check valve are
    # three different jobs, and the difference shows in what the unit may be
    # declared to do. Body style stays a variant, which is what
    # ``Valve(variant="ball")`` has always been.
    ("valve", "control"): ("ControlValve", """Control valve: the final element a loop's output lands on.

    The valve a controller modulates. **ISO 15519-2 Table A.3** builds
    one on two axes: A.3.20 is the general control valve, drawn with a
    general actuator standing on it, and §7.4.4.3 asks that an actuator
    be drawn without saying what type it is unless the type matters.
    What is drawn here is that general body with A.3.41's diaphragm on
    it, which Table 5 makes the P&ID's answer -- a P&ID's basic
    information runs to the **specific** symbols for valves and their
    actuators -- and which is a deviation on a PFD, where Table 4 asks
    for the general one. It is deliberate: the stencil set fuses body
    and operator into a single shape, so no general actuator exists to
    draw.
    ``default`` is the general body every sheet's CVs are drawn on;
    ``butterfly_pneumatic`` is the same actuator on a butterfly disc,
    and is reached as
    ``ControlValve(variant="butterfly", actuator="diaphragm")`` too.

    It is the one valve family that regularly declares ``fail=``, where
    it goes when its air is lost, and it may **not** be shown normally
    closed -- PIP PIC001 clause 4.2.2.10, because a darkened control
    valve on an issued sheet reads as a block valve someone has closed.
    Say ``fail="closed"`` instead.
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

    Worked by the flow itself. **It has no actuator**, so this class
    does not declare one: a check valve is not something a controller
    output can land on, and a signal line drawn to one is a mistake
    worth refusing rather than drawing. That missing nozzle is the whole
    reason this is a class and not a body style.

    Its arrow lives inside the outline and would be swallowed by a
    darkened body, so a normally closed one draws the letters ``NC``
    beside it instead (PIP PIC001 clause 4.2.2.8).
"""),

    # --- In-line fittings --------------------------------------------------
    #
    # ``fitting`` is outside _MAJOR_EQUIPMENT, so the bar is "ports or a
    # declarable property differ". Exactly two clear it, and the other
    # twenty-five stay what they have always been: styles of a pair of faces on
    # a line.
    ("fitting", "blind"): ("SpectacleBlind", """Spectacle blind: two discs on a tie, one bored and one solid.

    The one fitting with a **declarable property**, which is what makes
    it a class. Which disc is in the line is the whole of what the
    symbol says, and the stencil set draws both states:

    - ``normal_position="open"`` (the default) puts the **ring** in the
      line, with the solid disc parked above it: the line is through.
    - ``normal_position="closed"`` puts the **solid** disc in the line:
      blanked.

    A change of shape, not a mark added to one, so a blind is never
    shown in a position by inference.
"""),
    ("fitting", "venturi"): ("FlowElement", """Primary flow element: the device in the run an FE balloon reads.

    One class over the twelve the stencil set draws, because to the
    flowsheet they are the same thing -- a pair of faces on a line --
    and the choice between them is the metering principle: a
    differential-pressure profile (``default``/``venturi``,
    ``flow_nozzle``, ``v_cone``, ``wedge``, ``target``, ``pitot``,
    ``averaging_pitot``) or a meter body (``coriolis``, ``vortex``,
    ``ultrasonic``, ``turbine_meter``, ``positive_displacement``).

    It is a class rather than a style of ``Fitting`` because it is what
    an equipment or instrument schedule lists, which is the whole
    argument for the layer: a strainer and a venturi are the same shape
    of thing to the drawing and different rows on the list.

    Hang the balloon on one with
    :meth:`~pandid.flowsheet.Flowsheet.add_instrument`. The restriction
    orifice and the rotameter are **not** here: the first restricts
    rather than measures, and the second carries its own indication, so
    both stay ``Fitting`` variants where the class docstring already
    lists them.
"""),

    # --- Reactors ----------------------------------------------------------
    ("reactor", "default"): ("StirredTankReactor", """Stirred-tank reactor: a charge vessel with a top agitator.

    An agitator is a *drawn internal*, which the rule calls a variant --
    and this is the second of the two places the rule is deliberately
    overruled, for :class:`KnockoutDrum`'s reason: "stirred tank
    reactor" and "CSTR" are what a process engineer searches for, and it
    is what ``Reactor`` already draws when it is asked for by name. A
    near-duplicate of its base, accepted.

    ``n_feeds`` gives the vessel more than one charge nozzle, exactly as
    it does on :class:`pandid.units.Reactor`.
"""),

    # --- Storage -----------------------------------------------------------
    ("tank", "gas_holder"): ("GasHolder", """Gas holder: a bell floating in a water seal.

    The only tank drawing that gets a class, and the reason is the rule
    rather than an exception to it. Every other one is a **roof**, a
    **floor** or a **shell style** on a container that holds a liquid at
    atmospheric pressure -- a conical roof, a floating roof, a discharge
    cone, a pressure sphere -- so all of them are one purchase drawn
    several ways. A gas holder is not that container. It holds a *gas*,
    it has a moving part, and its volume is what varies while its
    pressure does not; the water in it is a seal and not the inventory.
    Different machine, different row, different supplier.

    ``inlet`` and ``outlet`` are the gas main, on the seal tank rather
    than on the bell: the bell travels the height of the holder every
    time it fills, so nothing is piped to it. ``vent`` and ``relief``
    *are* on the bell, because a holder's crown valves discharge to
    atmosphere and are piped nowhere. ``drain`` is the seal water.
"""),
}


# class -> {class-local variant: registry variant}, for the classes that answer
# for more than one drawing. A class absent here owns its DEVICES drawing alone.
#
# The left-hand names are what a caller may write, the right-hand ones what the
# registry (and so ``unit.variant``, and so a written spec) spells them. Both
# spellings are listed in the generated ``VARIANTS``, class-local first, so a
# sheet written out and read back still constructs: ``to_dict`` writes the
# registry name, and a class that would not accept its own output does not round
# trip.
OWNS = {
    # Every shell-and-tube style, including the two bundles that turn round
    # inside the shell. One class because they are one piece of equipment drawn
    # five ways, and they share a nozzle set to the letter.
    "ShellAndTubeExchanger": {
        "default": "default", "shell_tube": "shell_tube", "u_tube": "u_tube",
        "straight_tubes": "straight_tubes", "finned": "finned", "hairpin": "hairpin",
    },
    # Both ways of making the field. See the class docstring.
    "MagneticSeparator": {
        "default": "permanent_magnet", "electromagnetic": "electromagnetic",
    },
    # The three gas casings. The registry prefixes them ``gas_`` to tell them
    # from the liquid filters beside them; on a class that is only ever a gas
    # filter the prefix says nothing, so the class-local names drop it.
    "DustCollector": {
        "default": "gas", "fixed_bed": "gas_fixed_bed", "belt": "gas_belt",
    },
    "RotaryDrumFilter": {"default": "rotary", "scraper": "rotary_scraper"},
    # The diaphragm-actuated bodies. ``butterfly_pneumatic`` is a body style
    # under a pneumatic actuator, which is a control valve however the disc is
    # shaped -- and it is already one of the variants FAIL_ACTUATED lets declare
    # a fail position.
    "ControlValve": {
        "default": "control", "butterfly_pneumatic": "butterfly_pneumatic",
    },
    # Two bodies of one device: the bonnet-on-a-stem PRV and the spring-loaded
    # angle PSV. Body style, which the rule leaves a variant.
    "ReliefValve": {"default": "relief", "psv": "psv"},
    # The twelve primary elements, all from flow_sensors.xml. The metering
    # principle is the variant; being a flow element is the class.
    "FlowElement": {
        "default": "venturi", "venturi": "venturi", "flow_nozzle": "flow_nozzle",
        "coriolis": "coriolis", "vortex": "vortex", "ultrasonic": "ultrasonic",
        "turbine_meter": "turbine_meter",
        "positive_displacement": "positive_displacement",
        "v_cone": "v_cone", "wedge": "wedge", "target": "target",
        "pitot": "pitot", "averaging_pitot": "averaging_pitot",
    },
}


# class -> the complete nozzle list, where it is not what the base lays down.
#
# Everything else is *computed* from the live base class, which is the point:
# a nozzle added to Pump.PORTS or to HeatExchanger._VARIANT_PORTS reaches the
# generated classes without anyone editing a table here, and the committed file
# then disagrees with the generator until it is regenerated. Only a deliberate
# departure is written down.
PORT_OVERRIDES = {
    # A check valve has no actuator; see the class docstring.
    "CheckValve": [("inlet", "inlet", "process"), ("outlet", "outlet", "process")],
}


# class -> {nozzle: the name the symbol anchors it under}.
#
# Empty, and correctly so as of 0.1.2. Its three entries were the dust
# collectors, whose classes renamed the draws their drawings anchor ``vapor``
# and ``liquid`` -- and ``Separator`` itself now makes the same rename for the
# same three drawings, in :attr:`pandid.units.Separator._VARIANT_ANCHORS`, so
# these classes inherit it. A class that owns one drawing has that drawing's
# rename, and stating it twice was two places for one fact.
#
# The plumbing stays for the next class whose artwork ships a nozzle under
# another name. See :attr:`pandid.units.Unit.PORT_ANCHORS` for why such a rename
# cannot instead be a second pair of names on the symbol.
PORT_ANCHORS: dict[str, dict[str, str]] = {}


# (kind, variant) -> the word from the rule that says why this drawing gets no
# class of its own. Every registered key not claimed by a class is here, and
# :func:`claims` refuses to generate if one is missing: a new stencil has to be
# classified before it can be drawn from this layer.
STAYS_ON_BASE = {
    # The base classes' own drawings. A class already exists; naming it twice
    # would be the layer's first duplicate.
    ("block", "default"): "Block's own drawing",
    ("blower", "default"): "Blower's own drawing",
    ("boiler", "default"): "Boiler's own drawing",
    ("conveyor", "default"): "Conveyor's own drawing",
    ("cooler", "default"): "Cooler's own drawing",
    ("cooling_tower", "default"): "CoolingTower's own drawing (the fan on the stack)",
    # One machine drawn twice. Where the fan sits changes the casing and
    # nothing else: same water side, same air side, same basin, same six
    # nozzles in the same roles, and one row on an equipment list either way.
    ("cooling_tower", "induced_draft"):
        "fan arrangement, and the same drawing as the default",
    ("cooling_tower", "forced_draft"):
        "fan arrangement: the fan in a housing at the foot of each side",
    # Centrifuge's eight ISO 10628-2 group-9 rows. None differs from the
    # others in its ports -- all eight anchor the same feed/overflow/
    # underflow -- so none clears the bar a crusher's or a filter's press
    # clears; each is "a drawn internal" the rule's own phrase already
    # covers, the way Column's eight tray types are. Only where the mark
    # sits on the shell changes between them.
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
    # The eight ISO 10628-2 group-5 drawings (symbols._register_cooling_towers):
    # one outline, a draught arrangement and a fill characteristic, on the same
    # reasoning as the three vendored bodies just above -- same basin, same six
    # nozzles, one row on an equipment list whichever fan or fill is drawn.
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
    # ISO item 10.1 C0046, "Drier (general)": the group's own bare casing,
    # with none of the six marks that make a drawing one particular
    # machine. Not a scheduled item of its own -- an equipment list does
    # not row "a drier, unspecified" -- but a real drawing for the stage
    # before process design has picked shelf over turbo over belt, on
    # the same reasoning ("crushing_machine", "default") above gives
    # X8084 for a crusher-or-mill not yet chosen.
    ("dryer", "general"): "ISO item 10.1: the bare casing, no characteristic drawn",
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
    # The other three reactor bodies. What makes a reactor a CSTR rather than a
    # PBR is the ISO group-27/28 part inside it, which ``Reactor`` states with
    # ``agitator=`` and ``internals=``, so none of these three is a functional
    # type of its own: a jacket is cladding exactly as it is on a vessel;
    # ``mixing`` is the rectangle-with-a-V-bottom ``default`` used to draw, kept
    # under a name that says so; and a tubular shell is a shell.
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
    # Vessels: every one of these is a support, a head style, a cladding or an
    # attitude. A vessel on legs and a vessel on a skirt are one vessel, bought
    # once, with one row on the equipment list and one civil drawing between
    # them; the sheet shows which, and that is all a variant is for.
    ("vessel", "dished"): "head style, plus the brackets it stands on",
    ("vessel", "dome"): "head style: a raised manway dome",
    ("vessel", "skirted"): "support: a skirt",
    ("vessel", "legs"): "support: legs",
    ("vessel", "horizontal"): "attitude: the same vessel lying down",
    ("vessel", "swaged"): "shell style: one vessel in two diameters",
    ("vessel", "jacketed"): "cladding: a heating/cooling jacket",
    ("vessel", "insulated"): "cladding: thermal insulation",
    ("vessel", "electrical_heating"): "a heating element hung on the shell wall",
    # Tanks: roofs and floors. A floating-roof tank is a tank; the roof is what
    # the sheet is saying, and the schedule already has one row.
    ("tank", "conical"): "roof: conical",
    ("tank", "floating_roof"): "roof: floating",
    ("tank", "sphere"): "shell style: a pressure sphere on legs",
    ("tank", "conical_bottom"): "floor: a discharge cone",
    ("tank", "conical_ends"): "roof and floor: a cone at each end",
    ("tank", "dished_roof_conical_bottom"): "roof and floor",
    # Columns: the packing is a drawn internal, and a packed tower and a trayed
    # one are one line on an equipment list with the internals on the datasheet.
    ("column", "packed"): "drawn internal: beds of packing on their support grids",
    # Reducers: body style, and the fitting is bulk piping bought by the line.
    ("reducer", "default"): "Reducer's own drawing (the concentric body)",
    ("reducer", "concentric"): "body style, and the same drawing as the default",
    ("reducer", "eccentric"): "body style: flat along one side",
    # Vents: what is on top of the stack.
    ("vent", "exhaust_head"): "body style: a silencing hood",
    ("vent", "breather"): "body style: a conservation vent",
    # The two liquid filters whose gas counterparts DustCollector claims. The
    # medium is the variant on both sides of that pair, and neither liquid
    # casing is a scheduled item the base class does not already name.
    ("filter", "belt"): "medium: a cloth on rollers, in a liquid casing",
    ("filter", "fixed_bed"): "medium: a granular bed, in a liquid casing",
    # The horizontal flash drum: attitude, exactly as vessel/horizontal is.
    ("separator", "horizontal"): "attitude: the same separator lying down",
    # Valves: body style, every one. A gate, a ball, a globe and a needle valve
    # are four ways of building a hand-operated block valve, and to the
    # flowsheet they are one device with one pair of faces. The behaviour split
    # is above; this is what is left, and what ``Valve(variant=...)`` is for.
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
    ("valve", "three_way"): "body style: a third connection the run is switched between",
    ("valve", "angle"): "body style: the seat turns the flow a quarter",
    ("valve", "bleed"): "body style: the small drain valve tapped off a header",
    ("valve", "manual"): "operator style: a handwheel drawn on the body",
    ("valve", "hydraulic"): "operator style: a hydraulic cylinder drawn on the body",
    # Fittings: in-line devices, all with one pair of faces and none with a
    # property to declare. The four arrestor bodies are certification ratings,
    # which the rule names outright; the strainers and the sight glasses are
    # body styles; the couplings, the spool and the joints are bulk piping.
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
    """``{class-local variant: registry variant}`` for one class.

    A class named in :data:`OWNS` says its own; every other class owns the one
    drawing it is named for, under that name and under ``"default"`` -- because
    ``variant`` defaults to ``"default"`` and a class whose own drawing is what
    naming it should ask for has to accept it.
    """
    if class_name in OWNS:
        return dict(OWNS[class_name])
    return {"default": home} if home != "default" else {"default": "default"}


def declared_variants(mapping: dict[str, str]) -> tuple[str, ...]:
    """The tuple a generated ``VARIANTS`` carries: class-local names, then the
    registry spellings of any that were renamed.

    Both, because :attr:`~pandid.units.Unit.VARIANT_ALIASES` stores the
    *registry's* spelling on the unit, so that is what ``to_dict`` writes; a
    class that accepted only its own name would refuse to read back the spec it
    just wrote.
    """
    return tuple(dict.fromkeys([*mapping, *mapping.values()]))


def base_of(kind: str) -> type:
    """The class that owns ``kind``: the one a generated class subclasses.

    Read off ``units.__all__`` rather than written down, so a base class renamed
    or a kind moved between them cannot leave this file quietly pointing at the
    old one.
    """
    for name in units.__all__:
        cls = getattr(units, name)
        if cls is not units.Unit and cls.kind == kind and not cls.VARIANTS:
            return cls
    raise SystemExit(f"no class in units.__all__ owns kind {kind!r}")


def ports_for(base: type, variant: str) -> list[tuple[str, str, str]]:
    """The nozzles a generated class declares, taken from the live base class.

    ``_declared_ports()`` is the class-level list and ``_variant_ports()`` the
    per-variant one that :class:`~pandid.units.HeatExchanger`,
    :class:`~pandid.units.Separator`, :class:`~pandid.units.Reactor` and
    :class:`~pandid.units.Filter` lay down after it. Neither includes a
    nozzle the base's ``__init__`` adds by hand -- a Reactor's ``feed`` -- which
    is exactly right: a subclass restating one would hand ``_add_port`` a name
    it already has and be refused at construction.
    """
    declared = base._declared_ports()
    variant_ports = base._variant_ports(variant) if hasattr(base, "_variant_ports") else []
    return [*declared, *variant_ports]


# (keyword, member, default, max_n) for one variable-port family base --
# ``Mixer``, ``Splitter``, ``Column`` and ``Reactor`` today. ``keyword`` is
# the constructor argument a literal count is passed under (``n_feeds``),
# ``member`` the numbered nozzles' common prefix (``feed``), ``default`` the
# count an author gets by leaving the argument out, and ``max_n`` the
# highest arity the base hands back an exact class for.
_Family = tuple[str, str, int, int]

_ARITY_CLASS_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


@functools.lru_cache(maxsize=None)
def _arity_families() -> dict[str, dict[int, list[str]]]:
    """Every base's per-arity ``TYPE_CHECKING`` subclasses, read off units.py.

    ``{"Reactor": {1: [], 2: ["feed_1", "feed_2"], ...}, ...}``. Read off the
    *source* rather than the objects, and it has to be: a family's ``BaseN``
    classes are declared only under ``if TYPE_CHECKING:`` and so do not exist
    at import time -- ``tests/test_port_annotations.py`` reads them the same
    way, for the same reason.
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
    """What *base* would hand a generated subclass's ``__new__`` overloads,
    if it is a variable-port family base -- ``None`` if it is not one.

    Derived from the base rather than a hard-coded list of names, so a
    future family base earns this for its device subclasses without this
    file being told about it by name: whether ``base`` is one at all comes
    from :func:`_arity_families`, the member prefix from the nozzles its own
    arity-2 class declares, and the keyword and its default off the base's
    live ``__init__`` signature -- the argument right after ``name``, which
    is what every family base takes it as (``Mixer(name, n_inlets=2, ...)``,
    ``Reactor(name, n_feeds=1, ...)``).

    Why a subclass needs its own rather than inheriting the base's: a
    literal count on ``StirredTankReactor`` has to resolve to
    ``StirredTankReactor2``, not ``Reactor2`` -- the base's own overloads
    would hand back a type pyright no longer considers a
    ``StirredTankReactor`` at all (``t: StirredTankReactor =
    StirredTankReactor("R")`` would then be an error), whether or not the
    subclass's ports happen to match the base's.
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
    # ``inspect.signature(base)``, not ``base.__init__``: a class's own
    # signature already leaves ``self`` off, and asking it of the class
    # rather than the bound method is also what keeps this sound under
    # mypy, which otherwise cannot rule out a subclass overriding
    # ``__init__`` with an incompatible one.
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
    """Every registered ``(kind, variant)``, mapped to what claims it.

    The anti-drift check, and the reason this file exists rather than a
    declaration beside each unit class: nothing would tie *that* to the
    registry, and drift between the symbol table and the class layer is the
    failure this design is built to make impossible. Vendor a stencil and this
    refuses to run until someone has said what the equipment is.

    Refuses in both directions -- a registered drawing nobody claims, and a
    claim on a drawing nothing registers -- because either one means the two
    files have parted company, and the second is how a table keeps a line for a
    symbol that was removed.
    """
    registered = set(default_registry._symbols)
    claimed: dict[tuple[str, str], str] = {}
    twice: list[str] = []

    def claim(key: tuple[str, str], by: str) -> None:
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
    """Everything one generated class needs, resolved against the live library."""
    base = base_of(kind)
    mapping = variant_map(class_name, home)
    variants = declared_variants(mapping)
    aliases = {local: registry for local, registry in mapping.items() if local != registry}
    ports = PORT_OVERRIDES.get(class_name) or ports_for(base, home)
    # Every drawing a class answers for has to have the same nozzles, or the
    # class would be two devices sharing a name: PORTS is read once, at
    # construction, and there is no second list for the second variant.
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


HEADER = '''"""Equipment classes: what a piece of plant *is*, over its drawing.

GENERATED by scripts/gen_devices.py. Do not edit by hand.

:mod:`pandid.units` models equipment as a ``kind`` and a ``variant``,
which is what the symbol registry is keyed by and what a sheet is drawn
from. This module is the other half: one class per device the registry
draws, so that

    * an engineer looking for a cyclone finds :class:`Cyclone` rather
      than having to know it is ``Separator(variant="cyclone")``;
    * a type checker can answer ``cyclone.underflow``, because the
      nozzles are declared on the class and not held in a string;
    * an equipment list reads as equipment.

The split follows **a class is what the equipment is and ``variant=``
is how it is drawn**: a variant becomes a class when it names a distinct
scheduled item, and stays a variant when it names a support, a roof, a
cladding, an attitude, a drawn internal, a certification rating or a
body style. So a gate valve and a ball valve are one class and two
variants, while a check valve is a class of its own -- it has no
actuator, and that is a fact about the device rather than its picture.

The low-level form is not going anywhere.
``Separator(variant="cyclone")`` stays supported indefinitely, and it is
the only way to reach the ninety-odd drawings that never get a class of
their own; ``pandid.render.symbols.default_registry`` is still the whole
catalogue.

**One drawing, one nozzle vocabulary.** :class:`Cyclone`,
:class:`GravitySeparator` and :class:`ElectrostaticPrecipitator` collect
*dust*, and their drawings have anchored the catch ``liquid`` since
0.1.0. All three classes call it ``underflow`` and the gas draw
``overflow``, which is what classification and solid-liquid separation
call them.

``Separator(variant="cyclone")`` draws the same pair. The ``vapor``/
``liquid`` spelling it carried up to 0.1.1 still resolves, with a
:class:`DeprecationWarning` and a ``deprecated`` finding on
``fs.validate()``, and is gone in 0.1.3. The artwork is untouched: the
anchors it shipped with are mapped in
:attr:`pandid.units.Separator._VARIANT_ANCHORS`.

Not star-imported into :mod:`pandid.units`: this module imports its
bases from there, so that would be a genuine cycle. Use ``from pandid
import devices``, or take the names off the package, which re-exports
them all.
"""
{typing_import}
from pandid.ports import Port
from pandid.units import (
{imports})

__all__ = [
{exports}]
'''

#: Prepended to :data:`HEADER` only where a spec needs it: a generated class
#: with a family base's own overloads and per-arity classes to write (see
#: :func:`arity_family`). Every other release of this file has none, and
#: importing ``TYPE_CHECKING``, ``Any``, ``Literal`` and ``overload`` for
#: nothing would be an unused-import lint finding on every one of them.
_TYPING_IMPORT = "\nfrom typing import TYPE_CHECKING, Any, Literal, overload\n"


def render() -> str:
    """The whole generated module, as a string, writing nothing.

    Separate from :func:`main` so a test can regenerate the module in memory and
    compare it against the committed ``pandid/devices.py``. That file is
    regenerated wholesale, so a hand edit to it is lost the next time anyone runs
    the generator; nothing but that comparison notices, since a stale generated
    module still imports and still draws.
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
    # "\n" and not os.linesep, for the reason vendor_symbols.render() gives: the
    # test compares this string against the committed file read back in text
    # mode, so both ends speak LF whatever the checkout does on the way to disk.
    return "\n".join(lines)


def emit(spec: dict) -> str:
    """One class, as source.

    The nozzle names are written twice on purpose, once as the ``PORTS`` tuples
    that build them and once as bare annotations. An annotation with no
    assignment binds nothing -- it lands in ``__annotations__`` and nowhere else
    -- so ``_add_port``'s ``setattr`` still does the work and nothing about
    construction changes; what it buys is a checker and an editor that can see
    ``cyclone.underflow``, which is the whole point of the layer.
    """
    body = [
        "",
        f"class {spec['name']}({spec['base']}):",
        f'    """{spec["doc"].rstrip()}\n    """',
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
        # Two blank lines, matching the gap PEP 8 -- and every class above --
        # already keeps before a top-level statement: ``out`` ends on a real
        # line (the arity overloads' own last line, not a blank one).
        out += "\n\n\n" + _family_class_block(spec["name"], spec["family"])
    return out


def _family_overload_lines(name: str, family: "_Family") -> list[str]:
    """The ``if TYPE_CHECKING: ... def __new__`` lines a family subclass needs.

    The same shape :class:`~pandid.units.Column` writes by hand: a literal
    count has to pick an overload naming *this* class's own arity, or the
    whole reason a device subclass needs one (see :func:`arity_family`) is
    undone.
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
    """``ClassName1`` ... ``ClassName{max_n}``, the module-level block the
    overloads above hand back.

    Mirrors ``pandid.units``'s own per-arity classes: nothing but the
    numbered nozzles at every arity, and nothing at all at arity 1, since a
    lone member keeps its singular name (``feed``, not ``feed_1``) and the
    base class already declares that one.
    """
    _keyword, member, _default, max_n = family
    lines = ["if TYPE_CHECKING:", ""]
    for n in range(1, max_n + 1):
        lines.append(f"    class {name}{n}({name}):")
        if n == 1:
            lines.append("        pass")
        else:
            lines += [f"        {member}_{i}: Port" for i in range(1, n + 1)]
        lines.append("")
    return "\n".join(lines)


def _q(text: str) -> str:
    """One string, double-quoted, because that is how this package writes them."""
    return f'"{text}"'


def _variants_source(variants: tuple[str, ...]) -> str:
    """``VARIANTS`` as source: one line, or wrapped in the same brackets.

    A one-member tuple keeps its trailing comma because it is what makes it a
    tuple; a longer one does not, because the rest of the tree does not.
    """
    if len(variants) == 1:
        return f"({_q(variants[0])},)"
    flat = "(" + ", ".join(_q(v) for v in variants) + ")"
    if len(flat) + len("    VARIANTS = ") <= 99:
        return flat
    return _wrap("(", [_q(v) for v in variants], ")")


def _wrap(open_bracket: str, entries: list[str], close_bracket: str) -> str:
    """A literal too long for one line, one entry per line, closed at indent 4."""
    return (open_bracket + "\n"
            + "".join(f"        {entry},\n" for entry in entries)
            + "    " + close_bracket)


def _dict(mapping: dict[str, str]) -> str:
    return "{" + ", ".join(f"{_q(k)}: {_q(v)}" for k, v in mapping.items()) + "}"


def _ports_source(ports: list[tuple[str, str, str]]) -> str:
    """``PORTS`` as source, wrapped the way units.py writes its own.

    One line while it fits inside the hundred columns the rest of the tree keeps
    to, and one tuple per line after that.
    """
    tuples = ["(" + ", ".join(_q(field) for field in port) + ")" for port in ports]
    flat = "[" + ", ".join(tuples) + "]"
    return flat if len(flat) + len("    PORTS = ") <= 99 else _wrap("[", tuples, "]")


def main() -> None:
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT} ({len(DEVICES)} classes over "
          f"{len(default_registry._symbols) - len(STAYS_ON_BASE)} of the "
          f"{len(default_registry._symbols)} registered symbols)")


if __name__ == "__main__":
    main()
