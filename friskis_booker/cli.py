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
    """Ändra listan med pass som ska autobokas varje vecka."""
    username, password = get_credentials()

    client = BRPClient()
    client.login(username, password)

    # Ladda befintligt schema
    schedule_path = Path(__file__).resolve().parent.parent / "config" / "schedule.json"
    current = load_schedule()
    current_keys = {
        (e["weekday"], e["name"].lower(), e.get("time", ""), e.get("location", "").lower())
        for e in current
    }

    # Hämta pass för idag + 7 dagar framåt (så vi alltid ser en hel vecka)
    now = datetime.now(TZ)
    start = now.strftime("%Y-%m-%d")
    end_date = now + timedelta(days=7)
    end = end_date.strftime("%Y-%m-%d")

    click.echo(f"Hämtar tillgängliga pass ({start} — {end})...")
    all_activities = []
    for loc in LOCATIONS:
        bid = client.get_business_unit_id(loc)
        if bid is None:
            continue
        for a in client.get_group_activities(bid, start, end):
            all_activities.append((a, loc))

    if not all_activities:
        click.echo("Inga pass hittades.")
        sys.exit(1)

    # Gruppera per dag, filtrera passnamn
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

    # Bygg valbar lista med unika pass
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
            is_selected = (day, name.lower(), time_str, loc_name.lower()) in current_keys
            choices.append({
                "weekday": day, "name": name, "time": time_str,
                "location": loc_name, "selected": is_selected,
            })

    if not choices:
        click.echo("Inga matchande pass hittades.")
        sys.exit(1)

    # Visa nuvarande schema
    if current:
        click.echo("\nNuvarande schema:")
        for e in current:
            day = WEEKDAYS[e["weekday"] - 1]
            click.echo(f"  {day} {e.get('time', '—')} — {e['name']} ({e.get('location', '?')})")

    # Visa alla pass, markera redan valda
    click.echo("\nTillgängliga pass (* = redan vald):\n")
    for i, c in enumerate(choices, 1):
        day = WEEKDAYS[c["weekday"] - 1]
        marker = "*" if c["selected"] else " "
        click.echo(f"  {marker} {i:2d}. {day:8s} {c['time']}  {c['name']:25s} ({c['location']})")

    # Bygg lista av redan valda nummer
    pre_selected = [str(i + 1) for i, c in enumerate(choices) if c["selected"]]
    pre_str = ",".join(pre_selected) if pre_selected else ""

    click.echo(f"\nVälj pass (kommaseparerade nummer, Enter för att behålla [{pre_str}]):")
    raw = input("> ").strip()

    if not raw:
        if pre_selected:
            raw = pre_str
        else:
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
        c = choices[idx - 1]
        selected.append({
            "weekday": c["weekday"], "name": c["name"],
            "time": c["time"], "location": c["location"],
        })

    click.echo("\nUppdaterat schema:")
    for s in selected:
        day = WEEKDAYS[s["weekday"] - 1]
        click.echo(f"  {day} {s['time']} — {s['name']} ({s['location']})")

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
