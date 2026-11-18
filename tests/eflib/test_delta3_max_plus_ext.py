import struct

import pytest
from pytest_mock import MockerFixture

from custom_components.ecoflow_d3mp.eflib.devices.delta3_max_plus import (
    AcChargeMode,
    ChargeState,
    Device,
)
from custom_components.ecoflow_d3mp.eflib.entity import controls
from custom_components.ecoflow_d3mp.eflib.pb import pd335_sys_pb2

Upload = pd335_sys_pb2.DisplayPropertyUpload


def _float_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


@pytest.fixture
def device(mocker: MockerFixture):
    ble_dev = mocker.Mock()
    ble_dev.address = "AA:BB:CC:DD:EE:FF"
    device = Device(ble_dev, mocker.MagicMock(), "D3M1TEST1234")
    device._conn = mocker.AsyncMock()
    device._send_config_packet = mocker.AsyncMock()
    return device


def feed(device: Device, **fields):
    msg = Upload(**fields)
    device.reset_updated()
    device.update_from_message(msg)
    device._notify_updated = lambda: None
    device._recompute()
    return msg


def sent(device: Device) -> pd335_sys_pb2.ConfigWrite:
    device._send_config_packet.assert_awaited_once()
    return device._send_config_packet.await_args.args[0]


def resv(**at) -> pd335_sys_pb2.ResvInfo:
    words = [0] * 16
    for index, value in at.items():
        words[int(index.removeprefix("w"))] = value
    return pd335_sys_pb2.ResvInfo(resv_info=words)


# ── shore lead ───────────────────────────────────────────────────────────────


def test_plugged_in_unknown_before_any_flag(device):
    assert device.plugged_in_ac is None


def test_plugged_in_from_input_flag(device):
    feed(device, plug_in_info_ac_in_flag=1)
    assert device.plugged_in_ac is True
    feed(device, plug_in_info_ac_in_flag=0)
    assert device.plugged_in_ac is False


def test_plugged_in_from_flow_when_flag_is_clear(device):
    feed(device, plug_in_info_ac_in_flag=0, flow_info_ac_in=2)
    assert device.plugged_in_ac is True


def test_plugged_in_ignores_the_dead_charger_flag(device):
    feed(device, plug_in_info_ac_charger_flag=True)
    assert device.plugged_in_ac is None


# ── second AC group ──────────────────────────────────────────────────────────


def _ac_list(*watts):
    return pd335_sys_pb2.PowGetAcOutList(pow_get_ac_out_item=list(watts))


@pytest.mark.parametrize(
    ("watts", "expected"),
    [
        ((0, 0, -82, 0, 0), -82.0),
        ((0, 0, 0, -82, 0), -82.0),
        ((-141, 0, 0, 0, 0), 0.0),
    ],
)
def test_ac2_power_takes_whichever_index_carries_load(device, watts, expected):
    feed(device, pow_get_ac_out_list=_ac_list(*watts))
    assert device.ac_power_2 == expected
    assert device.ac_power_1 == watts[0]


def test_ac2_power_keeps_last_value_when_both_indices_carry_load(device):
    feed(device, pow_get_ac_out_list=_ac_list(0, 0, -82, 0, 0))
    feed(device, pow_get_ac_out_list=_ac_list(0, 0, -50, -60, 0))
    assert device.ac_power_2 == -82.0


def test_ac2_power_needs_the_full_list(device):
    feed(device, pow_get_ac_out_list=_ac_list(0, 0, -82))
    assert device.ac_power_2 is None


# ── state, faults ────────────────────────────────────────────────────────────


def test_charge_states(device):
    feed(device, cms_chg_dsg_state=2, bms_chg_dsg_state=1)
    assert device.charging_state is ChargeState.CHARGING
    assert device.main_battery_charging_state is ChargeState.DISCHARGING
    feed(device, cms_chg_dsg_state=9)
    assert device.charging_state is ChargeState.UNKNOWN


