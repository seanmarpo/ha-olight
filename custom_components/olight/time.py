"""Time entities: the quiet-hours window (DP112) as a start and an end time."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OlightConfigEntry
from .const import DP_PAUSE_WINDOW
from .entity import OlightEntity
from .protocol import decode_pause_window, encode_pause_window


async def async_setup_entry(hass: HomeAssistant, entry: OlightConfigEntry,
                            add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    add([
        OlightPauseTime(c, entry, "pause_start", "Quiet hours start", 0),
        OlightPauseTime(c, entry, "pause_end", "Quiet hours end", 1),
    ])


class OlightPauseTime(OlightEntity, TimeEntity):
    """One end of the window. Both ends live in the same four-byte DP, so writing one re-sends
    the other unchanged."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, key, name, index: int) -> None:
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._index = index

    @property
    def _window(self) -> tuple[time, time] | None:
        return decode_pause_window(self._dp(DP_PAUSE_WINDOW))

    @property
    def native_value(self) -> time | None:
        window = self._window
        return window[self._index] if window else None

    async def async_set_value(self, value: time) -> None:
        start, end = self._window or (time(0, 0), time(0, 0))
        if self._index == 0:
            start = value
        else:
            end = value
        await self.coordinator.async_set_dp(DP_PAUSE_WINDOW, encode_pause_window(start, end))
