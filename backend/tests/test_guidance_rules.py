from datetime import UTC, datetime

import pytest

from app.api.v1.history import parse_cursor
from app.core.errors import AppError
from app.services.guidance import add_years


def test_retention_clamps_leap_day_and_preserves_time_and_timezone():
    value = datetime(2024, 2, 29, 13, 30, tzinfo=UTC)
    assert add_years(value, 3) == datetime(2027, 2, 28, 13, 30, tzinfo=UTC)
    assert add_years(value, 4).day == 29


@pytest.mark.parametrize(
    "cursor", ["garbage", "e30", "W10", "bnVsbA", "////", "WyIxOTcwLTAxLTAxIiwibm90LXV1aWQiXQ"]
)
def test_malformed_cursors_are_safe_validation_errors(cursor):
    with pytest.raises(AppError) as error:
        parse_cursor(cursor)
    assert error.value.status == 422