def test_error_from_subsystem_code(device):
    feed(device, pd_err_code=0, bms_err_code=0, inv_err_code=0, dcdc_err_code=0)
    assert device.error_occurred is False
    feed(device, inv_err_code=303)
    assert device.error_occurred is True
    assert device.device_error_codes == [0, 0, 303, 0, 0, 0]


def test_misc_readings(device):
    feed(
        device,
        bms_min_cell_temp=19,
        module_wifi_rssi=-61.4,
        plug_in_info_pv_weak_source_flag=1,
    )
    assert device.main_battery_min_cell_temperature == 19
    assert device.wifi_rssi == -61
    assert device.solar_weak is True


# ── extra battery ────────────────────────────────────────────────────────────


def _pack():
    return resv(
        w0=_float_bits(87.5),
        w3=40000,
        w4=39500,
        w5=34560,
        w12=3331 | (3334 << 16),
        w13=22 | (23 << 8) | (24 << 16) | (22 << 24),
        w14=2,
    )


def test_extra_battery_reads_nothing_while_unplugged(device):
    feed(device, plug_in_info_dcp_in_flag=False, plug_in_info_dcp_resv=_pack())
    assert device.extra_battery_1_battery_level is None
    assert device.extra_battery_1_voltage is None
    assert device.extra_battery_1_max_cell_temperature is None


def test_extra_battery_readings(device):
    feed(device, plug_in_info_dcp_in_flag=True, plug_in_info_dcp_resv=_pack())
    assert device.extra_battery_1_battery_level == 87.5
    assert device.extra_battery_1_design_capacity == 40.0
    assert device.extra_battery_1_full_capacity == 39.5
    assert device.extra_battery_1_remaining_capacity == 34.56
    assert device.extra_battery_1_min_cell_voltage == 3.331
    assert device.extra_battery_1_max_cell_voltage == 3.334
    assert device.extra_battery_1_voltage == round(3.3325 * 16, 2)
    assert device.extra_battery_1_max_cell_temperature == 24
    assert device.extra_battery_1_min_cell_temperature == 22
    assert device.extra_battery_1_charging_state is ChargeState.CHARGING


def test_second_extra_battery_reads_its_own_port(device):
    feed(
        device,
        plug_in_info_dcp_in_flag=False,
        plug_in_info_dcp2_in_flag=True,
        plug_in_info_dcp2_resv=_pack(),
        plug_in_info_dcp2_sn="D3E1TEST5678",
        plug_in_info_dcp2_err_code=7,
    )
    assert device.extra_battery_1_battery_level is None
    assert device.extra_battery_2_battery_level == 87.5
    assert device.extra_battery_2_remaining_capacity == 34.56
    assert device.extra_battery_2_charging_state is ChargeState.CHARGING
    assert device.extra_battery_2_sn == "D3E1TEST5678"
    assert device.extra_battery_2_error_code == 7
    assert device.error_occurred is True


def test_removed_controls_stay_removed(device):
    keys = [c.key for c in device.get_controls(controls.ControlType)]
    assert "usb_ports" not in keys
    assert not any(key.startswith("energy_strategy") for key in keys)


def test_empty_port_reports_no_error_code(device):
    feed(device, plug_in_info_dcp_in_flag=False, plug_in_info_dcp_err_code=7)
    assert device.extra_battery_1_error_code is None
    assert device.error_occurred is False


def test_plugged_pack_reports_its_error_code(device):
    feed(device, plug_in_info_dcp_in_flag=True, plug_in_info_dcp_err_code=7)
    assert device.extra_battery_1_error_code == 7
    assert device.error_occurred is True


def _feed_remaining(device, now, mah):
    device._clock = lambda: now
    feed(device, plug_in_info_dcp_in_flag=True, plug_in_info_dcp_resv=resv(w5=mah))


