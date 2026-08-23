"""Datetime parsing and localization utilities for timezone-aware domain data."""
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Target timezone specified for the ParcelPilot dataset (Asia/Kolkata, UTC+05:30)
try:
    IST: tzinfo = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def parse_and_localize_datetime(
    value: Any,
    default_tz: tzinfo = IST,
) -> datetime | None:
    """Parse string or datetime object and ensure it is timezone-aware in the target timezone.
    
    Args:
        value: str, datetime, or None
        default_tz: Target timezone (defaults to Asia/Kolkata)
        
    Returns:
        Timezone-aware datetime in target timezone, or None if input is falsy.
    """
    if value is None:
        return None
    
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=default_tz)
        return value.astimezone(default_tz)
    
    if not isinstance(value, str):
        raise ValueError(f"Cannot parse datetime from type {type(value).__name__}: {value!r}")
    
    val_str = value.strip()
    if not val_str:
        return None
    
    # Handle explicit timezone suffix like '2026-08-16 11:00 Asia/Kolkata'
    target_tz_override = default_tz
    if " Asia/Kolkata" in val_str:
        val_str = val_str.replace(" Asia/Kolkata", "").strip()
        target_tz_override = IST
    elif " UTC" in val_str:
        val_str = val_str.replace(" UTC", "").strip()
        target_tz_override = timezone.utc

    # Try common datetime formats
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ]
    
    parsed_dt: datetime | None = None
    for fmt in formats:
        try:
            parsed_dt = datetime.strptime(val_str, fmt)
            break
        except ValueError:
            continue
            
    if parsed_dt is None:
        try:
            parsed_dt = datetime.fromisoformat(val_str)
        except ValueError as e:
            raise ValueError(f"Unrecognized datetime format: {value!r}") from e

    if parsed_dt.tzinfo is None:
        return parsed_dt.replace(tzinfo=target_tz_override).astimezone(default_tz)
    return parsed_dt.astimezone(default_tz)


def localize(value: datetime, tz: tzinfo = IST) -> datetime:
    """Ensure a datetime object is localized to the specified timezone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)
