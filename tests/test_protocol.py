"""Decoder tests. Pure functions, so they run without Home Assistant or a station."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "olight"))

import protocol  # noqa: E402
from datetime import time  # noqa: E402

from protocol import (  # noqa: E402
    RECORD_LEN,
    SLOT_ORDER,
    decode_pause_window,
    decode_slots,
    encode_pause_window,
)


# The DP110 blob exactly as published in tuya-local issue #6069.
PUBLISHED_DUMP = (
    "03016400000000000578000019000000000401640000000005780000190000000001"
    "01640000000005780000190000000002016400000000057800001900000000"
)


def record(slot, chem=0x01, soc=100, hours=0, mins=0, mv=1400, ca=0, byte12=25):
    """Build one 17-byte bay record."""
    return bytes([slot, chem, soc, hours, mins, 0, 0, 0]) \
        + mv.to_bytes(2, "big") + ca.to_bytes(2, "little") + bytes([byte12, 0, 0, 0, 0])


def payload(*records):
    return b"".join(records).hex()


def test_record_length_matches_spec():
    assert len(record(3)) == RECORD_LEN


def test_decodes_a_full_four_bay_payload():
    raw = payload(*(record(s) for s in SLOT_ORDER))
    assert len(bytes.fromhex(raw)) == 68
    slots = decode_slots(raw)
    assert set(slots) == set(SLOT_ORDER)
    aa1 = slots[3]
    assert (aa1.label, aa1.size) == ("AA1", "AA")
    assert (aa1.chemistry, aa1.soc, aa1.voltage, aa1.byte12) == ("nimh", 100, 1400, 25)


def test_published_dump_degrades_to_the_trustworthy_bay():
    """The DP110 dump published in tuya-local issue #6069 is 65 bytes, not 68.

    Zero bytes were lost transcribing it, so only the first record survives intact. That record is
    what confirms the field layout (1400 mV / 25 C on a charged Ni-MH cell). The decoder must
    recover it and discard the three misaligned ones rather than publishing impossible readings.
    """
    slots = decode_slots(PUBLISHED_DUMP)
    assert len(bytes.fromhex(PUBLISHED_DUMP)) == 65
    assert set(slots) == {3}
    assert (slots[3].voltage, slots[3].byte12, slots[3].soc) == (1400, 25, 100)


def test_empty_bay_reports_none_not_zero():
    """0 mV means no cell. Reporting 0% would read as a dead battery instead of an empty bay."""
    slots = decode_slots(payload(record(3, chem=0, soc=0, mv=0, byte12=0)))
    bay = slots[3]
    assert bay.occupied is False
    assert bay.soc is None and bay.voltage is None and bay.byte12 is None


def test_real_charging_records_from_hardware_are_not_dropped():
    """Four DP110 records captured from a real Ostation 2 Pro with Ni-MH cells charging.

    The current field is little-endian (byte 10 holds the value, byte 11 is 0). Decoded big-endian
    it read ~64000 mA and tripped the sanity ceiling, taking every bay offline. These must survive
    and report a sane ~250 mA charge current.
    """
    records = {
        1: "01010b0003000000054719003b00000000",
        2: "02010e0003000000055718003a00000000",
    }
    slots = decode_slots(payload(*(bytes.fromhex(h) for h in records.values())))
    assert set(slots) == {1, 2}
    assert slots[1].voltage == 1351 and slots[1].current == 250 and slots[1].soc == 11
    assert slots[2].voltage == 1367 and slots[2].current == 240 and slots[2].soc == 14
    assert slots[1].charging and slots[2].charging


def test_charging_is_driven_by_current():
    charging = decode_slots(payload(record(3, soc=40, ca=50)))[3]
    assert charging.charging is True
    assert charging.current == 500  # the raw field is tens of milliamps
    assert decode_slots(payload(record(3, ca=0)))[3].charging is False


def test_elapsed_time_is_flattened_to_minutes():
    assert decode_slots(payload(record(3, hours=2, mins=30)))[3].minutes == 150


@pytest.mark.parametrize("code,name", [(0x00, "detecting"), (0x01, "nimh"), (0x02, "liion")])
def test_known_chemistries(code, name):
    assert decode_slots(payload(record(3, chem=code, mv=1400)))[3].chemistry == name


def test_implausible_records_are_dropped():
    """A misaligned record decodes to physics that cannot happen; it must not reach a sensor."""
    bogus = record(4, mv=30720)
    slots = decode_slots(payload(record(3), bogus))
    assert 3 in slots and 4 not in slots


def test_base64_payload_is_accepted():
    """Some firmware/library combinations hand the raw DP over as base64 rather than hex."""
    import base64
    raw = b"".join(record(s) for s in SLOT_ORDER)
    assert decode_slots(base64.b64encode(raw).decode())[3].voltage == 1400


@pytest.mark.parametrize("junk", ["", None, "zzzz", 0, [], "0x"])
def test_garbage_never_raises(junk):
    assert decode_slots(junk) == {}


def test_trailing_byte_still_decodes_every_bay():
    """A firmware revision appending a byte must not take all four bays offline."""
    raw = b"".join(record(s) for s in SLOT_ORDER) + b"\x00"
    slots = decode_slots(raw.hex())
    assert set(slots) == set(SLOT_ORDER)


def test_unknown_slot_ids_are_ignored():
    assert decode_slots(payload(record(9))) == {}


def test_labels_cover_every_slot():
    assert set(protocol.SLOT_LABELS) == set(SLOT_ORDER) == set(protocol.SLOT_SIZE)


def test_byte12_over_100_does_not_drop_the_record():
    """Owners see byte 12 near 100 during a fast charge; whatever it is, it must not take the
    bay offline. It is not part of the plausibility check."""
    slots = decode_slots(payload(record(3, soc=60, ca=120, byte12=130)))
    assert slots[3].byte12 == 130 and slots[3].voltage == 1400


def test_hex_text_is_not_misread_as_base64():
    """A 136-char hex string is also syntactically valid base64 and decodes to 102 bytes — a
    multiple of 17. The decoder must still recognise it as hex."""
    raw = payload(*(record(s) for s in SLOT_ORDER))
    assert len(raw) == 136
    slots = decode_slots(raw)
    assert set(slots) == set(SLOT_ORDER) and slots[3].voltage == 1400


def test_base64_is_preferred_when_that_is_what_the_device_sent():
    import base64
    raw = b"".join(record(s) for s in SLOT_ORDER)
    text = base64.b64encode(raw).decode()
    assert set(decode_slots(text)) == set(SLOT_ORDER)


@pytest.mark.parametrize("value,expected", [
    ("AAAA", (time(0, 0), time(0, 0))),          # factory default: three zero bytes
    ("FgAHHg==", (time(22, 0), time(7, 30))),     # 22:00 - 07:30
    (bytes([6, 15, 8, 45]), (time(6, 15), time(8, 45))),
])
def test_pause_window_decodes(value, expected):
    assert decode_pause_window(value) == expected


@pytest.mark.parametrize("value", ["", None, 5, "not base64!", "GAAAAA=="])  # 24:00 is invalid
def test_pause_window_rejects_junk(value):
    assert decode_pause_window(value) is None


def test_pause_window_round_trips():
    start, end = time(23, 59), time(5, 1)
    assert decode_pause_window(encode_pause_window(start, end)) == (start, end)
