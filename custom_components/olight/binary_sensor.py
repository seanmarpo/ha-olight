"""Binary sensors: bin/compartment fill warnings and per-bay occupancy."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OlightConfigEntry
from .const import DP_AA_BIN_FULL, DP_AAA_BIN_FULL, DP_REJECT_BIN_FULL
from .entity import OlightEntity, OlightSlotEntity
from .protocol import SLOT_ORDER


async def async_setup_entry(hass: HomeAssistant, entry: OlightConfigEntry,
                            add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        OlightStationBinarySensor(c, entry, "reject_bin_full", "Rejected bin full",
                                  DP_REJECT_BIN_FULL, BinarySensorDeviceClass.PROBLEM),
        OlightStationBinarySensor(c, entry, "aa_bin_full", "AA compartment full",
                                  DP_AA_BIN_FULL),
        OlightStationBinarySensor(c, entry, "aaa_bin_full", "AAA compartment full",
                                  DP_AAA_BIN_FULL),
    ]
    for slot in SLOT_ORDER:
        entities += [
            OlightSlotBinarySensor(c, entry, slot, "occupied", "Battery present",
                                   lambda s: s.occupied,
                                   BinarySensorDeviceClass.PRESENCE),
            OlightSlotBinarySensor(c, entry, slot, "charging", "Charging",
                                   lambda s: s.charging,
                                   BinarySensorDeviceClass.BATTERY_CHARGING),
        ]
    add(entities)


class OlightStationBinarySensor(OlightEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, key, name, dp, dclass=None):
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._dp_id = dp
        self._attr_device_class = dclass
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        value = self._dp(self._dp_id)
        return bool(value) if value is not None else None


class OlightSlotBinarySensor(OlightSlotEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, slot, key, name, fn, dclass=None):
        super().__init__(coordinator, entry, slot, key)
        self._attr_name = name
        self._fn = fn
        self._attr_device_class = dclass

    @property
    def is_on(self) -> bool | None:
        state = self._state
        return self._fn(state) if state else None
