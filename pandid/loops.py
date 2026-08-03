"""Control loops: the measured variable and number an instrument tag opens with.

A loop is a *namespace*, not a drawn thing. It has no frame and no ports, it
never enters :attr:`~pandid.flowsheet.Flowsheet.units`, and so it reaches no
equipment list and nothing in layout, routing or rendering has to know it
exists. What it owns is the number, and what it checks is the first letter of
every balloon tagged from it:

    loop = fs.add_loop("F", 303)
    fe = fs.add(units.Fitting(loop.element("FE"), variant="venturi"))
    ft = fs.add_instrument("FT", loop, on=line, at=0.5, offset=95)
    fic = fs.add_instrument("FIC", loop, on=ft, at="N", offset=90, variant="shared")
    cv = fs.add(units.Valve(loop.tag("CV"), variant="control"))

The number is typed once. The measured-variable letter is still typed on every
balloon and checked against the loop at the call site, and that redundancy is the
point: a loop that *supplied* the letter would have every balloon agreeing by
construction, so an ``FIC`` reading a ``TT`` would become unrepresentable rather
than detected, and the check would have nothing left to check.

Two of those four members are not balloons, and they join through two different
methods because they are lettered by two different rules. A **primary element**
-- the venturi in the line -- is lettered from the measured variable exactly as
a balloon is, so :meth:`Loop.element` composes its tag and applies the same
check. A **final control element** is not: the reference sheet spells every
control valve ``CV-`` whatever it strokes, so there is nothing about
``CV-303``'s letters a first-letter rule could hold true, and
:meth:`Loop.tag` composes without one.

The distinction is in the two names rather than in a flag on one of them,
because it is a distinction between two pieces of equipment and not between two
strictnesses. An author reaching for either already knows which they have in
hand; the method they reach for asks that and nothing more, and a check nobody
has to remember to switch on is the only kind that catches what nobody noticed.

A loop is identified by the **pair**, not by the number. ``FIC-101`` and
``LIC-101`` are two loops on one sheet, which is the ordinary convention and
what :file:`examples/04_control_loop.py` draws, so nothing may recover loops by
grouping tags on the number alone.

Loops allocate once and never renumber, unlike streams. A stream number is
engine output and :meth:`~pandid.flowsheet.Flowsheet.renumber_streams` re-derives
it on every ``connect()``; a loop number is author intent that leaves the
drawing and lands in a DCS database, on a valve nameplate and in a
cause-and-effect chart, so the engine never rewrites one.

That argument is about a number which has *left*, and nothing leaves a draft.
Before the sheet is issued there is a stage where the numbers and the count of
loops are both still moving, and typing a literal at every ``add_loop`` is the
churn that stage is made of: add a loop near the top of a sheet whose series
runs in reading order and every number below it is retyped by hand, on a
drawing whose whole point is that a number is typed once. So the number may be
left out -- ``fs.add_loop("F")`` -- and the sheet allocates the next one from a
single counter running across measured variables.

Allocation does not weaken "allocate once"; it is where the once happens. The
counter runs at *declaration*, so the number is fixed by the line that declares
the loop exactly as a typed one is, and from that instant it is the loop's
number and nothing re-derives it: not a render, not a ``connect()``, not
another ``add_loop`` further down the file. What is deferred is only who types
the digits, and only until the draft settles.

The freeze is :meth:`~pandid.flowsheet.Flowsheet.to_dict`, which writes
``loops: [{variable, number}]`` with the number spelled out, allocated or
typed, because by then the distinction has stopped existing -- it is just the
loop's number. Reading that spec back gives a sheet whose numbers are nailed
down and whose counter is untouched, which is what an issued sheet is, and the
DCS argument above governs from there on. Auto-numbering is the draft stage;
``to_dict()`` is the issue.
"""

from __future__ import annotations


