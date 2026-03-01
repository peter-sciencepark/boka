from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from friskis_booker.api import BRPClient

TZ = ZoneInfo("Europe/Stockholm")
UTC = ZoneInfo("UTC")
WEEKDAYS = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"]

LOCATIONS = ["Jönköping - City", "Jönköping - Skeppsbron"]
ALLOWED_ACTIVITIES = [
    "hyrox hit",
    "hyrox cirkel",
    "skivstång",
    "skivstångintervall",
    "cirkelfys",
    "multifys skivstång",
]

log = logging.getLogger(__name__)


def parse_dt(s: str) -> datetime:
    """Parse ISO datetime, handling .000Z that Python 3.9 can't."""
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def load_schedule(path: str | None = None) -> list[dict]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "schedule.json"
    else:
        path = Path(path)
    with open(path) as f:
        return json.load(f)


def matches_entry(activity: dict, entry: dict, location: str | None = None) -> bool:
    name = activity.get("name", "")
    if entry["name"].lower() not in name.lower():
        return False

    if entry.get("location") and location:
        if entry["location"].lower() != location.lower():
            return False

    start_str = activity.get("duration", {}).get("start", "")
    if not start_str:
        return False

    start = parse_dt(start_str).astimezone(TZ)
    if start.isoweekday() != entry["weekday"]:
        return False

    if entry.get("time"):
        expected = entry["time"]
        actual = start.strftime("%H:%M")
        if actual != expected:
            return False

    return True


def is_bookable(activity: dict) -> tuple[bool, str]:
    now = datetime.now(TZ)

    cancelled = activity.get("cancelled", False)
    if cancelled:
        return False, "inställt"

    slots = activity.get("slots", {})
    total = slots.get("total", 0)
    booked = slots.get("booked", 0)
    if total > 0 and booked >= total:
        return False, "fullbokat"

    earliest_str = activity.get("bookableEarliest", "")
    if earliest_str:
        earliest = parse_dt(earliest_str)
        if earliest.tzinfo is None:
            earliest = earliest.replace(tzinfo=TZ)
        if now < earliest:
            return False, f"öppnar {earliest.strftime('%Y-%m-%d %H:%M')}"

    latest_str = activity.get("bookableLatest", "")
    if latest_str:
        latest = parse_dt(latest_str)
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=TZ)
        if now > latest:
            return False, "bokning stängd"

    return True, "ok"


def run_booking(
    client: BRPClient,
    schedule: list[dict],
    dry_run: bool = False,
) -> list[dict]:
    now = datetime.now(TZ)
    days_until_monday = (7 - now.weekday()) % 7 or 7
    next_monday = now + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)
    start = next_monday.strftime("%Y-%m-%d")
    end = next_sunday.strftime("%Y-%m-%d")

    # Hämta pass från alla locations
    activities = []  # list of (activity, location_name)
    for loc in LOCATIONS:
        bid = client.get_business_unit_id(loc)
        if bid is None:
            log.warning("Kunde inte hitta business unit för %s", loc)
            continue
        for a in client.get_group_activities(bid, start, end):
            s = a.get("duration", {}).get("start", "")
            if s:
                dt = parse_dt(s).astimezone(TZ)
                if next_monday.date() <= dt.date() <= next_sunday.date():
                    activities.append((a, loc))
    log.info("Hämtade %d pass för nästa vecka (%s — %s)", len(activities), start, end)

    existing_bookings = client.get_bookings()
    booked_ids = set()
    for b in existing_bookings:
        ga = b.get("groupActivity")
        if ga:
            if isinstance(ga, dict):
                booked_ids.add(ga.get("id"))
            else:
                booked_ids.add(ga)

    results = []

    for entry in schedule:
        for activity, loc in activities:
            if not matches_entry(activity, entry, loc):
                continue

            act_id = activity["id"]
            act_name = activity.get("name", "?")
            act_start = activity.get("duration", {}).get("start", "?")

            if act_id in booked_ids:
                log.info("Redan bokad: %s %s", act_name, act_start)
                results.append({"activity": act_name, "time": act_start, "status": "redan bokad"})
                continue

            bookable, reason = is_bookable(activity)
            if not bookable:
                log.info("Ej bokningsbar: %s %s — %s", act_name, act_start, reason)
                results.append({"activity": act_name, "time": act_start, "status": reason})
                continue

            if dry_run:
                log.info("Dry run — skulle boka: %s %s", act_name, act_start)
                results.append({"activity": act_name, "time": act_start, "status": "dry run"})
                continue

            try:
                client.book_activity(act_id)
                log.info("Bokad: %s %s", act_name, act_start)
                results.append({"activity": act_name, "time": act_start, "status": "bokad"})
            except Exception as e:
                log.error("Misslyckades boka %s %s: %s", act_name, act_start, e)
                results.append({"activity": act_name, "time": act_start, "status": f"fel: {e}"})

    return results
