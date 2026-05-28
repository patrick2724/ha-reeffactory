"""
Reef Factory WebSocket client.

All RF devices use the same binary WebSocket protocol over ws://[IP]:80
with subprotocol "arduino".

Frame format (sent/received):
  [name_len: 1 byte][name: N bytes][data_len: 4 bytes BE][data: M bytes]

The device sends push frames whenever data changes.
The client sends a join frame on connect to subscribe to updates.

Binary helpers:
  uint32 from bytes: (b[i]<<24)|(b[i+1]<<16)|(b[i+2]<<8)|b[i+3]
  uint16 from bytes: (b[i]<<8)|b[i+1]
"""

from __future__ import annotations

import asyncio
import logging
import struct
from collections.abc import Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

_LOGGER = logging.getLogger(__name__)

# Frame parsing states
_STATE_NAME_LEN = 0
_STATE_NAME = 1
_STATE_DATA_LEN = 2
_STATE_DATA = 3


def _encode_frame(name: str, data: bytes | None = None) -> bytes:
    """Encode a command frame to send to the device."""
    name_bytes = name.encode("utf-8")
    name_len = len(name_bytes)
    data_bytes = data if data else b""
    data_len = len(data_bytes)
    return bytes([name_len]) + name_bytes + struct.pack(">I", data_len) + data_bytes


def _parse_frames(buf: bytes) -> tuple[list[tuple[str, bytes]], bytes]:
    """
    Parse one or more frames from a raw buffer.
    Returns (list of (name, data) tuples, remaining_buffer).
    """
    frames: list[tuple[str, bytes]] = []
    pos = 0
    while pos < len(buf):
        if pos >= len(buf):
            break
        name_len = buf[pos]
        pos += 1
        if pos + name_len > len(buf):
            pos -= 1
            break
        name = buf[pos: pos + name_len].decode("utf-8", errors="replace")
        pos += name_len
        if pos + 4 > len(buf):
            pos -= (1 + name_len)
            break
        data_len = struct.unpack(">I", buf[pos: pos + 4])[0]
        pos += 4
        if pos + data_len > len(buf):
            pos -= (1 + name_len + 4)
            break
        data = buf[pos: pos + data_len]
        pos += data_len
        frames.append((name, data))
    return frames, buf[pos:]


class RfWebSocketClient:
    """
    Async WebSocket client for Reef Factory devices.

    Usage:
        client = RfWebSocketClient(host, device_type, connect_msg, refresh_cb)
        client.register_callback("khRefresh", my_handler)
        await client.start()
        ...
        await client.stop()
    """

    def __init__(
        self,
        host: str,
        connect_msg: str,
        callbacks: dict[str, Callable[[bytes], None]] | None = None,
    ) -> None:
        self._host = host
        self._connect_msg = connect_msg
        self._callbacks: dict[str, list[Callable[[bytes], None]]] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self._ws = None
        self._connected = False
        self._reconnect_delay = 5
        self._buf = b""
        self._disconnect_callbacks: list[Callable[[], None]] = []

        if callbacks:
            for name, cb in callbacks.items():
                self.register_callback(name, cb)

    def register_callback(self, name: str, callback: Callable[[bytes], None]) -> None:
        """Register a callback for a named frame."""
        self._callbacks.setdefault(name, []).append(callback)

    def register_disconnect_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to be called on disconnect."""
        self._disconnect_callbacks.append(callback)

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Start the client loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the client loop."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send_command(self, name: str, data: bytes | None = None) -> bool:
        """Send a command frame to the device."""
        if not self._connected or not self._ws:
            _LOGGER.warning("Cannot send %s: not connected to %s", name, self._host)
            return False
        try:
            frame = _encode_frame(name, data)
            await self._ws.send(frame)
            return True
        except Exception as exc:
            _LOGGER.error("Error sending %s to %s: %s", name, self._host, exc)
            return False

    async def _loop(self) -> None:
        """Main reconnect loop."""
        delay = 5
        while self._running:
            try:
                await self._connect()
                delay = 5  # reset on success
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _LOGGER.warning(
                    "Connection to %s failed: %s. Retrying in %ds", self._host, exc, delay
                )
            finally:
                self._connected = False
                for cb in self._disconnect_callbacks:
                    try:
                        cb()
                    except Exception:
                        pass

            if self._running:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def _connect(self) -> None:
        """Open WebSocket, send join, receive frames."""
        uri = f"ws://{self._host}/"
        _LOGGER.debug("Connecting to %s", uri)
        async with websockets.connect(
            uri,
            subprotocols=["arduino"],
            ping_interval=None,   # we handle ping ourselves via device protocol
            close_timeout=5,
            open_timeout=10,
        ) as ws:
            self._ws = ws
            self._connected = True
            self._buf = b""
            _LOGGER.info("Connected to Reef Factory device at %s", self._host)

            # Send join frame
            join_frame = _encode_frame(self._connect_msg, b"join")
            await ws.send(join_frame)

            # Receive loop
            async for raw in ws:
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
                self._buf += raw
                frames, self._buf = _parse_frames(self._buf)
                for name, data in frames:
                    _LOGGER.debug("Frame from %s: %s (%d bytes)", self._host, name, len(data))
                    for cb in self._callbacks.get(name, []):
                        try:
                            cb(data)
                        except Exception as exc:
                            _LOGGER.error("Callback error for %s/%s: %s", self._host, name, exc)


# ---------------------------------------------------------------------------
# Binary decode helpers (matching the JS: (b[i]<<24)|(b[i+1]<<16)|... )
# ---------------------------------------------------------------------------

def read_uint32(data: bytes, offset: int) -> tuple[int, int]:
    """Read a big-endian uint32 and return (value, new_offset)."""
    val = struct.unpack_from(">I", data, offset)[0]
    return val, offset + 4


def read_uint16(data: bytes, offset: int) -> tuple[int, int]:
    """Read a big-endian uint16 and return (value, new_offset)."""
    val = struct.unpack_from(">H", data, offset)[0]
    return val, offset + 2


def read_uint8(data: bytes, offset: int) -> tuple[int, int]:
    """Read a uint8 and return (value, new_offset)."""
    return data[offset], offset + 1


def read_float32_as_int(data: bytes, offset: int, scale: float = 100.0) -> tuple[float, int]:
    """Read uint32 and divide by scale to get float (e.g. 714 -> 7.14)."""
    raw, new_off = read_uint32(data, offset)
    return raw / scale, new_off
