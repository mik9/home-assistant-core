import logging
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS
from homeassistant.helpers.event import async_track_state_change_event
from .accessories import TYPES, HomeAccessory
from pyhap.const import CATEGORY_SENSOR

from .const import (
    CHAR_AIR_PARTICULATE_DENSITY,
    CHAR_AIR_QUALITY,
    CHAR_PM10_DENSITY,
    CHAR_PM2_5_DENSITY,
    CONF_LINKED_DENSITY_SENSOR,
    SERV_AIR_QUALITY_SENSOR,
)
from .util import convert_to_float, density_to_air_quality2, temperature_to_homekit
from homeassistant.core import callback


_LOGGER = logging.getLogger(__name__)

@TYPES.register("AirQualitySensor")
class AirQualitySensor2(HomeAccessory):
    """Generate a AirQualitySensor accessory as air quality sensor."""

    def __init__(self, *args):
        """Initialize a AirQualitySensor accessory object."""
        super().__init__(*args, category=CATEGORY_SENSOR)

        self.linked_density_sensor = self.config.get(CONF_LINKED_DENSITY_SENSOR)
        state = self.hass.states.get(self.entity_id)

        self.char_map = {}
        
        chars = [self.get_char_name(self.entity_id)]
        chars.append(self.get_char_name(self.linked_density_sensor))
        
        serv_air_quality = self.add_preload_service(
            SERV_AIR_QUALITY_SENSOR, chars
        )

        for char in chars:
            self.char_map[char] = serv_air_quality.configure_char(char,
                value=0
            )

        self.char_map[CHAR_AIR_QUALITY] = serv_air_quality.configure_char(
            CHAR_AIR_QUALITY, value=0
        )

        # Set the state so it is in sync on initial
        # GET to avoid an event storm after homekit startup
        self.async_update_state(state)

    def get_char_name(self, entity_id):
        state = self.hass.states.get(entity_id)
        device_class = state.attributes.get(ATTR_DEVICE_CLASS)

        if device_class == SensorDeviceClass.PM25:
            return CHAR_PM2_5_DENSITY
        elif device_class == SensorDeviceClass.PM10:
            return CHAR_PM10_DENSITY

    async def run(self):
        """Handle accessory driver started event.

        Run inside the Home Assistant event loop.
        """
        if self.linked_density_sensor:
            self._subscriptions.append(
                async_track_state_change_event(
                    self.hass,
                    [self.linked_density_sensor],
                    self.async_update_state,
                )
            )

        await super().run()

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""

        pm25 = None
        pm10 = None

        def read_vals(state):
            nonlocal pm25, pm10
            device_class = state.attributes.get(ATTR_DEVICE_CLASS)
            if device_class == SensorDeviceClass.PM25:
                pm25 = convert_to_float(state.state)
            elif device_class == SensorDeviceClass.PM10:
                pm10 = convert_to_float(state.state)
        
        read_vals(state = self.hass.states.get(self.entity_id))
        if self.linked_density_sensor:
            read_vals(self.hass.states.get(self.linked_density_sensor))
        
        if pm25 and self.char_map[CHAR_PM2_5_DENSITY].value != pm25:
            self.char_map[CHAR_PM2_5_DENSITY].set_value(pm25)
            _LOGGER.debug("%s: Set pm25 density to %d", self.entity_id, pm25)
        if pm10 and self.char_map[CHAR_PM10_DENSITY].value != pm10:
            self.char_map[CHAR_PM10_DENSITY].set_value(pm10)
            _LOGGER.debug("%s: Set pm10 density to %d", self.entity_id, pm10)

        if pm25 or pm10:
            air_quality = density_to_air_quality2(pm25, pm10)
            self.char_map[CHAR_AIR_QUALITY].set_value(air_quality)
            _LOGGER.debug("%s: Set air_quality to %d", self.entity_id, air_quality)
