# Privates Datenmanagement System

Ein umfassendes Dokumenten- und Datenmanagement-System basierend auf Streamlit mit KI-Unterstützung, Cloud-Synchronisation und automatischer Dokumentenverarbeitung.

## Funktionen

### Dokumentenmanagement
- **Dokumentenaufnahme**: Upload, Scan und automatische Kategorisierung von Dokumenten
- **Intelligente Ordner**: Automatische Sortierung basierend auf Schlüsselwörtern und KI-Analyse
- **Volltextsuche**: Durchsuchbare PDFs mit OCR-Unterstützung
- **Dokument-Chat**: KI-gestützte Fragen zu Dokumenteninhalten (OpenAI/Anthropic)
- **Duplikaterkennung**: Automatische Erkennung und Zusammenführung von Duplikaten

### Finanzen
- **Rechnungsverwaltung**: Automatische Extraktion von Rechnungsdaten
- **Finanz-Dashboard**: Übersicht über Einnahmen, Ausgaben und Budgets
- **Steuer-Report**: Automatische Generierung von Steuerberichten
- **Kontenübersicht**: Verwaltung von Bankkonten und Transaktionen

### Organisation
- **Kalender**: Termine und Erinnerungen mit iCal-Integration
- **Verträge**: Verwaltung mit Kündigungsfristen und Erinnerungen
- **Abonnements**: Übersicht über wiederkehrende Zahlungen
- **Garantien**: Verfolgung von Garantiezeiten
- **Versicherungen**: Policenverwaltung mit Dokumentenzuordnung

### Weitere Funktionen
- **E-Mail-Integration**: IMAP-basierte E-Mail-Verwaltung mit Dokumentenanhängen
- **Kilometerlogbuch**: Für Dienstreisen mit automatischer Berechnung
- **Inventarverwaltung**: Hausrat und Wertgegenstände
- **Immobilienverwaltung**: Für Vermieter und Hausbesitzer
- **Diktierfunktion**: Sprachmemos und Transkription
- **Backup-System**: Lokale und Cloud-Backups

### Cloud-Synchronisation
- **Google Drive Sync**: Automatischer Import aus öffentlichen und privaten Ordnern
- **Dropbox Sync**: Unterstützung für Dropbox-Ordner
- **Resume-Funktionalität**: Fortsetzung unterbrochener Syncs
- **Adaptive Batch-Verarbeitung**: Automatische Anpassung bei API-Drosselung

## Installation

### Voraussetzungen

- Python 3.10 oder höher
- PostgreSQL-Datenbank (empfohlen: Supabase)
- Optional: Redis für Caching (empfohlen: Upstash)
- Optional: Tesseract OCR für Texterkennung

### 1. Repository klonen

```bash
git clone <repository-url>
cd Privaten-Datenmanagement
```

### 2. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

### 3. Umgebungsvariablen konfigurieren

Erstelle eine `.env` Datei oder konfiguriere die Streamlit Secrets (`.streamlit/secrets.toml`):

```toml
# Datenbank (Supabase)
[database]
url = "postgresql://user:password@host:port/database"

# Supabase Storage
[supabase]
url = "https://xxx.supabase.co"
key = "your-supabase-anon-key"
service_key = "your-supabase-service-key"

# KI-Services (optional)
[openai]
api_key = "sk-..."

[anthropic]
api_key = "sk-ant-..."

# Google Drive API (für Cloud-Sync)
[google]
api_key = "AIza..."

# Redis Cache (optional)
[redis]
url = "redis://..."
```

### 4. Datenbank initialisieren

Die Datenbank-Tabellen werden automatisch beim ersten Start erstellt.

### 5. Anwendung starten

```bash
streamlit run streamlit_app.py
```

Die Anwendung ist dann unter `http://localhost:8501` erreichbar.

## Projektstruktur

```
Privaten-Datenmanagement/
├── streamlit_app.py          # Hauptanwendung mit Login und Dashboard
├── requirements.txt          # Python-Abhängigkeiten
├── database/
│   ├── db.py                 # Datenbankverbindung und Migrationen
│   ├── models.py             # SQLAlchemy Basismodelle
│   └── extended_models.py    # Erweiterte Modelle (Sync, Subscriptions, etc.)
├── services/
│   ├── cloud_sync_service.py # Google Drive/Dropbox Synchronisation
│   ├── document_service.py   # Dokumentenverarbeitung
│   ├── ai_service.py         # KI-Integration (OpenAI/Anthropic)
│   ├── ocr_service.py        # OCR-Texterkennung
│   └── email_service.py      # E-Mail-Integration
├── pages/
│   ├── 0_🔎_Suche.py         # Volltextsuche
│   ├── 1_📊_Dashboard.py     # Übersichts-Dashboard
│   ├── 2_📄_Dokumentenaufnahme.py
│   ├── 3_📁_Dokumente.py
│   ├── 4_🔍_Intelligente_Ordner.py
│   ├── 5_📅_Kalender.py
│   ├── 6_📧_E-Mail.py
│   ├── 7_💰_Finanzen.py
│   ├── 8_⚙️_Einstellungen.py  # Cloud-Sync Konfiguration hier!
│   └── ...                   # Weitere Seiten
├── migrations/               # SQL-Migrationen
├── config/                   # Konfigurationsdateien
└── utils/                    # Hilfsfunktionen
```

## Cloud-Synchronisation

### Zuständige Datei

Die Cloud-Synchronisation (Google Drive, Dropbox) wird vollständig in dieser Datei verwaltet:

**`services/cloud_sync_service.py`** (~5000 Zeilen)

### Hauptfunktionen

| Funktion | Beschreibung |
|----------|--------------|
| `CloudSyncService` | Hauptklasse für Sync-Operationen |
| `sync_connection_with_progress()` | Sync mit Fortschrittsanzeige (Generator) |
| `_collect_google_drive_files_public()` | Sammelt Dateien aus öffentlichen Google Drive Ordnern |
| `_download_google_drive_file_public()` | Download einzelner Dateien |
| `get_resume_info()` | Prüft ob unterbrochener Sync fortgesetzt werden kann |
| `save_resume_state()` | Speichert aktuellen Sync-Status |

### Konfiguration

Die Cloud-Sync-Verbindungen werden in den **Einstellungen** (Seite 8) konfiguriert:

1. Google Drive Ordner-Link einfügen
2. Zielordner in der App auswählen
3. Dateifilter festlegen (PDF, Bilder, etc.)
4. Automatische Synchronisation aktivieren

### Google API Key

Für öffentliche Google Drive Ordner benötigen Sie einen API Key:

1. Google Cloud Console öffnen
2. Neues Projekt erstellen
3. Google Drive API aktivieren
4. API Key erstellen
5. In Einstellungen einfügen

## Entwicklung

### Lokale Entwicklung

```bash
# Virtuelle Umgebung erstellen
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Abhängigkeiten installieren
pip install -r requirements.txt

# App starten mit Auto-Reload
streamlit run streamlit_app.py --server.runOnSave true
```

### Migrationen

Neue Datenbankmigrationen werden automatisch beim Start ausgeführt. Manuelle Migrationen befinden sich in `migrations/`.

## Deployment

### Streamlit Cloud

1. Repository mit GitHub verbinden
2. Secrets in Streamlit Cloud konfigurieren
3. Deploy starten

### Docker (optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "streamlit_app.py"]
```

## Lizenz

Privates Projekt - Alle Rechte vorbehalten.

## Support

Bei Fragen oder Problemen erstellen Sie bitte ein Issue im Repository.
