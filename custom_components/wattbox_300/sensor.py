from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODEL
from .coordinator import WattBoxConfigEntry, WattBoxCoordinator

PARALLEL_UPDATES = 0
DESCRIPTIONS = (
    SensorEntityDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
)


class WattBoxSensor(CoordinatorEntity[WattBoxCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WattBoxCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        serial = coordinator.data.serial
        self._attr_unique_id = f"{serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name="WattBox 300",
            manufacturer="WattBox",
            model=MODEL,
            serial_number=serial,
            configuration_url=f"https://{coordinator.client.host}",
        )

    @property
    def native_value(self) -> float | int:
        reading = self.coordinator.data
        return {
            "voltage": reading.voltage,
            "current": reading.current,
            "power": reading.power,
        }[self.entity_description.key]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattBoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(WattBoxSensor(entry.runtime_data, item) for item in DESCRIPTIONS)
