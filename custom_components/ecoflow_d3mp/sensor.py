"""EcoFlow BLE sensor"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum, EnumType
from typing import Any, Final, TypedDict, Unpack

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DeviceConfigEntry
from .const import CONF_EXTRA_BATTERY, DOMAIN, UNIQUE_ID_PREFIX
from .eflib import DeviceBase
from .eflib.device_mappings import extra_battery_indices
from .eflib.devices import delta3_max_plus
from .eflib.props.enums import IntFieldValue
from .entity import (
    DeviceNamedEntity,
    EcoflowBatteryAddonEntity,
    EcoflowEntity,
    resolve_entity_description_keys,
)
from .registry import async_get_device

_AMPERE_HOUR: Final = "Ah"


@dataclass(frozen=True, kw_only=True)
class EcoflowSensorEntityDescription[Device: DeviceBase](SensorEntityDescription):
    state_attribute_fields: list[str] = field(default_factory=list)
    native_unit_of_measurement_field: str | Callable[[Device], str] | None = None
    indexed_range: range | None = None
    name_field: str | None = None


class _SensorKwargs(TypedDict, total=False):
    translation_key: str
    translation_placeholders: dict[str, str]
    indexed_range: range
    entity_category: EntityCategory
    state_attribute_fields: list[str]
    name_field: str


def battery(
    key: str = "", enabled: bool = True, **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def power(
    key: str = "",
    *,
    enabled: bool = True,
    precision: int | None = None,
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT,
    **kwargs: Unpack[_SensorKwargs],
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=state_class,
        suggested_display_precision=precision,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def voltage(
    key: str = "",
    *,
    enabled: bool = True,
    precision: int | None = None,
    **kwargs: Unpack[_SensorKwargs],
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def signal_strength(
    key: str = "", enabled: bool = False, **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def temperature(
    key: str = "", enabled: bool = True, **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def duration(
    key: str = "", enabled: bool = True, **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement=UnitOfTime.HOURS,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def enum(
    key: str = "",
    enabled: bool = True,
    options: list[str] | type[IntFieldValue] | None = None,
    name: str | None = None,
    **kwargs: Unpack[_SensorKwargs],
) -> EcoflowSensorEntityDescription:
    if type(options) is EnumType and issubclass(options, IntFieldValue):
        options = options.options()

    return EcoflowSensorEntityDescription(
        key=key,
        name=name,
        device_class=SensorDeviceClass.ENUM,
        options=options,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def capacity(
    key: str = "", enabled: bool = True, **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=_AMPERE_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def raw(
    key: str = "",
    enabled: bool = True,
    state_class: SensorStateClass | None = None,
    **kwargs: Unpack[_SensorKwargs],
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        state_class=state_class,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def current(
    key: str = "", enabled: bool = True, **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def stored_energy(
    key: str = "", enabled: bool = True, **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=enabled,
        **kwargs,
    )


def diagnostic(
    key: str = "", **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    """Reported value kept for inspection, off unless the user turns it on"""
    return raw(key, enabled=False, entity_category=EntityCategory.DIAGNOSTIC, **kwargs)


def diagnostic_percent(
    key: str = "", **kwargs: Unpack[_SensorKwargs]
) -> EcoflowSensorEntityDescription:
    return EcoflowSensorEntityDescription(
        key=key,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        **kwargs,
    )


def port_power(
    name: str,
    *,
    enabled: bool = True,
    precision: int | None = None,
    **kwargs: Unpack[_SensorKwargs],
) -> EcoflowSensorEntityDescription:
    return power(
        enabled=enabled,
        precision=precision,
        translation_key="port_power",
        translation_placeholders={"name": name},
        **kwargs,
    )


def port_voltage(
    name: str,
    *,
    enabled: bool = False,
    precision: int | None = 2,
    **kwargs: Unpack[_SensorKwargs],
) -> EcoflowSensorEntityDescription:
    return voltage(
        enabled=enabled,
        precision=precision,
        translation_key="port_voltage",
        translation_placeholders={"name": name},
        entity_category=EntityCategory.DIAGNOSTIC,
        **kwargs,
    )


def port_error_code(
    name: str,
    *,
    enabled: bool = False,
    **kwargs: Unpack[_SensorKwargs],
) -> EcoflowSensorEntityDescription:
    return raw(
        enabled=enabled,
        translation_key="port_error_code",
        translation_placeholders={"name": name},
        entity_category=EntityCategory.DIAGNOSTIC,
        **kwargs,
    )


_SENSORS: Final[dict[str, SensorEntityDescription]] = {
    "battery_level": battery(),
    "main_battery_level": battery(),
    "input_power": power(precision=0),
    "output_power": power(precision=0),
    "remaining_time_charging": duration(enabled=False),
    "remaining_time_discharging": duration(enabled=False),
    "ac_input_power": power(precision=2),
    "ac_output_power": power(precision=2),
    "dc_12v_output_power": power(precision=2),
    "usba_1_output_power": power(),
    "usba_2_output_power": power(),
    "usbc_1_output_power": power(),
    "usbc_2_output_power": power(),
    "usbc_3_output_power": power(),
    "main_battery_max_cell_temperature": temperature(),
    "dc_port_1_input_power": power(precision=2),
    "dc_port_2_input_power": power(precision=2),
    "dc_port_1_state": enum(options=delta3_max_plus.DCPortState),
    "dc_port_2_state": enum(options=delta3_max_plus.DCPortState),
    "solar_input_power_1": power(enabled=False),
    "solar_input_power_2": power(enabled=False),
    "charging_state": enum(options=delta3_max_plus.ChargeState),
    "main_battery_charging_state": enum(
        options=delta3_max_plus.ChargeState, enabled=False
    ),
    "main_battery_min_cell_temperature": temperature(enabled=False),
    "pd_error_code": port_error_code("PD"),
    "bms_error_code": port_error_code("BMS"),
    "inverter_error_code": port_error_code("Inverter"),
    "dcdc_error_code": port_error_code("DC-DC"),
    "extra_battery_1_error_code": port_error_code("Extra Battery"),
    "extra_battery_2_error_code": port_error_code("Extra Battery (2)"),
    "run_state": diagnostic(),
    "outage_reserve_dc": diagnostic_percent(),
    "outage_reserve_ac_1": diagnostic_percent(),
    "outage_reserve_ac_2": diagnostic_percent(),
    "llc_flag": diagnostic(),
    "protocol_version": diagnostic(),
    "update_ban": diagnostic(),
    "protect_port": diagnostic(),
    "ac_power_{n}": port_power("AC ({n})", indexed_range=range(1, 3)),
    "wifi_rssi": signal_strength(enabled=False),
}

SENSOR_TYPES: Final[dict[str, SensorEntityDescription]] = (
    resolve_entity_description_keys(_SENSORS)
)


_BATTERY_ADDON_SENSORS: Final = {
    "extra_battery_{n}_battery_level": battery(translation_key="battery_level"),
    "extra_battery_{n}_max_cell_temperature": temperature(
        translation_key="max_cell_temperature"
    ),
    "extra_battery_{n}_voltage": port_voltage(
        "Battery",
        state_attribute_fields=[
            "extra_battery_{n}_max_cell_voltage",
            "extra_battery_{n}_min_cell_voltage",
        ],
    ),
    "extra_battery_{n}_max_cell_voltage": voltage(
        precision=3,
        enabled=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="max_cell_voltage",
    ),
    "extra_battery_{n}_min_cell_voltage": voltage(
        precision=3,
        enabled=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="min_cell_voltage",
    ),
    "extra_battery_{n}_min_cell_temperature": temperature(
        enabled=False, translation_key="min_cell_temperature"
    ),
    "extra_battery_{n}_remaining_capacity": capacity(
        translation_key="remaining_capacity"
    ),
    "extra_battery_{n}_full_capacity": capacity(
        enabled=False, translation_key="full_capacity"
    ),
    "extra_battery_{n}_design_capacity": capacity(
        enabled=False, translation_key="design_capacity"
    ),
    "extra_battery_{n}_remaining_energy": stored_energy(
        translation_key="remaining_energy"
    ),
    "extra_battery_{n}_full_energy": stored_energy(
        enabled=False, translation_key="full_energy"
    ),
    "extra_battery_{n}_type": diagnostic(translation_key="extra_battery_type"),
    "extra_battery_{n}_current": current(translation_key="current"),
    "extra_battery_{n}_charging_state": enum(
        options=delta3_max_plus.ChargeState, translation_key="charging_state"
    ),
}


def _sensor_class(sensor: str) -> "type[EcoflowSensor]":
    description = SENSOR_TYPES[sensor]
    has_device_name = (
        isinstance(description, EcoflowSensorEntityDescription)
        and description.name_field is not None
    )
    return EcoflowNamedSensor if has_device_name else EcoflowSensor


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: DeviceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    device = config_entry.runtime_data

    new_sensors = [
        _sensor_class(sensor)(device, sensor)
        for sensor in SENSOR_TYPES
        if hasattr(device, sensor)
    ]

    if new_sensors:
        async_add_entities(new_sensors)

    conf = config_entry.data.get(CONF_EXTRA_BATTERY)
    if battery_entities := _get_extra_battery_entities(
        hass=hass,
        device=device,
        conf=conf,
        config_entry_id=config_entry.entry_id,
    ):
        async_add_entities(battery_entities)

    if conf is None:
        _add_extra_batteries_when_reported(
            config_entry=config_entry,
            device=device,
            async_add_entities=async_add_entities,
            added={
                i
                for i in extra_battery_indices(device)
                if getattr(device, f"extra_battery_{i}_enabled", False)
            },
        )


def _add_extra_batteries_when_reported(
    config_entry: DeviceConfigEntry,
    device: DeviceBase,
    async_add_entities: AddConfigEntryEntitiesCallback,
    added: set[int],
) -> None:
    """
    Add the sensors of a pack the device reports only after setup

    Setup finishes once the device is authenticated, which is before it has said
    which packs are plugged in, so without a stored selection a pack would
    otherwise be missed until the next reload.
    """
    for battery_index in extra_battery_indices(device):
        if battery_index in added:
            continue

        prop = f"extra_battery_{battery_index}_enabled"

        def _on_enabled(enabled: Any, battery_index: int = battery_index) -> None:
            if not enabled or battery_index in added:
                return
            added.add(battery_index)
            async_add_entities(_extra_battery_sensors(device, battery_index))

        device.register_state_update_callback(_on_enabled, prop)
        config_entry.async_on_unload(
            lambda cb=_on_enabled, prop=prop: device.remove_state_update_callback(
                cb, prop
            )
        )


def _get_extra_battery_entities(
    hass: HomeAssistant,
    device: DeviceBase,
    conf: list[str] | None,
    config_entry_id: str,
):
    available_indices = extra_battery_indices(device)

    if not available_indices:
        return []

    if conf is not None:
        enabled_indices = {int(i) for i in conf}
    else:
        enabled_indices = {
            i
            for i in available_indices
            if getattr(device, f"extra_battery_{i}_enabled", False)
        }

    # Without a stored selection a pack that has not been reported yet may still
    # show up, and removing its device would drop the user's entity settings
    registry = dr.async_get(hass)
    for battery_index in available_indices if conf is not None else ():
        if battery_index not in enabled_indices:
            identifier = (DOMAIN, f"{device.address}_battery_{battery_index}")
            if dev_entry := async_get_device(
                registry,
                identifiers={identifier},
                config_entry_id=config_entry_id,
            ):
                registry.async_remove_device(dev_entry.id)

    return [
        entity
        for battery_index in enabled_indices
        if battery_index in available_indices
        for entity in _extra_battery_sensors(device, battery_index)
    ]


def _extra_battery_sensors(
    device: DeviceBase, battery_index: int
) -> list["EcoflowBatteryAddonSensor"]:
    battery_entities: list[EcoflowBatteryAddonSensor] = []
    # A port whose layout is assumed rather than measured starts out disabled
    unverified_ports = getattr(device, "UNVERIFIED_EXTRA_BATTERY_PORTS", ())
    for template_key, desc in _BATTERY_ADDON_SENSORS.items():
        attr_name = template_key.replace("{n}", str(battery_index))
        if not hasattr(device, attr_name):
            continue
        if battery_index in unverified_ports:
            desc = replace(desc, entity_registry_enabled_default=False)

        battery_entities.append(
            EcoflowBatteryAddonSensor(
                device=device,
                sensor=attr_name,
                description=replace(
                    desc,
                    key=attr_name,
                    state_attribute_fields=[
                        attr.replace("{n}", str(battery_index))
                        for attr in desc.state_attribute_fields
                    ],
                ),
                battery_index=battery_index,
            )
        )

    return battery_entities


class EcoflowSensor(EcoflowEntity, SensorEntity):
    """Base representation of a sensor."""

    def __init__(self, device: DeviceBase, sensor: str):
        """Initialize the sensor."""
        super().__init__(device)

        self._sensor = sensor
        self._attr_unique_id = f"{UNIQUE_ID_PREFIX}_{device.serial_number}_{sensor}"

        if sensor in SENSOR_TYPES:
            self.entity_description = SENSOR_TYPES[sensor]
            if self.entity_description.translation_key is None:
                self._attr_translation_key = self.entity_description.key

        self._attribute_fields = (
            self.entity_description.state_attribute_fields
            if isinstance(self.entity_description, EcoflowSensorEntityDescription)
            else []
        )

        self._register_update_callback(None, sensor)
        for attribute_field in self._attribute_fields:
            self._register_update_callback(None, attribute_field)

    @property
    def native_value(self):
        """Return the value of the sensor."""
        value = getattr(self._device, self._sensor, None)
        if isinstance(value, Enum):
            return value.name.lower()
        return value

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        if isinstance(self.entity_description, EcoflowSensorEntityDescription):
            unit = self.entity_description.native_unit_of_measurement_field
            match unit:
                case str():
                    return getattr(self._device, unit)
                case Callable():
                    return unit(self._device)
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._attribute_fields:
            return {}

        return {
            field_name: getattr(self._device, field_name)
            for field_name in self._attribute_fields
            if hasattr(self._device, field_name)
        }


class EcoflowNamedSensor(DeviceNamedEntity, EcoflowSensor):
    """Sensor whose display name comes from a device field (see DeviceNamedEntity)"""


class EcoflowBatteryAddonSensor(EcoflowBatteryAddonEntity, SensorEntity):
    def __init__(
        self,
        device: DeviceBase,
        sensor: str,
        description: SensorEntityDescription,
        battery_index: int,
    ) -> None:
        super().__init__(device=device, battery_index=battery_index)
        self._sensor = sensor
        self._attr_unique_id = (
            f"{UNIQUE_ID_PREFIX}_{device.serial_number}_{description.key}"
        )
        self._attr_native_value = getattr(device, sensor, None)
        self.entity_description = description
        if self.entity_description.translation_key is None:
            self._attr_translation_key = self.entity_description.key

        self._attribute_fields = (
            description.state_attribute_fields
            if isinstance(description, EcoflowSensorEntityDescription)
            else []
        )

        self._register_update_callback(None, sensor)
        for attribute_field in self._attribute_fields:
            self._register_update_callback(None, attribute_field)

    @property
    def native_value(self):
        value = getattr(self._device, self._sensor, None)
        if isinstance(value, Enum):
            return value.name.lower()
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        prefix = f"extra_battery_{self._battery_index}_"
        return {
            field_name.removeprefix(prefix): getattr(self._device, field_name)
            for field_name in self._attribute_fields
            if hasattr(self._device, field_name)
        }
