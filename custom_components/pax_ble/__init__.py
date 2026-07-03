"""Support for Pax fans."""

import logging

from functools import partial
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICES
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_MAC, CONF_NAME, DOMAIN, PLATFORMS
from .helpers import getCoordinator

_LOGGER = logging.getLogger(__name__)


def _coordinators_for_entry(hass: HomeAssistant, entry_id: str) -> dict:
    """Return coordinators for one config entry."""
    return hass.data.get(DOMAIN, {}).get(entry_id, {}).get(CONF_DEVICES, {})


def _all_coordinators(hass: HomeAssistant):
    """Yield all coordinators across Pax BLE config entries."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        yield from entry_data.get(CONF_DEVICES, {}).values()


def _device_mac(device_entry: DeviceEntry) -> str | None:
    """Return the Pax BLE MAC/identifier for a device registry entry."""
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN:
            return identifier
    return None


def _data_without_device(entry_data: dict, device_key: str) -> dict:
    """Copy config-entry data and remove one device."""
    devices = dict(entry_data.get(CONF_DEVICES, {}))
    devices.pop(device_key, None)
    return {**entry_data, CONF_DEVICES: devices}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pax BLE from a config entry."""
    _LOGGER.debug("Setting up configuration for Pax BLE")
    hass.data.setdefault(DOMAIN, {})

    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    entry_data[CONF_DEVICES] = {}

    for device_key, device_data in entry.data[CONF_DEVICES].items():
        name = device_data[CONF_NAME]
        mac = device_data[CONF_MAC]

        device_registry = dr.async_get(hass)
        dev = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, mac)},
            connections={(dr.CONNECTION_BLUETOOTH, mac)},
            name=name,
        )

        entry_data[CONF_DEVICES][device_key] = getCoordinator(hass, device_data, dev)

    if not entry_data.get("forwarded"):
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry_data["forwarded"] = True
    else:
        _LOGGER.debug("Platforms already forwarded for entry %s", entry.entry_id)

    for coordinator in entry_data[CONF_DEVICES].values():
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(entry.add_update_listener(update_listener))

    if not hass.services.has_service(DOMAIN, "request_update"):
        hass.services.async_register(
            DOMAIN, "request_update", partial(service_request_update, hass)
        )

    return True


async def service_request_update(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the service call to update entities for a specific device."""
    device_id = call.data.get("device_id")
    if not device_id:
        _LOGGER.error("Device ID is required")
        return

    device_registry = dr.async_get(hass)
    if not device_registry.async_get(device_id):
        _LOGGER.error("No device entry found for device ID %s", device_id)
        return

    for coordinator in _all_coordinators(hass):
        if coordinator.device_id == device_id:
            await coordinator.async_request_refresh()
            return

    _LOGGER.warning("No coordinator found for device ID %s", device_id)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old config entries."""
    if config_entry.version == 1:
        _LOGGER.error(
            "You have an old PAX configuration, please remove and add again. "
            "Sorry for the inconvenience!"
        )
        return False

    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Pax BLE entry after config changes."""
    _LOGGER.debug("Updating Pax BLE entry")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Pax BLE entry")

    for coordinator in _coordinators_for_entry(hass, entry.entry_id).values():
        await coordinator.disconnect()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove one Pax BLE device from config-entry data."""
    mac = _device_mac(device_entry)
    if mac is None:
        return False

    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, config_entry.entry_id):
        if device_entry.id == ent.device_id:
            ent_reg.async_remove(ent.entity_id)

    new_data = _data_without_device(config_entry.data, mac)
    hass.config_entries.async_update_entry(config_entry, data=new_data)

    return True
