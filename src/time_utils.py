"""
Time utility with external NTP sync + HTTP fallback -> local clock.

Ensures all time-dependent functions (session detection, news calendar,
scan timestamps) use a reliable time source rather than relying on the
potentially wrong local PC clock.

Usage:
    from src.time_utils import now_epoch, now_gmtime, now_datetime, today_str

    ts = now_epoch()           # UTC epoch (float)
    gm = now_gmtime()          # UTC struct_time
    dt = now_datetime()        # UTC datetime
    d  = today_str()           # "YYYY-MM-DD" in UTC
"""

import json as _json
import logging as _logging
import socket as _socket
import struct as _struct
import time as _time
import urllib.request as _urllib_req
import urllib.error as _urllib_err
from datetime import datetime as _dt, timezone as _tz

_logger = _logging.getLogger("TimeUtils")

# -- NTP / HTTP config --
_NTP_SERVERS = ["pool.ntp.org", "time.google.com", "time.windows.com"]
_NTP_PORT = 123
_HTTP_URL = "https://worldtimeapi.org/api/timezone/Etc/UTC"

# NTP epoch (1900-01-01) to Unix epoch (1970-01-01) offset in seconds
_NTP_DELTA = 2208988800.0

# -- Cache --
_SYNC_INTERVAL = 300  # re-sync every 5 minutes
_ntp_offset: float = 0.0      # external_epoch - local_epoch
_last_sync: float = 0.0       # local time of last successful sync
_first_warning: bool = True   # only warn once about no sync


def _query_ntp() -> float | None:
    """Query an NTP server, return UTC epoch (float) or None on failure."""
    packet = b'\x1b' + 47 * b'\0'
    for server in _NTP_SERVERS:
        try:
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(packet, (server, _NTP_PORT))
            data, _addr = sock.recvfrom(1024)
            sock.close()
            # Transmit timestamp is at bytes 40-47 (unsigned 32-bit ints)
            t = _struct.unpack('!12I', data)[10]
            return float(t) - _NTP_DELTA
        except Exception:
            continue
    return None


def _query_http() -> float | None:
    """Query worldtimeapi.org, return UTC epoch (float) or None on failure."""
    try:
        req = _urllib_req.Request(
            _HTTP_URL,
            headers={"User-Agent": "InelidaMarketScan/1.0"},
        )
        with _urllib_req.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
            ts = data.get("unixtime")
            return float(ts) if ts else None
    except Exception:
        return None


def _sync() -> bool:
    """Attempt to synchronise with an external time source.

    Tries NTP first (precise), then HTTP (reliable through firewalls).
    Stores the offset between external time and local clock.
    Returns True if synchronisation succeeded.
    """
    global _ntp_offset, _last_sync, _first_warning

    now_local = _time.time()

    # -- NTP --
    ntp = _query_ntp()
    if ntp is not None:
        _ntp_offset = ntp - now_local
        _last_sync = now_local
        _first_warning = True  # reset warning after successful sync
        _logger.debug("NTP synced: offset=%.3fs", _ntp_offset)
        return True

    # -- HTTP fallback --
    http = _query_http()
    if http is not None:
        _ntp_offset = http - now_local
        _last_sync = now_local
        _first_warning = True
        _logger.debug("HTTP synced: offset=%.3fs", _ntp_offset)
        return True

    if _first_warning:
        _logger.warning(
            "No external time source available (NTP + HTTP both failed). "
            "Using local PC clock. Check firewall/network."
        )
        _first_warning = False
    _last_sync = now_local  # mark attempt even on failure, avoid retry spam
    return False


def now_epoch() -> float:
    """Return current UTC epoch (seconds since 1970-01-01).

    Synchronised with NTP/HTTP when possible, falling back to local clock.
    The first call triggers synchronisation; subsequent calls reuse the
    cached offset and re-sync every 5 minutes.
    """
    global _ntp_offset, _last_sync

    now_local = _time.time()

    # Sync if never attempted or interval expired
    if _last_sync == 0.0 or (now_local - _last_sync) > _SYNC_INTERVAL:
        _sync()

    if _last_sync > 0 and _ntp_offset != 0.0:
        return now_local + _ntp_offset
    return now_local


def now_gmtime() -> _time.struct_time:
    """Return current UTC time as a struct_time (like time.gmtime())."""
    return _time.gmtime(now_epoch())


def now_datetime() -> _dt:
    """Return current UTC datetime."""
    return _dt.fromtimestamp(now_epoch(), tz=_tz.utc)


