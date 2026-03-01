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


@cli.command()
@click.option("--push/--no-push", default=True, help="Committa och pusha till GitHub")
def setup(push):
    """Välj pass för nästa vecka interaktivt."""
    username, password = get_credentials()

    client = BRPClient()
    client.login(username, password)

    # Hämta pass för nästa vecka (mån-sön) från alla locations
    now = datetime.now(TZ)
    days_until_monday = (7 - now.weekday()) % 7 or 7  # alltid nästa måndag
    next_monday = now + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)
    start = next_monday.strftime("%Y-%m-%d")
    end = next_sunday.strftime("%Y-%m-%d")

    click.echo(f"Hämtar pass för nästa vecka ({start} — {end})...")
    all_activities = []  # list of (activity, location_name)
    for loc in LOCATIONS:
        bid = client.get_business_unit_id(loc)
        if bid is None:
            click.echo(f"  Varning: hittade inte {loc}")
            continue
        for a in client.get_group_activities(bid, start, end):
            all_activities.append((a, loc))

    if not all_activities:
        click.echo("Inga pass publicerade för nästa vecka ännu. Passen dyker upp efter att denna veckas pass slutat.")
        sys.exit(1)

    # Gruppera per dag, filtrera datum och passnamn
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
        if dt.date() < next_monday.date() or dt.date() > next_sunday.date():
            continue
        day_key = dt.isoweekday()
        by_day.setdefault(day_key, []).append((dt, a, loc_name))

    # Visa unika pass (namn + veckodag + tid + location)
    seen = set()
    choices = []
    for day in sorted(by_day.keys()):
        for dt, a, loc_name in sorted(by_day[day], key=lambda x: x[0]):
            name = a.get("name", "?")
            time_str = dt.strftime("%H:%M")
            key = (day, name, time_str, loc_name)
            if key in seen:
                continue
            seen.add(key)
            choices.append({"weekday": day, "name": name, "time": time_str, "location": loc_name})

    if not choices:
        click.echo("Inga matchande pass hittades för nästa vecka.")
        sys.exit(1)

    click.echo("\nTillgängliga pass:\n")
    for i, c in enumerate(choices, 1):
        day = WEEKDAYS[c["weekday"] - 1]
        click.echo(f"  {i:2d}. {day:8s} {c['time']}  {c['name']:25s} ({c['location']})")

    click.echo(f"\nVälj pass att boka (kommaseparerade nummer, t.ex. 1,3,5):")
    raw = input("> ").strip()

    if not raw:
        click.echo("Inget valt, avbryter.")
        return

    selected = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            click.echo(f"Ogiltigt: {part}")
            return
        idx = int(part)
        if idx < 1 or idx > len(choices):
            click.echo(f"Utanför intervall: {idx}")
            return
        selected.append(choices[idx - 1])

    click.echo("\nDitt schema:")
    for s in selected:
        day = WEEKDAYS[s["weekday"] - 1]
        click.echo(f"  {day} {s['time']} — {s['name']} ({s['location']})")

    schedule_path = Path(__file__).resolve().parent.parent / "config" / "schedule.json"
    with open(schedule_path, "w") as f:
        json.dump(selected, f, indent=2, ensure_ascii=False)
    click.echo(f"\nSparat till {schedule_path}")

    if push:
        repo_root = Path(__file__).resolve().parent.parent
        subprocess.run(["git", "add", "config/schedule.json"], cwd=repo_root)
        subprocess.run(
            ["git", "commit", "-m", "Uppdatera schema"],
            cwd=repo_root,
        )
        subprocess.run(["git", "push"], cwd=repo_root)
        click.echo("Pushat till GitHub!")
