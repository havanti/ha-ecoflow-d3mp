import math
import struct
import time
from collections.abc import Sequence

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from google.protobuf.message import Message

from ..commands import TimeCommands
from ..device_options import (
    UNLOCK_AC_CHARGING_MINIMUM,
    UNLOCK_DC_CHARGING_MINIMUM,
    option_field,
)
from ..devicebase import DeviceBase
from ..entity import controls, units
from ..entity.base import dynamic
from ..packet import Packet
from ..pb import pd335_sys_pb2
from ..props import (
    ProtobufProps,
    computed_field,
    field_group,
    pb_field,
    proto_attr_mapper,
    repeated_pb_field_type,
)
from ..props.enums import IntFieldValue
from ..props.transforms import flow_is_on, out_power, pround

pb = proto_attr_mapper(pd335_sys_pb2.DisplayPropertyUpload)

# The two places the second AC group has been seen in pow_get_ac_out_list. The
# layout is a firmware property, not a model one: units of the same model report
# either, and the losing index is structurally always zero.
_AC2_INDEX_A = 2
_AC2_INDEX_B = 3
_AC_LIVE_WATTS = 0.5

# Backup reserve. EcoFlow documents 0-50 % for this model, and the app keeps the
# reserve this far above the discharge limit: reaching the discharge limit drops
# every output and wins over the reserve, which is known to trigger a few points
# early.
BACKUP_RESERVE_MAX = 50
BACKUP_RESERVE_SPREAD = 5

STANDBY_MAX_MINUTES = 1440
SCREEN_OFF_MAX_SECONDS = 1800
LCD_LIGHT_MAX = 255

# What EcoFlow offers for this model. A unit reporting more is not given more.
DISCHARGE_LIMIT_MAX = 30
CHARGE_LIMIT_MIN = 50
CHARGE_LIMIT_MAX = 100
AC_CHARGING_POWER_MAX = 2400
DC_CHARGING_CURRENT_MAX = 8

# Extra battery ports. Only the first has ever been seen occupied; the second is
# read on the assumption that it reports the way the first does.
EXTRA_BATTERY_PORTS = 2

RUN_STATE_SHUTTING_DOWN = 2

# The extra battery reports its BMS as a list of raw 32-bit words
_RESV_SOC = 0
_RESV_DESIGN_MAH = 3
_RESV_FULL_MAH = 4
_RESV_REMAIN_MAH = 5
_RESV_CELL_MV = 12
_RESV_TEMPS = 13
_RESV_CHG_STATE = 14
_RESV_TEMP_SENSORS = 4
_PACK_CELLS_IN_SERIES = 16
# The pack reports capacity in Ah and no energy. Its rated 2048 Wh over the 40 Ah
# it reports as design capacity is 51.2 V, the nominal voltage of sixteen LiFePO4
# cells, and that is what turns its Ah into Wh. Measured on the D3E1 pack only; a
# pack with a different cell count would need its own voltage.
_CELL_NOMINAL_V = 3.2
_PACK_NOMINAL_V = _PACK_CELLS_IN_SERIES * _CELL_NOMINAL_V
# A pack that was just unplugged reports zeroes for its cells
_CELL_MV_FLOOR = 2000
_MAH_PER_AH = 1000
_SECONDS_PER_HOUR = 3600
# How long the extra battery's remaining capacity is watched before its change is
# read as a current. It moves in whole mAh a few times a minute, so a shorter
# window measures the quantisation rather than the load.
_CAPACITY_FLOW_WINDOW_S = 60
_MV_PER_V = 1000


class DCPortState(IntFieldValue):
    UNKNOWN = -1

    OFF = 0
    CAR = 1
    SOLAR = 2


class ChargeState(IntFieldValue):
    UNKNOWN = -1

    IDLE = 0
    DISCHARGING = 1
    CHARGING = 2


class AcChargeMode(IntFieldValue):
    UNKNOWN = -1

    CUSTOM = pd335_sys_pb2.AC_IN_CHG_MODE_SELF_DEF_POW
    OPTIMAL = pd335_sys_pb2.AC_IN_CHG_MODE_BAT_OPTIMAL_POW
    SILENT = pd335_sys_pb2.AC_IN_CHG_MODE_SILENCE


