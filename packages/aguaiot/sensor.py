import re
import copy
import numbers
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.entity import DeviceInfo
from .const import SENSORS, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    agua = hass.data[DOMAIN][entry.entry_id]["agua"]

    sensors = []
    for device in agua.devices:
        hybrid = "power_wood_set" in device.registers

        for sensor in SENSORS:
            if (
                sensor.key in device.registers
                and (sensor.force_enabled or device.get_register_enabled(sensor.key))
                and (
                    (sensor.hybrid_only and hybrid)
                    or (sensor.hybrid_exclude and not hybrid)
                    or (not sensor.hybrid_only and not sensor.hybrid_exclude)
                )
            ):
                sensors.append(AguaIOTHeatingSensor(coordinator, device, sensor))

    async_add_entities(sensors, True)


class AguaIOTHeatingSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, device, description):
        """Initialize the thermostat."""
        CoordinatorEntity.__init__(self, coordinator)
        self._device = device
        self.entity_description = description

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self._device.id_device}_{self.entity_description.key}"

    @property
    def name(self):
        """Return the name of the device, if any."""
        return f"{self._device.name} {self.entity_description.name}"

    @property
    def device_info(self):
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.id_device)},
            name=self._device.name,
            manufacturer="Micronova",
            model=self._device.name_product,
        )

    @property
    def native_value(self):
        from homeassistant.const import STATE_UNAVAILABLE
        INVALID_SENSOR_VALUES = {
            "status_get": 32768,
            "alarms_get": 32768,
            "power_get": 32768,
            "temp_gas_flue_get": 32798,
            "temp_air_get": 16384,
            "temp_air2_get": 16384,
            "real_power_get": 8193,
        }
        """Return the state of the sensor."""
        raw_value = self._device.get_register_value(self.entity_description.key)
        if self.entity_description.key in INVALID_SENSOR_VALUES:
            if raw_value == INVALID_SENSOR_VALUES[self.entity_description.key]:
                return STATE_UNAVAILABLE
        if self.entity_description.raw_value:
            return self._device.get_register_value(self.entity_description.key)
        else:
            value = self._device.get_register_value_description(
                self.entity_description.key
            )
            # Do not return a description if the sensor expects a number
            if not self.entity_description.native_unit_of_measurement or isinstance(
                value, numbers.Number
            ):
                return value

    @property
    def extra_state_attributes(self):
        """Expose plain value as extra attribute when needed."""
        if (
            not self.entity_description.raw_value
            and self._device.get_register_value_options(self.entity_description.key)
        ):
            return {
                "raw_value": self._device.get_register_value(
                    self.entity_description.key
                ),
            }

    @property
    def options(self):
        if self.entity_description.device_class == SensorDeviceClass.ENUM:
            options = sorted(
                list(
                    set(
                        self._device.get_register_value_options(
                            self.entity_description.key
                        ).values()
                    )
                )
            )
            cur_value = self._device.get_register_value_description(
                self.entity_description.key
            )
            if cur_value not in options:
                options.append(cur_value)

            return options