def test_extra_battery_current_needs_a_full_window(device):
    _feed_remaining(device, 0, 20000)
    _feed_remaining(device, 30, 19988)
    assert device.extra_battery_1_current is None


@pytest.mark.parametrize(
    ("after_a_minute", "amps"),
    [(19976, -1.4), (20024, 1.4), (20000, 0.0)],
)
def test_extra_battery_current_from_capacity_change(device, after_a_minute, amps):
    _feed_remaining(device, 0, 20000)
    _feed_remaining(device, 60, after_a_minute)
    assert device.extra_battery_1_current == amps


def test_extra_battery_current_is_forgotten_when_unplugged(device):
    _feed_remaining(device, 0, 20000)
    _feed_remaining(device, 60, 19976)
    feed(device, plug_in_info_dcp_in_flag=False)
    assert device.extra_battery_1_current is None
    _feed_remaining(device, 120, 19000)
    assert device.extra_battery_1_current is None


def test_extra_battery_negative_temperature(device):
    pack = resv(w13=0xFB | (2 << 8) | (1 << 16) | (0 << 24))
    feed(device, plug_in_info_dcp_in_flag=True, plug_in_info_dcp_resv=pack)
    assert device.extra_battery_1_min_cell_temperature == -5
    assert device.extra_battery_1_max_cell_temperature == 2


def test_extra_battery_rejects_garbage(device):
    pack = resv(w0=_float_bits(float("nan")), w12=0)
    feed(device, plug_in_info_dcp_in_flag=True, plug_in_info_dcp_resv=pack)
    assert device.extra_battery_1_battery_level is None
    assert device.extra_battery_1_voltage is None


def test_extra_battery_short_list(device):
    pack = pd335_sys_pb2.ResvInfo(resv_info=[_float_bits(50.0)])
    feed(device, plug_in_info_dcp_in_flag=True, plug_in_info_dcp_resv=pack)
    assert device.extra_battery_1_battery_level == 50.0
    assert device.extra_battery_1_remaining_capacity is None


# ── backup reserve ───────────────────────────────────────────────────────────


def test_reserve_reads_its_own_flag_not_self_powered(device):
    feed(device, energy_backup_en=True, backup_reverse_soc=40)
    assert device.backup_reserve is True
    assert device.backup_reserve_level == 40


async def test_reserve_arming_carries_both_sub_fields(device):
    feed(device, energy_backup_en=False, backup_reverse_soc=40, cms_min_dsg_soc=10)
    await device.enable_backup_reserve(True)
    cfg = sent(device)
    assert cfg.cfg_energy_backup.energy_backup_en is True
    assert cfg.cfg_energy_backup.energy_backup_start_soc == 40
    assert not cfg.HasField("cfg_energy_strategy_operate_mode")


async def test_reserve_disarming_keeps_the_level(device):
    feed(device, energy_backup_en=True, backup_reverse_soc=40, cms_min_dsg_soc=10)
    await device.enable_backup_reserve(False)
    cfg = sent(device)
    assert cfg.cfg_energy_backup.energy_backup_en is False
    assert cfg.cfg_energy_backup.energy_backup_start_soc == 40


async def test_reserve_refuses_without_a_level(device):
    with pytest.raises(ValueError):
        await device.enable_backup_reserve(True)
    device._send_config_packet.assert_not_awaited()


@pytest.mark.parametrize("level", [12, 55])
async def test_reserve_refuses_to_arm_outside_the_window(device, level):
    feed(device, backup_reverse_soc=level, cms_min_dsg_soc=10)
    with pytest.raises(ValueError):
        await device.enable_backup_reserve(True)
    device._send_config_packet.assert_not_awaited()


async def test_reserve_can_be_disarmed_from_a_bad_level(device):
    feed(device, energy_backup_en=True, backup_reverse_soc=12, cms_min_dsg_soc=10)
    await device.enable_backup_reserve(False)
    assert sent(device).cfg_energy_backup.energy_backup_en is False


