def out_power(x: float) -> float:
    """Negate and round output power, returning 0 for zero values"""
    return -round(x, 2) if x != 0 else 0.0


def flow_is_on(x: int) -> bool:
    """Return True when the flow info bitmask indicates an active port"""
    # Same check as in the app; values other than 0 (off) or 2 (on) are unknown
    return (int(x) & 0b11) in [0b10, 0b11]


def pround(precision: int = 2):
    """Return a transform that rounds a float to the given precision"""

    def _round(val: float | None) -> float | None:
        return None if val is None else round(val, precision)

    return _round
