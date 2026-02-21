"""Type coercion utilities for converting extracted strings to typed values."""

import re
from datetime import datetime, timezone
from typing import Any, Type


class CoercionError(Exception):
    """Raised when type coercion fails."""

    pass


class TypeCoercer:
    """Converts string values to typed Python values with smart coercion."""

    # Pattern for extracting numeric values
    NUMERIC_PATTERN = re.compile(r"[-+]?\d*\.?\d+")

    # Boolean true values (case-insensitive)
    TRUE_VALUES = frozenset({"true", "yes", "1", "on", "enabled"})
    FALSE_VALUES = frozenset({"false", "no", "0", "off", "disabled"})

    @classmethod
    def coerce(
        cls, value: str | list[str] | None, target_type: Type[Any], coerce_mode: bool = False
    ) -> Any:
        """Coerce a string value to the target type.

        Args:
            value: String value to coerce, or list of strings, or None
            target_type: Target Python type
            coerce_mode: If True, use aggressive coercion (e.g., extract numbers from "$19.99")

        Returns:
            Coerced value of target type

        Raises:
            CoercionError: If coercion fails
        """
        if value is None:
            return None

        # Handle list of values
        if isinstance(value, list):
            return [cls.coerce(v, target_type, coerce_mode) for v in value]

        # String type - no conversion needed
        if target_type is str:
            return value

        # Integer type
        if target_type is int:
            return cls._coerce_int(value, coerce_mode)

        # Float type
        if target_type is float:
            return cls._coerce_float(value, coerce_mode)

        # Boolean type
        if target_type is bool:
            return cls._coerce_bool(value)

        # Datetime type
        if target_type is datetime:
            return cls._coerce_datetime(value)

        # Unknown type - return as string
        return value

    @classmethod
    def _coerce_int(cls, value: str, coerce_mode: bool) -> int:
        """Coerce string to integer."""
        if coerce_mode:
            # Remove commas and extract numeric portion
            cleaned = value.replace(",", "")
            match = cls.NUMERIC_PATTERN.search(cleaned)
            if match:
                # Extract and convert to int (truncating decimals)
                return int(float(match.group()))
            raise CoercionError(f"Cannot extract integer from: {value}")
        else:
            # Strict mode - try direct conversion
            try:
                # Handle comma-separated numbers
                cleaned = value.replace(",", "")
                return int(cleaned)
            except ValueError:
                raise CoercionError(f"Cannot convert to int: {value}")

    @classmethod
    def _coerce_float(cls, value: str, coerce_mode: bool) -> float:
        """Coerce string to float."""
        if coerce_mode:
            # Remove commas and extract numeric portion
            cleaned = value.replace(",", "")
            match = cls.NUMERIC_PATTERN.search(cleaned)
            if match:
                return float(match.group())
            raise CoercionError(f"Cannot extract float from: {value}")
        else:
            # Strict mode - try direct conversion
            try:
                cleaned = value.replace(",", "")
                return float(cleaned)
            except ValueError:
                raise CoercionError(f"Cannot convert to float: {value}")

    @classmethod
    def _coerce_bool(cls, value: str) -> bool:
        """Coerce string to boolean."""
        lower = value.lower().strip()
        if lower in cls.TRUE_VALUES:
            return True
        if lower in cls.FALSE_VALUES:
            return False
        raise CoercionError(f"Cannot convert to bool: {value}")

    @classmethod
    def _coerce_datetime(cls, value: str) -> datetime:
        """Coerce string to datetime.

        Supports common formats:
        - ISO 8601: 2024-01-15T10:30:00
        - Date only: 2024-01-15
        - US format: 01/15/2024
        - European format: 15/01/2024
        """
        value = value.strip()

        # Try ISO format first
        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                # Normalise to UTC so all extracted datetimes are timezone-aware.
                # Format strings without a %z specifier produce naive datetimes;
                # treat them as UTC rather than leaving them naive.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        raise CoercionError(f"Cannot parse datetime: {value}")
