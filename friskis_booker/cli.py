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
from friskis_booker.booker import WEEKDAYS, TZ, load_schedule, parse_dt, run_booking

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

    business_unit_id = client.get_business_unit_id("Jönköping")
    if business_unit_id is None:
        click.echo("Kunde inte hitta Jönköping")
        sys.exit(1)

    # Hämta pass för nästa vecka (mån-sön)
    now = datetime.now(TZ)
    days_until_monday = (7 - now.weekday()) % 7 or 7  # alltid nästa måndag
    next_monday = now + timedelta(days=days_until_monday)
    next_sunday = next_monday + timedelta(days=6)
    start = next_monday.strftime("%Y-%m-%d")
    end = next_sunday.strftime("%Y-%m-%d")

    click.echo(f"Hämtar pass för nästa vecka ({start} — {end})...")
    activities = client.get_group_activities(business_unit_id, start, end)

    if not activities:
        click.echo("Inga pass publicerade för nästa vecka ännu. Passen dyker upp efter att denna veckas pass slutat.")
        sys.exit(1)

    # Gruppera per dag och sortera
    by_day = {}
    for a in activities:
        if a.get("cancelled"):
            continue
        start_str = a.get("duration", {}).get("start", "")
        if not start_str:
            continue
        dt = parse_dt(start_str).astimezone(TZ)
        # Filtrera bort pass som inte är nästa vecka
        if dt.date() < next_monday.date() or dt.date() > next_sunday.date():
            continue
        day_key = dt.isoweekday()
        by_day.setdefault(day_key, []).append((dt, a))

    # Visa unika pass (namn + veckodag + tid), deduplika över veckor
    seen = set()
    choices = []
    for day in sorted(by_day.keys()):
        for dt, a in sorted(by_day[day], key=lambda x: x[0]):
            name = a.get("name", "?")
            time_str = dt.strftime("%H:%M")
            key = (day, name, time_str)
            if key in seen:
                continue
            seen.add(key)
            choices.append({"weekday": day, "name": name, "time": time_str})

    click.echo("\nTillgängliga pass:\n")
    for i, c in enumerate(choices, 1):
        day = WEEKDAYS[c["weekday"] - 1]
        click.echo(f"  {i:2d}. {day:8s} {c['time']}  {c['name']}")

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

    # Lägg till location
    for s in selected:
        s["location"] = "Jönköping City"

    click.echo("\nDitt schema:")
    for s in selected:
        day = WEEKDAYS[s["weekday"] - 1]
        click.echo(f"  {day} {s['time']} — {s['name']}")

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
