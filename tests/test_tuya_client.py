"""Client tests against a fake tinytuya device — no network, no station."""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "olight"))


class FakeDevice:
    """Stands in for tinytuya.Device; scripted replies, records every call."""

    instances: list = []

    def __init__(self, dev_id, host, key):
        self.args = (dev_id, host, key)
        self.replies: list = []
        self.pushes: list = []
        self.calls: list = []
        self.closed = False
        FakeDevice.instances.append(self)

    def set_version(self, v): self.calls.append(("version", v))
    def set_socketPersistent(self, v): self.calls.append(("persistent", v))
    def set_socketTimeout(self, v): self.calls.append(("timeout", v))
    def set_socketRetryLimit(self, v): self.calls.append(("retry", v))
    def close(self): self.closed = True
    def heartbeat(self, nowait=False): self.calls.append(("heartbeat",))

    def receive(self):
        """Buffered pushes, oldest first; None once the buffer is empty (a read timeout)."""
        self.calls.append(("receive",))
        if not self.pushes:
            return None
        push = self.pushes.pop(0)
        if isinstance(push, Exception):
            raise push
        return push

    def _next(self):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def status(self):
        self.calls.append(("status",))
        return self._next()

    def set_value(self, dp, value, nowait=False):
        self.calls.append(("set", dp, value))
        return self._next()


@pytest.fixture
def client(monkeypatch):
    FakeDevice.instances.clear()
    monkeypatch.setitem(sys.modules, "tinytuya", types.SimpleNamespace(Device=FakeDevice))
    sys.modules.pop("tuya_client", None)
    import tuya_client
    return tuya_client


def script(*replies):
    """Queue replies for the next device the client creates."""
    FakeDevice.pending = list(replies)


def new_device_with(*replies):
    original_init = FakeDevice.__init__

    def init(self, *a, **k):
        original_init(self, *a, **k)
        self.replies = list(replies)
    return init


