import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import click
import requests
from dotenv import load_dotenv

from friskis_booker.api import BRPClient
from friskis_booker.booker import (
    ALLOWED_ACTIVITIES,
    LOCATIONS,
    WEEKDAYS,
    TZ,
    load_schedule,
    parse_dt,
    run_booking,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

USERS = ["peter", "alexandra"]
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
WORKER_URL = os.environ.get("WORKER_URL", "https://friskis-schedule.peter-schon1974.workers.dev")
WORKER_PIN = os.environ.get("WORKER_PIN", "")


def get_credentials(user: str) -> tuple[str, str]:
    suffix = user.upper()
    username = os.environ.get(f"FRISKIS_USERNAME_{suffix}", "")
    password = os.environ.get(f"FRISKIS_PASSWORD_{suffix}", "")
    if not username and user == "peter":
        username = os.environ.get("FRISKIS_USERNAME", "")
    if not password and user == "peter":
        password = os.environ.get("FRISKIS_PASSWORD", "")
    if not username or not password:
        click.echo(f"Sätt FRISKIS_USERNAME_{suffix} och FRISKIS_PASSWORD_{suffix} som miljövariabler eller i .env")
        sys.exit(1)
    return username, password


def worker_get(path, params=None):
    """GET from worker API."""
    if not WORKER_PIN:
        return None
    try:
        resp = requests.get(f"{WORKER_URL}{path}", params=params,
                            headers={"X-Pin": WORKER_PIN}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def worker_put(path, data, params=None):
    """PUT to worker API."""
    if not WORKER_PIN:
        return None
    try:
        resp = requests.put(f"{WORKER_URL}{path}", json=data, params=params,
                            headers={"X-Pin": WORKER_PIN, "Content-Type": "application/json"},
                            timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def load_schedule_for_user(user, schedule_path=None):
    """Load schedule: try worker API first, fall back to local file."""
    if schedule_path:
        return load_schedule(schedule_path)
    data = worker_get("/schedule", params={"user": user})
    if data and "schedule" in data:
        log.info("Schema hämtat från KV (%d poster)", len(data["schedule"]))
        return data["schedule"]
    local_path = CONFIG_DIR / f"{user}.json"
    if local_path.exists():
        log.info("Fallback: läser schema från lokal fil")
        return load_schedule(str(local_path))
    return []


def get_schedule_path(user: str) -> Path:
    return CONFIG_DIR / f"{user}.json"


user_option = click.option(
    "--user", type=click.Choice(USERS), default="peter",
    help="Vilken användare (default: peter)",
)


@click.group()
def cli():
    """Friskis & Svettis auto-booker."""


@cli.command()
@click.option("--schedule", "schedule_path", default=None, help="Sökväg till schedule.json")
@click.option("--dry-run", is_flag=True, help="Visa vad som skulle bokas utan att boka")
@user_option
def book(schedule_path, dry_run, user):
    """Boka schemalagda pass."""
    username, password = get_credentials(user)
    schedule = load_schedule_for_user(user, schedule_path)

    if not schedule:
        click.echo(f"Inget schema för {user}.")
        return

    client = BRPClient()
    client.login(username, password)
    click.echo(f"Inloggad som {username} (användare: {user})")

    results = run_booking(client, schedule, dry_run=dry_run)

    if not results:
        click.echo("Inga matchande pass hittades.")
    for r in results:
        click.echo(f"  {r['activity']} {r['time']} — {r['status']}")


@cli.command("list")
@click.option("--schedule", "schedule_path", default=None, help="Sökväg till schedule.json")
@user_option
def list_schedule(schedule_path, user):
    """Visa konfigurerat schema."""
    schedule = load_schedule_for_user(user, schedule_path)
    click.echo(f"Konfigurerat schema för {user}:")
    for entry in schedule:
        day = WEEKDAYS[entry["weekday"] - 1]
        time = entry.get("time", "—")
        click.echo(f"  {day} {time} — {entry['name']}")


@cli.command()
@click.option("--schedule", "schedule_path", default=None, help="Sökväg till schedule.json")
@user_option
def check(schedule_path, user):
    """Visa tillgängliga pass utan att boka."""
    username, password = get_credentials(user)
    schedule = load_schedule_for_user(user, schedule_path)

    client = BRPClient()
    client.login(username, password)
    click.echo(f"Inloggad som {username} (användare: {user})")

    results = run_booking(client, schedule, dry_run=True)

    if not results:
        click.echo("Inga matchande pass hittades.")
    for r in results:
        click.echo(f"  {r['activity']} {r['time']} — {r['status']}")


def save_schedule(schedule, user, sync=True):
    """Save schedule locally and sync to KV."""
    schedule_path = get_schedule_path(user)
    with open(schedule_path, "w") as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)
    click.echo(f"\nSparat lokalt till {schedule_path}")
    if sync:
        result = worker_put("/schedule", {"schedule": schedule}, params={"user": user})
        if result and result.get("ok"):
            click.echo("Synkat till KV!")
        else:
            click.echo("Varning: kunde inte synka till KV.")


def fetch_available_activities(client):
    now = datetime.now(TZ)
    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=7)).strftime("%Y-%m-%d")

    all_activities = []
    for loc in LOCATIONS:
        bid = client.get_business_unit_id(loc)
        if bid is None:
            continue
        for a in client.get_group_activities(bid, start, end):
            all_activities.append((a, loc))

    by_day = {}
    for a, loc_name in all_activities:
        if a.get("cancelled"):
            continue
        name = a.get("name", "")
        if not any(allowed in name.lower() for allowed in ALLOWED_ACTIVITIES):
            continue
        start_str = a.get("duration", {}).get("start", "")
        if not start_str:
            continue
        dt = parse_dt(start_str).astimezone(TZ)
        day_key = dt.isoweekday()
        by_day.setdefault(day_key, []).append((dt, a, loc_name))

    choices = []
    seen = set()
    for day in sorted(by_day.keys()):
        for dt, a, loc_name in sorted(by_day[day], key=lambda x: x[0]):
            name = a.get("name", "?")
            time_str = dt.strftime("%H:%M")
            key = (day, name, time_str, loc_name)
            if key in seen:
                continue
            seen.add(key)
            choices.append({"weekday": day, "name": name, "time": time_str, "location": loc_name})
    return choices


