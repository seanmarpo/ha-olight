"""Blocking Tuya LAN client, kept off the event loop.

The Ostation speaks Tuya protocol 3.5 on the local network and **accepts a single local connection
at a time** — if Home Assistant reconnects on every poll, or the Olight app is open at the same
time, the station drops whoever connected first. So we hold one persistent socket per device and
serialise every call through it.

The station also **closes an idle socket**: owners who scripted it report that without regular
heartbeats "the Ostation will kill the socket connection". `heartbeat()` is the keep-alive; the
caller decides the cadence (the coordinator uses Home Assistant's own timer, so nothing lingers
when the entry unloads).

The station **does not include its bay telemetry (DP110) or quiet-hours window (DP112) in a status
reply**. It only sends them as unsolicited pushes, every few seconds while a cell is charging and
otherwise only when something changes. Two consequences shape this client:

- Every message read on the socket (status reply, push, heartbeat ack, write ack) is merged into one
  cache of last-known datapoints, and that cache is what callers get. Replacing state with the
  latest status reply would blank every bay entity whenever the station goes quiet.
- tinytuya's request methods return the *first* message in the socket buffer, which is often a
  push that arrived earlier rather than the reply asked for. So each call drains the buffer before
  and after the request, and a reply's own content never decides what the state is.

tinytuya is synchronous; the coordinator runs these methods in an executor thread.
"""

from __future__ import annotations

import logging
import threading

import tinytuya

_LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSION = 3.5
_CONNECT_TIMEOUT = 5
# Below the ~10 s at which Tuya firmware tends to give up on a quiet socket. Each heartbeat also
# collects any pushes that arrived since the last one, so this is the upper bound on how stale a
# bay reading can be.
HEARTBEAT_INTERVAL = 8.0
# How long a drain waits for one more buffered message. Pushes are already in the socket buffer by
# the time we look, so this only needs to cover a reply still in flight.
_DRAIN_TIMEOUT = 0.3
_DRAIN_MAX = 32


class OstationError(Exception):
    """Raised when the station can't be reached or refuses a command."""


class OstationClient:
    """One persistent, serialised LAN connection to a single station."""

    def __init__(self, device_id: str, host: str, local_key: str) -> None:
        self._device_id = device_id
        self._host = host
        self._local_key = local_key
        self._lock = threading.Lock()
        self._device: tinytuya.Device | None = None
        # Last-known value of every datapoint. Survives reconnects on purpose: a dropped socket
        # says nothing about the cells in the bays.
        self._cache: dict = {}

    def _connect(self) -> tinytuya.Device:
        device = tinytuya.Device(self._device_id, self._host, self._local_key)
        device.set_version(PROTOCOL_VERSION)
        # Persistent socket + heartbeats: reconnecting per poll costs a full 3.5 handshake and
        # makes the station drop the app's connection every few seconds.
        device.set_socketPersistent(True)
        device.set_socketTimeout(_CONNECT_TIMEOUT)
        device.set_socketRetryLimit(1)
        return device

    def _reset(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except Exception:  # noqa: BLE001 - closing a dead socket must never mask the real error
                pass
        self._device = None

    @staticmethod
    def _message_dps(result) -> dict | None:
        """Datapoints carried by one message, or None if it carried none (acks, empty reads).

        tinytuya reports transport problems as a payload rather than an exception.
        """
        if result is None:
            return None
        if not isinstance(result, dict):
            raise OstationError(f"unexpected reply: {result!r}")
        if "Error" in result:
            raise OstationError(str(result.get("Error")))
        dps = result.get("dps")
        return dps if isinstance(dps, dict) and dps else None

    def _absorb(self, result) -> bool:
        """Merge one message into the cache. Returns whether it carried any datapoints."""
        dps = self._message_dps(result)
        if dps is None:
            return False
        self._cache.update(dps)
        return True

    def _drain(self) -> bool:
        """Read everything already buffered on the socket into the cache.

        Pushes accumulate in the kernel buffer between calls; left there, the next request would
        read one of them as its 'reply'.
        """
        assert self._device is not None
        got = False
        self._device.set_socketTimeout(_DRAIN_TIMEOUT)
        try:
            for _ in range(_DRAIN_MAX):
                result = self._device.receive()
                if result is None:
                    break
                got |= self._absorb(result)
        finally:
            if self._device is not None:
                self._device.set_socketTimeout(_CONNECT_TIMEOUT)
        return got

    def seed(self, dps: dict) -> None:
        """Pre-load last-known datapoints (e.g. persisted across a restart).

        Live data always wins: only datapoints not yet seen on this connection are filled in.
        """
        with self._lock:
            for key, value in dps.items():
                self._cache.setdefault(key, value)

    @property
    def cached(self) -> dict:
        with self._lock:
            return dict(self._cache)

    def status(self) -> dict:
        """Query the station and return every datapoint known so far. Retries once on a stale
        socket."""
        with self._lock:
            for attempt in (1, 2):
                if self._device is None:
                    self._device = self._connect()
                try:
                    got = self._drain()
                    got |= self._absorb(self._device.status())
                    got |= self._drain()  # the real reply, if status() returned a push instead
                    if not got:
                        raise OstationError("station sent no datapoints")
                    return dict(self._cache)
                except OstationError:
                    self._reset()
                    if attempt == 2:
                        raise
                except Exception as err:  # noqa: BLE001
                    self._reset()
                    if attempt == 2:
                        raise OstationError(str(err)) from err
            raise OstationError("unreachable")  # pragma: no cover - loop always returns or raises

    def set_dp(self, dp: int, value) -> dict:
        """Write one datapoint and return every datapoint known afterwards."""
        with self._lock:
            if self._device is None:
                self._device = self._connect()
            try:
                self._drain()
                result = self._device.set_value(dp, value, nowait=False)
                # The ack may have been preceded by a push; an error payload is still an error.
                self._message_dps(result)
                self._absorb(result)
                self._drain()
                return dict(self._cache)
            except OstationError:
                self._reset()
                raise
            except Exception as err:  # noqa: BLE001
                self._reset()
                raise OstationError(str(err)) from err

    def heartbeat(self) -> bool:
        """Keep the persistent socket alive and collect any pushes since the last call.

        Returns whether the cache changed. Does nothing when not connected: the next real call
        opens the socket, and a heartbeat should never be the thing that establishes a connection.
        On failure the socket is dropped so the next poll starts clean instead of spending its
        single retry on a dead one.
        """
        with self._lock:
            if self._device is None:
                return False
            before = dict(self._cache)
            try:
                self._absorb(self._device.heartbeat(nowait=False))
                self._drain()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("heartbeat failed, dropping the socket: %s", err)
                self._reset()
                return False
            return self._cache != before

    def close(self) -> None:
        with self._lock:
            self._reset()
