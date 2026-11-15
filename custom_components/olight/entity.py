"""Base entities: the station itself, and one sub-device per charging bay."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_MODEL, DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import OstationCoordinator
from .protocol import SLOT_LABELS, SLOT_SIZE, SlotState


def station_device_info(entry: ConfigEntry) -> DeviceInfo:
    """The station as a single Home Assistant device.

    Identifiers are keyed on the Tuya device id, which survives the station changing IP — keying on
    the host would orphan the device and its history the moment DHCP moved it.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_DEVICE_ID])},
        name=entry.title,
        manufacturer=MANUFACTURER,
        model=entry.data.get(CONF_MODEL, DEFAULT_MODEL),
        serial_number=entry.data[CONF_DEVICE_ID],
    )


def slot_device_info(entry: ConfigEntry, slot: int, station_device_id: str) -> DeviceInfo:
    """Each bay as its own device under the station.

    Four bays × six readings is twenty-four entities; flat under one device that is an unreadable
    wall. Nesting them means the user opens 'AA1' and sees only that bay.

    The station is linked by its device-registry id (via_device_id); the DeviceInfo(via_device=...)
    identifier tuple it replaces is deprecated and removed in HA 2027.8.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.data[CONF_DEVICE_ID]}_slot{slot}")},
        name=SLOT_LABELS.get(slot, f"Slot {slot}"),
        manufacturer=MANUFACTURER,
        model=f"{SLOT_SIZE.get(slot, '')} charging bay".strip(),
        via_device_id=station_device_id,
    )


class OlightEntity(CoordinatorEntity[OstationCoordinator]):
    """Anything attached to the station as a whole."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OstationCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_{key}"
        self._attr_device_info = station_device_info(entry)

    @property
    def _dps(self) -> dict:
        return self.coordinator.data.dps if self.coordinator.data else {}

    def _dp(self, dp: int):
        return self._dps.get(str(dp))


class OlightSlotEntity(CoordinatorEntity[OstationCoordinator]):
    """Anything reporting on one charging bay."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OstationCoordinator, entry: ConfigEntry,
                 slot: int, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._slot = slot
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_ID]}_slot{slot}_{key}"
        self._attr_device_info = slot_device_info(entry, slot, coordinator.station_device_id)

    @property
    def _state(self) -> SlotState | None:
        data = self.coordinator.data
        return data.slots.get(self._slot) if data else None

    @property
    def available(self) -> bool:
        # A bay missing from the telemetry means we couldn't decode it, not that it's empty — an
        # empty bay still reports a record. Showing the last known value would be a lie.
        return self.coordinator.last_update_success and self._state is not None
