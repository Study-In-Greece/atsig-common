from datetime import date, datetime
from zoneinfo import ZoneInfo

# The time of Greece, for the dates that users and calls live by. A container runs in
# UTC, where `date.today()` is the previous day from 00:00 to 03:00 in Greece.
ATHENS = ZoneInfo("Europe/Athens")


def today_athens() -> date:
    """The date today in Greece, whatever the time zone of the process is."""
    return datetime.now(ATHENS).date()