def entry_key(e):
    return (e["weekday"], e["name"].lower(), e.get("time", ""), e.get("location", "").lower())


def print_schedule(schedule, header="Nuvarande schema"):
    if not schedule:
        click.echo(f"\n{header}: (tomt)")
        return
    click.echo(f"\n{header}:")
    for e in sorted(schedule, key=lambda e: (e["weekday"], e.get("time", ""))):
        day = WEEKDAYS[e["weekday"] - 1]
        click.echo(f"  {day} {e.get('time', '—')} — {e['name']} ({e.get('location', '?')})")


@cli.command()
@click.option("--sync/--no-sync", default=True, help="Synka till KV")
@user_option
def add(sync, user):
    """Lägg till pass i schemat."""
    username, password = get_credentials(user)
    client = BRPClient()
    client.login(username, password)

    current = load_schedule_for_user(user)
    current_set = {entry_key(e) for e in current}

    print_schedule(current)

    click.echo("\nHämtar tillgängliga pass...")
    all_choices = fetch_available_activities(client)

    available = [c for c in all_choices if entry_key(c) not in current_set]

    if not available:
        click.echo("Alla tillgängliga pass finns redan i schemat.")
        return

    click.echo("\nLägg till pass:\n")
    for i, c in enumerate(available, 1):
        day = WEEKDAYS[c["weekday"] - 1]
        click.echo(f"  {i:2d}. {day:8s} {c['time']}  {c['name']:25s} ({c['location']})")

    click.echo("\nVälj pass att lägga till (kommaseparerade nummer, Enter för att avbryta):")
    raw = input("> ").strip()

    if not raw:
        click.echo("Avbryter.")
        return

    to_add = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            click.echo(f"Ogiltigt: {part}")
            return
        idx = int(part)
        if idx < 1 or idx > len(available):
            click.echo(f"Utanför intervall: {idx}")
            return
        c = available[idx - 1]
        to_add.append({"weekday": c["weekday"], "name": c["name"], "time": c["time"], "location": c["location"]})

    updated = current + to_add
    print_schedule(updated, "Uppdaterat schema")
    save_schedule(updated, user, sync)


