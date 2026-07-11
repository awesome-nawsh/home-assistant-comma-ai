"""The comma.ai integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo

from .api import CommaAPIClient
from .const import CONF_JWT_TOKEN, DOMAIN, PLATFORMS
from .coordinator import CommaDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class CommaData:
    """Dataclass for runtime data."""

    coordinator: CommaDataUpdateCoordinator
    api_client: CommaAPIClient


type CommaConfigEntry = ConfigEntry[CommaData]


async def _async_entry_updated(hass: HomeAssistant, config_entry: CommaConfigEntry) -> None:
    """Handle config entry option updates."""
    coordinator = config_entry.runtime_data.coordinator
    coordinator.set_update_interval(coordinator.current_update_interval)
    await coordinator.async_request_refresh()


def _async_clear_stale_distance_unit_overrides(
    hass: HomeAssistant, config_entry: CommaConfigEntry
) -> None:
    """Clear any per-entity unit overrides baked in by the old suggested_unit_of_measurement.

    Older versions of this integration seeded a "mi" unit override into the entity
    registry for the distance sensors. That override takes precedence over the
    dynamic unit we now compute from the distance_unit option, so it must be
    cleared once for the new option to actually take effect.
    """
    registry = er.async_get(hass)
    for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if entry.domain != "sensor":
            continue
        if not entry.unique_id.endswith(("_total_distance", "_week_distance")):
            continue
        sensor_options = entry.options.get("sensor", {})
        if sensor_options.get("unit_of_measurement") is not None:
            registry.async_update_entity_options(
                entry.entity_id,
                "sensor",
                {**sensor_options, "unit_of_measurement": None},
            )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: CommaConfigEntry,
) -> bool:
    """Set up comma.ai integration using config entry."""
    _LOGGER.debug("Setting up comma.ai integration")
    
    api_client = CommaAPIClient(
        jwt_token=config_entry.data[CONF_JWT_TOKEN],
        session=async_get_clientsession(hass),
    )
    
    # Validate the token by fetching profile
    try:
        profile = await api_client.get_profile()
        _LOGGER.debug("Authenticated as user: %s", profile.get("username"))
    except Exception as err:
        _LOGGER.error("Failed to authenticate with comma.ai: %s", err)
        return False

    coordinator = CommaDataUpdateCoordinator(hass, config_entry, api_client)
    await coordinator.async_config_entry_first_refresh()

    config_entry.runtime_data = CommaData(
        coordinator=coordinator,
        api_client=api_client,
    )
    config_entry.async_on_unload(config_entry.add_update_listener(_async_entry_updated))

    _async_clear_stale_distance_unit_overrides(hass, config_entry)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CommaConfigEntry) -> bool:
    """Unload comma.ai config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        del entry.runtime_data
    return unload_ok

