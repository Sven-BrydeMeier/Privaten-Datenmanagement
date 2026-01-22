# Cloud-Sync Service Dokumentation

## Übersicht

Der Cloud-Sync-Service ermöglicht die automatische Synchronisation von Dokumenten aus Google Drive und Dropbox in das Datenmanagement-System.

**Hauptdatei:** `services/cloud_sync_service.py` (~5000 Zeilen)

## Architektur

```
┌─────────────────────────────────────────────────────────┐
│                    Cloud-Sync-Service                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │ Google Drive │    │   Dropbox    │    │  Resume    │ │
│  │    Sync      │    │    Sync      │    │  Manager   │ │
│  └──────┬───────┘    └──────┬───────┘    └─────┬──────┘ │
│         │                   │                   │        │
│         ▼                   ▼                   ▼        │
│  ┌─────────────────────────────────────────────────────┐│
│  │              Sync Engine (Generator)                 ││
│  │  - Batch-Verarbeitung                               ││
│  │  - Fortschrittsanzeige                              ││
│  │  - Fehlerbehandlung                                 ││
│  └─────────────────────────────────────────────────────┘│
│                           │                              │
│         ┌─────────────────┼─────────────────┐           │
│         ▼                 ▼                 ▼           │
│  ┌────────────┐   ┌────────────┐   ┌────────────────┐  │
│  │  Download  │   │    PDF     │   │   Supabase     │  │
│  │  Manager   │   │ Validation │   │    Storage     │  │
│  └────────────┘   └────────────┘   └────────────────┘  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Hauptkomponenten

### 1. CloudSyncService (Klasse)

Die Hauptklasse für alle Sync-Operationen.

```python
from services.cloud_sync_service import CloudSyncService

# Initialisierung
sync_service = CloudSyncService(user_id=1)

# Sync starten
result = sync_service.sync_connection(connection_id=1)

# Sync mit Fortschritt (Generator)
for progress in sync_service.sync_connection_with_progress(connection_id=1):
    print(f"Fortschritt: {progress['progress_percent']}%")
    print(f"Aktuelle Datei: {progress['current_file']}")
```

### 2. Resume-Funktionalität

Ermöglicht die Fortsetzung unterbrochener Syncs.

```python
from services.cloud_sync_service import (
    get_resume_info,
    get_all_interrupted_syncs,
    clear_resume_state
)

# Prüfen ob Resume möglich
resume_info = get_resume_info(connection_id=1, user_id=1)
if resume_info:
    print(f"Kann fortgesetzt werden ab Datei {resume_info['resume_from_index']}")
    print(f"Letzte erfolgreiche Datei: {resume_info['last_successful_file']}")

# Alle unterbrochenen Syncs eines Benutzers
interrupted = get_all_interrupted_syncs(user_id=1)
for sync in interrupted:
    print(f"Verbindung {sync['connection_id']}: {sync['progress_percent']}% abgeschlossen")
```

### 3. Adaptive Batch-Verarbeitung

Passt die Batch-Größe automatisch an die API-Geschwindigkeit an.

```python
from services.cloud_sync_service import calculate_adaptive_batch_size

# Berechnet optimale Batch-Größe basierend auf Verarbeitungszeiten
new_batch = calculate_adaptive_batch_size(
    connection_id=1,
    user_id=1,
    current_batch_size=50,
    recent_processing_times=[2.5, 3.1, 45.2, 60.0, 55.3]  # Sekunden pro Datei
)
# Bei langsamen Zeiten wird Batch reduziert (z.B. auf 25)
```

## Konfiguration

### SYNC_CONFIG (Zeile 529-551)

```python
SYNC_CONFIG = {
    "download_timeout": 120,           # Sekunden pro Download
    "api_timeout": 60,                 # Sekunden für API-Aufrufe
    "max_retries": 3,                  # Wiederholungsversuche
    "retry_delay_base": 2,             # Basis für Exponential Backoff
    "pause_between_files": 0.3,        # Pause zwischen Dateien
    "ram_warning_threshold_mb": 450,   # RAM-Warnschwelle
    "ram_critical_threshold_mb": 550,  # RAM-Abbruchschwelle
    "resume_max_age_hours": 24,        # Max. Alter für Resume
    "adaptive_min_batch_size": 10,     # Min. Batch-Größe
    "adaptive_max_batch_size": 200,    # Max. Batch-Größe
    "slow_file_threshold_seconds": 30, # Schwelle für "langsame" Datei
}
```

## Google Drive Sync

### Öffentliche Ordner (ohne OAuth)

Für öffentliche Google Drive Ordner wird nur ein API-Key benötigt:

```python
# Intern verwendete Methoden:

