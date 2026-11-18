import dataclasses
import functools
import inspect
from collections.abc import Awaitable, Callable
from types import MethodType
from typing import TYPE_CHECKING, Any, cast, get_type_hints

from ..props.enums import IntFieldValue
from ..props.updatable_props import Field
from . import DynamicValue, EntityType, units

if TYPE_CHECKING:
    from ..devicebase import DeviceBase


def _resolve(value: float | DynamicValue | None, device: "DeviceBase") -> float | None:
    if isinstance(value, DynamicValue):
        raw = getattr(device, value.prop_name, None)
        if raw is None:
            return None
        return value.transform(raw) if value.transform is not None else float(raw)
    return value


class ControlType(EntityType):
    pass


class toggle(ControlType):
    type SwitchFunc[D: "DeviceBase"] = Callable[[D, bool], Awaitable[None]]

    enable_func: SwitchFunc = dataclasses.field(
        default=cast("SwitchFunc", None),
        repr=False,
        init=False,
    )

    def __call__[D: "DeviceBase"](
        self,
        func: Callable[[D, bool], Awaitable[None]],
    ):
        _check_value_param(func, bool, type(self).__name__)
        self.enable_func = func
        self._field.sensor(self)
        return func


class outlet(toggle):
    pass


class switch(toggle):
    pass


class _ButtonField(Field[None]):
    """
    Stateless placeholder field backing a `button` control

    Exists only so the control is registered for discovery like any other field;
    reading it from a device instance returns the bound press method, keeping the
    decorated function directly callable.
    """

    def __init__(self, press_func: Callable[..., Awaitable[Any]]) -> None:
        self._press_func = press_func

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return MethodType(self._press_func, instance)


class button(ControlType):
    """
    Stateless action control mapped to a HA button entity

    Unlike other controls, a button is not tied to an existing state field. The
    decorator replaces the method with an internal field named after it, so the
    entity key matches the method name and the method stays callable on the device:

        @controls.button()
        async def power_off(self) -> None: ...
    """

    type PressFunc[D: "DeviceBase"] = Callable[[D], Awaitable[Any]]

    field: Any = None
    press_func: PressFunc = dataclasses.field(
        default=cast("PressFunc", None),
        repr=False,
        init=False,
    )

    def __call__[D: "DeviceBase"](
        self,
        func: Callable[[D], Awaitable[Any]],
    ) -> _ButtonField:
        self.press_func = func
        return _ButtonField(func).sensor(self)


class NumberType(ControlType):
    type ValueFunc[D: "DeviceBase", float] = Callable[[D, float], Awaitable[bool]]

    set_value_func: ValueFunc = dataclasses.field(
        default=cast("Any", None),
        repr=False,
        init=False,
    )
    max: float | None = None
    min: float = 0
    step: float = 1.0

    def __call__[F: Callable[[Any, float], Awaitable[bool]]](
        self,
        func: F,
    ) -> F:
        _check_value_param(func, float, type(self).__name__)

        control = self

        @functools.wraps(func)
        async def _check_limits(
            device: "DeviceBase", value: float, *args, **kwargs
        ) -> bool:
            if (low := _resolve(control.min, device)) is not None:
                value = max(low, value)
            if (high := _resolve(control.max, device)) is not None:
                value = min(high, value)
            return await func(device, value, *args, **kwargs)

        self.set_value_func = _check_limits

        self._field.sensor(self)
        return cast("F", _check_limits)


class power(NumberType):
    unit: units.Power = units.Power.WATT


class battery(NumberType):
    pass


class current(NumberType):
    unit: units.Current = units.Current.AMPERE


class voltage(NumberType):
    unit: units.Voltage = units.Voltage.VOLT


class duration(NumberType):
    """A delay the device counts down, in the unit the device itself stores"""

    unit: units.Time = units.Time.MINUTE


class level(NumberType):
    """A plain setting with no physical unit, such as a display brightness"""


@dataclasses.dataclass
class option_set[E: IntFieldValue]:
    """
    The options a select offers, and the ones it withholds

    `exclude` drops a member for good, for an internal state that is never a choice.
    `exclude_if` drops one only while a device field says so, which keeps the rest of
    the select usable where hiding the whole entity would not
    """

    options: type[E]
    excluded: list[E] = dataclasses.field(default_factory=list, init=False)
    conditional: list[tuple[DynamicValue, list[E]]] = dataclasses.field(
        default_factory=list, init=False
    )

    def exclude(self, *options: E) -> "option_set[E]":
        self.excluded.extend(options)
        return self

    def exclude_if(
        self, condition: "Field[Any] | bool", *options: E
    ) -> "option_set[E]":
        """
        Withhold `options` while `condition` holds

        `condition` is a boolean field, or a `dynamic(field, transform)` reading one -
        which is annotated as the value it resolves to, the same way a number's `min`
        takes one
        """
        if isinstance(condition, Field):
            condition = cast("Any", DynamicValue(condition))
        if not isinstance(condition, DynamicValue):
            raise TypeError(
                f"{condition!r} is not a field to read the condition from - pass the "
                "field itself, or dynamic(field, transform)"
            )
        self.conditional.append((condition, list(options)))
        return self


class select[E: IntFieldValue](ControlType):
    type SetFunc = Callable[[DeviceBase, E], Awaitable[None]]

    options: "type[E] | option_set[E] | list[str]"
    set_value_func: SetFunc = dataclasses.field(
        repr=False,
        init=False,
    )

    def __post_init__(self) -> None:
        options = self.options
        excluded: list[E] = []
        self._conditional: list[tuple[DynamicValue, list[E]]] = []
        if isinstance(options, option_set):
            self._conditional = options.conditional
            excluded = options.excluded
            options = options.options

        if isinstance(options, list):
            self._value_type: type[E] | None = None
            self._options_str = options
        else:
            self._value_type = options
            self._options_str = options.options(include_unknown=False, exclude=excluded)
        self.options = self._options_str

    @property
    def options_str(self) -> list[str]:
        return self._options_str

    @property
    def conditional_options(self) -> list[tuple[DynamicValue, list[str]]]:
        """Each condition, with the options to withhold while it holds"""
        return [
            (condition, [option.name.lower() for option in options])
            for condition, options in self._conditional
        ]

    def __call__[D: "DeviceBase"](
        self,
        func: Callable[[D, E], Awaitable[None]],
    ):
        if self._value_type is not None:
            _check_value_param(func, self._value_type, type(self).__name__)

        value_type = self._value_type

        @functools.wraps(func)
        async def _func(device: D, value: E | str) -> None:
            if isinstance(value, str) and value_type is not None:
                value = value_type[value.upper()]

            await func(device, value)  # pyright: ignore[reportArgumentType]

        self.set_value_func = _func  # pyright: ignore[reportAttributeAccessIssue]
        self._field.sensor(self)
        return _func


def _check_value_param(func: Any, expected: type, decorator_name: str) -> None:
    hints = get_type_hints(func)
    params = list(inspect.signature(func).parameters.values())
    if len(params) < 2:
        raise TypeError(
            f"@{decorator_name}: decorated function must accept "
            f"(self, value: {expected.__name__})"
        )
    value_param = params[1]
    value_type = hints.get(value_param.name)
    if value_type is not None and value_type is not expected:
        raise TypeError(
            f"@{decorator_name}: parameter '{value_param.name}' must be "
            f"{expected.__name__}, got {value_type}"
        )
