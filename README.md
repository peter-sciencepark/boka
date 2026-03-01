# Friskis Auto-Booker

Automatisk bokning av gruppträningspass på Friskis & Svettis Jönköping.

## Hur det fungerar

1. Du väljer vilka pass du vill ha med `friskis add` och `friskis remove`
2. GitHub Actions kör `friskis book` automatiskt och bokar nästa veckas pass
3. Bokning sker så fort passet blir bokningsbart (ca 30 min efter att denna veckas pass slutat)

Schemat är **veckoåterkommande** — samma pass bokas varje vecka tills du ändrar.

## Kommandon

Alla kommandon körs med `friskis` från terminalen.

| Kommando | Vad det gör |
|---|---|
| `friskis add` | Visa tillgängliga pass och lägg till i schemat. Sparar och pushar till GitHub. |
| `friskis remove` | Visa schemat och välj pass att ta bort. Sparar och pushar till GitHub. |
| `friskis list` | Visa ditt nuvarande schema (utan att kontakta API:t) |
| `friskis check` | Kolla om nästa veckas pass finns och om de går att boka |
| `friskis book` | Boka nästa veckas pass (körs av GitHub Actions, men kan köras manuellt) |
| `friskis book --dry-run` | Visa vad som skulle bokas utan att boka |

## Veckorutin

1. Kör `friskis list` för att se vad du har
2. Kör `friskis add` för att lägga till nya pass (visar bara pass som inte redan finns i schemat)
3. Kör `friskis remove` för att ta bort pass du inte längre vill ha
4. Välj pass genom att skriva numren kommaseparerat (t.ex. `1,3,5`)
5. Schemat pushas automatiskt till GitHub — Actions tar hand om resten

## schedule.json — exempel

Du kan redigera `config/schedule.json` direkt på GitHub eller via `friskis add`/`friskis remove`. Varje pass har `weekday` (1=Måndag, 7=Söndag), `name`, `time` och `location`.

Kopiera och anpassa:

```json
[
  {"weekday": 1, "name": "Skivstång",          "time": "17:30", "location": "Jönköping - City"},
  {"weekday": 1, "name": "SkivstångIntervall",  "time": "18:30", "location": "Jönköping - Skeppsbron"},
  {"weekday": 2, "name": "Cirkelfys",           "time": "07:00", "location": "Jönköping - City"},
  {"weekday": 3, "name": "HYROX Hit",           "time": "06:30", "location": "Jönköping - City"},
  {"weekday": 4, "name": "Multifys skivstång",  "time": "17:30", "location": "Jönköping - City"},
  {"weekday": 5, "name": "Skivstång",           "time": "16:30", "location": "Jönköping - Skeppsbron"},
  {"weekday": 7, "name": "HYROX Cirkel",        "time": "16:30", "location": "Jönköping - City"}
]
```

Tillgängliga passnamn: `HYROX Hit`, `HYROX Cirkel`, `Skivstång`, `SkivstångIntervall`, `Cirkelfys`, `Multifys skivstång`.

**Tips:** Redigerar du direkt på GitHub, glöm inte komma `,` mellan varje objekt.

## Anläggningar och passfilter

Bokaren hämtar pass från:
- Jönköping - City
- Jönköping - Skeppsbron

Filtrerat till: Hyrox Hit, Hyrox Cirkel, Skivstång, Skivstång Intervall, Cirkelfys, Multifys skivstång.

Vill du ändra filter eller anläggningar, redigera `LOCATIONS` och `ALLOWED_ACTIVITIES` i `friskis_booker/booker.py`.

## GitHub Actions

Kör automatiskt:
- **07:50** varje morgon
- **Var 30:e minut 16:00–20:00** varje dag

Secrets som behövs i repot:
- `FRISKIS_USERNAME` — din e-post/personnummer
- `FRISKIS_PASSWORD` — ditt lösenord

Manuell trigger: `gh workflow run book.yml` eller via GitHub-webben.

## Installationsreferens

Om du behöver installera om:

```bash
cd ~/friskis-booker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
# Redigera .env med dina credentials
```

`friskis`-kommandot är en länk från `~/bin/friskis` → `~/friskis-booker/friskis`.