# 1. Ordner-ID aus Link extrahieren
folder_id = service._google_get_folder_id_from_link(
    "https://drive.google.com/drive/folders/1ABC123..."
)

# 2. Dateien sammeln (rekursiv durch Unterordner)
files = service._collect_google_drive_files_public(connection, session)

# 3. Einzelne Datei herunterladen
content = service._download_google_drive_file_public(file_id, api_key)
```

### Wichtige Methoden für Google Drive

| Methode | Zeilen | Beschreibung |
|---------|--------|--------------|
| `_google_get_folder_id_from_link()` | 1779-1820 | Extrahiert Folder-ID aus URL |
| `_google_list_folder_public()` | 1822-1890 | Listet Ordnerinhalt via API |
| `_collect_google_drive_files_public()` | 2050-2200 | Sammelt alle Dateien rekursiv |
| `_download_google_drive_file_public()` | 2433-2560 | Lädt einzelne Datei herunter |

### API-Key Konfiguration

```python
# In den Streamlit Secrets (.streamlit/secrets.toml):
[google]
api_key = "AIzaSy..."

# Oder in der Datenbank (CloudSyncConnection):
connection.access_token = "AIzaSy..."  # Für öffentliche Ordner
```

## Sync-Ablauf

### Phase 1: Scanning

```
1. Verbindung aus DB laden
2. Ordner-ID extrahieren
3. Alle Dateien rekursiv sammeln
4. Bereits synchronisierte Dateien filtern (via Hash)
5. Batch-Größe anwenden
```

### Phase 2: Downloading

```
1. Für jede Datei:
   a. Download starten
   b. PDF validieren (Header, EOF, Seiten)
   c. In Supabase Storage hochladen
   d. Dokument-Eintrag in DB erstellen
   e. Sync-Log schreiben
   f. Resume-Status speichern (alle 3 Dateien)
2. RAM-Check nach jeder Datei
3. Adaptive Pause bei API-Drosselung
```

### Phase 2.5: Retry

```
1. Fehlgeschlagene Dateien erneut versuchen
2. Längere Pausen zwischen Retries
3. Max. 1 Retry pro Datei in diesem Durchlauf
```

### Phase 3: Abschluss

```
1. Statistik zusammenfassen
2. Resume-Status löschen (bei Erfolg)
3. Diagnose-Bericht speichern
4. Connection-Status aktualisieren
```

## Diagnose-System

### SyncDiagnostics (Klasse, Zeilen 196-512)

Erfasst detaillierte Metriken während des Syncs:

```python
from services.cloud_sync_service import create_sync_diagnostics

diag = create_sync_diagnostics()
diag.start({"connection_id": 1})
diag.log_event("scan_start", "Starte Scan...")
diag.log_api_call("google_drive", "list_files", 250, True)
diag.capture_memory("after_file_100")
diag.finish(success=True, result_data={...})

