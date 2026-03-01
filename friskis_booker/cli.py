import logging
import os
import sys

import click
from dotenv import load_dotenv

from friskis_booker.api import BRPClient
from friskis_booker.booker import WEEKDAYS, load_schedule, run_booking

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
