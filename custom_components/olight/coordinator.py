"""Polls one Ostation over the LAN and decodes its datapoints for the entities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, DP_TELEMETRY, UPDATE_INTERVAL_SECONDS
from .protocol import SlotState, decode_slots
from .tuya_client import OstationClient, OstationError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class OstationData:
    """One poll's worth of state."""

    dps: dict
    slots: dict[int, SlotState]


class OstationCoordinator(DataUpdateCoordinator[OstationData]):
    """Keeps the single LAN connection warm and hands decoded state to the entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: OstationClient) -> None:
        # Pass the entry explicitly: the ContextVar fallback is deprecated in Home Assistant.
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}",
                         update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS))
        self.client = client
        # Registry id of the station device, used by the bays as their via_device_id. Populated in
        # async_setup_entry once the station device is registered, before the platforms load.
        self.station_device_id: str | None = None

    async def _async_update_data(self) -> OstationData:
        try:
            dps = await self.hass.async_add_executor_job(self.client.status)
        except OstationError as err:
            raise UpdateFailed(f"Ostation unreachable: {err}") from err
        # A poll that carries no telemetry still carries the booleans; decode what's there rather
        # than failing the whole update and blanking every entity.
        return OstationData(dps=dps, slots=decode_slots(dps.get(str(DP_TELEMETRY))))

    async def async_heartbeat(self, _now: datetime | None = None) -> None:
        """Keep-alive between polls; driven by a Home Assistant time interval, not a thread."""
        await self.hass.async_add_executor_job(self.client.heartbeat)

    async def async_set_dp(self, dp: int, value) -> None:
        """Write a datapoint, then refresh so the UI reflects what the station actually did.

        Errors surface to the user: silently swallowing them makes a toggle flip in the dashboard
        while the station never moved.
        """
        try:
            await self.hass.async_add_executor_job(self.client.set_dp, dp, value)
        except OstationError as err:
            raise HomeAssistantError(f"Ostation refused the command: {err}") from err
        finally:
            await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.hass.async_add_executor_job(self.client.close)
