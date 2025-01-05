from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import BINARY_SENSORS, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    agua = hass.data[DOMAIN][entry.entry_id]["agua"]

    sensors = []
    for device in agua.devices:
        hybrid = "power_wood_set" in device.registers

        for sensor in BINARY_SENSORS:
            if (
                sensor.key in device.registers
                and (sensor.force_enabled or device.get_register_enabled(sensor.key))
                and (not sensor.hybrid_only or hybrid)
            ):
                sensors.append(AguaIOTHeatingBinarySensor(coordinator, device, sensor))

    async_add_entities(sensors, True)


class AguaIOTHeatingBinarySensor(CoordinatorEntity, BinarySensorEntity):
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
    def icon(self):
        if self.is_on:
            return self.entity_description.icon_on or self.entity_description.icon
        else:
            return self.entity_description.icon

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
    def is_on(self):
        """Return the state of the sensor."""
        return bool(self._device.get_register_value(self.entity_description.key))
