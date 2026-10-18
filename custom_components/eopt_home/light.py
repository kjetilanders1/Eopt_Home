"""Light platform for Eopt Home integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .sensio_lib import Hub, Light, LightState, SensioException

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Eopt Home lights from a config entry."""
    hub: Hub = hass.data[DOMAIN][entry.entry_id]
    lights = hub.get_lights()

    entities = [SensioLightEntity(light, hub, entry) for light in lights]
    async_add_entities(entities)
    _LOGGER.debug("Added %d Eopt Home light entities", len(entities))


class SensioLightEntity(LightEntity):
    """Representation of a Sensio/Eopt Home light.

    Lights with a state function in the project get their real state pushed
    from the controller (also when wall switches are used); the rest stay
    optimistic (assumed state).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, light: Light, hub: Hub, entry: ConfigEntry) -> None:
        """Initialize the light entity."""
        self._light = light
        self._hub = hub
        self._attr_unique_id = f"{DOMAIN}_{light.unique_id}"
        self._attr_name = light.name
        self._attr_assumed_state = not light.has_real_state
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Eopt Home ({entry.data.get('project_name', 'Hub')})",
            "manufacturer": "Eopt Home",
            "model": "Sensio Controller",
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to state and connection updates."""
        self.async_on_remove(self._light.add_listener(self._handle_update))
        self.async_on_remove(self._hub.add_availability_listener(self._handle_availability))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable only if the controller connection stays down past the grace period."""
        return self._hub.available

    @property
    def is_on(self) -> bool | None:
        """Return True if the light is on, None while unknown."""
        if self._light.state == LightState.UNKNOWN:
            return None
        return self._light.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        try:
            await self._light.turn_on()
        except SensioException as err:
            raise HomeAssistantError(f"Could not turn on {self.name}: {err}") from err
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        try:
            await self._light.turn_off()
        except SensioException as err:
            raise HomeAssistantError(f"Could not turn off {self.name}: {err}") from err
        self.async_write_ha_state()
