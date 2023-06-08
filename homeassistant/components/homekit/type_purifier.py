import logging

from pyhap.const import CATEGORY_AIR_PURIFIER

from homeassistant.components.fan import ATTR_PERCENTAGE, ATTR_PERCENTAGE_STEP, ATTR_PRESET_MODE, ATTR_PRESET_MODES, DOMAIN, SERVICE_SET_PERCENTAGE, SERVICE_SET_PRESET_MODE
from homeassistant.components.number.const import ATTR_MAX, ATTR_MIN
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_OFF, STATE_ON
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
    PROP_MIN_STEP,
    SERV_AIR_PURIFIER,
    SERV_AIR_QUALITY_SENSOR,
    SERV_STATELESS_PROGRAMMABLE_SWITCH,
    SERV_SWITCH,
)
from .util import coerce_int, convert_to_float, density_to_air_quality2, temperature_to_homekit
from homeassistant.core import callback


_LOGGER = logging.getLogger(__name__)

STATE_TARGET_MANUAL = 0
STATE_TARGET_AUTOMATIC = 1

STATE_CURRENT_OFF = 0
STATE_CURRENT_INACTIVE = 1
STATE_CURRENT_ACTIVE = 2

@TYPES.register("AirPurifier")
class AirPurifier(HomeAccessory):
    """Generate a AirPurifier accessory."""

    service_type = SERV_AIR_PURIFIER

    def __init__(self, *args):
        super().__init__(*args, category=CATEGORY_AIR_PURIFIER)

        state = self.hass.states.get(self.entity_id)
        percentage_step = state.attributes.get(ATTR_PERCENTAGE_STEP, 1)

        additional_chars = [CHAR_ACTIVE, CHAR_CURRENT_PURIFIER_STATE, CHAR_TARGET_PURIFIER_STATE, CHAR_ROTATION_SPEED]

        self.physical_controls = self.config.get(CONF_PURIFIER_LOCK_PHYSICAL_CONTROLS)
        self.filter_life_level = self.config.get(CONF_PURIFIER_FILTER_LIFE_LEVEL)
        self.motor_speed = self.config.get(CONF_PURIFIER_MOTOR_SPEED)

        if self.physical_controls:
            additional_chars.append(CHAR_LOCK_PHYSICAL_CONTROLS)

        if self.filter_life_level:
            additional_chars.append(CHAR_FILTER_LIFE_LEVEL)

        serv_fan = self.add_preload_service(SERV_AIR_PURIFIER, additional_chars)
        self.set_primary_service(serv_fan)
        self.char_active = serv_fan.configure_char(CHAR_ACTIVE, value=0)
        self.char_speed = serv_fan.configure_char(
                CHAR_ROTATION_SPEED,
                value=100,
                properties={PROP_MIN_STEP: percentage_step},
            )

        self.char_current_state = serv_fan.configure_char(CHAR_CURRENT_PURIFIER_STATE, value=0)
        self.char_target_state = serv_fan.configure_char(CHAR_TARGET_PURIFIER_STATE, value=0)
        if self.physical_controls:
            self.char_lock = serv_fan.configure_char(CHAR_LOCK_PHYSICAL_CONTROLS,
                value=0
            )
            self.async_update_physical_controls(self.hass.states.get(self.physical_controls))
        if self.filter_life_level:
            self.char_filter_life_level = serv_fan.configure_char(CHAR_FILTER_LIFE_LEVEL,
                value=0
            )
            self.async_update_filter_life_level(self.hass.states.get(self.filter_life_level))

        self.async_update_state(state)
        serv_fan.setter_callback = self._set_chars

    async def run(self):
        """Handle accessory driver started event.

        Run inside the Home Assistant event loop.
        """
        def subscribe_if_present(entity_id, callback):
            if entity_id:
                self._subscriptions.append(
                    async_track_state_change_event(
                        self.hass,
                        [entity_id],
                        lambda e: callback(e.data.get('new_state')),
                    )
                )

        subscribe_if_present(self.physical_controls, self.async_update_physical_controls)
        subscribe_if_present(self.filter_life_level, self.async_update_filter_life_level)
        subscribe_if_present(self.motor_speed, self.async_update_linked)

        await super().run()

    @callback
    def async_update_linked(self, *args):
        self.async_update_state(self.hass.states.get(self.entity_id))

    def async_update_physical_controls(self, new_state):
        _LOGGER.debug("AirPurifier async_update_physical_controls: %s", new_state)
        self.char_lock.set_value(new_state.state == STATE_ON)

    def async_update_filter_life_level(self, new_state):
        _LOGGER.debug("AirPurifier async_update_filter_life_level: %s", new_state)
        if level := convert_to_float(new_state.state):
            self.char_filter_life_level.set_value(level)

    @callback
    def async_update_state(self, new_state):
        """Update accessory after state change."""

        _LOGGER.debug("AirPurifier async_update_state: %s", new_state)

        state = new_state.state
        attributes = new_state.attributes

        if state in (STATE_ON, STATE_OFF):
            self._state = 1 if state == STATE_ON else 0
            _LOGGER.debug("AirPurifier current_state, char_active: %s", self._state)
            self.char_active.set_value(self._state)

        if mode := attributes.get(ATTR_PRESET_MODE):
            target_state = STATE_TARGET_MANUAL if mode == "Fan" else STATE_TARGET_AUTOMATIC
            _LOGGER.debug("AirPurifier current_state, percentage: %s", target_state)
            self.char_target_state.set_value(target_state)
        
        # Handle Speed
        if self.char_speed is not None and state != STATE_OFF:
            # We do not change the homekit speed when turning off
            # as it will clear the restore state
            percentage = attributes.get(ATTR_PERCENTAGE)
            # If the homeassistant component reports its speed as the first entry
            # in its speed list but is not off, the hk_speed_value is 0. But 0
            # is a special value in homekit. When you turn on a homekit accessory
            # it will try to restore the last rotation speed state which will be
            # the last value saved by char_speed.set_value. But if it is set to
            # 0, HomeKit will update the rotation speed to 100 as it thinks 0 is
            # off.
            #
            # Therefore, if the hk_speed_value is 0 and the device is still on,
            # the rotation speed is mapped to 1 otherwise the update is ignored
            # in order to avoid this incorrect behavior.
            if percentage == 0 and state == STATE_ON:
                percentage = max(1, self.char_speed.properties[PROP_MIN_STEP])
            if percentage is None and state == STATE_OFF:
                percentage = 0
            _LOGGER.debug("AirPurifier async_update_state, percentage: %s", percentage)
            if percentage is not None:
                self.char_speed.set_value(percentage)

        if self.motor_speed:
            rpm = coerce_int(self.hass.states.get(self.motor_speed).state)

            _LOGGER.debug("AirPurifier async_update_state, motor, rpm, state: %s, %s", rpm, state)

            if rpm == 0:
                if state == STATE_ON:
                    current_state = STATE_CURRENT_INACTIVE
                else:
                    current_state = STATE_CURRENT_OFF
            else:
                if state == STATE_ON:
                    current_state = STATE_CURRENT_ACTIVE
                else:
                    current_state = STATE_CURRENT_INACTIVE
        else:
            if state == STATE_ON:
                current_state = STATE_CURRENT_ACTIVE
            else:
                current_state = STATE_CURRENT_OFF

        _LOGGER.debug("AirPurifier async_update_state, current_state: %s", current_state)
        
        # self.char_active.set_value(current_state == STATE_CURRENT_ACTIVE)
        self.char_current_state.set_value(current_state)

    def _set_chars(self, char_values):
        _LOGGER.debug("AirPurifier _set_chars: %s", char_values)

        if CHAR_ACTIVE in char_values:
            if char_values[CHAR_ACTIVE]:
                # If the device supports set speed we
                # do not want to turn on as it will take
                # the fan to 100% than to the desired speed.
                #
                # Setting the speed will take care of turning
                # on the fan if FanEntityFeature.SET_SPEED is set.
                if not self.char_speed or CHAR_ROTATION_SPEED not in char_values:
                    self.set_state(1)
            else:
                # Its off, nothing more to do as setting the
                # other chars will likely turn it back on which
                # is what we want to avoid
                self.set_state(0)
                return

        if CHAR_TARGET_PURIFIER_STATE in char_values:
            if char_values[CHAR_TARGET_PURIFIER_STATE] == STATE_TARGET_AUTOMATIC:
                self.set_preset_mode(True, 'Auto')
            else:
                self.set_preset_mode(False, None)

        # We always do this LAST to ensure they
        # get the speed they asked for
        if CHAR_ROTATION_SPEED in char_values:
            self.set_percentage(char_values[CHAR_ROTATION_SPEED])

        if CHAR_LOCK_PHYSICAL_CONTROLS in char_values:
            self.async_call_service(
                SWITCH_DOMAIN,
                SERVICE_TURN_ON if char_values[CHAR_LOCK_PHYSICAL_CONTROLS] else SERVICE_TURN_OFF,
                {ATTR_ENTITY_ID: self.physical_controls}
            )
    
    def set_state(self, value):
        """Set state if call came from HomeKit."""
        _LOGGER.debug("%s: Set state to %d", self.entity_id, value)
        service = SERVICE_TURN_ON if value == 1 else SERVICE_TURN_OFF
        params = {ATTR_ENTITY_ID: self.entity_id}
        self.async_call_service(DOMAIN, service, params)

    def set_preset_mode(self, value, preset_mode):
        """Set preset_mode if call came from HomeKit."""
        _LOGGER.debug(
            "%s: Set preset_mode %s to %d", self.entity_id, preset_mode, value
        )
        params = {ATTR_ENTITY_ID: self.entity_id}
        if value:
            params[ATTR_PRESET_MODE] = preset_mode
            self.async_call_service(DOMAIN, SERVICE_SET_PRESET_MODE, params)
        else:
            self.async_call_service(DOMAIN, SERVICE_TURN_ON, params)

    def set_percentage(self, value):
        """Set state if call came from HomeKit."""
        _LOGGER.debug("%s: Set speed to %d", self.entity_id, value)
        params = {ATTR_ENTITY_ID: self.entity_id, ATTR_PERCENTAGE: value}
        self.async_call_service(DOMAIN, SERVICE_SET_PERCENTAGE, params, value)