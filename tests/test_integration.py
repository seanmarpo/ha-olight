"""End to end through Home Assistant: setup, devices, entity states, commands, unload."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.olight.tuya_client import HEARTBEAT_INTERVAL
from custom_components.olight.const import (
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_MODEL,
    DOMAIN,
    UPDATE_INTERVAL_SECONDS,
)

from .conftest import DEVICE_ID, HOST, LOCAL_KEY, bay


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEVICE_ID, title="Ostation 2 Pro",
        data={CONF_HOST: HOST, CONF_DEVICE_ID: DEVICE_ID, CONF_LOCAL_KEY: LOCAL_KEY,
              CONF_MODEL: "Ostation 2 Pro"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_station_and_four_bays_are_registered_as_devices(
        hass: HomeAssistant, fake_station) -> None:
    entry = await _setup(hass)
    registry = dr.async_get(hass)
    # async_get_device(identifiers=...) is deprecated: identifiers are only unique per config entry.
    station = registry.async_get_device_by_identifier((DOMAIN, DEVICE_ID), entry.entry_id)
    assert station is not None and station.manufacturer == "Olight"
    for slot, label in ((3, "AA1"), (4, "AA2"), (1, "AAA1"), (2, "AAA2")):
        d = registry.async_get_device_by_identifier(
            (DOMAIN, f"{DEVICE_ID}_slot{slot}"), entry.entry_id)
        assert d is not None and d.name == label
        assert d.via_device_id == station.id
    ent = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent, entry.entry_id)
    assert len(entities) == 43


async def test_bay_readings_match_the_payload(hass: HomeAssistant, fake_station) -> None:
    await _setup(hass)
    s = hass.states
    # AA1: full Ni-MH cell, idle.
    assert s.get("sensor.aa1_charge").state == "100"
    assert s.get("sensor.aa1_voltage").state == "1400"
    assert s.get("sensor.aa1_current").state == "0"
    assert s.get("sensor.aa1_byte_12").state == "25"
    assert s.get("sensor.aa1_chemistry").state == "Ni-MH"
    assert s.get("binary_sensor.aa1_battery_present").state == STATE_ON
    assert s.get("binary_sensor.aa1_charging").state == STATE_OFF
    # AA2: 40 % and taking 500 mA.
    assert s.get("sensor.aa2_charge").state == "40"
    assert s.get("sensor.aa2_current").state == "500"
    assert s.get("binary_sensor.aa2_charging").state == STATE_ON
    # AAA1: empty bay — no fake zeros.
    assert s.get("binary_sensor.aaa1_battery_present").state == STATE_OFF
    assert s.get("sensor.aaa1_charge").state == "unknown"
    assert s.get("sensor.aaa1_voltage").state == "unknown"
    assert s.get("sensor.aaa1_chemistry").state == "Detecting"


async def test_station_entities(hass: HomeAssistant, fake_station) -> None:
    await _setup(hass)
    s = hass.states
    assert s.get("switch.ostation_2_pro_charging").state == STATE_ON
    assert s.get("switch.ostation_2_pro_quiet_hours").state == STATE_OFF
    assert s.get("sensor.ostation_2_pro_batteries_charged").state == "2"
    assert s.get("sensor.ostation_2_pro_batteries_rejected").state == "1"
    assert s.get("number.ostation_2_pro_wake_sensitivity").state == "3.0"
    assert s.get("binary_sensor.ostation_2_pro_aa_compartment_full").state == STATE_ON
    assert s.get("binary_sensor.ostation_2_pro_rejected_bin_full").state == STATE_OFF


async def test_quiet_hours_window_is_decoded_and_written_back(
        hass: HomeAssistant, fake_station) -> None:
    fake_station.dps["112"] = "FgAHHg=="  # 22:00 - 07:30
    await _setup(hass)
    assert hass.states.get("time.ostation_2_pro_quiet_hours_start").state == "22:00:00"
    assert hass.states.get("time.ostation_2_pro_quiet_hours_end").state == "07:30:00"
    await hass.services.async_call(
        "time", "set_value",
        {"entity_id": "time.ostation_2_pro_quiet_hours_end", "time": "06:45:00"}, blocking=True)
    await hass.async_block_till_done()
    assert fake_station.writes == [(112, "FgAGLQ==")]  # start kept, end replaced


async def test_never_configured_window_reads_as_midnight(
        hass: HomeAssistant, fake_station) -> None:
    fake_station.dps["112"] = "AAAA"  # three zero bytes, as shipped
    await _setup(hass)
    assert hass.states.get("time.ostation_2_pro_quiet_hours_start").state == "00:00:00"


async def test_switch_writes_the_datapoint_and_refreshes(
        hass: HomeAssistant, fake_station) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.ostation_2_pro_charging"}, blocking=True)
    await hass.async_block_till_done()
    assert fake_station.writes == [(101, False)]
    assert hass.states.get("switch.ostation_2_pro_charging").state == STATE_OFF


async def test_number_writes_an_integer(hass: HomeAssistant, fake_station) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.ostation_2_pro_wake_sensitivity", "value": 5}, blocking=True)
    await hass.async_block_till_done()
    assert fake_station.writes == [(105, 5)]


async def test_poll_picks_up_a_cell_being_inserted(
        hass: HomeAssistant, fake_station) -> None:
    await _setup(hass)
    assert hass.states.get("binary_sensor.aaa1_battery_present").state == STATE_OFF
    fake_station.dps["110"] = _with_aaa1(bay(1, soc=10, mv=1210, ca=30, byte12=22))
    before = fake_station.polls
    _advance_one_poll(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_station.polls == before + 1, "the scheduled refresh did not run"
    assert hass.states.get("binary_sensor.aaa1_battery_present").state == STATE_ON
    assert hass.states.get("sensor.aaa1_voltage").state == "1210"
    assert hass.states.get("sensor.aaa1_current").state == "300"


def _advance_one_poll(hass: HomeAssistant) -> None:
    """Fire the coordinator's next scheduled refresh (it is a loop.call_at handle)."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=UPDATE_INTERVAL_SECONDS + 1))


def _with_aaa1(record: bytes) -> str:
    return b"".join([bay(3), bay(4, soc=40, ca=50), record, bay(2)]).hex()


async def test_station_going_dark_makes_entities_unavailable(
        hass: HomeAssistant, fake_station) -> None:
    await _setup(hass)
    fake_station.fail = OSError("connection reset")
    _advance_one_poll(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.aa1_voltage").state == STATE_UNAVAILABLE
    assert hass.states.get("switch.ostation_2_pro_charging").state == STATE_UNAVAILABLE


async def test_unload_closes_the_socket(hass: HomeAssistant, fake_station) -> None:
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(d.closed for d in fake_station.instances)
    assert hass.states.get("sensor.aa1_voltage") is None or \
        hass.states.get("sensor.aa1_voltage").state == STATE_UNAVAILABLE


async def test_heartbeat_runs_on_the_timer_and_stops_with_the_entry(
        hass: HomeAssistant, fake_station) -> None:
    entry = await _setup(hass)
    assert fake_station.heartbeats == 0
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=HEARTBEAT_INTERVAL + 1))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_station.heartbeats == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2 * HEARTBEAT_INTERVAL + 2))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_station.heartbeats == 1  # unsubscribed: nothing keeps poking a closed socket
