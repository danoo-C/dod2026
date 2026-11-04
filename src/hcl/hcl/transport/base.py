"""What every transport offers the link (docs/hcl.md 4.1).

A transport is a byte pipe to the board: a real serial port, a TCP socket to
the Windows bridge, or the simulated board. The link's I/O thread is the only
caller, and it treats all of them the same way.
"""

from abc import ABC, abstractmethod


class TransportError(Exception):
    """The port is gone or broke (unplugged, closed, refused to open).
    The link reacts by closing it and reconnecting later."""


class Transport(ABC):
    simulated = False  # True only for the simulated board

    @abstractmethod
    def open(self) -> None:
        """Connect. Raises TransportError if that is not possible right now."""

    @abstractmethod
    def read(self, max_bytes: int, timeout: float) -> bytes:
        """Up to max_bytes that arrived, waiting at most `timeout` seconds.
        b"" if nothing came. Raises TransportError if the port is gone."""

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Send all of data. Raises TransportError if the port is gone."""

    @abstractmethod
    def close(self) -> None:
        """Disconnect. Safe to call more than once, and after an error."""
