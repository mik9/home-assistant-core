"""Class to hold all sensor accessories."""
from __future__ import annotations

from collections.abc import Callable
import logging
from typing import NamedTuple

from pyhap.const import CATEGORY_SENSOR

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    DEVICE_CLASS_CO,
    DEVICE_CLASS_CO2,
    STATE_HOME,
    STATE_ON,
    TEMP_CELSIUS,
)
from homeassistant.core import callback

from .accessories import TYPES, HomeAccessory
from .const import (
    CHAR_AIR_PARTICULATE_DENSITY,
    CHAR_AIR_QUALITY,
    CHAR_CARBON_DIOXIDE_DETECTED,
    CHAR_CARBON_DIOXIDE_LEVEL,
    CHAR_CARBON_DIOXIDE_PEAK_LEVEL,
    CHAR_CARBON_MONOXIDE_DETECTED,
    CHAR_CARBON_MONOXIDE_LEVEL,
    CHAR_CARBON_MONOXIDE_PEAK_LEVEL,
    CHAR_CONTACT_SENSOR_STATE,
    CHAR_CURRENT_AMBIENT_LIGHT_LEVEL,
    CHAR_CURRENT_HUMIDITY,
    CHAR_CURRENT_TEMPERATURE,
    CHAR_LEAK_DETECTED,
    CHAR_MOTION_DETECTED,
    CHAR_OCCUPANCY_DETECTED,
    CHAR_SMOKE_DETECTED,
    PROP_CELSIUS,
    SERV_AIR_QUALITY_SENSOR,
    SERV_CARBON_DIOXIDE_SENSOR,
    SERV_CARBON_MONOXIDE_SENSOR,
    SERV_CONTACT_SENSOR,
    SERV_HUMIDITY_SENSOR,
    SERV_LEAK_SENSOR,
    SERV_LIGHT_SENSOR,
    SERV_MOTION_SENSOR,
    SERV_OCCUPANCY_SENSOR,
    SERV_SMOKE_SENSOR,
    SERV_TEMPERATURE_SENSOR,
    THRESHOLD_CO,
    THRESHOLD_CO2,
)
from .util import convert_to_float, density_to_air_quality, temperature_to_homekit

_LOGGER = logging.getLogger(__name__)


class SI(NamedTuple):
    """Service info."""

    service: str
    char: str
    format: Callable[[bool], int | bool]


BINARY_SENSOR_SERVICE_MAP: dict[str, SI] = {
    DEVICE_CLASS_CO: SI(
        SERV_CARBON_MONOXIDE_SENSOR, CHAR_CARBON_MONOXIDE_DETECTED, int
    ),
    DEVICE_CLASS_CO2: SI(SERV_CARBON_DIOXIDE_SENSOR, CHAR_CARBON_DIOXIDE_DETECTED, int),
    BinarySensorDeviceClass.DOOR: SI(
        SERV_CONTACT_SENSOR, CHAR_CONTACT_SENSOR_STATE, int
    ),
    BinarySensorDeviceClass.GARAGE_DOOR: SI(
        SERV_CONTACT_SENSOR, CHAR_CONTACT_SENSOR_STATE, int
    ),
    BinarySensorDeviceClass.GAS: SI(
        SERV_CARBON_MONOXIDE_SENSOR, CHAR_CARBON_MONOXIDE_DETECTED, int
    ),
    BinarySensorDeviceClass.MOISTURE: SI(SERV_LEAK_SENSOR, CHAR_LEAK_DETECTED, int),
    BinarySensorDeviceClass.MOTION: SI(SERV_MOTION_SENSOR, CHAR_MOTION_DETECTED, bool),
    BinarySensorDeviceClass.OCCUPANCY: SI(
        SERV_OCCUPANCY_SENSOR, CHAR_OCCUPANCY_DETECTED, int
    ),
    BinarySensorDeviceClass.OPENING: SI(
        SERV_CONTACT_SENSOR, CHAR_CONTACT_SENSOR_STATE, int
    ),
    BinarySensorDeviceClass.SMOKE: SI(SERV_SMOKE_SENSOR, CHAR_SMOKE_DETECTED, int),
    BinarySensorDeviceClass.WINDOW: SI(
        SERV_CONTACT_SENSOR, CHAR_CONTACT_SENSOR_STATE, int
    ),
}


@TYPES.register("TemperatureSensor")
class TemperatureSensor(HomeAccessory):
    """Generate a TemperatureSensor accessory for a temperature sensor.

    Sensor entity must return temperature in °C, °F.
    """

    def __init__(self, *args):
        """Initialize a TemperatureSensor accessory object."""
        super().__init__(*args, category=CATEGORY_SENSOR)
        state = self.hass.states.get(self.entity_id)
        serv_temp = self.add_preload_service(SERV_TEMPERATURE_SENSOR)
        self.char_temp = serv_temp.configure_char(
            CHAR_CURRENT_TEMPERATURE, value=0, properties=PROP_CELSIUS
        )
        # Set the state so it is in sync on initial
        # GET to avoid an event storm after homekit startup
        self.async_update_state(state)

    @callback
    def async_update_state(self, new_state):
        """Update temperature after state changed."""
        unit = new_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, TEMP_CELSIUS)
        if (temperature := convert_to_float(new_state.state)) is not None:
            temperature = temperature_to_homekit(temperature, unit)
            self.char_temp.set_value(temperature)
            _LOGGER.debug(
                "%s: Current temperature set to %.1f°C", self.entity_id, temperature
            )


