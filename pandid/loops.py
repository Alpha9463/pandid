"""Control loops: the variable and number an instrument tag opens with.

A loop is a *namespace*, not a drawn thing. It has no frame and no
ports, it never enters :attr:`~pandid.flowsheet.Flowsheet.units`, and so
it reaches no equipment list and nothing in layout, routing or rendering
has to know it exists. What it owns is the number, and what it checks is
the first letter of every balloon tagged from it::

    loop = fs.add_loop("F", 303)
    fe = fs.add(units.Fitting(loop.element("FE"), variant="venturi"))
    fs.add_balloon(fe, at="N", offset=38)
    ft = fs.add_instrument("FT", loop, near=fe.balloon, at="N", offset=23)
    fic = fs.add_instrument("FIC", loop, near=ft, at="E", offset=70,
                            variant="shared")
    cv = fs.add(units.Valve(loop.tag("CV"), variant="control"))

The number is typed once. The measured-variable letter is still typed on
every balloon and checked against the loop at the call site, so an
``FIC`` reading a ``TT`` is detected rather than made unrepresentable.

The two members that are not balloons join through two methods, because
they are lettered by two rules. A **primary element** -- the venturi in
the line -- is lettered from the measured variable exactly as a balloon
is, so :meth:`Loop.element` composes its tag and applies the same check.
A **final control element** is not: the reference sheet spells every
control valve ``CV-`` whatever it strokes, so :meth:`Loop.tag` composes
without a check.

A loop is identified by the **pair**, not by the number. ``FIC-101`` and
``LIC-101`` are two loops on one sheet, so nothing may recover loops by
grouping tags on the number alone.

Loops allocate once and never renumber, unlike streams. A stream number
is engine output and
:meth:`~pandid.flowsheet.Flowsheet.renumber_streams` re-derives it on
every ``connect()``; a loop number is author intent that lands in a DCS
database, on a valve nameplate and in a cause-and-effect chart.

The number may still be left out -- ``fs.add_loop("F")`` -- and the
sheet allocates the next one from a single counter running across
measured variables. The counter runs at *declaration*, so the number is
fixed by the line that declares the loop and nothing re-derives it
afterwards. :meth:`~pandid.flowsheet.Flowsheet.to_dict` writes
``loops: [{variable, number}]`` with the number spelled out either way,
so reading that spec back gives a sheet whose numbers are nailed down.
The counter is nailed down with them: the reader sets it past the
highest number the file declares, so a draft that was frozen and read
back carries on its series instead of starting it again.
"""

from __future__ import annotations


class Loop:
    """One control loop: a measured-variable letter and a number.

    Built by :meth:`~pandid.flowsheet.Flowsheet.add_loop` rather than
    directly, so the sheet refuses a duplicate. The number is required
    *here* and optional there because a series belongs to a sheet: by
    the time a loop exists it has a number, and nothing downstream can
    tell whether it was typed or counted.
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
                "leaves the drawing for the DCS. Omit it entirely -- add_loop('F') -- "
                "and the sheet allocates its next one; an empty string asks for a loop "
                "whose members share nothing, which is not the same request"
            )
        self.variable = variable.upper()
        self.number = number

    @property
    def name(self) -> str:
        """The loop's identity as a string (``"F-303"``).

        Not a tag: no instrument carries it, because a member's tag
        opens with the measured variable and continues with its own
        function letters.
        """
        return f"{self.variable}-{self.number}"

    def tag(self, letters: str) -> str:
        """The tag a **final control element** carries.

        ``loop.tag("CV")`` gives ``"CV-303"``. This is how anything not
        lettered from the measured variable joins a loop: the returned
        string is an ordinary tag, so every unit class joins on the same
        terms.

        The measured-variable check is *not* applied, and cannot be. The
        reference sheet spells every control valve ``CV-...`` whatever
        it strokes -- ``LIC-306`` drives ``CV-306``, ``PIC-301`` drives
        ``CV-301-1`` -- so a final element's letters do not track its
        loop.

        Its **number** does, and that is the half this supplies.
        CHEE4001 p.13: "A loop number is assigned to each group of
        components required to perform the desired function of the
        monitor or control scheme." The valve is in the group.

        **A primary element goes through** :meth:`element` **instead**;
        see issue #203.
        """
        letters = letters.strip()
        if not letters:
            raise ValueError(
                f"loop {self.name} was given an empty tag; a member's tag is its own "
                f"letters over the loop's number, e.g. {self.variable}T-{self.number}"
            )
        return f"{letters}-{self.number}"

    def element(self, letters: str) -> str:
        """The tag a **primary element** carries, checked.

        ``loop.element("FE")`` gives ``"FE-303"``. A primary element is
        the thing in the pipe the measurement is taken from -- an
        orifice plate, a venturi, a coriolis meter -- and it is lettered
        from the measured variable exactly as a balloon is, so this
        makes the same check :meth:`check` does. On a flow loop
        ``element("TE")`` raises where :meth:`tag` composed ``TE-303``
        silently (issue #203).

        The rule is the measured variable and nothing else, so a
        restriction orifice ``FO`` and a sight glass ``FG`` on a flow
        loop are as welcome as ``FE``. What is refused is a *different
        variable*.
        """
        letters = letters.strip()
        if not letters:
            raise ValueError(
                f"loop {self.name} was given an empty tag; a primary element's tag is "
                f"the measured variable and its own function letter over the loop's "
                f"number, e.g. {self.variable}E-{self.number}"
            )
        first = letters[:1]
        if first.upper() != self.variable:
            raise ValueError(
                f"loop {self.name} measures {self.variable!r}, but {letters!r} opens "
                f"with {first!r}. A primary element is lettered from the measured "
                f"variable, so this loop's element is {self.variable}E and not "
                f"{letters!r}. If {letters!r} is the final control element it is not "
                f"lettered that way at all -- use loop.tag({letters!r}), which composes "
                f"the number without the check"
            )
        return f"{letters}-{self.number}"

    def check(self, letters: str) -> None:
        """Raise unless *letters* opens with the measured variable.

        The rule an instrument balloon is held to, called from
        :meth:`~pandid.flowsheet.Flowsheet.add_instrument` where the
        letters are typed, so a ``TT`` put on a flow loop fails at that
        line rather than as a finding at render time.
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
