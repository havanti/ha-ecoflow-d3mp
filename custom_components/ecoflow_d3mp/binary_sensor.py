"""EcoFlow BLE binary sensor"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, TypedDict, Unpack

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.ecoflow_d3mp.eflib import DeviceBase

from . import DeviceConfigEntry
from .const import UNIQUE_ID_PREFIX
from .entity import EcoflowEntity, resolve_entity_description_keys


@dataclass(frozen=True, kw_only=True)
class EcoflowBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Binary sensor entity description with optional indexed expansion support."""

    update_state: Callable[[bool], None] | None = None
    indexed_range: range | None = None
    state_attribute_fields: list[str] = field(default_factory=list)


class _BinarySensorKwargs(TypedDict, total=False):
    translation_key: str
    translation_placeholders: dict[str, str]
    indexed_range: range
    entity_category: EntityCategory
    state_attribute_fields: list[str]


def _make_desc(
    device_class: BinarySensorDeviceClass | None,
    key: str = "",
    *,
    enabled: bool = True,
    **kwargs: Unpack[_BinarySensorKwargs],
) -> EcoflowBinarySensorEntityDescription:
    return EcoflowBinarySensorEntityDescription(
        key=key,
        device_class=device_class,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def problem(
    key: str = "", *, enabled: bool = True, **kwargs: Unpack[_BinarySensorKwargs]
) -> EcoflowBinarySensorEntityDescription:
    return _make_desc(BinarySensorDeviceClass.PROBLEM, key, enabled=enabled, **kwargs)


def plug(
    key: str = "", *, enabled: bool = True, **kwargs: Unpack[_BinarySensorKwargs]
) -> EcoflowBinarySensorEntityDescription:
    return _make_desc(BinarySensorDeviceClass.PLUG, key, enabled=enabled, **kwargs)


def _diagnostic() -> EcoflowBinarySensorEntityDescription:
    return _make_desc(None, enabled=False, entity_category=EntityCategory.DIAGNOSTIC)


_BINARY_SENSORS: Final[dict[str, BinarySensorEntityDescription]] = {
    "plugged_in_ac": plug(),
    "fast_charge": _make_desc(None),
    "outage_reserve_dc_enabled": _diagnostic(),
    "outage_reserve_ac_1_enabled": _diagnostic(),
    "outage_reserve_ac_2_enabled": _diagnostic(),
    # Unverified polarity, see the field on the device
    "outage_active": _diagnostic(),
    "error_occurred": problem(
        enabled=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_attribute_fields=["error_code", "device_error_codes"],
    ),
    "solar_weak": problem(enabled=False, entity_category=EntityCategory.DIAGNOSTIC),
}

BINARY_SENSOR_TYPES: Final[dict[str, BinarySensorEntityDescription]] = (
    resolve_entity_description_keys(_BINARY_SENSORS)
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: DeviceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for passed config_entry in HA."""
    device = config_entry.runtime_data

    new_sensors = [
        EcoflowBinarySensor(device, sensor)
        for sensor in BINARY_SENSOR_TYPES
        if hasattr(device, sensor)
    ]

    if new_sensors:
        async_add_entities(new_sensors)


class EcoflowBinarySensor(EcoflowEntity, BinarySensorEntity):
    def __init__(
        self,
        device: DeviceBase,
        sensor: str,
    ):
        super().__init__(device)

        self._attr_unique_id = (
            f"{UNIQUE_ID_PREFIX}_{self._device.serial_number}_{sensor}"
        )
        self._attr_is_on = getattr(self._device, sensor, None)

        if sensor in BINARY_SENSOR_TYPES:
            self.entity_description = BINARY_SENSOR_TYPES[sensor]
            self._prop_name = self.entity_description.key
            if self.entity_description.translation_key is None:
                self._attr_translation_key = self.entity_description.key

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        self._device.register_state_update_callback(self.state_updated, self._prop_name)
        await super().async_added_to_hass()

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        self._device.remove_state_update_callback(self.state_updated, self._prop_name)
        await super().async_will_remove_from_hass()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes from configured attribute fields."""
        if not isinstance(
            self.entity_description, EcoflowBinarySensorEntityDescription
        ):
            return None

        return {
            field_name: getattr(self._device, field_name)
            for field_name in self.entity_description.state_attribute_fields
            if hasattr(self._device, field_name)
        } or None

    @callback
    def state_updated(self, state: bool):
        self._attr_is_on = state
        self.async_write_ha_state()
