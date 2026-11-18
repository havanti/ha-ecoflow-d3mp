import pytest
from homeassistant.helpers.device_registry import DeviceInfo
from pytest_mock import MockerFixture

from custom_components.ecoflow_d3mp import entity
from custom_components.ecoflow_d3mp.const import DOMAIN
from custom_components.ecoflow_d3mp.eflib.devices.delta3_max_plus import Device

ADDRESS = "AA:BB:CC:DD:EE:FF"
ENTRY_ID = "entry-1"
STATION = (DOMAIN, ADDRESS)

links_by_id = pytest.mark.skipif(
    not entity._LINKS_PARENT_BY_ID,
    reason="this Home Assistant links a parent device by identifier pair",
)
links_by_pair = pytest.mark.skipif(
    entity._LINKS_PARENT_BY_ID,
    reason="this Home Assistant links a parent device by registry id",
)


class _Registry:
    """Device registry holding the devices of several config entries"""

    def __init__(self, devices):
        self._devices = devices

    def async_get_devices(self, *, identifiers, connections, config_entry_id):
        return [
            device
            for device in self._devices
            if device.identifiers & identifiers
            and config_entry_id in (None, device.config_entry_id)
        ]


def _registered(mocker, device_id, entry_id=ENTRY_ID, identifiers=frozenset({STATION})):
    return mocker.Mock(id=device_id, config_entry_id=entry_id, identifiers=identifiers)


@pytest.fixture
def addon(mocker: MockerFixture):
    ble_dev = mocker.Mock()
    ble_dev.address = ADDRESS
    addon = entity.EcoflowBatteryAddonEntity(
        Device(ble_dev, mocker.MagicMock(), "D3M1TEST1234"), 1
    )
    addon.hass = mocker.Mock()
    addon.platform = mocker.Mock()
    addon.platform.config_entry.entry_id = ENTRY_ID
    return addon


def _register(mocker, devices):
    mocker.patch.object(entity.dr, "async_get", return_value=_Registry(devices))


def test_link_uses_a_field_this_home_assistant_declares(addon, mocker):
    _register(mocker, [_registered(mocker, "station-id")])
    declared = DeviceInfo.__optional_keys__ | DeviceInfo.__required_keys__
    link = addon._station_link()
    assert link
    assert set(link) <= declared


@links_by_pair
def test_pack_links_by_identifier_pair(addon):
    assert addon.device_info["via_device"] == STATION


@links_by_id
def test_pack_links_by_the_station_registry_id(addon, mocker):
    _register(mocker, [_registered(mocker, "station-id")])
    info = addon.device_info
    assert info["via_device_id"] == "station-id"
    assert "via_device" not in info


@links_by_id
def test_pack_links_to_the_station_of_its_own_config_entry(addon, mocker):
    _register(
        mocker,
        [
            _registered(mocker, "foreign-id", entry_id="entry-2"),
            _registered(mocker, "station-id"),
        ],
    )
    assert addon.device_info["via_device_id"] == "station-id"


@links_by_id
def test_pack_stays_unlinked_and_says_so_when_the_station_is_missing(addon, mocker):
    _register(mocker, [])
    warning = mocker.patch.object(entity._LOGGER, "warning")
    info = addon.device_info
    assert "via_device_id" not in info
    assert "via_device" not in info
    warning.assert_called_once()
