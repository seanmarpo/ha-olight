"""Switches: charging on/off and the quiet-hours pause."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OlightConfigEntry
from .const import DP_PAUSE_ENABLED, DP_POWER
from .entity import OlightEntity


async def async_setup_entry(hass: HomeAssistant, entry: OlightConfigEntry,
                            add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    add([
        OlightSwitch(c, entry, "power", "Charging", DP_POWER,
                     dclass=SwitchDeviceClass.SWITCH),
        OlightSwitch(c, entry, "pause_schedule", "Quiet hours", DP_PAUSE_ENABLED,
                     diag=True),
    ])


class OlightSwitch(OlightEntity, SwitchEntity):
    def __init__(self, coordinator, entry, key, name, dp, dclass=None, diag=False):
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._dp_id = dp
        self._attr_device_class = dclass
        if diag:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        value = self._dp(self._dp_id)
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_dp(self._dp_id, False)
