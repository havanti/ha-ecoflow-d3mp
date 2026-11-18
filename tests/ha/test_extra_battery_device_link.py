import pytest
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_mock import MockerFixture

from custom_components.ecoflow_d3mp import entity
from custom_components.ecoflow_d3mp.const import DOMAIN

ADDRESS = "AA:BB:CC:DD:EE:FF"


@pytest.fixture
def addon(mocker: MockerFixture):
    device = mocker.Mock()
    device.address = ADDRESS
    device.name = "EF-TEST"
    device.extra_battery_1_sn = None
    addon = entity.EcoflowBatteryAddonEntity(device, 1)
    addon.hass = mocker.Mock()
    mocker.patch.object(entity.dr, "async_get")
    return addon


def _takes_parent_id(mocker: MockerFixture, *, supported: bool):
    annotations = dict(DeviceInfo.__annotations__)
    annotations.pop("via_device_id", None)
    if supported:
        annotations["via_device_id"] = str
    mocker.patch.object(DeviceInfo, "__annotations__", annotations)


def test_pack_links_by_identifier_where_that_is_all_there_is(addon, mocker):
    _takes_parent_id(mocker, supported=False)
    info = addon.device_info
    assert info["via_device"] == (DOMAIN, ADDRESS)
    assert "via_device_id" not in info


def test_pack_links_by_registry_id_where_supported(addon, mocker):
    _takes_parent_id(mocker, supported=True)
    parent = mocker.Mock(id="parent-id")
    lookup = mocker.patch.object(entity, "async_get_device", return_value=parent)
    info = addon.device_info
    assert info["via_device_id"] == "parent-id"
    assert "via_device" not in info
    assert lookup.call_args.kwargs["identifiers"] == {(DOMAIN, ADDRESS)}


def test_pack_stays_unlinked_when_the_station_is_not_registered(addon, mocker):
    _takes_parent_id(mocker, supported=True)
    mocker.patch.object(entity, "async_get_device", return_value=None)
    info = addon.device_info
    assert "via_device_id" not in info
    assert "via_device" not in info
