"""UTC timestamp conversion shared by persistence repositories."""
from datetime import datetime, timezone
from typing import Optional


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_timestamp(value: Optional[datetime]) -> Optional[str]:
    return ensure_utc(value).isoformat() if value is not None else None


def parse_timestamp(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value))
