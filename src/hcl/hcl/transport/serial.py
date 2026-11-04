"""A real port through pyserial (docs/hcl.md 4.1, 4.2).

The same class handles a USB serial port (/dev/ttyUSB0, development in WSL)
and a TCP connection to the Windows bridge (socket://host.docker.internal:7777,
the notebook): pyserial opens both from a URL.
"""

from __future__ import annotations

import serial

from hcl.transport.base import Transport, TransportError

WRITE_TIMEOUT = 1.0  # a write that takes longer than this means the port is stuck


class SerialTransport(Transport):
    def __init__(self, url: str, baud: int = 115200) -> None:
        if not url:
            raise ValueError("no port given")
        self.url = url
        self.baud = baud
        self._port: serial.SerialBase | None = None
        self._timeout: float | None = None

    def open(self) -> None:
        self.close()
        try:
            port = serial.serial_for_url(self.url, do_not_open=True, baudrate=self.baud,
                                         timeout=0, write_timeout=WRITE_TIMEOUT)
            # Off before opening, so opening the port doesn't reset the board
            # through its auto-reset circuit (hcl.md 4.2).
            port.dtr = False
            port.rts = False
            port.open()
            # Whatever was waiting is from before us. pyserial already does this
            # for real ports in open(); for socket:// (the bridge) it doesn't.
            port.reset_input_buffer()
        except (serial.SerialException, OSError, ValueError) as e:
            raise TransportError(str(e) or type(e).__name__) from e
        self._port = port
        self._timeout = 0

    def read(self, max_bytes: int, timeout: float) -> bytes:
        port = self._require()
        try:
            if timeout != self._timeout:
                port.timeout = timeout  # reconfigures the port, so only when it changes
                self._timeout = timeout
            waiting = port.in_waiting
            if waiting:
                return port.read(min(waiting, max_bytes))
            first = port.read(1)  # waits up to `timeout` for something to arrive
            if not first:
                return b""
            more = min(port.in_waiting, max_bytes - 1)
            return first + port.read(more) if more > 0 else first
        except (serial.SerialException, OSError) as e:
            raise TransportError(str(e) or type(e).__name__) from e

    def write(self, data: bytes) -> None:
        port = self._require()
        try:
            port.write(data)
        except (serial.SerialException, OSError) as e:  # SerialTimeoutException is a SerialException
            raise TransportError(str(e) or type(e).__name__) from e

    def close(self) -> None:
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except (serial.SerialException, OSError):
                pass

    def _require(self) -> serial.SerialBase:
        if self._port is None:
            raise TransportError("port is closed")
        return self._port
