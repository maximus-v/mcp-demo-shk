# MCP-Demo SHK

Eigenständige Django-Anwendung für einen fiktiven **Sanitär-Heizung-Klima-Betrieb**
(„Acp SHK Betrieb"), die ihre Projekt-, Zeit-, Material- und Kostendaten über einen
**MCP-Server** (Model Context Protocol) bereitstellt – **lesend und schreibend**.
Ein Chatbot (z. B. Claude Web Client) kann darüber:

- **Monteur-Sicht:** das Projekttagebuch natürlichsprachig erfassen (Stunden, Material, Fortschritt),
- **Meister-Sicht:** Auswertungen ziehen (Verzug, schwache Projekttypen, Budgetrisiko) und
  abgeschlossene Vorgänge abrechnen (HTML-Rechnung).

**Live:** https://maxvorhauer.pythonanywhere.com · **MCP-Endpoint:** `https://maxvorhauer.pythonanywhere.com/mcp`

## Tech-Stack

- Python 3.13 (Produktion) / 3.10–3.14 lauffähig · Django 5.2
- `django-mcp-server` (Streamable-HTTP-Endpoint `/mcp`) · `mcp` SDK
- `python-dotenv` für Konfiguration · SQLite
- Docker (`gunicorn` + `whitenoise`) für ein containerisiertes Deployment

## Projektstruktur

| Pfad | Inhalt |
|------|--------|
| `mcp_demo/` | Django-Projekt (settings, urls, wsgi) |
| `shk/models.py` | Datenmodell (7 Modelle) + berechnete Properties; Betrieb als Konstanten |
| `shk/admin.py` | Admin-Pflegeoberfläche |
| `shk/mcp.py` | **MCP-Server**: 5 Tools + Serializer |
| `shk/views.py` · `shk/templates/shk/rechnung.html` | HTML-Rechnungs-View |
| `shk/management/commands/seed_demo.py` | Demo-Daten erzeugen / Fixture dumpen |
| `shk/management/commands/seed_beispielrechnung.py` | Beispielrechnung anlegen |
| `shk/fixtures/demo_seed.json` | versionierter Seed (20 Projekte, 10 Monteure, …) |

## Konfiguration (`.env`)

Werte werden aus einer **nicht eingecheckten** `.env` geladen (Vorlage: `.env.example`).
Secrets gehören nie ins Repo.

| Variable | Bedeutung | Default |
|----------|-----------|---------|
| `DJANGO_SECRET_KEY` | Secret Key. Leer → wird lokal in `.secret_key` erzeugt. | (auto) |
| `DJANGO_DEBUG` | `True` lokal, `False` in Produktion | `False` |
| `DJANGO_ALLOWED_HOSTS` | **kommagetrennt, ohne Klammern/Quotes**, z. B. `example.com,www.example.com` | leer (lokal: localhost) |

Secret Key generieren:
```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

## Lokales Setup

```bash
git clone https://github.com/maximus-v/mcp-demo-shk.git
cd mcp-demo-shk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # DJANGO_DEBUG=True für lokal
python manage.py migrate
python manage.py loaddata demo_seed
python manage.py createsuperuser
python manage.py runserver
```

URLs (lokal):
- Admin: http://127.0.0.1:8000/admin/
- Rechnung: http://127.0.0.1:8000/rechnung/<id>/
- MCP: http://127.0.0.1:8000/mcp

> In der eingecheckten lokalen `db.sqlite3` existiert bereits ein Superuser
> (`admin` / `admin@example.com`). Passwort unbekannt/vergessen? Zurücksetzen mit:
> ```bash
> python manage.py changepassword admin
> ```

## Mit Docker starten

Voraussetzung: Docker (inkl. `docker compose`). Auf macOS ohne Docker Desktop
reicht `docker` + [`colima`](https://github.com/abiosoft/colima)
(`brew install docker docker-compose colima`; bei
`... check if the daemon is running` einmalig `colima start` ausführen).

```bash
docker compose up --build
```

Das baut das Image und startet den Container. Beim ersten Start passiert
automatisch:

- Datenbank-Migration (`manage.py migrate`)
- Laden der Demo-Daten aus `shk/fixtures/demo_seed.json` (steuerbar über
  `DJANGO_SEED_DEMO` in `docker-compose.yml`, Standard: `"true"`)

Die Anwendung läuft danach unter **http://localhost:8000** (Admin unter
`/admin/`, MCP-Endpoint unter `/mcp`). Die SQLite-Datenbank liegt im
Docker-Volume `sqlite_data` (Pfad im Container: `/app/data/db.sqlite3`,
gesteuert über `DJANGO_DB_PATH`) und bleibt beim `down` erhalten.

Zum Stoppen: `Strg+C`, danach `docker compose down`.

**Superuser anlegen** (bei laufendem Container): Das Docker-Volume startet mit
einer leeren Datenbank, ein Superuser existiert dort also noch nicht.
```bash
docker compose exec web python manage.py createsuperuser
```

**Demo-Daten neu erzeugen / Beispielrechnung anlegen:**
```bash
docker compose exec web python manage.py seed_demo --flush
docker compose exec web python manage.py seed_beispielrechnung
```

**Konfiguration** (in `docker-compose.yml` voreingestellt, für eine echte
Bereitstellung anpassen):

| Variable | Bedeutung | Default in docker-compose.yml |
|---|---|---|
| `DJANGO_SECRET_KEY` | Geheimer Schlüssel für Sessions/CSRF | `change-me-in-production` – **unbedingt ändern** |
| `DJANGO_DEBUG` | Debug-Modus (im Container aus) | `False` |
| `DJANGO_ALLOWED_HOSTS` | Erlaubte Hostnamen, kommagetrennt | `localhost,127.0.0.1` |
| `DJANGO_DB_PATH` | Pfad der SQLite-Datei (Docker-Volume) | `/app/data/db.sqlite3` |
| `DJANGO_SEED_DEMO` | Demo-Daten beim Start laden | `true` |

## Lokal testen

**Berechnete Werte / Serializer (ohne MCP):**
```bash
python manage.py shell -c "from shk.mcp import build_projekt_status; import json; print(json.dumps(build_projekt_status()['aggregation_nach_projekttyp'], ensure_ascii=False, indent=2))"
```

**MCP-Endpoint per HTTP (Smoke-Test, initialize):**
```bash
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
```
Erwartung: JSON-RPC-Antwort mit `serverInfo: django_mcp_server`.

**Mit MCP Inspector (interaktiv):**
```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP → URL: http://127.0.0.1:8000/mcp
```

**Beispielrechnung anlegen** (für die Rechnungs-View):
```bash
python manage.py seed_beispielrechnung   # gibt View-Link + ID aus
```

> Hinweis: Wird `shk/mcp.py` oder ein neues Template/`templates/`-Verzeichnis neu
> angelegt, den Dev-Server einmal **neu starten** (Auto-Discovery / Template-Dirs
> werden beim Start eingelesen).

## Die fünf MCP-Tools

| Tool | Art | Zweck |
|------|-----|-------|
| `log_projekttagebuch` | schreibend | Tagebucheintrag + Material erfassen; bei Abschluss Vorgangsstatus setzen. Material muss aus dem Katalog stammen. |
| `get_projekt_status` | lesend | Überfällige / „aus dem Plan"-Vorgänge + Aggregation nach Projekttyp |
| `get_budget_status` | lesend | Kostenvoranschlag, Ist-Kosten, Budgetauslastung, gefährdete Projekte |
| `get_abrechenbare_vorgaenge` | lesend | Abgeschlossene, nicht abgerechnete Vorgänge mit Betragsaufschlüsselung + `vorgang_id` |
| `erstelle_rechnung` | schreibend | Finale Rechnung schreiben, Vorgang als abgerechnet markieren, View-Link liefern (Doppelabrechnung verhindert) |

## Test-Prompts (im Chatbot, nach Registrierung des MCP-Servers)

1. **Status/Verzug** – „Welche Projekte laufen aus dem Plan oder haben überfällige Vorgänge – und welcher Projekttyp läuft am schlechtesten?"
2. **Budget** – „Bei welchen Projekten wird das Budget eng? Zeig mir Soll, Ist und Auslastung."
3. **Abrechenbar** – „Was kann ich gerade abrechnen? Liste alle abgeschlossenen, noch nicht abgerechneten Vorgänge mit Beträgen."
4. **Erfassen (schreibend)** – „Trag ins Projekttagebuch ein: Ich (Mario) war heute auf der Baustelle Wettiner Str. 12 in Dresden, habe 6 Stunden an der Installation der Wärmepumpe gearbeitet und einen Pufferspeicher 300 L verbaut."
5. **Abrechnen (schreibend)** – „Erstelle die Rechnung für den ersten abrechenbaren Vorgang aus der vorigen Liste und gib mir den Link."

Empfohlene Demo-Reihenfolge: **1 → 2 → 3 → 5** (prüfen, dann abrechnen mit `vorgang_id` aus Schritt 3); **4** als Erfassungs-Story – danach zeigt ein erneutes `get_projekt_status`, dass die Arbeit sofort einfließt.

Gültige Beispieldaten: Monteure *Mario Köhler, Sven Bauer, Dennis Richter*; Katalog-Produkte
*Pufferspeicher 300 L, PV-Modul 430 Wp, Wärmepumpe Luft/Wasser 8 kW* (Fantasie-Produkte werden
bewusst abgelehnt).

## In den Claude Web Client einbinden

Settings → Connectors / Custom MCP server → URL eintragen:
```
https://maxvorhauer.pythonanywhere.com/mcp
```
Lokal (z. B. für Tests von außen) per Tunnel öffentlich machen: `ngrok http 8000` → `https://…/mcp`.

## Produktion (PythonAnywhere)

```bash
git clone https://github.com/maximus-v/mcp-demo-shk.git
cd mcp-demo-shk
python3.13 -m venv venv && source venv/bin/activate   # venv ist an die Python-Version gebunden
pip install -r requirements.txt

# .env anlegen
cat > .env <<'EOF'
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=maxvorhauer.pythonanywhere.com
DJANGO_SECRET_KEY=
EOF

python manage.py migrate
python manage.py loaddata demo_seed
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

**Web-Tab konfigurieren:**
- **Virtualenv:** `/home/maxvorhauer/mcp-demo-shk/venv`
- **WSGI-Datei** (`/var/www/maxvorhauer_pythonanywhere_com_wsgi.py`):
  ```python
  import os, sys
  path = '/home/maxvorhauer/mcp-demo-shk'
  if path not in sys.path:
      sys.path.insert(0, path)
  os.environ['DJANGO_SETTINGS_MODULE'] = 'mcp_demo.settings'   # Unterstrich!
  from django.core.wsgi import get_wsgi_application
  application = get_wsgi_application()
  ```
- **Static files:** Mapping `/static/` → `/home/maxvorhauer/mcp-demo-shk/staticfiles`
- Danach **Reload** klicken.

### Stolpersteine (gelöst)

- **`ModuleNotFoundError: No module named 'mcp-demo'`** → `DJANGO_SETTINGS_MODULE` muss
  `mcp_demo.settings` (Unterstrich) sein, nicht der Verzeichnisname `mcp-demo-shk`.
- **`400 Bad Request`** → `DJANGO_ALLOWED_HOSTS` fehlt oder ist falsch formatiert. Reiner
  Hostname, **ohne** `['...']`/Quotes: `DJANGO_ALLOWED_HOSTS=maxvorhauer.pythonanywhere.com`.
- **Admin ohne Styling** → `collectstatic` ausführen + Static-Mapping setzen.
- **Python-Version** → venv mit Python 3.13 erstellen (PythonAnywhere unterstützt kein 3.14);
  eine venv lässt sich nicht nachträglich umstellen, dann neu anlegen.
- **MCP-Streaming** → Auf PythonAnywhere (WSGI, keine WebSockets) funktionieren JSON-RPC-Requests;
  langlebige SSE-Streams können limitiert sein. Für intensiven Streaming-Betrieb eine
  ASGI-Plattform (Render/Fly.io/uvicorn) erwägen.

### Erreichbarkeit prüfen
```bash
curl -I https://maxvorhauer.pythonanywhere.com/admin/    # erwartet: 302 (→ Login)
```

## Datenmodell (Kurzüberblick)

Betrieb (Konstante) · Monteur ⇄ Projekt (M2M) · Projektvorgang → Projekt · Projekttagebuch →
Projekt/Vorgang/Monteur · Materialposition → Tagebuch/Produkt (**Produkt Pflicht**) · Rechnung →
Projekt/Vorgang. Ableitungen (Restaufwand, überfällig, „läuft aus dem Plan", Personal-/Material-/
Ist-Kosten, Budgetauslastung, Rechnungsbetrag, abrechenbar) werden **zur Laufzeit berechnet**.
Stundensatz 60 €, Werkstoffpauschale 10 % auf den Produkt-Verkaufspreis, 8 h/Arbeitstag.

## Seed-Daten

`seed_demo` erzeugt deterministisch (relativ zum Demo-Tag **09.06.2026**): 15 Produkte,
10 Monteure, 20 Projekte (50 % Privatperson/1 Monteur, 50 % Großbaustelle/mehrere Monteure)
mit gestaffeltem Reifegrad – inkl. überfälliger/„aus dem Plan"-/Budget-Fälle und abrechenbarer
Vorgänge. Wärmepumpe ist bewusst der schwächste Typ.

```bash
python manage.py seed_demo --flush                              # DB neu seeden
python manage.py seed_demo --flush --dump shk/fixtures/demo_seed.json   # + Fixture aktualisieren
python manage.py seed_demo --reference-date 2026-06-09          # Stichtag setzen
```
