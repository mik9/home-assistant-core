import logging
from homeassistant.components.fan import ATTR_PERCENTAGE, ATTR_PRESET_MODE, ATTR_PRESET_MODES, DOMAIN, SERVICE_SET_PERCENTAGE, SERVICE_SET_PRESET_MODE
from homeassistant.components.homekit.type_fans import BaseFan
from homeassistant.components.number.const import ATTR_MAX, ATTR_MIN
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_ON
from homeassistant.helpers.event import async_track_state_change_event
from .accessories import TYPES, HomeAccessory
from pyhap.const import CATEGORY_AIR_PURIFIER, CATEGORY_SENSOR

from .const import (
    CHAR_ACTIVE,
    CHAR_AIR_PARTICULATE_DENSITY,
    CHAR_AIR_QUALITY,
    CHAR_CURRENT_PURIFIER_STATE,
    CHAR_FILTER_LIFE_LEVEL,
    CHAR_LOCK_PHYSICAL_CONTROLS,
    CHAR_NAME,
    CHAR_ON,
    CHAR_PM10_DENSITY,
    CHAR_PM2_5_DENSITY,
    CHAR_ROTATION_SPEED,
    CHAR_TARGET_PURIFIER_STATE,
    CONF_LINKED_DENSITY_SENSOR,
    CONF_PURIFIER_FILTER_LIFE_LEVEL,
    CONF_PURIFIER_IGNORED_PRESETS,
    CONF_PURIFIER_LOCK_PHYSICAL_CONTROLS,
    CONF_PURIFIER_MOTOR_SPEED,
    MAX_NAME_LENGTH,
    SERV_AIR_PURIFIER,
    SERV_AIR_QUALITY_SENSOR,
    SERV_STATELESS_PROGRAMMABLE_SWITCH,
    SERV_SWITCH,
)
from .util import convert_to_float, density_to_air_quality2, temperature_to_homekit
from homeassistant.core import callback


_LOGGER = logging.getLogger(__name__)

STATE_TARGET_MANUAL = 0
STATE_TARGET_AUTOMATIC = 1

STATE_CURRENT_OFF = 0
STATE_CURRENT_INACTIVE = 1
STATE_CURRENT_ACTIVE = 2

@TYPES.register("AirPurifier")
class AirPurifier(BaseFan):
    """Generate a AirPurifier accessory."""

    service_type = SERV_AIR_PURIFIER

    def _on_add_service(self, chars):
        additional_chars = [CHAR_CURRENT_PURIFIER_STATE, CHAR_TARGET_PURIFIER_STATE]

        self.physical_controls = self.config.get(CONF_PURIFIER_LOCK_PHYSICAL_CONTROLS)
        self.filter_life_level = self.config.get(CONF_PURIFIER_FILTER_LIFE_LEVEL)
        self.motor_speed = self.config.get(CONF_PURIFIER_MOTOR_SPEED)

        if self.physical_controls:
            additional_chars.append(CHAR_LOCK_PHYSICAL_CONTROLS)

        if self.filter_life_level:
            additional_chars.append(CHAR_FILTER_LIFE_LEVEL)

        serv_fan = super()._on_add_service(chars + additional_chars)

        self.char_current_state = serv_fan.configure_char(CHAR_CURRENT_PURIFIER_STATE, value=0)
        self.char_target_state = serv_fan.configure_char(CHAR_TARGET_PURIFIER_STATE, value=0)
        if self.physical_controls:
            self.char_lock = serv_fan.configure_char(CHAR_LOCK_PHYSICAL_CONTROLS,
                value=0
            )
        if self.filter_life_level:
            self.char_filter_life_level = serv_fan.configure_char(CHAR_FILTER_LIFE_LEVEL,
                value=0
            )

        return serv_fan

    async def run(self):
        """Handle accessory driver started event.

        Run inside the Home Assistant event loop.
        """
        def subscribe_if_present(entity_id):
            if entity_id:
                self._subscriptions.append(
                    async_track_state_change_event(
                        self.hass,
                        [entity_id],
                        self.async_update_linked,
                    )
                )

        subscribe_if_present(self.physical_controls)
        subscribe_if_present(self.filter_life_level)
        subscribe_if_present(self.motor_speed)

        await super().run()

    @callback
    def async_update_linked(self, *args):
        self.async_update_state(self.hass.states.get(self.entity_id))

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""

        super().async_update_state(new_state)

        if mode := new_state.attributes.get(ATTR_PRESET_MODE):
            self.char_target_state.set_value(
                STATE_TARGET_MANUAL if mode == "Fan" else STATE_TARGET_AUTOMATIC
            )

        if self.physical_controls:
            physical_controls_lock_state = self.hass.states.get(self.physical_controls)
            self.char_lock.set_value(physical_controls_lock_state.state == STATE_ON)

        if self.filter_life_level:
            life_level_state = self.hass.states.get(self.filter_life_level)
            if level := convert_to_float(life_level_state.state):
                self.char_filter_life_level.set_value(level)

        if self.motor_speed:
            motor_state = self.hass.states.get(self.motor_speed)
            rpm = convert_to_float(motor_state.state)

            if rpm == 0:
                if new_state.state == STATE_ON:
                    current_state = STATE_CURRENT_INACTIVE
                else:
                    current_state = STATE_CURRENT_OFF
            else:
                current_state = STATE_CURRENT_ACTIVE
        else:
            if new_state.state == STATE_ON:
                current_state = STATE_CURRENT_ACTIVE
            else:
                current_state = STATE_CURRENT_OFF
        
        
        self.char_current_state.set_value(current_state)

    def _set_chars(self, char_values):
        super()._set_chars(char_values)

        if CHAR_LOCK_PHYSICAL_CONTROLS in char_values:
            self.async_call_service(
                SWITCH_DOMAIN,
                SERVICE_TURN_ON if char_values[CHAR_LOCK_PHYSICAL_CONTROLS] else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self.physical_controls}
            )
