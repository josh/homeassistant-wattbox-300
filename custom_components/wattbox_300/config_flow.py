from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.helpers import selector

from .api import (
    InvalidAuth,
    UnsupportedModel,
    WattBoxClient,
    WattBoxError,
    validate_host,
)
from .const import CONF_VERIFY_SSL, DEFAULT_SCAN_INTERVAL, DOMAIN


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, "admin")
            ): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, False)
            ): bool,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
        }
    )


class WattBoxConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _configure(
        self, step: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        entry = None
        if step == "reconfigure":
            entry = self._get_reconfigure_entry()
        elif step == "reauth_confirm":
            entry = self._get_reauth_entry()
        defaults = dict(entry.data) if entry else {}
        errors = {}
        if user_input is not None:
            defaults.update(user_input)
            try:
                data = dict(user_input)
                data[CONF_HOST] = validate_host(data[CONF_HOST])
                client = WattBoxClient(
                    data[CONF_HOST],
                    data[CONF_USERNAME],
                    data[CONF_PASSWORD],
                    data[CONF_VERIFY_SSL],
                )
                reading = await self.hass.async_add_executor_job(client.fetch)
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except UnsupportedModel:
                errors["base"] = "unsupported_model"
            except WattBoxError:
                errors["base"] = "cannot_connect"
            else:
                if entry is not None:
                    if reading.serial != entry.unique_id:
                        return self.async_abort(reason="wrong_device")
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                await self.async_set_unique_id(reading.serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="WattBox 300", data=data)
        return self.async_show_form(
            step_id=step, data_schema=_schema(defaults), errors=errors
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._configure("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._configure("reconfigure", user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._configure("reauth_confirm", user_input)
