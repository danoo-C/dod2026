"""Transports: how bytes get to the board (docs/hcl.md 4.1). Not public API."""

from hcl.transport.base import Transport, TransportError

__all__ = ["Transport", "TransportError"]
