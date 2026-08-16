from __future__ import annotations

import math


def _coordinate(value: object, *, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return None
    return number


def normalize_latitude(value: object) -> float | None:
    return _coordinate(value, minimum=-90.0, maximum=90.0)


def normalize_longitude(value: object) -> float | None:
    return _coordinate(value, minimum=-180.0, maximum=180.0)


def valid_coordinates(latitude: object, longitude: object) -> bool:
    return normalize_latitude(latitude) is not None and normalize_longitude(longitude) is not None