def _resv_words(msg) -> list[int] | None:
    return list(msg.resv_info) if msg is not None else None


def _word(words: list[int] | None, index: int) -> int | None:
    if words is None or len(words) <= index:
        return None
    return words[index]


def _rounded(value: float) -> int | None:
    return round(value) if math.isfinite(value) else None


def _bits_to_float(value: int) -> float | None:
    result = struct.unpack("<f", (value & 0xFFFFFFFF).to_bytes(4, "little"))[0]
    return result if math.isfinite(result) else None


# The device reports delivered power as negative. Both group readings are turned
# positive, like every other output of this device.
class _Ac2PortPower(repeated_pb_field_type(pb.pow_get_ac_out_list.pow_get_ac_out_item)):
    def get_item(self, value: Sequence[float]) -> float | None:
        if len(value) <= _AC2_INDEX_B:
            return None
        a = value[_AC2_INDEX_A]
        b = value[_AC2_INDEX_B]
        a_live = abs(a) > _AC_LIVE_WATTS
        b_live = abs(b) > _AC_LIVE_WATTS
        if a_live and b_live:
            # neither known layout - report nothing rather than a guess
            return None
        if a_live:
            return out_power(a)
        if b_live:
            return out_power(b)
        return 0.0


class _ACPortPower(repeated_pb_field_type(pb.pow_get_ac_out_list.pow_get_ac_out_item)):
    index: int

    def get_item(self, value: Sequence[float]) -> float | None:
        return out_power(value[self.index]) if value else None


class _DcChargingMaxField(
    repeated_pb_field_type(
        list_field=pb.plug_in_info_pv_chg_max_list.pv_chg_max_item,
        value_field=lambda x: x.pv_chg_amp_max,
        per_item=True,
    )
):
    vol_type: int

    def get_value(self, item: pd335_sys_pb2.PvChgMaxItem) -> int | None:
        return item.pv_chg_amp_max if item.pv_chg_vol_type == self.vol_type else None


class _DcAmpSettingField(
    repeated_pb_field_type(
        list_field=pb.pv_dc_chg_setting_list.list_info,
        value_field=lambda x: x.pv_chg_amp_limit,
        per_item=True,
    )
):
    vol_type: int
    plug_index: int

    def get_value(self, item: pd335_sys_pb2.PvDcChgSetting) -> int | None:
        return (
            item.pv_chg_amp_limit
            if item.pv_plug_index == self.plug_index
            and item.pv_chg_vol_spec == self.vol_type
            else None
        )


class _OutageReserveField(
    repeated_pb_field_type(
        list_field=pb.power_outages_list.power_outage_item,
        value_field=lambda x: x.power_outage_min_soc,
        per_item=True,
    )
):
    port: int

    def get_value(self, item: pd335_sys_pb2.PowerOutageItem) -> int | None:
        return (
            item.power_outage_min_soc
            if item.power_outage_port_type == self.port
            else None
        )


class _OutageReserveEnabledField(
    repeated_pb_field_type(
        list_field=pb.power_outages_list.power_outage_item,
        value_field=lambda x: x.power_outage_port_enable,
        per_item=True,
    )
):
    port: int

    def get_value(self, item: pd335_sys_pb2.PowerOutageItem) -> bool | None:
        return (
            item.power_outage_port_enable
            if item.power_outage_port_type == self.port
            else None
        )


# The same five readings exist once per extra battery port, under different names
_DCP_IN_FLAG = {1: pb.plug_in_info_dcp_in_flag, 2: pb.plug_in_info_dcp2_in_flag}
_DCP_SN = {1: pb.plug_in_info_dcp_sn, 2: pb.plug_in_info_dcp2_sn}
_DCP_TYPE = {1: pb.plug_in_info_dcp_type, 2: pb.plug_in_info_dcp2_type}
_DCP_RESV = {1: pb.plug_in_info_dcp_resv, 2: pb.plug_in_info_dcp2_resv}
_DCP_ERR_CODE = {
    1: pb.plug_in_info_dcp_err_code,
    2: pb.plug_in_info_dcp2_err_code,
}