@pytest.mark.parametrize(("asked", "written"), [(3, 15), (30, 30), (80, 50)])
async def test_reserve_level_is_clamped_to_the_window(device, asked, written):
    feed(device, cms_min_dsg_soc=10)
    await device.set_backup_reserve_level(asked)
    assert sent(device).cfg_backup_reverse_soc == written


async def test_discharge_limit_stays_clear_of_an_armed_reserve(device):
    feed(device, energy_backup_en=True, backup_reverse_soc=30, cms_max_chg_soc=100)
    assert device.battery_discharge_limit_ceiling == 25
    await device.set_battery_discharge_limit(28)
    assert sent(device).cfg_min_dsg_soc == 25


async def test_discharge_limit_stops_at_the_vendor_limit_while_the_reserve_is_off(
    device,
):
    feed(device, energy_backup_en=False, backup_reverse_soc=30, cms_max_chg_soc=90)
    assert device.battery_discharge_limit_ceiling == 30
    await device.set_battery_discharge_limit(45)
    assert sent(device).cfg_min_dsg_soc == 30


async def test_discharge_limit_ceiling_never_exceeds_the_vendor_limit(device):
    feed(device, energy_backup_en=True, backup_reverse_soc=50)
    assert device.battery_discharge_limit_ceiling == 30


async def test_charge_limit_stops_at_the_vendor_minimum(device):
    await device.set_battery_charge_limit(20)
    assert sent(device).cfg_max_chg_soc == 50


async def test_ac_charging_power_stops_at_the_vendor_maximum(device):
    feed(device, plug_in_info_ac_in_chg_hal_pow_max=3000)
    assert device.ac_charging_power_max == 2400
    await device.set_ac_charging_power(2800)
    assert sent(device).cfg_plug_in_info_ac_in_chg_pow_max == 2400


@pytest.mark.parametrize(
    ("setter", "plug_index"),
    [
        ("set_dc_port_1_charging_current", pd335_sys_pb2.PV_PLUG_INDEX_1),
        ("set_dc_port_2_charging_current", pd335_sys_pb2.PV_PLUG_INDEX_2),
    ],
)
async def test_dc_charging_current_stays_inside_the_vendor_range(
    device, setter, plug_index
):
    await getattr(device, setter)(20)
    setting = sent(device).cfg_pv_dc_chg_setting
    assert setting.pv_plug_index == plug_index
    assert setting.pv_chg_amp_limit == 8


def test_dc_charging_current_is_off_by_default(device):
    by_key = {c.key: c for c in device.get_controls(controls.current)}
    assert by_key["dc_port_1_charging_current"].enabled is False
    assert by_key["dc_port_2_charging_current"].enabled is False


# ── power off ────────────────────────────────────────────────────────────────


async def test_power_off_warns_while_power_flows(device, mocker):
    warning = mocker.patch.object(device._logger, "warning")
    feed(device, pow_in_sum_w=0, pow_out_sum_w=95)
    await device.power_off()
    assert sent(device).cfg_power_off is True
    warning.assert_called_once()


async def test_power_off_is_silent_at_rest(device, mocker):
    warning = mocker.patch.object(device._logger, "warning")
    feed(device, pow_in_sum_w=0, pow_out_sum_w=0)
    await device.power_off()
    assert sent(device).cfg_power_off is True
    warning.assert_not_called()


# ── read-only settings ───────────────────────────────────────────────────────


def test_fast_charge_and_run_state(device):
    feed(device, fast_charge_switch=1, cms_bms_run_state=1)
    assert device.fast_charge is True
    assert device.run_state == 1


