"""Read-only heating binary sensors for Eopt Home: heat demand and heat relay per zone."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensio_lib import ClimateZone, Hub

KINDS = {
    # key: (name suffix, attribute on ClimateZone)
    "heat_demand": ("varmebehov", "heat_demand"),
    "relay": ("varmerelé", "relay_on"),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only heat demand / relay sensors."""
    hub: Hub = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for zone in hub.get_climate_zones():
        entities.append(ZoneBinarySensor(hub, entry, zone, "heat_demand"))
        if zone.relay_address is not None:
            entities.append(ZoneBinarySensor(hub, entry, zone, "relay"))
    async_add_entities(entities)


class ZoneBinarySensor(BinarySensorEntity):
    """Heat demand or relay state for one heating zone."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, hub: Hub, entry: ConfigEntry, zone: ClimateZone, key: str) -> None:
        self._hub = hub
        self._zone = zone
        suffix, self._attr = KINDS[key]
        self._attr_unique_id = f"{DOMAIN}_{zone.unique_id}_{key}"
        self._attr_name = f"{zone.name} {suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Eopt Home ({entry.data.get('project_name', 'Hub')})",
            "manufacturer": "Eopt Home",
            "model": "Sensio Controller",
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._zone.add_listener(self._handle_update))
        self.async_on_remove(self._hub.add_availability_listener(self._handle_availability))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._hub.available

    @property
    def is_on(self) -> bool | None:
        return getattr(self._zone, self._attr)
