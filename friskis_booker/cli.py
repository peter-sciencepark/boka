import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import click
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


def get_credentials() -> tuple[str, str]:
    username = os.environ.get("FRISKIS_USERNAME", "")
    password = os.environ.get("FRISKIS_PASSWORD", "")
    if not username or not password:
        click.echo("Sätt FRISKIS_USERNAME och FRISKIS_PASSWORD som miljövariabler eller i .env")
        sys.exit(1)
    return username, password


@click.group()
def cli():
    """Friskis & Svettis auto-booker."""


@cli.command()
@click.option("--schedule", "schedule_path", default=None, help="Sökväg till schedule.json")
@click.option("--dry-run", is_flag=True, help="Visa vad som skulle bokas utan att boka")
def book(schedule_path, dry_run):
    """Boka schemalagda pass."""
    username, password = get_credentials()
    schedule = load_schedule(schedule_path)

    client = BRPClient()
    client.login(username, password)
    click.echo(f"Inloggad som {username}")

    results = run_booking(client, schedule, dry_run=dry_run)

    if not results:
        click.echo("Inga matchande pass hittades.")
    for r in results:
        click.echo(f"  {r['activity']} {r['time']} — {r['status']}")


@cli.command("list")
@click.option("--schedule", "schedule_path", default=None, help="Sökväg till schedule.json")
def list_schedule(schedule_path):
    """Visa konfigurerat schema."""
    schedule = load_schedule(schedule_path)
    click.echo("Konfigurerat schema:")
    for entry in schedule:
        day = WEEKDAYS[entry["weekday"] - 1]
        time = entry.get("time", "—")
        click.echo(f"  {day} {time} — {entry['name']}")


@cli.command()
@click.option("--schedule", "schedule_path", default=None, help="Sökväg till schedule.json")
def check(schedule_path):
    """Visa tillgängliga pass utan att boka."""
    username, password = get_credentials()
    schedule = load_schedule(schedule_path)

    client = BRPClient()
    client.login(username, password)
    click.echo(f"Inloggad som {username}")

    results = run_booking(client, schedule, dry_run=True)

    if not results:
        click.echo("Inga matchande pass hittades.")
    for r in results:
        click.echo(f"  {r['activity']} {r['time']} — {r['status']}")


SCHEDULE_PATH = Path(__file__).resolve().parent.parent / "config" / "schedule.json"


def save_and_push(schedule, push):
    with open(SCHEDULE_PATH, "w") as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)
    click.echo(f"\nSparat till {SCHEDULE_PATH}")
    if push:
        repo_root = Path(__file__).resolve().parent.parent
        subprocess.run(["git", "add", "config/schedule.json"], cwd=repo_root)
        subprocess.run(["git", "commit", "-m", "Uppdatera schema"], cwd=repo_root)
        subprocess.run(["git", "push"], cwd=repo_root)
        click.echo("Pushat till GitHub!")


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
@click.option("--push/--no-push", default=True, help="Committa och pusha till GitHub")
def add(push):
    """Lägg till pass i schemat."""
    username, password = get_credentials()
    client = BRPClient()
    client.login(username, password)

    current = load_schedule()
    current_set = {entry_key(e) for e in current}

    print_schedule(current)

    click.echo("\nHämtar tillgängliga pass...")
    all_choices = fetch_available_activities(client)

    # Visa bara pass som inte redan finns i schemat
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
    save_and_push(updated, push)


@cli.command()
@click.option("--push/--no-push", default=True, help="Committa och pusha till GitHub")
def remove(push):
    """Ta bort pass från schemat."""
    current = load_schedule()

    if not current:
        click.echo("Schemat är tomt.")
        return

    click.echo("\nNuvarande schema:\n")
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
    save_and_push(updated, push)
