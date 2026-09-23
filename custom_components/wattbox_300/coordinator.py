import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
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
        self.client = client
        self.expected_serial = entry.unique_id

    async def _async_update_data(self) -> PowerReading:
        try:
            reading = await self.hass.async_add_executor_job(self.client.fetch)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed("WattBox login failed") from err
        except WattBoxError as err:
            raise UpdateFailed(str(err)) from err
        if reading.serial != self.expected_serial:
            raise UpdateFailed("The address now belongs to a different WattBox")
        return reading


type WattBoxConfigEntry = ConfigEntry[WattBoxCoordinator]
