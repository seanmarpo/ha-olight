"""Sensors: per-bay cell telemetry, plus the station's counters."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OlightConfigEntry
from .const import DP_DIAGNOSTIC, DP_FULLY_CHARGED, DP_REJECTED
from .entity import OlightEntity, OlightSlotEntity
from .protocol import SLOT_ORDER, SlotState

CHEMISTRY_LABELS = {
    "detecting": "Detecting",
    "nimh": "Ni-MH",
    "liion": "Li-ion",
    "unknown": "Unknown",
}


async def async_setup_entry(hass: HomeAssistant, entry: OlightConfigEntry,
                            add: AddConfigEntryEntitiesCallback) -> None:
    c = entry.runtime_data
    entities: list[SensorEntity] = [
        OlightStationSensor(c, entry, "fully_charged", "Batteries charged",
                            DP_FULLY_CHARGED, sclass=SensorStateClass.TOTAL_INCREASING),
        OlightStationSensor(c, entry, "rejected", "Batteries rejected",
                            DP_REJECTED, sclass=SensorStateClass.TOTAL_INCREASING),
        OlightStationSensor(c, entry, "diagnostic", "Diagnostic code",
                            DP_DIAGNOSTIC, diag=True),
    ]
    # Every bay always reports, whether or not a cell is in it, so the entity set is static and
    # doesn't need to appear and disappear as the user swaps batteries.
    for slot in SLOT_ORDER:
        entities += [
            OlightSlotSensor(c, entry, slot, "soc", "Charge", lambda s: s.soc,
                             unit=PERCENTAGE, dclass=SensorDeviceClass.BATTERY,
                             sclass=SensorStateClass.MEASUREMENT),
            OlightSlotSensor(c, entry, slot, "voltage", "Voltage", lambda s: s.voltage,
                             unit=UnitOfElectricPotential.MILLIVOLT,
                             dclass=SensorDeviceClass.VOLTAGE,
                             sclass=SensorStateClass.MEASUREMENT),
            OlightSlotSensor(c, entry, slot, "current", "Current", lambda s: s.current,
                             unit=UnitOfElectricCurrent.MILLIAMPERE,
                             dclass=SensorDeviceClass.CURRENT,
                             sclass=SensorStateClass.MEASUREMENT),
            # Byte 12 of the record is unmapped upstream. The community first read it as a
            # temperature (~25 at rest) but it is reported near 100 during a fast charge and
            # tracks the *other* bay's activity, so it is exposed raw, without a unit, until
            # someone establishes what it is.
            OlightSlotSensor(c, entry, slot, "byte12", "Byte 12", lambda s: s.byte12,
                             sclass=SensorStateClass.MEASUREMENT, diag=True),
            OlightSlotSensor(c, entry, slot, "chemistry", "Chemistry",
                             lambda s: CHEMISTRY_LABELS.get(s.chemistry, s.chemistry)),
            OlightSlotSensor(c, entry, slot, "duration", "Charging time",
                             lambda s: s.minutes if s.occupied else None,
                             unit=UnitOfTime.MINUTES,
                             dclass=SensorDeviceClass.DURATION,
                             sclass=SensorStateClass.MEASUREMENT),
        ]
    add(entities)


class OlightStationSensor(OlightEntity, SensorEntity):
    """A plain integer datapoint on the station."""

    def __init__(self, coordinator, entry, key, name, dp, sclass=None, diag=False):
        super().__init__(coordinator, entry, key)
        self._attr_name = name
        self._dp_id = dp
        self._attr_state_class = sclass
        if diag:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self._dp(self._dp_id)


class OlightSlotSensor(OlightSlotEntity, SensorEntity):
    """One reading from one charging bay."""

    def __init__(self, coordinator, entry, slot, key, name,
                 fn: Callable[[SlotState], object],
                 unit=None, dclass=None, sclass=None, diag=False):
        super().__init__(coordinator, entry, slot, key)
        self._attr_name = name
        self._fn = fn
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = dclass
        self._attr_state_class = sclass
        if diag:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        state = self._state
        return self._fn(state) if state else None