# Bericht abrufen
report = diag.get_full_report()
analysis = diag.get_failure_analysis()
```

### Diagnose-Bericht Struktur

```json
{
  "summary": {
    "total_files": 1537,
    "files_processed": 166,
    "files_successful": 165,
    "duration_seconds": 1847.5
  },
  "memory": {
    "start_mb": 362.1,
    "end_mb": 378.4,
    "max_mb": 385.2,
    "growth_mb": 16.3
  },
  "api_stats": {
    "total_calls": 334,
    "failed_calls": 2,
    "avg_duration_ms": 1250.3
  },
  "events": [...],
  "errors": [...],
  "possible_causes": ["Container timeout", "API throttling"],
  "recommendations": ["Resume-Funktion nutzen", "Batch-Größe reduzieren"]
}
```

## Datenbank-Modelle

### CloudSyncConnection (extended_models.py)

```python
class CloudSyncConnection(Base):
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    provider = Column(Enum(CloudProvider))  # GOOGLE_DRIVE, DROPBOX

    # Authentifizierung
    access_token = Column(Text)      # OAuth Token oder API Key
    refresh_token = Column(Text)

    # Ordner
    remote_folder_path = Column(String(1000))
    remote_folder_id = Column(String(255))
    local_folder_id = Column(Integer, ForeignKey('folders.id'))

    # Einstellungen
    file_extensions = Column(JSON)   # [".pdf", ".jpg"]
    max_file_size_mb = Column(Integer, default=50)
    auto_sync_enabled = Column(Boolean, default=True)

    # Resume-Felder (NEU)
    resume_from_index = Column(Integer, default=0)
    resume_session_id = Column(String(50))
    resume_total_files = Column(Integer)
    resume_file_list_hash = Column(String(64))
    sync_interrupted_at = Column(DateTime)
    last_successful_file = Column(String(500))

    # Adaptive Sync
    adaptive_batch_size = Column(Integer, default=50)
    avg_file_processing_time = Column(Float)
    api_throttle_detected = Column(Boolean, default=False)
```

### CloudSyncLog (extended_models.py)

```python
class CloudSyncLog(Base):
    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey('cloud_sync_connections.id'))

    # Quelldatei
    remote_file_path = Column(String(1000))
    remote_file_id = Column(String(255))
    remote_file_hash = Column(String(64))  # Für Duplikaterkennung

    # Zieldatei
    document_id = Column(Integer, ForeignKey('documents.id'))

    # Status
    sync_status = Column(String(50))  # synced, skipped, error
    error_message = Column(Text)

    synced_at = Column(DateTime)
```

## Fehlerbehandlung

### Retry mit Exponential Backoff

```python
@retry_with_backoff(max_retries=3, base_delay=2.0)
def download_file(url):
    response = requests.get(url, timeout=120)
    return response.content
```

### Fehlertypen und Behandlung

| Fehler | Behandlung |
|--------|------------|
| 429 Too Many Requests | Exponential Backoff, Batch reduzieren |
| 500/503 Server Error | Retry nach Pause |
| Timeout | Resume-Status speichern, Batch beenden |
| RAM-Limit | Sync pausieren, Cache leeren |
| PDF korrupt | Überspringen, in failed_files speichern |

## Verwendung in der UI

### In Einstellungen (pages/8_⚙️_Einstellungen.py)

```python
from services.cloud_sync_service import CloudSyncService, get_all_interrupted_syncs

# Unterbrochene Syncs anzeigen
interrupted = get_all_interrupted_syncs(user_id)
if interrupted:
    st.warning(f"{len(interrupted)} unterbrochene Syncs gefunden")
    for sync in interrupted:
        if st.button(f"Fortsetzen: {sync['provider_name']}"):
            # Sync mit Resume starten
            service = CloudSyncService(user_id)
            for progress in service.sync_connection_with_progress(sync['connection_id']):
                progress_bar.progress(progress['progress_percent'] / 100)
```

## Performance-Tipps

1. **Batch-Größe**: Bei vielen Dateien mit 50-100 starten
2. **API-Key Quota**: Google Drive API hat 10.000 Anfragen/Tag Limit
3. **RAM**: Bei >500 Dateien regelmäßig Cache leeren
4. **Netzwerk**: Bei instabiler Verbindung kleinere Batches verwenden
5. **Resume**: Bei Streamlit Cloud immer aktiviert lassen

## Troubleshooting

### Sync stoppt ohne Fehler

- Prüfe Diagnose-Bericht in DB (`cloud_sync_diagnostics`)
- Wahrscheinlich Container-Timeout auf Streamlit Cloud
- Lösung: Resume nutzen, kleinere Batches

### Sehr langsame Downloads

- API-Drosselung durch Google
- Lösung: Längere Pausen, kleinere Batches, später erneut versuchen

### PDF-Validierung fehlgeschlagen

- Download möglicherweise unvollständig
- Lösung: Retry mit längerer Timeout
