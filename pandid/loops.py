"""Control loops: the variable and number instrument tags share.

:meth:`~pandid.flowsheet.Flowsheet.add_loop` returns a :class:`Loop`;
:meth:`~pandid.flowsheet.Flowsheet.add_control_loop` builds a
transmitter, controller and output and returns a :class:`ControlLoop`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pandid._checks import is_whole

if TYPE_CHECKING:
    from pandid.streams import Stream
    from pandid.units import Instrument, Unit


class Loop:
    """One control loop: a measured-variable letter and a number.

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
    TypeError
        If ``number`` is neither text nor a whole number.
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
        if not (isinstance(number, str) or is_whole(number)):
            raise TypeError(
                f"a loop number is text or a whole number (an int), got {number!r}"
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
        """Return the loop's identity, such as ``"F-303"``."""
        return f"{self.variable}-{self.number}"

    def tag(self, letters: str) -> str:
        """Return a final control element's tag, such as ``"CV-303"``.

        The letters are not checked against the measured variable.

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
        """Return a checked primary element tag, such as ``"FE-303"``.

        Parameters
        ----------
        letters : str
            The element's letters, opening with the measured variable.

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
        """Check that letters open with the measured variable.

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

    Parameters
    ----------
    loop : Loop
        Loop the members are numbered from.
    transmitter : Instrument
        Balloon reading the process, such as ``FT-101``.
    controller : Instrument
        Balloon holding the setpoint, such as ``FIC-101``.
    final_element : Unit
        Unit the output acts on, such as a valve.
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

    def __repr__(self) -> str:
        """Return a representation naming the loop and its members."""
        return (f"ControlLoop({self.loop.name!r}, {self.transmitter.name!r} -> "
                f"{self.controller.name!r} -> {self.final_element.name!r})")