def test_outage_reserve_per_port(device):
    items = [
        pd335_sys_pb2.PowerOutageItem(
            power_outage_port_type=port,
            power_outage_min_soc=soc,
            power_outage_port_enable=armed,
        )
        for port, soc, armed in (
            (pd335_sys_pb2.PORT_AC2, 30, True),
            (pd335_sys_pb2.PORT_DC, 10, False),
            (pd335_sys_pb2.PORT_AC, 20, False),
        )
    ]
    feed(
        device,
        power_outages_list=pd335_sys_pb2.PowerOutagesList(power_outage_item=items),
    )
    assert device.outage_reserve_dc == 10
    assert device.outage_reserve_ac_1 == 20
    assert device.outage_reserve_ac_2 == 30
    assert device.outage_reserve_dc_enabled is False
    assert device.outage_reserve_ac_2_enabled is True


# ── plain setters ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "arg", "field", "expected"),
    [
        ("enable_xboost", True, "cfg_xboost_en", True),
        ("enable_beeper", False, "cfg_beep_en", False),
        ("enable_output_memory", True, "cfg_output_power_off_memory", True),
        ("set_device_standby_time", 120.0, "cfg_dev_standby_time", 120),
        ("set_ac_1_standby_time", 0.0, "cfg_ac_standby_time", 0),
        ("set_ac_2_standby_time", 60.0, "cfg_ac2_standby_time", 60),
        ("set_dc_standby_time", 5000.0, "cfg_dc_standby_time", 1440),
        ("set_screen_off_time", 300.0, "cfg_screen_off_time", 300),
        ("set_screen_off_time", 9999.0, "cfg_screen_off_time", 1800),
        ("set_screen_brightness", 300.0, "cfg_lcd_light", 255),
    ],
)
async def test_setters_write_one_field(device, method, arg, field, expected):
    await getattr(device, method)(arg)
    cfg = sent(device)
    assert cfg.HasField(field)
    assert getattr(cfg, field) == expected
    assert len(cfg.ListFields()) == 1


async def test_charge_mode_goes_out_alone(device):
    control = next(
        c for c in device.get_controls(controls.select) if c.key == "ac_charging_mode"
    )
    await control.set_value_func(device, "silent")
    cfg = sent(device)
    assert cfg.cfg_ac_in_chg_mode == pd335_sys_pb2.AC_IN_CHG_MODE_SILENCE
    assert len(cfg.ListFields()) == 1


def test_charge_mode_reading(device):
    feed(device, plug_in_info_ac_in_chg_mode=pd335_sys_pb2.AC_IN_CHG_MODE_SILENCE)
    assert device.ac_charging_mode is AcChargeMode.SILENT


def test_readbacks(device):
    feed(
        device,
        xboost_en=True,
        en_beep=False,
        output_power_off_memory=True,
        dev_standby_time=120,
        ac_standby_time=720,
        ac2_standby_time=60,
        dc_standby_time=0,
        screen_off_time=300,
        lcd_light=128,
    )
    assert device.xboost is True
    assert device.beeper is False
    assert device.output_memory is True
    assert device.device_standby_time == 120
    assert device.ac_1_standby_time == 720
    assert device.ac_2_standby_time == 60
    assert device.dc_standby_time == 0
    assert device.screen_off_time == 300
    assert device.screen_brightness == 128


# ── the controls other models share stay theirs ──────────────────────────────


def test_control_keys_are_unique_and_complete(device):
    keys = [c.key for c in device.get_controls(controls.ControlType)]
    assert len(keys) == len(set(keys))
    for key in (
        "backup_reserve",
        "backup_reserve_level",
        "battery_discharge_limit",
        "battery_charge_limit",
        "xboost",
        "beeper",
        "output_memory",
        "ac_charging_mode",
        "device_standby_time",
        "ac_1_standby_time",
        "ac_2_standby_time",
        "dc_standby_time",
        "screen_off_time",
        "screen_brightness",
        "ac_ports_1",
        "ac_ports_2",
        "dc_12v_port",
    ):
        assert key in keys, key


def test_wifi_rssi_survives_a_non_number(device):
    feed(device, module_wifi_rssi=float("nan"))
    assert device.wifi_rssi is None