class Loop:
    """One control loop: a measured-variable letter and a number.

    Built by :meth:`~pandid.flowsheet.Flowsheet.add_loop` rather than directly,
    so the sheet it belongs to is the thing that refuses a duplicate. The number
    is required *here* and optional there for the same reason: a series belongs
    to a sheet, so the sheet is the only thing that can say what comes next. By
    the time a loop exists it has a number, and nothing downstream can tell, or
    needs to tell, whether it was typed or counted.
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

        Not a tag: no instrument carries it, because a member's tag opens with
        the measured variable and continues with its own function letters.
        """
        return f"{self.variable}-{self.number}"

    def tag(self, letters: str) -> str:
        """The tag a **final control element** of this loop carries
        (``loop.tag("CV")`` -> ``"CV-303"``).

        This is how anything not lettered from the measured variable joins a
        loop. Loop 303's final element is a :class:`~pandid.units.Valve`; it is
        not minted by :meth:`~pandid.flowsheet.Flowsheet.add_instrument`, and
        the returned string is an ordinary tag, so every unit class joins on the
        same terms.

        The measured-variable check is *not* applied here, and cannot be for a
        final element. It is the check
        :meth:`~pandid.flowsheet.Flowsheet.add_instrument` makes, because it is
        a rule about a **functional letter string**: an instrument's first
        letter is what it measures. A final control element is not tagged that
        way. The reference sheet spells every control valve ``CV-...`` whatever
        it strokes -- ``LIC-306`` drives ``CV-306`` and ``PIC-301`` drives
        ``CV-301-1`` -- so a final element's letters do not track its loop.

        Its **number** does, and that is the half this supplies. CHEE4001 p.11
        labels the control valve of a flow loop ``Loop No.`` alongside the
        element, the transmitter and the controller, all four numbered 504, and
        p.13 gives the rule they follow: "A loop number is assigned to each
        group of components required to perform the desired function of the
        monitor or control scheme." The valve is in the group. So the number is
        what membership is written with, and the signal edge into the actuator
        is what it is drawn with.

        **A primary element goes through** :meth:`element` **instead**, and that
        is issue #203. Both are units rather than balloons and both used to come
        through here, but only one of them is lettered from the measured
        variable, so ``flow_loop.tag("TE")`` quietly composed ``TE-303`` while
        ``add_instrument("TT", flow_loop)`` had always raised. Nothing about a
        control valve's letters can be checked; everything about an element's
        can.
        """
        letters = letters.strip()
        if not letters:
            raise ValueError(
                f"loop {self.name} was given an empty tag; a member's tag is its own "
                f"letters over the loop's number, e.g. {self.variable}T-{self.number}"
            )
        return f"{letters}-{self.number}"

    def element(self, letters: str) -> str:
        """The tag a **primary element** of this loop carries, checked
        (``loop.element("FE")`` -> ``"FE-303"``).

        A primary element is the thing in the pipe the measurement is taken from
        -- an orifice plate, a venturi, a coriolis meter -- and it is lettered
        from the measured variable exactly as a balloon is: ``F`` for flow, then
        ``E`` for element. So the check :meth:`check` makes for a balloon is the
        check this makes, and on a flow loop ``element("TE")`` raises where
        :meth:`tag` had composed ``TE-303`` and said nothing (issue #203).

        **Why a second name and not a flag on** :meth:`tag`. The two calls tag
        two different pieces of equipment, and an engineer writing the sheet
        knows perfectly well which one is in their hands -- an element in the
        line, or the valve at the end of the loop. Putting that in the method
        name asks for the fact they already have and gives back the check that
        follows from it. Putting it in ``tag(letters, check=...)`` puts the same
        fact in a parameter that says nothing about the equipment, has to pick
        one default for both, and is passed by nobody: whichever way it
        defaulted, the safe call would be the one an author had to remember to
        write, which is exactly backwards for a check whose purpose is to catch
        what an author did not notice.

        The rule is the measured variable and nothing else, so a restriction
        orifice ``FO`` and a sight glass ``FG`` on a flow loop are as welcome
        here as ``FE``. What is refused is a *different variable*.
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
