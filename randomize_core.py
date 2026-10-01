"""Blender-independent random value generation for Randomize Value."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any


SUPPORTED_TYPES = frozenset({"BOOLEAN", "INT", "FLOAT", "ENUM"})


def ordered_bounds(first: float | int, second: float | int) -> tuple[float | int, float | int]:
    """Return two numeric bounds in ascending order."""

    return (first, second) if first <= second else (second, first)


def clamp(value: float | int, minimum: float | int, maximum: float | int) -> float | int:
    """Clamp a numeric value to an inclusive interval."""

    return max(minimum, min(maximum, value))


def enum_items_in_range(
    enum_items: Sequence[str],
    minimum_index: int,
    maximum_index: int,
) -> tuple[str, ...]:
    """Return an inclusive, clamped enum-index range.

    Negative indices count from the end, so the default range ``0`` to ``-1``
    includes every item.
    """

    items = tuple(enum_items)
    if not items:
        return ()

    last_index = len(items) - 1

    def resolve(index: int) -> int:
        index = int(index)
        if index < 0:
            index += len(items)
        return int(clamp(index, 0, last_index))

    low, high = ordered_bounds(resolve(minimum_index), resolve(maximum_index))
    return items[low : high + 1]


def random_scalar(
    value_type: str,
    rng: random.Random,
    *,
    minimum: float | int = 0,
    maximum: float | int = 1,
    probability: float = 0.5,
    enum_items: Sequence[str] = (),
    enum_flag: bool = False,
) -> Any:
    """Generate one value using a caller-owned deterministic RNG."""

    if value_type == "BOOLEAN":
        return rng.random() < clamp(probability, 0.0, 1.0)

    if value_type == "INT":
        low, high = ordered_bounds(int(minimum), int(maximum))
        return rng.randint(low, high)

    if value_type == "FLOAT":
        low, high = ordered_bounds(float(minimum), float(maximum))
        return rng.uniform(low, high)

    if value_type == "ENUM":
        if not enum_items:
            raise ValueError("An enum property has no selectable items")
        if enum_flag:
            return {item for item in enum_items if rng.random() < 0.5}
        return rng.choice(tuple(enum_items))

    raise ValueError(f"Unsupported property type: {value_type}")


def random_value(
    value_type: str,
    rng: random.Random,
    *,
    array_length: int = 0,
    minimum: float | int | Sequence[float | int] = 0,
    maximum: float | int | Sequence[float | int] = 1,
    probability: float = 0.5,
    enum_items: Sequence[str] = (),
    enum_flag: bool = False,
) -> Any:
    """Generate a scalar or a list whose components are generated independently."""

    if array_length > 0:
        def component(bound: float | int | Sequence[float | int], index: int) -> float | int:
            if isinstance(bound, Sequence) and not isinstance(bound, (str, bytes)):
                return bound[index]
            return bound

        return [
            random_scalar(
                value_type,
                rng,
                minimum=component(minimum, index),
                maximum=component(maximum, index),
                probability=probability,
                enum_items=enum_items,
                enum_flag=enum_flag,
            )
            for index in range(array_length)
        ]
    return random_scalar(
        value_type,
        rng,
        minimum=minimum,
        maximum=maximum,
        probability=probability,
        enum_items=enum_items,
        enum_flag=enum_flag,
    )
