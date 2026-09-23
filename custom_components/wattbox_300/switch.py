from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WattBoxConfigEntry, WattBoxCoordinator

PARALLEL_UPDATES = 1


class WattBoxOutletSwitch(CoordinatorEntity[WattBoxCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, coordinator: WattBoxCoordinator, index: int) -> None:
        super().__init__(coordinator)
        self._index = index
        serial = coordinator.data.serial
        self._attr_unique_id = f"{serial}_outlet_{index + 1}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, serial)})

    @property
    def name(self) -> str:
        return self.coordinator.data.outlets[self._index].name

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.outlets[self._index].is_on

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_outlet(self._index + 1, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_outlet(self._index + 1, False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattBoxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        WattBoxOutletSwitch(entry.runtime_data, index) for index in range(5)
    )
