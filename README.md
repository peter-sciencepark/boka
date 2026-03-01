# Friskis Auto-Booker

Automatisk bokning av gruppträningspass på Friskis & Svettis Jönköping.

## Hur det fungerar

1. Du väljer vilka pass du vill ha med `friskis setup` (en gång i veckan)
2. GitHub Actions kör `friskis book` automatiskt och bokar nästa veckas pass
3. Bokning sker så fort passet blir bokningsbart (ca 30 min efter att denna veckas pass slutat)

Schemat är **veckoåterkommande** — samma pass bokas varje vecka tills du ändrar.

## Kommandon

Alla kommandon körs med `friskis` från terminalen.

| Kommando | Vad det gör |
|---|---|
| `friskis setup` | Välj/ändra vilka pass som ska autobokas. Visar veckans utbud, markerar redan valda med `*`. Sparar och pushar till GitHub. |
| `friskis list` | Visa ditt nuvarande schema (utan att kontakta API:t) |
| `friskis check` | Kolla om nästa veckas pass finns och om de går att boka |
| `friskis book` | Boka nästa veckas pass (körs av GitHub Actions, men kan köras manuellt) |
| `friskis book --dry-run` | Visa vad som skulle bokas utan att boka |

## Veckorutin

1. Kör `friskis setup` en gång i veckan (t.ex. söndag kväll)
2. Välj pass genom att skriva numren kommaseparerat (t.ex. `1,3,5`)
3. Tryck Enter utan att skriva något för att behålla befintligt schema
4. Schemat pushas automatiskt till GitHub — Actions tar hand om resten

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
