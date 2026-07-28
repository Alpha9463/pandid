"""Control loops: the measured variable and number an instrument tag opens with.

A loop is a *namespace*, not a drawn thing. It has no frame and no ports, it
never enters :attr:`~pandid.flowsheet.Flowsheet.units`, and so it reaches no
equipment list and nothing in layout, routing or rendering has to know it
exists. What it owns is the number, and what it checks is the first letter of
every balloon tagged from it:

    loop = fs.add_loop("F", 303)
    fs.add_instrument("FE", loop, on=line, at=0.5, offset=0)
    ft = fs.add_instrument("FT", loop, on=line, at=0.5, offset=95)
    cv = fs.add(units.Valve(loop.tag("CV"), variant="control"))

The number is typed once. The measured-variable letter is still typed on every
balloon and checked against the loop at the call site, and that redundancy is the
point: a loop that *supplied* the letter would have every balloon agreeing by
construction, so an ``FIC`` reading a ``TT`` would become unrepresentable rather
than detected, and the check would have nothing left to check.

:meth:`Loop.tag` is the route in for everything that is not a balloon, and it
composes without checking. A primary element and a final control element are
part of the loop, but a final element is not tagged from the measured variable
and its number need not match its loop's either, so there is nothing about
``CV-303`` a first-letter rule could hold true.

A loop is identified by the **pair**, not by the number. ``FIC-101`` and
``LIC-101`` are two loops on one sheet, which is the ordinary convention and
what :file:`examples/04_control_loop.py` draws, so nothing may recover loops by
grouping tags on the number alone.

Loops allocate once and never renumber, unlike streams. A stream number is
engine output and :meth:`~pandid.flowsheet.Flowsheet.renumber_streams` re-derives
it on every ``connect()``; a loop number is author intent that leaves the
drawing and lands in a DCS database, on a valve nameplate and in a
cause-and-effect chart, so the engine never rewrites one.
"""

from __future__ import annotations


class Loop:
    """One control loop: a measured-variable letter and a number.

    Built by :meth:`~pandid.flowsheet.Flowsheet.add_loop` rather than directly,
    so the sheet it belongs to is the thing that refuses a duplicate.
    """

    def __init__(self, variable: str, number: str | int):
        variable = str(variable).strip()
        if len(variable) != 1 or not variable.isalpha():
            raise ValueError(
                f"a loop's measured variable is a single ISA letter ('F' for flow, 'L' "
                f"for level, 'T' for temperature), got {variable!r}. The function "
                f"letters stay on each instrument, so the loop takes only the first one"
            )
        number = str(number).strip()
        if not number:
            raise ValueError(
                "a loop needs a number: it is what the loop's members share and what "
                "leaves the drawing for the DCS, so the engine never invents one"
            )
        self.variable = variable.upper()
        self.number = number

    @property
    def name(self) -> str:
        """The loop's identity as a string (``"F-303"``).

        Not a tag: no instrument carries it, because a member's tag opens with
        the measured variable and continues with its own function letters.
        """
        return f"{self.variable}-{self.number}"

    def tag(self, letters: str) -> str:
        """The tag a member of this loop carries (``loop.tag("CV")`` -> ``"CV-303"``).

        This is how anything that is not a balloon joins a loop. Loop 303's
        primary element is a venturi (:class:`~pandid.units.Fitting`) and its
        final element a :class:`~pandid.units.Valve`; neither is minted by
        :meth:`~pandid.flowsheet.Flowsheet.add_instrument`, and the returned
        string is an ordinary tag, so every unit class joins on the same terms.

        The measured-variable check is *not* applied here, and cannot be. It is
        the check :meth:`~pandid.flowsheet.Flowsheet.add_instrument` makes,
        because it is a rule about a **functional letter string**: an
        instrument's first letter is what it measures. A final control element
        is not tagged that way. The reference sheet spells every control valve
        ``CV-...`` whatever it strokes, and its ``LIC-304`` drives ``CV-305``, so
        neither the letters nor the number of a final element track its loop.
        What establishes that membership is the signal edge into the actuator.
        """
        letters = letters.strip()
        if not letters:
            raise ValueError(
                f"loop {self.name} was given an empty tag; a member's tag is its own "
                f"letters over the loop's number, e.g. {self.variable}T-{self.number}"
            )
        return f"{letters}-{self.number}"

    def check(self, letters: str) -> None:
        """Raise unless *letters* opens with this loop's measured variable.

        The rule an instrument balloon is held to. Called from
        :meth:`~pandid.flowsheet.Flowsheet.add_instrument`, where the letters
        are typed, so a ``TT`` put on a flow loop fails at that line rather than
        turning up as a finding at render time.
        """
        first = letters.strip()[:1]
        if not first:
            raise ValueError(
                f"loop {self.name} was given an empty tag; an instrument's functional "
                f"letters open with the measured variable, e.g. {self.variable}T"
            )
        if first.upper() != self.variable:
            raise ValueError(
                f"loop {self.name} measures {self.variable!r}, but {letters!r} opens "
                f"with {first!r}. An instrument's first letter is the measured "
                f"variable, so {letters!r} belongs to a {first.upper()!r} loop. Either "
                f"give this one the loop's letter ({self.variable}{letters.strip()[1:]}), "
                f"or put it on a loop of its own"
            )

    def __repr__(self) -> str:
        return f"Loop({self.variable!r}, {self.number!r})"