@cli.command()
@click.option("--sync/--no-sync", default=True, help="Synka till KV")
@user_option
def remove(sync, user):
    """Ta bort pass från schemat."""
    current = load_schedule_for_user(user)

    if not current:
        click.echo("Schemat är tomt.")
        return

    click.echo(f"\nNuvarande schema för {user}:\n")
    sorted_schedule = sorted(current, key=lambda e: (e["weekday"], e.get("time", "")))
    for i, e in enumerate(sorted_schedule, 1):
        day = WEEKDAYS[e["weekday"] - 1]
        click.echo(f"  {i:2d}. {day:8s} {e.get('time', '—')}  {e['name']:25s} ({e.get('location', '?')})")

    click.echo("\nVälj pass att ta bort (kommaseparerade nummer, Enter för att avbryta):")
    raw = input("> ").strip()

    if not raw:
        click.echo("Avbryter.")
        return

    to_remove = set()
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            click.echo(f"Ogiltigt: {part}")
            return
        idx = int(part)
        if idx < 1 or idx > len(sorted_schedule):
            click.echo(f"Utanför intervall: {idx}")
            return
        to_remove.add(idx - 1)

    updated = [e for i, e in enumerate(sorted_schedule) if i not in to_remove]
    print_schedule(updated, "Uppdaterat schema")
    save_schedule(updated, user, sync)


@cli.command("dump-activities")
@click.option("--sync/--no-sync", default=True, help="Synka till KV")
def dump_activities(sync):
    """Hämta tillgängliga pass och synka till KV."""
    username, password = get_credentials("peter")
    client = BRPClient()
    client.login(username, password)

    click.echo("Hämtar tillgängliga pass...")
    activities = fetch_available_activities(client)

    activities_path = CONFIG_DIR / "activities.json"
    with open(activities_path, "w") as f:
        json.dump(activities, f, indent=2, ensure_ascii=False)
    click.echo(f"Sparade {len(activities)} pass lokalt")

    if sync:
        result = worker_put("/activities", {"activities": activities})
        if result and result.get("ok"):
            click.echo("Synkat till KV!")
        else:
            click.echo("Varning: kunde inte synka till KV.")


@cli.command("dump-bookings")
@user_option
@click.option("--sync/--no-sync", default=True, help="Synka till KV")
def dump_bookings(user, sync):
    """Hämta bokade pass och synka till KV."""
    username, password = get_credentials(user)
    client = BRPClient()
    client.login(username, password)

    click.echo(f"Hämtar bokade pass för {user}...")
    raw_bookings = client.get_bookings()

    bookings = []
    for b in raw_bookings:
        ga = b.get("groupActivity")
        if not ga or not isinstance(ga, dict):
            continue
        start_str = b.get("duration", {}).get("start", "")
        if not start_str:
            continue
        dt = parse_dt(start_str).astimezone(TZ)
        name = ga.get("name", "?")
        location = b.get("businessUnit", {}).get("name", "")
        booking_type = b.get("type", "")
        waiting_pos = None
        if booking_type == "waitingListBooking":
            waiting_pos = b.get("waitingListBooking", {}).get("waitingListPosition")
        bookings.append({
            "name": name,
            "date": dt.strftime("%Y-%m-%d"),
            "weekday": dt.isoweekday(),
            "time": dt.strftime("%H:%M"),
            "location": location,
            "waitingList": waiting_pos,
        })

    bookings.sort(key=lambda b: (b["date"], b["time"]))

    bookings_path = CONFIG_DIR / f"bookings-{user}.json"
    with open(bookings_path, "w") as f:
        json.dump(bookings, f, indent=2, ensure_ascii=False)
    click.echo(f"Sparade {len(bookings)} bokningar lokalt")

    if sync:
        result = worker_put("/bookings", {"bookings": bookings}, params={"user": user})
        if result and result.get("ok"):
            click.echo("Synkat till KV!")
        else:
            click.echo("Varning: kunde inte synka till KV.")
