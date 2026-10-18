"""Read-only heating sensors for Eopt Home: zone temperatures/setpoints and the power meter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensio_lib import ClimateZone, Hub, PowerMeter


@dataclass(frozen=True, kw_only=True)
class ZoneSensorDescription(SensorEntityDescription):
    value: Callable[[ClimateZone], float | None]


@dataclass(frozen=True, kw_only=True)
class MeterSensorDescription(SensorEntityDescription):
    value: Callable[[PowerMeter], float | None]


ZONE_SENSORS = (
    ZoneSensorDescription(
        key="temperature",
        name="Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda z: z.measured_temperature,
    ),
    ZoneSensorDescription(
        key="setpoint",
        name="Settpunkt",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda z: z.setpoint,
    ),
)

METER_SENSORS = (
    MeterSensorDescription(
        key="power",
        name="Effekt",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value=lambda m: m.power_w,
    ),
    MeterSensorDescription(
        key="energy",
        name="Energi",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value=lambda m: m.energy_kwh,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only heating sensors."""
    hub: Hub = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        ZoneSensor(hub, entry, zone, desc) for zone in hub.get_climate_zones() for desc in ZONE_SENSORS
    ]
    meter = hub.get_power_meter()
    if meter is not None:
        entities += [MeterSensor(hub, entry, meter, desc) for desc in METER_SENSORS]
    async_add_entities(entities)


class _HubValueSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: Hub, entry: ConfigEntry, source, description) -> None:
        self._hub = hub
        self._source = source
        self.entity_description = description
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Eopt Home ({entry.data.get('project_name', 'Hub')})",
            "manufacturer": "Eopt Home",
            "model": "Sensio Controller",
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._source.add_listener(self._handle_update))
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
    def native_value(self) -> float | None:
        return self.entity_description.value(self._source)


class ZoneSensor(_HubValueSensor):
    """Temperature or setpoint for one heating zone."""

    def __init__(self, hub: Hub, entry: ConfigEntry, zone: ClimateZone, description: ZoneSensorDescription) -> None:
        super().__init__(hub, entry, zone, description)
        self._attr_unique_id = f"{DOMAIN}_{zone.unique_id}_{description.key}"
        self._attr_name = f"{zone.name} {description.name.lower()}"


class MeterSensor(_HubValueSensor):
    """House power meter value."""

    def __init__(self, hub: Hub, entry: ConfigEntry, meter: PowerMeter, description: MeterSensorDescription) -> None:
        super().__init__(hub, entry, meter, description)
        self._attr_unique_id = f"{DOMAIN}_{entry.unique_id}_meter_{description.key}"
        self._attr_name = f"Strømmåler {description.name.lower()}"