def test_connect_uses_protocol_35_and_a_persistent_socket(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__", new_device_with({"dps": {"101": True}}))
    c = client.OstationClient("d" * 22, "10.0.0.2", "k" * 16)
    assert c.status() == {"101": True}
    dev = FakeDevice.instances[0]
    assert dev.args == ("d" * 22, "10.0.0.2", "k" * 16)
    assert ("version", 3.5) in dev.calls
    assert ("persistent", True) in dev.calls


def test_socket_is_reused_between_polls(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__",
                        new_device_with({"dps": {"101": True}}, {"dps": {"101": False}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    c.status(); c.status()
    # One connection for two polls: reconnecting per poll would evict the app every 15 s.
    assert len(FakeDevice.instances) == 1


def test_error_payload_triggers_one_reconnect_then_succeeds(client, monkeypatch):
    replies = iter([
        [{"Error": "Network Error: Unable to Connect", "Err": "901"}],  # first device
        [{"dps": {"101": True}}],                                        # second device
    ])
    original_init = FakeDevice.__init__

    def init(self, *a, **k):
        original_init(self, *a, **k)
        self.replies = next(replies)
    monkeypatch.setattr(FakeDevice, "__init__", init)

    c = client.OstationClient("d" * 22, "h", "k" * 16)
    assert c.status() == {"101": True}
    assert len(FakeDevice.instances) == 2
    assert FakeDevice.instances[0].closed is True


def test_persistent_failure_raises_after_retry(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__", new_device_with({"Error": "boom"}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    with pytest.raises(client.OstationError):
        c.status()
    assert len(FakeDevice.instances) == 2  # exactly one retry, not an infinite loop


def test_reply_without_dps_is_an_error(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__", new_device_with({"foo": 1}, {"foo": 1}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    with pytest.raises(client.OstationError):
        c.status()


def test_set_dp_writes_and_returns_dps(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__", new_device_with({"dps": {"101": False}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    assert c.set_dp(101, False) == {"101": False}
    assert ("set", 101, False) in FakeDevice.instances[0].calls


def test_set_dp_failure_resets_the_socket(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__", new_device_with(OSError("reset by peer")))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    with pytest.raises(client.OstationError):
        c.set_dp(101, True)
    assert FakeDevice.instances[0].closed is True


def test_close_is_safe_when_never_connected(client):
    client.OstationClient("d" * 22, "h", "k" * 16).close()


def test_heartbeat_is_sent_only_when_connected(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__", new_device_with({"dps": {"101": True}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    assert c.heartbeat() is False          # nothing to keep alive yet, and no socket opened for it
    assert FakeDevice.instances == []
    c.status()
    assert c.heartbeat() is False          # sent, but nothing new arrived
    assert ("heartbeat",) in FakeDevice.instances[0].calls


def test_failed_heartbeat_drops_the_socket_so_the_next_poll_starts_clean(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__",
                        new_device_with({"dps": {"101": True}}, {"dps": {"101": True}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    c.status()

    def boom(self, nowait=False): raise OSError("reset by peer")
    monkeypatch.setattr(FakeDevice, "heartbeat", boom)
    assert c.heartbeat() is False
    assert FakeDevice.instances[0].closed is True
    monkeypatch.setattr(FakeDevice, "heartbeat", lambda self, nowait=False: None)
    assert c.status() == {"101": True}     # reconnects without needing its retry
    assert len(FakeDevice.instances) == 2


# --- The station pushes DP110/DP112 and never includes them in a status reply ------------------

def test_status_reply_without_telemetry_keeps_the_last_pushed_telemetry(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__",
                        new_device_with({"dps": {"101": True}}, {"dps": {"101": False}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    c.status()
    FakeDevice.instances[0].pushes.append({"protocol": 4, "dps": {"110": "AA=="}})
    assert c.heartbeat() is True
    # The station goes quiet: the next status reply has no DP110, which must not erase it.
    assert c.status() == {"101": False, "110": "AA=="}


def test_push_read_in_place_of_the_status_reply_is_merged_not_returned_alone(client, monkeypatch):
    """tinytuya returns the first buffered message: here a push, with the real reply behind it."""
    monkeypatch.setattr(FakeDevice, "__init__",
                        new_device_with({"protocol": 4, "dps": {"110": "AA=="}}))
    original_status = FakeDevice.status

    def status(self):
        reply = original_status(self)
        self.pushes.append({"dps": {"101": True, "102": 4}})  # the real reply, still buffered
        return reply
    monkeypatch.setattr(FakeDevice, "status", status)
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    assert c.status() == {"101": True, "102": 4, "110": "AA=="}


def test_pushes_buffered_between_calls_are_drained_before_the_request(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__",
                        new_device_with({"dps": {"101": True}}, {"dps": {"101": True}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    c.status()
    dev = FakeDevice.instances[0]
    dev.pushes += [{"dps": {"110": "AQ=="}}, {"dps": {"110": "Ag=="}}]
    dev.calls.clear()
    assert c.status()["110"] == "Ag=="  # the newest push wins
    assert dev.calls.index(("receive",)) < dev.calls.index(("status",))


def test_seeded_values_fill_gaps_but_never_override_live_data(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__",
                        new_device_with({"dps": {"101": True}}, {"dps": {"101": True}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    c.seed({"110": "old", "112": "AAAA"})
    assert c.status() == {"101": True, "110": "old", "112": "AAAA"}
    FakeDevice.instances[0].pushes.append({"dps": {"110": "new"}})
    c.heartbeat()
    c.seed({"110": "old"})
    assert c.cached["110"] == "new"


def test_cache_survives_a_reconnect(client, monkeypatch):
    replies = iter([[{"dps": {"101": True}}], [{"dps": {"101": True}}]])
    original_init = FakeDevice.__init__

    def init(self, *a, **k):
        original_init(self, *a, **k)
        self.replies = next(replies)
    monkeypatch.setattr(FakeDevice, "__init__", init)
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    c.status()
    FakeDevice.instances[0].pushes += [{"dps": {"110": "AA=="}}, OSError("reset by peer")]
    assert c.heartbeat() is False          # the socket died mid-drain
    assert c.status()["110"] == "AA=="     # a dropped socket says nothing about the cells


def test_error_payload_while_draining_fails_the_call(client, monkeypatch):
    monkeypatch.setattr(FakeDevice, "__init__", new_device_with({"dps": {"101": True}}))
    c = client.OstationClient("d" * 22, "h", "k" * 16)
    c.status()
    FakeDevice.instances[0].pushes.append({"Error": "Network Error", "Err": "901"})
    assert c.heartbeat() is False
    assert FakeDevice.instances[0].closed is True
