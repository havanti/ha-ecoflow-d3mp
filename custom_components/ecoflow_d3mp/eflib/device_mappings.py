from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .devicebase import DeviceBase

ADDON_BATTERY_MAP: dict[str, str] = {
    "D3E1": "DELTA 3 Max Plus Extra Battery",
}


MAX_EXTRA_BATTERIES = 10


def extra_battery_indices(device: "DeviceBase") -> list[int]:
    """Slots for which the device declares an extra-battery level field"""
    return [
        i
        for i in range(1, MAX_EXTRA_BATTERIES + 1)
        if hasattr(device, f"extra_battery_{i}_battery_level")
    ]


def battery_name_from_sn(sn: str | None) -> str:
    if not sn:
        return "Extra Battery"
    return ADDON_BATTERY_MAP.get(sn[:4], "Extra Battery")


def battery_name_from_device(device: "DeviceBase", index: int) -> str:
    return getattr(
        device,
        "extra_battery_name",
        battery_name_from_sn(getattr(device, f"extra_battery_{index}_sn", None)),
    )
