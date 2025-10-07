"""Utility functions for working with match scoring data."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict


def resolve_weight_mapping(
    match_model: type[Any],
    attribute_name: str,
    default: Dict[str, float],
) -> Dict[str, float]:
    """Return a mapping of field names to weights for the given model."""

    mapping = getattr(match_model, attribute_name, None)
    if isinstance(mapping, dict) and mapping:
        resolved: Dict[str, float] = {}
        for key, value in mapping.items():
            try:
                resolved[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        if resolved:
            return resolved
    return {key: float(value) for key, value in default.items()}


def resolve_endgame_points_mapping(
    match_model: type[Any],
    attribute_name: str,
    default: Dict[str, float],
) -> Dict[str, float]:
    """Return the endgame point mapping for the given model."""

    mapping = getattr(match_model, attribute_name, None)
    if isinstance(mapping, dict) and mapping:
        resolved: Dict[str, float] = {}
        for key, value in mapping.items():
            try:
                resolved[str(key).upper()] = float(value)
            except (TypeError, ValueError):
                continue
        if resolved:
            return resolved
    return {key: float(value) for key, value in default.items()}


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Enum):
        value = value.value
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def calculate_phase_points(record: Any, weights: Dict[str, float]) -> float:
    return sum(to_float(getattr(record, field, 0)) * float(weight) for field, weight in weights.items())


def calculate_endgame_points(value: Any, mapping: Dict[str, float]) -> float:
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return 0.0

    normalized = str(value).upper()
    try:
        return float(mapping.get(normalized, mapping.get(str(value), 0.0)))
    except (TypeError, ValueError):
        return 0.0


def extract_field_value(record: Any, field_name: str) -> float:
    return to_float(getattr(record, field_name, 0))