class _CapacityFlow:
    """
    Current of a pack, measured from the change in its remaining capacity

    The device reports no current for the extra battery, and its power field reads
    zero while the pack empties. Charging reads positive.
    """

    def __init__(self) -> None:
        self.current: float | None = None
        self._ref_ah: float | None = None
        self._ref_time = 0.0

    def reset(self) -> None:
        self.current = None
        self._ref_ah = None

    def update(self, remaining_ah: float, now: float) -> None:
        if self._ref_ah is None:
            self._ref_ah = remaining_ah
            self._ref_time = now
            return
        elapsed = now - self._ref_time
        if elapsed < _CAPACITY_FLOW_WINDOW_S:
            return
        hours = elapsed / _SECONDS_PER_HOUR
        self.current = round((remaining_ah - self._ref_ah) / hours, 1)
        self._ref_ah = remaining_ah
        self._ref_time = now


def _per_port(name: str, factory):
    return field_group(
        factory, EXTRA_BATTERY_PORTS, name_template=f"extra_battery_{{n}}_{name}"
    )


def _pack_reading(name: str, read):
    """One reading out of an extra battery's word list, per port"""

    def factory(port: int):
        def value(device: "Device"):
            if (words := device._extra_battery_words(port)) is None:
                return None
            return read(words)

        return computed_field(value)

    return _per_port(name, factory)


def _pack_soc(words: list[int]) -> float | None:
    if (word := _word(words, _RESV_SOC)) is None:
        return None
    soc = _bits_to_float(word)
    if soc is None or not 0.0 <= soc <= 100.0:
        return None
    return round(soc, 2)


def _pack_ah(index: int):
    def read(words: list[int]) -> float | None:
        if (word := _word(words, index)) is None:
            return None
        return word / _MAH_PER_AH

    return read


def _pack_wh(index: int):
    amp_hours = _pack_ah(index)

    def read(words: list[int]) -> float | None:
        if (ah := amp_hours(words)) is None:
            return None
        return ah * _PACK_NOMINAL_V

    return read


def _pack_cells_mv(words: list[int]) -> tuple[int, int] | None:
    if (word := _word(words, _RESV_CELL_MV)) is None:
        return None
    cells = (word & 0xFFFF, (word >> 16) & 0xFFFF)
    if min(cells) < _CELL_MV_FLOOR:
        return None
    return cells


def _pack_min_cell_voltage(words: list[int]) -> float | None:
    if (cells := _pack_cells_mv(words)) is None:
        return None
    return min(cells) / _MV_PER_V


def _pack_max_cell_voltage(words: list[int]) -> float | None:
    if (cells := _pack_cells_mv(words)) is None:
        return None
    return max(cells) / _MV_PER_V


def _pack_voltage(words: list[int]) -> float | None:
    if (cells := _pack_cells_mv(words)) is None:
        return None
    return round(sum(cells) / len(cells) / _MV_PER_V * _PACK_CELLS_IN_SERIES, 2)


def _pack_temperatures(words: list[int]) -> list[int] | None:
    if (word := _word(words, _RESV_TEMPS)) is None:
        return None
    return [
        struct.unpack("<b", bytes([(word >> (8 * i)) & 0xFF]))[0]
        for i in range(_RESV_TEMP_SENSORS)
    ]


def _pack_max_temperature(words: list[int]) -> int | None:
    if (temps := _pack_temperatures(words)) is None:
        return None
    return max(temps)


def _pack_min_temperature(words: list[int]) -> int | None:
    if (temps := _pack_temperatures(words)) is None:
        return None
    return min(temps)


def _pack_charging_state(words: list[int]) -> ChargeState | None:
    if (word := _word(words, _RESV_CHG_STATE)) is None:
        return None
    return ChargeState.from_value(word)


def _port_error_code(port: int):
    def value(device: "Device") -> int | None:
        # An empty port has no fault to report
        if not getattr(device, f"extra_battery_{port}_enabled"):
            return None
        return getattr(device, f"_extra_battery_{port}_raw_error_code")

    return computed_field(value)


def _port_current(port: int):
    def value(device: "Device") -> float | None:
        return device._extra_battery_flows[port].current

    return computed_field(value)


