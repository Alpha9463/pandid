"""Define control loops: the variable and number instrument tags share.

A loop is a namespace, not a drawn thing: it has no frame or ports and is
not in :attr:`~pandid.flowsheet.Flowsheet.units`. It owns a number and
checks the first letter of every balloon tagged from it::

    loop = fs.add_loop("F", 303)
    fe = fs.add(units.Fitting(loop.element("FE"), variant="venturi"))
    fs.add_balloon(fe, at="N", offset=38)
    ft = fs.add_instrument("FT", loop, near=fe.balloon, at="N", offset=23)
    fic = fs.add_instrument("FIC", loop, near=ft, at="E", offset=70,
                            variant="shared")
    cv = fs.add(units.Valve(loop.tag("CV"), variant="control"))

The common single loop of transmitter, controller and valve is one call
(:meth:`~pandid.flowsheet.Flowsheet.add_control_loop`), returning a
:class:`ControlLoop`::

    loop = fs.add_control_loop("F", 303, measuring=feed, acting_on=cv)

A primary element is lettered from the measured variable, so
:meth:`Loop.element` checks its letter. A final control element is not
(control valves are ``CV-`` whatever they act on), so :meth:`Loop.tag`
does not check. A loop is identified by its variable and number together:
``FIC-101`` and ``LIC-101`` are different loops.

Loop numbers are author intent and are never renumbered. If the number is
omitted, the flowsheet allocates the next one from a single counter when
the loop is declared. :meth:`~pandid.flowsheet.Flowsheet.to_dict` writes
every number explicitly, and reading a spec sets the counter past the
highest number in it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pandid.streams import Stream
    from pandid.units import Instrument, Unit


class Loop:
    """One control loop: a measured-variable letter and a number.

    Create loops with :meth:`~pandid.flowsheet.Flowsheet.add_loop`, which
    refuses duplicates and allocates a number when none is given.

    Parameters
    ----------
    variable : str
        Single ISA measured-variable letter, such as ``"F"``.
    number : str or int
        Loop number.

    Attributes
    ----------
    variable : str
        Upper-case measured-variable letter.
    number : str
        Loop number as text.

    Raises
    ------
    ValueError
        If ``variable`` is not one letter or ``number`` is empty.
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
        """Return the loop's identity, such as ``"F-303"``.

        This is not a tag; no instrument carries it.

        Returns
        -------
        str
            Variable and number.
        """
        return f"{self.variable}-{self.number}"

    def tag(self, letters: str) -> str:
        """Return a final control element's tag on this loop.

        ``loop.tag("CV")`` gives ``"CV-303"``. The letters are not checked
        against the measured variable: a control valve is ``CV-`` whatever
        it acts on. The number joins it to the loop. Use :meth:`element`
        for a primary element.

        Parameters
        ----------
        letters : str
            The element's own letters.

        Returns
        -------
        str
            Letters and loop number.

        Raises
        ------
        ValueError
            If ``letters`` is empty.
        """
        letters = letters.strip()
        if not letters:
            raise ValueError(
                f"loop {self.name} was given an empty tag; a member's tag is its own "
                f"letters over the loop's number, e.g. {self.variable}T-{self.number}"
            )
        return f"{letters}-{self.number}"

    def element(self, letters: str) -> str:
        """Return a primary element's tag on this loop, checked.

        ``loop.element("FE")`` gives ``"FE-303"``. A primary element (an
        orifice plate, venturi or meter) is lettered from the measured
        variable, so its first letter must match it, as for a balloon. Any
        function letter is allowed: ``FO`` and ``FG`` are fine on a flow
        loop.

        Parameters
        ----------
        letters : str
            The element's letters.

        Returns
        -------
        str
            Letters and loop number.

        Raises
        ------
        ValueError
            If ``letters`` is empty or opens with another variable.
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
        """Check that instrument letters open with the measured variable.

        Called by :meth:`~pandid.flowsheet.Flowsheet.add_instrument`, so a
        ``TT`` on a flow loop fails where it is written.

        Parameters
        ----------
        letters : str
            Instrument function letters.

        Raises
        ------
        ValueError
            If ``letters`` is empty or opens with another variable.
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
        """Return a constructor-style representation."""
        return f"Loop({self.variable!r}, {self.number!r})"


class ControlLoop:
    """Handle for a single-variable feedback loop and its members.

    Returned by :meth:`~pandid.flowsheet.Flowsheet.add_control_loop`. It
    draws nothing and is not in
    :attr:`~pandid.flowsheet.Flowsheet.units`; its members are ordinary
    balloons, units and signal streams that can still be pinned or
    reconnected. It wraps the :class:`Loop` rather than subclassing it, so
    :attr:`~pandid.flowsheet.Flowsheet.loops` keeps one entry per loop.
    Cascade, ratio, split-range and override loops are built by hand.

    Parameters
    ----------
    loop : Loop
        Loop the members are numbered from.
    transmitter : Instrument
        Balloon reading the process, such as ``FT-101``.
    controller : Instrument
        Balloon holding the setpoint, such as ``FIC-101``.
    final_element : Unit
        Unit the output acts on: a valve, damper, louvre or drive. Where a
        port was given, the unit that owns it.
    measurement : Stream
        Signal from transmitter to controller.
    output : Stream
        Signal from controller to final element.

    Attributes
    ----------
    loop, transmitter, controller, final_element, measurement, output
        The parameters above.
    """

    def __init__(self, loop: Loop, transmitter: "Instrument",
                 controller: "Instrument", final_element: "Unit",
                 measurement: "Stream", output: "Stream"):
        self.loop = loop
        self.transmitter = transmitter
        self.controller = controller
        self.final_element = final_element
        self.measurement = measurement
        self.output = output

    @property
    def variable(self) -> str:
        """Return the loop's measured-variable letter."""
        return self.loop.variable

    @property
    def number(self) -> str:
        """Return the loop's number as text."""
        return self.loop.number

    @property
    def name(self) -> str:
        """Return the loop's identity, such as ``"F-101"``."""
        return self.loop.name

    def tag(self, letters: str) -> str:
        """Return a final control element's tag; see :meth:`Loop.tag`.

        Parameters
        ----------
        letters : str
            The element's own letters.

        Returns
        -------
        str
            Letters and loop number.
        """
        return self.loop.tag(letters)

    def element(self, letters: str) -> str:
        """Return a primary element's tag; see :meth:`Loop.element`.

        Parameters
        ----------
        letters : str
            The element's letters.

        Returns
        -------
        str
            Letters and loop number.
        """
        return self.loop.element(letters)

    def check(self, letters: str) -> None:
        """Check instrument letters; see :meth:`Loop.check`.

        This lets :meth:`~pandid.flowsheet.Flowsheet.add_instrument` accept
        this handle wherever it accepts a loop.

        Parameters
        ----------
        letters : str
            Instrument function letters.
        """
        self.loop.check(letters)

    def __repr__(self) -> str:
        """Return a representation naming the loop and its members."""
        return (f"ControlLoop({self.name!r}, {self.transmitter.name!r} -> "
                f"{self.controller.name!r} -> {self.final_element.name!r})")
