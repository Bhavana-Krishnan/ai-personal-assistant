"""Generate a valid .ics file from all events (and task due dates).
Import it into Google Calendar / Apple Calendar / Outlook to get
real push-notifications / reminders on any device.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from . import db


def _utc(local_iso: str) -> datetime:
    dt = datetime.fromisoformat(local_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(db.TZ_NAME))
    return dt.astimezone(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _esc(s: str) -> str:
    return (s or "").replace("\\","\\\\").replace(";","\\;").replace(",","\\,").replace("\n","\\n")


def _fold(line: str) -> str:
    """RFC 5545 line folding: max 75 octets per line."""
    b, out = line.encode("utf-8"), []
    while len(b) > 74:
        cut = 74
        while cut > 0 and (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b" " + b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n".join(out)


def _vevent(uid, title, start_iso, end_iso, desc, remind_min, repeat="none") -> str:
    s = _utc(start_iso)
    e = _utc(end_iso) if end_iso else s + timedelta(minutes=30)
    if e <= s:
        e = s + timedelta(minutes=30)
    now = _fmt(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}@personal-assistant",
        f"DTSTAMP:{now}",
        f"DTSTART:{_fmt(s)}",
        f"DTEND:{_fmt(e)}",
        _fold(f"SUMMARY:{_esc(title)}"),
    ]
    if desc:
        lines.append(_fold(f"DESCRIPTION:{_esc(desc)}"))
    if repeat in ("daily","weekly","monthly"):
        lines.append(f"RRULE:FREQ={repeat.upper()}")
    if remind_min and int(remind_min) >= 0:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY",
                  _fold(f"DESCRIPTION:{_esc(title)}"),
                  f"TRIGGER:-PT{int(remind_min)}M", "END:VALARM"]
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def build_ics() -> str:
    parts = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Personal Assistant//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Personal Assistant",
        f"X-WR-TIMEZONE:{db.TZ_NAME}",
    ]
    for ev in db.rows("SELECT * FROM events"):
        parts.append(_vevent(f"ev-{ev['id']}", ev["title"], ev["start"], ev["end"],
                             ev["description"], ev["remind_minutes"], ev["repeat"]))
    for t in db.rows("SELECT * FROM tasks WHERE status='open' AND due IS NOT NULL AND due!=''"):
        due = t["due"] if "T" in t["due"] else t["due"] + "T09:00"
        parts.append(_vevent(f"task-{t['id']}", "Task: " + t["title"], due, None,
                             t["notes"], 30))
    parts.append("END:VCALENDAR")
    return "\r\n".join(parts) + "\r\n"
