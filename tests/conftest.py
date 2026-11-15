"""Shared fixtures. The HA-level tests replace tinytuya.Device with a scripted fake so the whole
integration — config flow, coordinator, entities, commands — runs with no station and no network."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEVICE_ID = "bf0123456789abcdef0123"  # 22 chars
LOCAL_KEY = "0123456789abcdef"        # 16 chars
HOST = "192.168.1.50"


def bay(slot, chem=0x01, soc=100, hours=0, mins=0, mv=1400, ca=0, byte12=25) -> bytes:
    """One 17-byte DP110 record."""
    return (bytes([slot, chem, soc, hours, mins, 0, 0, 0]) + mv.to_bytes(2, "big")
            + ca.to_bytes(2, "little") + bytes([byte12, 0, 0, 0, 0]))


def telemetry(**overrides) -> str:
    """A full four-bay DP110 payload; pass slot=bytes to override a bay."""
    default = {3: bay(3), 4: bay(4, soc=40, ca=50), 1: bay(1, chem=0, soc=0, mv=0, byte12=0), 2: bay(2)}
    default.update(overrides)
    return b"".join(default[s] for s in (3, 4, 1, 2)).hex()


def station_dps(**overrides) -> dict:
    dps = {
        "101": True, "102": 2, "103": False, "104": True, "105": 3, "106": False,
        "108": 1, "110": telemetry(), "111": False, "112": "AAAA", "113": 0,
    }
    dps.update(overrides)
    return dps


# Like the real station: these never appear in a status reply, only as pushes when they change.
PUSH_ONLY = ("110", "112")


class FakeTuyaDevice:
    """Scripted stand-in for tinytuya.Device shared by every HA-level test.

    `dps` is the station's true state. Mirroring the real firmware, a status reply carries only
    the station-level datapoints; DP110/DP112 arrive through receive() as a push whenever they
    differ from what this connection was last sent.
    """

    dps: dict = {}
    fail: Exception | dict | None = None
    instances: list = []
    writes: list = []
    polls: int = 0
    heartbeats: int = 0

    def __init__(self, dev_id, host, key):
        self.args = (dev_id, host, key)
        self.closed = False
        self.pushed: dict = {}
        FakeTuyaDevice.instances.append(self)

    def set_version(self, v): self.version = v
    def set_socketPersistent(self, v): pass
    def set_socketTimeout(self, v): pass
    def set_socketRetryLimit(self, v): pass
    def close(self): self.closed = True
    def heartbeat(self, nowait=False):
        FakeTuyaDevice.heartbeats += 1
        return self._failure()

    @staticmethod
    def _failure():
        if isinstance(FakeTuyaDevice.fail, Exception):
            raise FakeTuyaDevice.fail
        return FakeTuyaDevice.fail

    def receive(self):
        if (failure := self._failure()) is not None:
            return failure
        pending = {k: v for k, v in FakeTuyaDevice.dps.items()
                   if k in PUSH_ONLY and self.pushed.get(k) != v}
        if not pending:
            return None
        self.pushed.update(pending)
        return {"protocol": 4, "t": 0, "dps": pending}

    def status(self):
        FakeTuyaDevice.polls += 1
        if (failure := self._failure()) is not None:
            return failure
        return {"dps": {k: v for k, v in FakeTuyaDevice.dps.items() if k not in PUSH_ONLY}}

    def set_value(self, dp, value, nowait=False):
        FakeTuyaDevice.writes.append((dp, value))
        FakeTuyaDevice.dps[str(dp)] = value
        if str(dp) in PUSH_ONLY:
            return None  # its new value arrives as a push
        return {"dps": {str(dp): value}}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """pytest-homeassistant-custom-component needs this to load custom_components/."""
    yield


@pytest.fixture
def fake_station(monkeypatch):
    """Route tinytuya.Device to the fake and reset its script between tests."""
    FakeTuyaDevice.dps = station_dps()
    FakeTuyaDevice.fail = None
    FakeTuyaDevice.instances = []
    FakeTuyaDevice.writes = []
    FakeTuyaDevice.polls = 0
    FakeTuyaDevice.heartbeats = 0
    import tinytuya
    monkeypatch.setattr(tinytuya, "Device", FakeTuyaDevice)
    return FakeTuyaDevice
