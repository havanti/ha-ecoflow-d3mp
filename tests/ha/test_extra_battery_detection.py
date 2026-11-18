from collections import defaultdict

import pytest

from custom_components.ecoflow_d3mp import sensor
from custom_components.ecoflow_d3mp.config_flow import EFBLEConfigFlow
from custom_components.ecoflow_d3mp.const import CONF_EXTRA_BATTERY


class _Device:
    """Stand-in for a device with one extra-battery slot"""

    address = "AA:BB:CC:DD:EE:FF"
    name = "EF-TEST"
    extra_battery_1_battery_level = None
    extra_battery_1_enabled = None

    def __init__(self):
        self.callbacks = defaultdict(set)

    def register_state_update_callback(self, callback, propname):
        self.callbacks[propname].add(callback)

    def remove_state_update_callback(self, callback, propname):
        self.callbacks[propname].discard(callback)

    def report(self, propname, value):
        setattr(self, propname, value)
        for callback in list(self.callbacks[propname]):
            callback(value)


class _Entry:
    def __init__(self):
        self.unload = []

    def async_on_unload(self, func):
        self.unload.append(func)


@pytest.fixture
def device():
    return _Device()


@pytest.fixture
def built(monkeypatch):
    """Replace the entity factory so no Home Assistant entity is constructed"""
    monkeypatch.setattr(
        sensor, "_extra_battery_sensors", lambda device, index: [f"battery-{index}"]
    )


def _watch(device, added=()):
    entry = _Entry()
    entities = []
    sensor._add_extra_batteries_when_reported(
        config_entry=entry,
        device=device,
        async_add_entities=entities.extend,
        added=set(added),
    )
    return entry, entities


def test_pack_reported_after_setup_is_added_once(device, built):
    _, entities = _watch(device)
    assert entities == []

    device.report("extra_battery_1_enabled", True)
    device.report("extra_battery_1_enabled", True)

    assert entities == ["battery-1"]


def test_absent_pack_adds_nothing(device, built):
    _, entities = _watch(device)

    device.report("extra_battery_1_enabled", False)

    assert entities == []


def test_pack_present_at_setup_is_not_added_twice(device, built):
    _, entities = _watch(device, added={1})

    device.report("extra_battery_1_enabled", True)

    assert entities == []


def test_unload_stops_watching(device, built):
    entry, entities = _watch(device)

    for func in entry.unload:
        func()
    device.report("extra_battery_1_enabled", True)

    assert entities == []


def test_undetected_pack_keeps_its_device_without_a_selection(device, mocker):
    registry = mocker.patch.object(sensor.dr, "async_get").return_value
    mocker.patch.object(sensor, "async_get_device")

    assert sensor._get_extra_battery_entities(None, device, None, "entry") == []

    registry.async_remove_device.assert_not_called()


def test_deselected_pack_loses_its_device(device, mocker):
    registry = mocker.patch.object(sensor.dr, "async_get").return_value
    mocker.patch.object(sensor, "async_get_device")

    assert sensor._get_extra_battery_entities(None, device, [], "entry") == []

    registry.async_remove_device.assert_called_once()


def _created_data(mocker, device):
    flow = EFBLEConfigFlow()
    flow._user_id = "1"
    flow._local_names = {}
    create = mocker.patch.object(flow, "async_create_entry")
    flow._create_entry({}, device)
    return create.call_args.kwargs["data"]


def test_new_entry_leaves_detection_open_when_nothing_is_reported(device, mocker):
    assert CONF_EXTRA_BATTERY not in _created_data(mocker, device)


def test_new_entry_stores_a_reported_pack(device, mocker):
    device.extra_battery_1_enabled = True

    assert _created_data(mocker, device)[CONF_EXTRA_BATTERY] == ["1"]