class Device(DeviceBase, ProtobufProps):
    """Delta 3 Max Plus"""

    SN_PREFIX = (b"D3M1",)
    NAME_PREFIX = "EF-D3"

    # Ports whose word layout is assumed from port 1 rather than measured
    UNVERIFIED_EXTRA_BATTERY_PORTS = (2,)

    battery_level = pb_field(pb.cms_batt_soc, pround(2))
    main_battery_level = pb_field(pb.bms_batt_soc, pround(2))

    ac_input_power = pb_field(pb.pow_get_ac_in)
    ac_output_power = pb_field(pb.pow_get_ac_out, out_power)

    input_power = pb_field(pb.pow_in_sum_w)
    output_power = pb_field(pb.pow_out_sum_w)

    dc_port_1_input_power = pb_field(pb.pow_get_pv, pround(2))
    dc_port_1_state = pb_field(pb.plug_in_info_pv_type, DCPortState.from_value)
    dc_port_2_input_power = pb_field(pb.pow_get_pv2, pround(2))
    dc_port_2_state = pb_field(pb.plug_in_info_pv2_type, DCPortState.from_value)

    usbc_1_output_power = pb_field(pb.pow_get_typec1, out_power)
    usbc_2_output_power = pb_field(pb.pow_get_typec2, out_power)
    usba_1_output_power = pb_field(pb.pow_get_qcusb1, out_power)
    usba_2_output_power = pb_field(pb.pow_get_qcusb2, out_power)

    battery_discharge_limit = pb_field(pb.cms_min_dsg_soc)
    battery_charge_limit = pb_field(pb.cms_max_chg_soc)

    main_battery_max_cell_temperature = pb_field(pb.bms_max_cell_temp)
    ac_ports_1 = pb_field(pb.flow_info_ac_out, flow_is_on)

    dc_12v_port = pb_field(pb.flow_info_12v, flow_is_on)
    dc_12v_output_power = pb_field(pb.pow_get_12v, out_power)
    disable_grid_bypass = pb_field(pb.bypass_out_disable)

    remaining_time_charging = pb_field(pb.cms_chg_rem_time)
    remaining_time_discharging = pb_field(pb.cms_dsg_rem_time)

    error_code = pb_field(pb.errcode)

    ac_charging_power = pb_field(pb.plug_in_info_ac_in_chg_pow_max)

    dc_port_1_charging_current = _DcAmpSettingField(
        pd335_sys_pb2.PV_CHG_VOL_SPEC_12V, pd335_sys_pb2.PV_PLUG_INDEX_1
    )
    dc_port_1_charging_current_max = _DcChargingMaxField(
        pd335_sys_pb2.PV_CHG_VOL_SPEC_12V
    )
    dc_port_2_charging_current = _DcAmpSettingField(
        pd335_sys_pb2.PV_CHG_VOL_SPEC_12V, pd335_sys_pb2.PV_PLUG_INDEX_2
    )
    dc_port_2_charging_current_max = _DcChargingMaxField(
        pd335_sys_pb2.PV_CHG_VOL_SPEC_12V
    )
    dc_charging_current_min = option_field(
        UNLOCK_DC_CHARGING_MINIMUM, enabled=0, disabled=4
    )

    ac_ports_2 = pb_field(pb.flow_info_ac2_out, flow_is_on)

    ac_power_1 = _ACPortPower(0)
    ac_power_2 = _Ac2PortPower()

    usbc_3_output_power = pb_field(pb.pow_get_typec3, out_power)
    _ac_charging_power_max = pb_field(pb.plug_in_info_ac_in_chg_hal_pow_max)
    ac_charging_power_min = option_field(
        UNLOCK_AC_CHARGING_MINIMUM, enabled=1, disabled=200
    )

    # plug_in_info_ac_charger_flag is not sent; the input flag and the input flow
    # mask are
    _ac_in_flag = pb_field(pb.plug_in_info_ac_in_flag)
    _ac_in_flow = pb_field(pb.flow_info_ac_in)

    charging_state = pb_field(pb.cms_chg_dsg_state, ChargeState.from_value)
    main_battery_charging_state = pb_field(pb.bms_chg_dsg_state, ChargeState.from_value)
    main_battery_min_cell_temperature = pb_field(pb.bms_min_cell_temp)
    wifi_rssi = pb_field(pb.module_wifi_rssi, _rounded)
    solar_weak = pb_field(pb.plug_in_info_pv_weak_source_flag, bool)

    # the device-wide errcode is not sent; the subsystems report
    pd_error_code = pb_field(pb.pd_err_code)
    bms_error_code = pb_field(pb.bms_err_code)
    inverter_error_code = pb_field(pb.inv_err_code)
    dcdc_error_code = pb_field(pb.dcdc_err_code)

    # Read back on energy_backup_en. energy_strategy_operate_mode comes back as an
    # empty submessage and cannot confirm anything.
    backup_reserve = pb_field(pb.energy_backup_en)
    backup_reserve_level = pb_field(pb.backup_reverse_soc)

    xboost = pb_field(pb.xboost_en)
    beeper = pb_field(pb.en_beep)
    output_memory = pb_field(pb.output_power_off_memory)
    ac_charging_mode = pb_field(pb.plug_in_info_ac_in_chg_mode, AcChargeMode.from_value)

    device_standby_time = pb_field(pb.dev_standby_time)
    ac_1_standby_time = pb_field(pb.ac_standby_time)
    ac_2_standby_time = pb_field(pb.ac2_standby_time)
    dc_standby_time = pb_field(pb.dc_standby_time)
    screen_off_time = pb_field(pb.screen_off_time)
    screen_brightness = pb_field(pb.lcd_light)

    # Reported, never written: there is no command for it
    fast_charge = pb_field(pb.fast_charge_switch, bool)
    run_state = pb_field(pb.cms_bms_run_state)

    # What each output keeps back for a mains outage, and whether that is armed
    outage_reserve_dc = _OutageReserveField(pd335_sys_pb2.PORT_DC)
    outage_reserve_ac_1 = _OutageReserveField(pd335_sys_pb2.PORT_AC)
    outage_reserve_ac_2 = _OutageReserveField(pd335_sys_pb2.PORT_AC2)
    outage_reserve_dc_enabled = _OutageReserveEnabledField(pd335_sys_pb2.PORT_DC)
    outage_reserve_ac_1_enabled = _OutageReserveEnabledField(pd335_sys_pb2.PORT_AC)
    outage_reserve_ac_2_enabled = _OutageReserveEnabledField(pd335_sys_pb2.PORT_AC2)
    # Unverified: only ever seen at 0, with mains present. Which way round it reads
    # is settled by pulling the mains lead.
    outage_active = pb_field(pb.power_outages_active_flag, bool)

    # Reported values whose meaning is not known; exposed so a change is visible
    llc_flag = pb_field(pb.llc_hv_lv_flag)
    protocol_version = pb_field(pb.std_proto_version)
    update_ban = pb_field(pb.update_ban_flag)
    protect_port = pb_field(pb.power_protect_port_select)

    _extra_battery_enabled = _per_port(
        "enabled", lambda port: pb_field(_DCP_IN_FLAG[port])
    )
    _extra_battery_sn = _per_port("sn", lambda port: pb_field(_DCP_SN[port]))
    _extra_battery_type = _per_port("type", lambda port: pb_field(_DCP_TYPE[port]))
    _extra_battery_raw_error_code = field_group(
        lambda port: pb_field(_DCP_ERR_CODE[port]),
        EXTRA_BATTERY_PORTS,
        name_template="_extra_battery_{n}_raw_error_code",
    )
    _extra_battery_error_code = _per_port("error_code", _port_error_code)
    _extra_battery_current = _per_port("current", _port_current)
    _extra_battery_resv = field_group(
        lambda port: pb_field(_DCP_RESV[port], _resv_words),
        EXTRA_BATTERY_PORTS,
        name_template="_extra_battery_{n}_resv",
    )

    _extra_battery_battery_level = _pack_reading("battery_level", _pack_soc)
    _extra_battery_design_capacity = _pack_reading(
        "design_capacity", _pack_ah(_RESV_DESIGN_MAH)
    )
    _extra_battery_full_capacity = _pack_reading(
        "full_capacity", _pack_ah(_RESV_FULL_MAH)
    )
    _extra_battery_remaining_capacity = _pack_reading(
        "remaining_capacity", _pack_ah(_RESV_REMAIN_MAH)
    )
    _extra_battery_full_energy = _pack_reading("full_energy", _pack_wh(_RESV_FULL_MAH))
    _extra_battery_remaining_energy = _pack_reading(
        "remaining_energy", _pack_wh(_RESV_REMAIN_MAH)
    )
    _extra_battery_min_cell_voltage = _pack_reading(
        "min_cell_voltage", _pack_min_cell_voltage
    )
    _extra_battery_max_cell_voltage = _pack_reading(
        "max_cell_voltage", _pack_max_cell_voltage
    )
    _extra_battery_voltage = _pack_reading("voltage", _pack_voltage)
    _extra_battery_max_cell_temperature = _pack_reading(
        "max_cell_temperature", _pack_max_temperature
    )
    _extra_battery_min_cell_temperature = _pack_reading(
        "min_cell_temperature", _pack_min_temperature
    )
    _extra_battery_charging_state = _pack_reading(
        "charging_state", _pack_charging_state
    )

    @computed_field
    def solar_input_power_1(self) -> float:
        if (
            self.dc_port_1_state is DCPortState.SOLAR
            and self.dc_port_1_input_power is not None
        ):
            return round(self.dc_port_1_input_power, 2)
        return 0

    @computed_field
    def solar_input_power_2(self) -> float:
        if (
            self.dc_port_2_state is DCPortState.SOLAR
            and self.dc_port_2_input_power is not None
        ):
            return round(self.dc_port_2_input_power, 2)
        return 0

    @computed_field
    def ac_charging_power_max(self) -> int:
        if self._ac_charging_power_max is None:
            return AC_CHARGING_POWER_MAX
        return min(self._ac_charging_power_max, AC_CHARGING_POWER_MAX)

    @computed_field
    def dc_port_1_charging_current_ceiling(self) -> int:
        if self.dc_port_1_charging_current_max is None:
            return DC_CHARGING_CURRENT_MAX
        return min(self.dc_port_1_charging_current_max, DC_CHARGING_CURRENT_MAX)

    @computed_field
    def dc_port_2_charging_current_ceiling(self) -> int:
        if self.dc_port_2_charging_current_max is None:
            return DC_CHARGING_CURRENT_MAX
        return min(self.dc_port_2_charging_current_max, DC_CHARGING_CURRENT_MAX)

    @computed_field
    def plugged_in_ac(self) -> bool | None:
        if self._ac_in_flag is None and self._ac_in_flow is None:
            return None
        if self._ac_in_flag:
            return True
        return self._ac_in_flow is not None and flow_is_on(self._ac_in_flow)

    @computed_field
    def device_error_codes(self) -> list[int]:
        return [
            code or 0
            for code in (
                self.pd_error_code,
                self.bms_error_code,
                self.inverter_error_code,
                self.dcdc_error_code,
                self.extra_battery_1_error_code,
                self.extra_battery_2_error_code,
            )
        ]

    @computed_field
    def error_occurred(self) -> bool:
        return bool(self.error_code) or any(self.device_error_codes)

    @computed_field
    def backup_reserve_level_min(self) -> int:
        return min(
            (self.battery_discharge_limit or 0) + BACKUP_RESERVE_SPREAD,
            BACKUP_RESERVE_MAX,
        )

    @computed_field
    def battery_discharge_limit_ceiling(self) -> int:
        # While the reserve is armed the discharge limit has to stay clear of it
        if self.backup_reserve and self.backup_reserve_level is not None:
            return min(
                DISCHARGE_LIMIT_MAX,
                max(0, self.backup_reserve_level - BACKUP_RESERVE_SPREAD),
            )
        return DISCHARGE_LIMIT_MAX

    def _extra_battery_words(self, port: int) -> list[int] | None:
        # A port sends the same list full of zeroes while nothing is plugged in,
        # so every reading is gated on the port's presence flag
        if not getattr(self, f"extra_battery_{port}_enabled"):
            return None
        words = getattr(self, f"_extra_battery_{port}_resv")
        # The flag and the list arrive on their own schedule: around plugging and
        # unplugging the flag can say "present" over a list that is still all
        # zeroes, and a pack that is there never reports one
        if not words or not any(words):
            return None
        return words

    def __init__(
        self, ble_dev: BLEDevice, adv_data: AdvertisementData, sn: str
    ) -> None:
        super().__init__(ble_dev, adv_data, sn)
        self._time_commands = TimeCommands(self)
        self._clock = time.monotonic
        self._extra_battery_flows = {
            port: _CapacityFlow() for port in range(1, EXTRA_BATTERY_PORTS + 1)
        }

    def _recompute(self):
        for port, flow in self._extra_battery_flows.items():
            remaining = getattr(self, f"extra_battery_{port}_remaining_capacity")
            if remaining is None:
                flow.reset()
            else:
                flow.update(remaining, self._clock())
        super()._recompute()

    @classmethod
    def check(cls, sn):
        return sn[:4] in cls.SN_PREFIX

    async def packet_parse(self, data: bytes):
        return Packet.from_bytes(data, xor_payload=True)

    async def data_parse(self, packet: Packet):
        processed = False
        self.reset_updated()

        if packet.src == 0x02 and packet.cmd_set == 0xFE and packet.cmd_id == 0x15:
            self.update_from_bytes(pd335_sys_pb2.DisplayPropertyUpload, packet.payload)

            processed = True
        elif (
            packet.src == 0x35
            and packet.cmd_set == 0x01
            and packet.cmd_id == Packet.NET_BLE_COMMAND_CMD_SET_RET_TIME
        ):
            if len(packet.payload) == 0:
                self._time_commands.async_send_all()
            processed = True

        self._notify_updated()

        return processed

    async def _send_config_packet(self, message: Message):
        payload = message.SerializeToString()
        packet = Packet(0x20, 0x02, 0xFE, 0x11, payload, 0x01, 0x01, 0x13)
        await self.send_packet(packet, raise_on_failure=True)

    @controls.button(enabled=False)
    async def power_off(self) -> None:
        # The device obeys only while nothing flows and acknowledges nothing; the
        # only report is run_state going to RUN_STATE_SHUTTING_DOWN
        if (self.input_power or 0) > 0 or (self.output_power or 0) > 0:
            self._logger.warning(
                "Power off sent with %s W coming in and %s W going out. The device "
                "ignores it until both are zero.",
                self.input_power,
                self.output_power,
            )
        await self._send_config_packet(pd335_sys_pb2.ConfigWrite(cfg_power_off=True))

    @controls.outlet(ac_ports_1)
    async def enable_ac_ports_1(self, enabled: bool):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_ac_out_open=enabled)
        )

    @controls.outlet(ac_ports_2)
    async def enable_ac_ports_2(self, enabled: bool):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_ac2_out_open=enabled)
        )

    @controls.battery(
        battery_discharge_limit, max=dynamic(battery_discharge_limit_ceiling)
    )
    async def set_battery_discharge_limit(self, limit: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_min_dsg_soc=int(limit))
        )
        return True

    @controls.switch(backup_reserve)
    async def enable_backup_reserve(self, enabled: bool):
        level = self.backup_reserve_level
        if level is None:
            raise ValueError("Backup reserve level is not known yet")
        if enabled and not (
            self.backup_reserve_level_min <= level <= BACKUP_RESERVE_MAX
        ):
            raise ValueError(
                f"Backup reserve of {level} % has to be between "
                f"{self.backup_reserve_level_min} % and {BACKUP_RESERVE_MAX} %"
            )

        # Both sub-fields, every time: one left out is one set to zero, which
        # wipes the stored level the moment the reserve is armed
        config = pd335_sys_pb2.ConfigWrite()
        config.cfg_energy_backup.energy_backup_en = enabled
        config.cfg_energy_backup.energy_backup_start_soc = int(level)
        await self._send_config_packet(config)

    @controls.battery(
        backup_reserve_level,
        min=dynamic(backup_reserve_level_min),
        max=BACKUP_RESERVE_MAX,
    )
    async def set_backup_reserve_level(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_backup_reverse_soc=int(value))
        )
        return True

    @controls.switch(xboost)
    async def enable_xboost(self, enabled: bool):
        await self._send_config_packet(pd335_sys_pb2.ConfigWrite(cfg_xboost_en=enabled))

    @controls.switch(beeper)
    async def enable_beeper(self, enabled: bool):
        await self._send_config_packet(pd335_sys_pb2.ConfigWrite(cfg_beep_en=enabled))

    @controls.switch(output_memory)
    async def enable_output_memory(self, enabled: bool):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_output_power_off_memory=enabled)
        )

    @controls.select(ac_charging_mode, options=AcChargeMode)
    async def set_ac_charging_mode(self, value: AcChargeMode):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_ac_in_chg_mode=value.value)
        )

    @controls.duration(device_standby_time, max=STANDBY_MAX_MINUTES)
    async def set_device_standby_time(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_dev_standby_time=int(value))
        )
        return True

    @controls.duration(ac_1_standby_time, max=STANDBY_MAX_MINUTES)
    async def set_ac_1_standby_time(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_ac_standby_time=int(value))
        )
        return True

    @controls.duration(ac_2_standby_time, max=STANDBY_MAX_MINUTES)
    async def set_ac_2_standby_time(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_ac2_standby_time=int(value))
        )
        return True

    @controls.duration(dc_standby_time, max=STANDBY_MAX_MINUTES)
    async def set_dc_standby_time(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_dc_standby_time=int(value))
        )
        return True

    @controls.duration(
        screen_off_time, max=SCREEN_OFF_MAX_SECONDS, unit=units.Time.SECOND
    )
    async def set_screen_off_time(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_screen_off_time=int(value))
        )
        return True

    @controls.level(screen_brightness, max=LCD_LIGHT_MAX)
    async def set_screen_brightness(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_lcd_light=int(value))
        )
        return True

    @controls.battery(battery_charge_limit, min=CHARGE_LIMIT_MIN, max=CHARGE_LIMIT_MAX)
    async def set_battery_charge_limit(self, limit: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_max_chg_soc=int(limit))
        )
        return True

    @controls.power(
        ac_charging_power,
        min=dynamic(ac_charging_power_min),
        max=dynamic(ac_charging_power_max),
    )
    async def set_ac_charging_power(self, value: float):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(
                cfg_ac_in_chg_mode=pd335_sys_pb2.AC_IN_CHG_MODE_SELF_DEF_POW,
                cfg_plug_in_info_ac_in_chg_pow_max=int(value),
            )
        )
        return True

    # Unverified read-back: the device names its ports in pv_dc_chg_setting_list and
    # sends no limit with them, so what was set cannot be confirmed
    @controls.current(
        dc_port_1_charging_current,
        min=dynamic(dc_charging_current_min),
        max=dynamic(dc_port_1_charging_current_ceiling),
        enabled=False,
    )
    async def set_dc_port_1_charging_current(
        self,
        value: float,
        plug_index: pd335_sys_pb2.PV_PLUG_INDEX = pd335_sys_pb2.PV_PLUG_INDEX_1,
    ) -> bool:
        config = pd335_sys_pb2.ConfigWrite()
        config.cfg_pv_dc_chg_setting.pv_plug_index = plug_index
        config.cfg_pv_dc_chg_setting.pv_chg_vol_spec = pd335_sys_pb2.PV_CHG_VOL_SPEC_12V
        config.cfg_pv_dc_chg_setting.pv_chg_amp_limit = int(value)

        await self._send_config_packet(config)
        return True

    @controls.current(
        dc_port_2_charging_current,
        min=dynamic(dc_charging_current_min),
        max=dynamic(dc_port_2_charging_current_ceiling),
        enabled=False,
    )
    async def set_dc_port_2_charging_current(self, value: float) -> bool:
        return await self.set_dc_port_1_charging_current(
            value, plug_index=pd335_sys_pb2.PV_PLUG_INDEX_2
        )

    @controls.switch(dc_12v_port)
    async def enable_dc_12v_port(self, enabled: bool):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_dc_12v_out_open=enabled)
        )

    @controls.switch(disable_grid_bypass, enabled=False)
    async def enable_disable_grid_bypass(self, enabled: bool):
        await self._send_config_packet(
            pd335_sys_pb2.ConfigWrite(cfg_bypass_out_disable=enabled)
        )
