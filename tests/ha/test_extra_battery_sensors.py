import pytest
from pytest_mock import MockerFixture

from custom_components.ecoflow_d3mp import sensor
from custom_components.ecoflow_d3mp.eflib.devices.delta3_max_plus import Device


@pytest.fixture
def device(mocker: MockerFixture):
    ble_dev = mocker.Mock()
    ble_dev.address = "AA:BB:CC:DD:EE:FF"
    return Device(ble_dev, mocker.MagicMock(), "D3M1TEST1234")


def _enabled_by_default(device, port):
    return [
        entity.entity_description.entity_registry_enabled_default
        for entity in sensor._extra_battery_sensors(device, port)
    ]


def test_measured_port_offers_enabled_sensors(device):
    assert any(_enabled_by_default(device, 1))


def test_unverified_port_starts_fully_disabled(device):
    defaults = _enabled_by_default(device, 2)
    assert defaults
    assert not any(defaults)


def test_both_ports_offer_the_same_sensors(device):
    def kinds(port):
        prefix = f"extra_battery_{port}_"
        return [
            entity.entity_description.key.removeprefix(prefix)
            for entity in sensor._extra_battery_sensors(device, port)
        ]

    assert kinds(1) == kinds(2)
