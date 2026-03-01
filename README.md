# Friskis Auto-Booker

Automatisk bokning av gruppträningspass på Friskis & Svettis Jönköping.

## Setup

```bash
cd ~/friskis-booker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
# Redigera .env med dina credentials
```

## Användning

```bash
# Visa konfigurerat schema
python -m friskis_booker list

# Kolla tillgängliga pass (dry run)
python -m friskis_booker check

# Boka schemalagda pass
python -m friskis_booker book

# Dry run (visa utan att boka)
python -m friskis_booker book --dry-run
```

## Schema

Redigera `config/schedule.json` med dina önskade pass. Weekday: 1=Måndag, 7=Söndag.

## GitHub Actions

Lägg till `FRISKIS_USERNAME` och `FRISKIS_PASSWORD` som repository secrets. Workflowet körs automatiskt var 30:e minut 17-22 CET.