@TYPES.register("HumiditySensor")
class HumiditySensor(HomeAccessory):
    """Generate a HumiditySensor accessory as humidity sensor."""

    def __init__(self, *args):
        """Initialize a HumiditySensor accessory object."""
        super().__init__(*args, category=CATEGORY_SENSOR)
        state = self.hass.states.get(self.entity_id)
        serv_humidity = self.add_preload_service(SERV_HUMIDITY_SENSOR)
        self.char_humidity = serv_humidity.configure_char(
            CHAR_CURRENT_HUMIDITY, value=0
        )
        # Set the state so it is in sync on initial
        # GET to avoid an event storm after homekit startup
        self.async_update_state(state)

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""
        if (humidity := convert_to_float(new_state.state)) is not None:
            self.char_humidity.set_value(humidity)
            _LOGGER.debug("%s: Percent set to %d%%", self.entity_id, humidity)

@TYPES.register("CarbonMonoxideSensor")
class CarbonMonoxideSensor(HomeAccessory):
    """Generate a CarbonMonoxidSensor accessory as CO sensor."""

    def __init__(self, *args):
        """Initialize a CarbonMonoxideSensor accessory object."""
        super().__init__(*args, category=CATEGORY_SENSOR)
        state = self.hass.states.get(self.entity_id)
        serv_co = self.add_preload_service(
            SERV_CARBON_MONOXIDE_SENSOR,
            [CHAR_CARBON_MONOXIDE_LEVEL, CHAR_CARBON_MONOXIDE_PEAK_LEVEL],
        )
        self.char_level = serv_co.configure_char(CHAR_CARBON_MONOXIDE_LEVEL, value=0)
        self.char_peak = serv_co.configure_char(
            CHAR_CARBON_MONOXIDE_PEAK_LEVEL, value=0
        )
        self.char_detected = serv_co.configure_char(
            CHAR_CARBON_MONOXIDE_DETECTED, value=0
        )
        # Set the state so it is in sync on initial
        # GET to avoid an event storm after homekit startup
        self.async_update_state(state)

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""
        if (value := convert_to_float(new_state.state)) is not None:
            self.char_level.set_value(value)
            if value > self.char_peak.value:
                self.char_peak.set_value(value)
            co_detected = value > THRESHOLD_CO
            self.char_detected.set_value(co_detected)
            _LOGGER.debug("%s: Set to %d", self.entity_id, value)


@TYPES.register("CarbonDioxideSensor")
class CarbonDioxideSensor(HomeAccessory):
    """Generate a CarbonDioxideSensor accessory as CO2 sensor."""

    def __init__(self, *args):
        """Initialize a CarbonDioxideSensor accessory object."""
        super().__init__(*args, category=CATEGORY_SENSOR)
        state = self.hass.states.get(self.entity_id)
        serv_co2 = self.add_preload_service(
            SERV_CARBON_DIOXIDE_SENSOR,
            [CHAR_CARBON_DIOXIDE_LEVEL, CHAR_CARBON_DIOXIDE_PEAK_LEVEL],
        )
        self.char_level = serv_co2.configure_char(CHAR_CARBON_DIOXIDE_LEVEL, value=0)
        self.char_peak = serv_co2.configure_char(
            CHAR_CARBON_DIOXIDE_PEAK_LEVEL, value=0
        )
        self.char_detected = serv_co2.configure_char(
            CHAR_CARBON_DIOXIDE_DETECTED, value=0
        )
        # Set the state so it is in sync on initial
        # GET to avoid an event storm after homekit startup
        self.async_update_state(state)

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""
        if (value := convert_to_float(new_state.state)) is not None:
            self.char_level.set_value(value)
            if value > self.char_peak.value:
                self.char_peak.set_value(value)
            co2_detected = value > THRESHOLD_CO2
            self.char_detected.set_value(co2_detected)
            _LOGGER.debug("%s: Set to %d", self.entity_id, value)


@TYPES.register("LightSensor")
class LightSensor(HomeAccessory):
    """Generate a LightSensor accessory as light sensor."""

    def __init__(self, *args):
        """Initialize a LightSensor accessory object."""
        super().__init__(*args, category=CATEGORY_SENSOR)
        state = self.hass.states.get(self.entity_id)
        serv_light = self.add_preload_service(SERV_LIGHT_SENSOR)
        self.char_light = serv_light.configure_char(
            CHAR_CURRENT_AMBIENT_LIGHT_LEVEL, value=0
        )
        # Set the state so it is in sync on initial
        # GET to avoid an event storm after homekit startup
        self.async_update_state(state)

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""
        if (luminance := convert_to_float(new_state.state)) is not None:
            self.char_light.set_value(luminance)
            _LOGGER.debug("%s: Set to %d", self.entity_id, luminance)


@TYPES.register("BinarySensor")
class BinarySensor(HomeAccessory):
    """Generate a BinarySensor accessory as binary sensor."""

    def __init__(self, *args):
        """Initialize a BinarySensor accessory object."""
        super().__init__(*args, category=CATEGORY_SENSOR)
        state = self.hass.states.get(self.entity_id)
        device_class = state.attributes.get(ATTR_DEVICE_CLASS)
        service_char = (
            BINARY_SENSOR_SERVICE_MAP[device_class]
            if device_class in BINARY_SENSOR_SERVICE_MAP
            else BINARY_SENSOR_SERVICE_MAP[BinarySensorDeviceClass.OCCUPANCY]
        )

        self.format = service_char.format
        service = self.add_preload_service(service_char.service)
        initial_value = False if self.format is bool else 0
        self.char_detected = service.configure_char(
            service_char.char, value=initial_value
        )
        # Set the state so it is in sync on initial
        # GET to avoid an event storm after homekit startup
        self.async_update_state(state)

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""
        state = new_state.state
        detected = self.format(state in (STATE_ON, STATE_HOME))
        self.char_detected.set_value(detected)
        _LOGGER.debug("%s: Set to %d", self.entity_id, detected)
