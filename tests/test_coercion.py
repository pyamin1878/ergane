"""Tests for type coercion functionality."""

from datetime import datetime

import pytest

from ergane.schema.coercion import CoercionError, TypeCoercer


class TestStringCoercion:
    """Tests for string type coercion."""

    def test_string_passthrough(self):
        """String type returns value unchanged."""
        assert TypeCoercer.coerce("hello", str) == "hello"

    def test_string_with_coerce_mode(self):
        """String type ignores coerce mode."""
        assert TypeCoercer.coerce("hello", str, coerce_mode=True) == "hello"


class TestIntegerCoercion:
    """Tests for integer type coercion."""

    def test_simple_int(self):
        """Simple integer string converts correctly."""
        assert TypeCoercer.coerce("42", int) == 42

    def test_negative_int(self):
        """Negative integer string converts correctly."""
        assert TypeCoercer.coerce("-17", int) == -17

    def test_int_with_commas(self):
        """Integer with thousand separators converts correctly."""
        assert TypeCoercer.coerce("1,234", int) == 1234
        assert TypeCoercer.coerce("1,234,567", int) == 1234567

    def test_int_coerce_mode_extracts_number(self):
        """Coerce mode extracts integer from text."""
        assert TypeCoercer.coerce("$42", int, coerce_mode=True) == 42
        assert TypeCoercer.coerce("42 items", int, coerce_mode=True) == 42
        assert TypeCoercer.coerce("Item #123", int, coerce_mode=True) == 123

    def test_int_coerce_mode_truncates_decimal(self):
        """Coerce mode truncates decimal portion."""
        assert TypeCoercer.coerce("$19.99", int, coerce_mode=True) == 19

    def test_int_invalid_raises(self):
        """Invalid integer raises CoercionError."""
        with pytest.raises(CoercionError):
            TypeCoercer.coerce("not a number", int)

    def test_int_coerce_mode_no_number_raises(self):
        """Coerce mode with no extractable number raises."""
        with pytest.raises(CoercionError):
            TypeCoercer.coerce("no numbers here", int, coerce_mode=True)


class TestFloatCoercion:
    """Tests for float type coercion."""

    def test_simple_float(self):
        """Simple float string converts correctly."""
        assert TypeCoercer.coerce("3.14", float) == 3.14

    def test_negative_float(self):
        """Negative float string converts correctly."""
        assert TypeCoercer.coerce("-2.5", float) == -2.5

    def test_float_with_commas(self):
        """Float with thousand separators converts correctly."""
        assert TypeCoercer.coerce("1,234.56", float) == 1234.56

    def test_float_coerce_mode_extracts_number(self):
        """Coerce mode extracts float from price strings."""
        assert TypeCoercer.coerce("$19.99", float, coerce_mode=True) == 19.99
        assert TypeCoercer.coerce("Price: 42.50", float, coerce_mode=True) == 42.50

    def test_float_coerce_mode_currency(self):
        """Coerce mode handles currency formats."""
        assert TypeCoercer.coerce("USD 99.99", float, coerce_mode=True) == 99.99

    def test_float_invalid_raises(self):
        """Invalid float raises CoercionError."""
        with pytest.raises(CoercionError):
            TypeCoercer.coerce("not a number", float)


class TestBooleanCoercion:
    """Tests for boolean type coercion."""

    def test_true_values(self):
        """Various true string values convert to True."""
        for value in ["true", "True", "TRUE", "yes", "Yes", "1", "on", "enabled"]:
            assert TypeCoercer.coerce(value, bool) is True

    def test_false_values(self):
        """Various false string values convert to False."""
        for value in ["false", "False", "FALSE", "no", "No", "0", "off", "disabled"]:
            assert TypeCoercer.coerce(value, bool) is False

    def test_whitespace_handling(self):
        """Whitespace around boolean values is stripped."""
        assert TypeCoercer.coerce("  true  ", bool) is True
        assert TypeCoercer.coerce("  false  ", bool) is False

    def test_invalid_bool_raises(self):
        """Invalid boolean string raises CoercionError."""
        with pytest.raises(CoercionError):
            TypeCoercer.coerce("maybe", bool)


class TestDatetimeCoercion:
    """Tests for datetime type coercion."""

    def test_iso_format(self):
        """ISO 8601 format parses correctly and is UTC-aware."""
        from datetime import timezone
        result = TypeCoercer.coerce("2024-01-15T10:30:00", datetime)
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert result.tzinfo is not None

    def test_iso_format_with_microseconds(self):
        """ISO format with microseconds parses correctly."""
        result = TypeCoercer.coerce("2024-01-15T10:30:00.123456", datetime)
        assert result.microsecond == 123456
        assert result.tzinfo is not None

    def test_iso_format_with_z(self):
        """ISO format with Z suffix parses correctly and is UTC-aware."""
        from datetime import timezone
        result = TypeCoercer.coerce("2024-01-15T10:30:00Z", datetime)
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert result.tzinfo is not None

    def test_date_only(self):
        """Date-only format parses correctly and is UTC-aware."""
        from datetime import timezone
        result = TypeCoercer.coerce("2024-01-15", datetime)
        assert result == datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert result.tzinfo is not None

    def test_datetime_with_space(self):
        """Datetime with space separator parses correctly and is UTC-aware."""
        from datetime import timezone
        result = TypeCoercer.coerce("2024-01-15 10:30:00", datetime)
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert result.tzinfo is not None

    def test_us_date_format(self):
        """US date format (MM/DD/YYYY) parses correctly and is UTC-aware."""
        from datetime import timezone
        result = TypeCoercer.coerce("01/15/2024", datetime)
        assert result == datetime(2024, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert result.tzinfo is not None

    def test_invalid_datetime_raises(self):
        """Invalid datetime string raises CoercionError."""
        with pytest.raises(CoercionError):
            TypeCoercer.coerce("not a date", datetime)


class TestListCoercion:
    """Tests for list value coercion."""

    def test_list_of_strings(self):
        """List of strings is returned unchanged."""
        result = TypeCoercer.coerce(["a", "b", "c"], str)
        assert result == ["a", "b", "c"]

    def test_list_of_ints(self):
        """List of string integers converts to list of ints."""
        result = TypeCoercer.coerce(["1", "2", "3"], int)
        assert result == [1, 2, 3]

    def test_list_of_floats_with_coerce(self):
        """List of price strings converts to list of floats."""
        result = TypeCoercer.coerce(["$10.99", "$20.50"], float, coerce_mode=True)
        assert result == [10.99, 20.50]

    def test_empty_list(self):
        """Empty list returns empty list."""
        result = TypeCoercer.coerce([], str)
        assert result == []


class TestNoneHandling:
    """Tests for None value handling."""

    def test_none_returns_none(self):
        """None input returns None for all types."""
        assert TypeCoercer.coerce(None, str) is None
        assert TypeCoercer.coerce(None, int) is None
        assert TypeCoercer.coerce(None, float) is None
        assert TypeCoercer.coerce(None, bool) is None
        assert TypeCoercer.coerce(None, datetime) is None