def today_str() -> str:
    """Return current UTC date as 'YYYY-MM-DD'."""
    return _time.strftime("%Y-%m-%d", now_gmtime())


def ntp_offset() -> float:
    """Return the current NTP offset (external - local) in seconds.

    Positive = local clock is behind external time.
    Negative = local clock is ahead.
    Returns 0.0 if never synced.
    """
    return _ntp_offset


# -- Market Hours (Forex) --------------------------------------------------------

# Forex market: open Sunday 22:00 UTC → Friday 22:00 UTC
_MARKET_OPEN_HOUR = 22       # Sunday open hour (UTC)
_MARKET_CLOSE_WEEKDAY = 4    # Friday
_MARKET_CLOSE_HOUR = 22      # Friday close hour (UTC)


def is_weekend() -> bool:
    """Return True if it is Saturday or Sunday (UTC)."""
    return now_datetime().weekday() >= 5


def is_market_open() -> bool:
    """Return True if the Forex market is currently open.

    Forex market hours: Sunday 22:00 UTC → Friday 22:00 UTC.
    Closed on weekends and during the Friday-Sunday gap.
    """
    dt = now_datetime()
    wd = dt.weekday()  # 0=Monday, 6=Sunday
    h = dt.hour

    # Saturday: always closed
    if wd == 5:
        return False
    # Sunday: closed before 22:00 UTC
    if wd == 6 and h < _MARKET_OPEN_HOUR:
        return False
    # Friday: closed after 22:00 UTC
    if wd == 4 and h >= _MARKET_CLOSE_HOUR:
        return False
    return True


def market_status() -> dict:
    """Return a comprehensive market status dictionary.

    Keys:
        utc_epoch: current UTC epoch
        utc_iso:   ISO 8601 datetime string
        weekday:   0=Monday .. 6=Sunday
        weekday_name: 'Monday' .. 'Sunday'
        hour_utc:  current UTC hour (0-23)
        date_utc:  'YYYY-MM-DD'
        is_weekend: bool
        is_market_open: bool
        next_open_epoch: epoch of next market open (if closed now)
        next_close_epoch: epoch of next market close (if open now)
    """
    dt = now_datetime()
    wd = dt.weekday()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    status = {
        "utc_epoch": dt.timestamp(),
        "utc_iso": dt.isoformat(),
        "weekday": wd,
        "weekday_name": days[wd],
        "hour_utc": dt.hour,
        "date_utc": dt.strftime("%Y-%m-%d"),
        "is_weekend": wd >= 5,
        "is_market_open": is_market_open(),
    }

    # Compute next open/close
    if not status["is_market_open"]:
        # Market is closed → when does it next open?
        if wd == 5:  # Saturday
            # Next open: Sunday 22:00 UTC
            next_open = dt.replace(hour=_MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
            # Sunday = weekday 6
            days_until_sunday = 1
            from datetime import timedelta as _td
            next_open += _td(days=days_until_sunday)
        elif wd == 6 and dt.hour < _MARKET_OPEN_HOUR:
            # Sunday before 22h → opens today at 22:00
            next_open = dt.replace(hour=_MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
        elif wd == 4 and dt.hour >= _MARKET_CLOSE_HOUR:
            # Friday after 22h → opens Sunday 22:00
            next_open = dt.replace(hour=_MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
            from datetime import timedelta as _td
            next_open += _td(days=2)  # skip to Sunday
        else:
            # Monday-Thursday before market close but is_market_open=False?
            # Shouldn't happen, but fallback
            next_open = dt.replace(hour=_MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
        status["next_open_epoch"] = next_open.timestamp()
        status["next_open_iso"] = next_open.isoformat()
    else:
        # Market is open → when does it close?
        if wd <= 3:  # Monday(0) through Thursday(3)
            # Closes Friday 22:00
            next_close = dt.replace(hour=_MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
            from datetime import timedelta as _td
            days_until_friday = 4 - wd  # Friday = weekday 4
            next_close += _td(days=days_until_friday)
        elif wd == 4:  # Friday — closes today at 22:00 (if before)
            next_close = dt.replace(hour=_MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
            # If already past 22:00, is_market_open would have returned False
        else:  # Sunday (wd=6) after 22h — just opened, next close is Friday 22:00
            # Friday is 4, Sunday is 6 → (4 - 6) % 7 = 5 days
            next_close = dt.replace(hour=_MARKET_CLOSE_HOUR, minute=0, second=0, microsecond=0)
            from datetime import timedelta as _td
            next_close += _td(days=5)
        status["next_close_epoch"] = next_close.timestamp()
        status["next_close_iso"] = next_close.isoformat()

    return status
