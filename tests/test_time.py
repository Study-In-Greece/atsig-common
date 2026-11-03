import datetime as dt
import time

import pytest

from atsig_common import time as athens_time


class Frozen(dt.datetime):
    instant: dt.datetime

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(athens_time, "datetime", Frozen)

    def at(utc: str) -> None:
        Frozen.instant = dt.datetime.fromisoformat(utc).replace(tzinfo=dt.UTC)

    return at


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        ("2026-12-31 22:30", "2027-01-01"),  # winter, UTC+2
        ("2026-12-31 21:30", "2026-12-31"),
        ("2026-06-30 21:30", "2026-07-01"),  # summer, UTC+3
        ("2026-06-30 20:30", "2026-06-30"),
    ],
)
def test_the_date_is_the_one_in_athens(frozen, utc, expected):
    frozen(utc)

    assert str(athens_time.today_athens()) == expected


def test_it_does_not_depend_on_the_time_zone_of_the_process(monkeypatch):
    # UTC+14 and UTC-11: `date.today()` differs between them for half of every day,
    # the date in Athens must not
    results = []
    for zone in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
        results.append(athens_time.today_athens())

    monkeypatch.undo()
    time.tzset()
    assert results[0] == results[1]
