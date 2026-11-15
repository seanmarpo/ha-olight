"""Number: how readily the station wakes when someone walks past."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OlightConfigEntry
from .const import DP_WAKE_SENSITIVITY, WAKE_SENSITIVITY_MAX, WAKE_SENSITIVITY_MIN
from .entity import OlightEntity


async def async_setup_entry(hass: HomeAssistant, entry: OlightConfigEntry,
                            add: AddConfigEntryEntitiesCallback) -> None:
    add([OlightWakeSensitivity(entry.runtime_data, entry)])


class OlightWakeSensitivity(OlightEntity, NumberEntity):
    _attr_name = "Wake sensitivity"
    _attr_native_min_value = WAKE_SENSITIVITY_MIN
    _attr_native_max_value = WAKE_SENSITIVITY_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "wake_sensitivity")

    @property
    def native_value(self) -> float | None:
        value = self._dp(DP_WAKE_SENSITIVITY)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_dp(DP_WAKE_SENSITIVITY, int(value))
