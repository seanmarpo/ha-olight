"""Config flow: validation, connection check, duplicates, reconfigure."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.olight.const import CONF_DEVICE_ID, CONF_LOCAL_KEY, DOMAIN

from .conftest import DEVICE_ID, HOST, LOCAL_KEY

USER_INPUT = {CONF_HOST: HOST, CONF_DEVICE_ID: DEVICE_ID, CONF_LOCAL_KEY: LOCAL_KEY,
              CONF_NAME: "Garage charger"}


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    return result


async def test_user_flow_creates_entry(hass: HomeAssistant, fake_station) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garage charger"
    assert result["data"][CONF_DEVICE_ID] == DEVICE_ID
    assert result["data"][CONF_LOCAL_KEY] == LOCAL_KEY
    assert result["data"][CONF_HOST] == HOST
    # The validation connection must be closed before the coordinator opens the real one:
    # the station allows a single client, so a leaked probe socket would block it.
    assert fake_station.instances[0].closed is True


@pytest.mark.parametrize("field,value,error", [
    (CONF_DEVICE_ID, "tooshort", "invalid_device_id"),
    (CONF_LOCAL_KEY, "short", "invalid_local_key"),
])
async def test_field_length_is_checked_before_connecting(
        hass: HomeAssistant, fake_station, field, value, error) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, field: value})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}
    assert fake_station.instances == []  # no connection attempted with bad input


async def test_cannot_connect_keeps_the_form(hass: HomeAssistant, fake_station) -> None:
    fake_station.fail = {"Error": "Network Error: Unable to Connect", "Err": "901"}
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_same_station_twice_aborts_and_refreshes_host(
        hass: HomeAssistant, fake_station) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=DEVICE_ID, data={**USER_INPUT}).add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "192.168.1.99"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data[CONF_HOST] == "192.168.1.99"


async def test_reconfigure_updates_host_and_key_in_place(
        hass: HomeAssistant, fake_station) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DEVICE_ID, data={**USER_INPUT})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "10.0.0.7", CONF_LOCAL_KEY: "fedcba9876543210"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "10.0.0.7"
    assert entry.data[CONF_LOCAL_KEY] == "fedcba9876543210"
    assert entry.data[CONF_DEVICE_ID] == DEVICE_ID  # never changes: it is the identity
    # The reload is scheduled in the background. Wait for it, or it can run during teardown
    # after HA has stopped and leave the heartbeat timer behind.
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_reconfigure_rejects_a_key_that_does_not_work(
        hass: HomeAssistant, fake_station) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DEVICE_ID, data={**USER_INPUT})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    fake_station.fail = {"Error": "Unexpected Payload from Device", "Err": "904"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_LOCAL_KEY: "fedcba9876543210"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_LOCAL_KEY] == LOCAL_KEY  # untouched
