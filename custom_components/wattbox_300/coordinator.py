import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InvalidAuth, PowerReading, WattBoxClient, WattBoxError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class WattBoxCoordinator(DataUpdateCoordinator[PowerReading]):
    def __init__(
        self, hass: HomeAssistant, entry: "WattBoxConfigEntry", client: WattBoxClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self._operation_lock = asyncio.Lock()
        self.client = client
        self.expected_serial = entry.unique_id

    async def _async_update_data(self) -> PowerReading:
        async with self._operation_lock:
            return await self._async_fetch()

    async def _async_fetch(self) -> PowerReading:
        try:
            reading = await self.hass.async_add_executor_job(self.client.fetch)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed("WattBox login failed") from err
        except WattBoxError as err:
            raise UpdateFailed(str(err)) from err
        if reading.serial != self.expected_serial:
            raise UpdateFailed("The address now belongs to a different WattBox")
        return reading

    async def async_set_outlet(self, outlet: int, on: bool) -> None:
        if self.expected_serial is None:
            raise HomeAssistantError("WattBox identity is unavailable")
        async with self._operation_lock:
            try:
                reading = await self.hass.async_add_executor_job(
                    self.client.set_outlet, outlet, on, self.expected_serial
                )
            except WattBoxError as err:
                self.async_set_update_error(UpdateFailed(str(err)))
                raise HomeAssistantError(
                    "Outlet command could not be verified; check its state before retrying"
                ) from err
            self.async_set_updated_data(reading)


type WattBoxConfigEntry = ConfigEntry[WattBoxCoordinator]
