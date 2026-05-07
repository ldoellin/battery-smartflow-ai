from __future__ import annotations

import logging

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, PLATFORMS, AI_MODES, MANUAL_ACTIONS
from .coordinator import ZendureSmartFlowCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_MODE = "set_mode"
SERVICE_SET_MANUAL_ACTION = "set_manual_action"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (YAML not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    coordinator = ZendureSmartFlowCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_MODE):
        _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator:
            await coordinator.async_shutdown()
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_SET_MODE)
            hass.services.async_remove(DOMAIN, SERVICE_SET_MANUAL_ACTION)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to new version."""
    if entry.version == 1:
        new_data = {**entry.data}

        if "pack_capacity_kwh" not in new_data:
            new_data["pack_capacity_kwh"] = 2.88

        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            version=2,
        )

    return True


def _register_services(hass: HomeAssistant) -> None:
    async def handle_set_mode(call: ServiceCall) -> None:
        entry_id: str = call.data["config_entry_id"]
        mode: str = call.data["mode"]
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            raise ValueError(f"No Battery SmartFlow AI entry with id {entry_id!r}")
        coordinator.set_ai_mode(mode)
        await coordinator._save()

    async def handle_set_manual_action(call: ServiceCall) -> None:
        entry_id: str = call.data["config_entry_id"]
        action: str = call.data["action"]
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            raise ValueError(f"No Battery SmartFlow AI entry with id {entry_id!r}")
        coordinator.set_manual_action(action)
        await coordinator._save()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MODE,
        handle_set_mode,
        schema=vol.Schema({
            vol.Required("config_entry_id"): cv.string,
            vol.Required("mode"): vol.In(AI_MODES),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MANUAL_ACTION,
        handle_set_manual_action,
        schema=vol.Schema({
            vol.Required("config_entry_id"): cv.string,
            vol.Required("action"): vol.In(MANUAL_ACTIONS),
        }),
    )
