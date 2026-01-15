"""
Cloud-Sync Service für Dropbox und Google Drive
Ermöglicht automatische Synchronisation von Dokumenten aus Cloud-Ordnern
"""
import os
import hashlib
import json
import logging
import traceback
from datetime import datetime, timedelta

# psutil ist optional (für Speicher-Monitoring)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import requests
from urllib.parse import urlencode, urlparse, parse_qs

import re
from bs4 import BeautifulSoup

from database.models import Document, Folder, DocumentStatus
from database.db import get_db
from database.extended_models import (
    CloudSyncConnection, CloudSyncLog, CloudProvider, SyncStatus, CloudSyncDiagnostic
)

# Streamlit Cache-Clearing (optional)
try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False
    st = None

logger = logging.getLogger(__name__)

# Flag für Heartbeat-Spalten-Verfügbarkeit (None = ungeprüft, True/False = Ergebnis)
# Ermöglicht graceful degradation wenn Migration nicht angewendet wurde
_HEARTBEAT_COLUMNS_AVAILABLE = None


def _check_heartbeat_columns_available() -> bool:
    """
    Prüft einmalig ob die Heartbeat-Spalten in der Datenbank existieren.
    Cached das Ergebnis im Modul-Level Flag.
    """
    global _HEARTBEAT_COLUMNS_AVAILABLE

    if _HEARTBEAT_COLUMNS_AVAILABLE is not None:
        return _HEARTBEAT_COLUMNS_AVAILABLE

    try:
        from sqlalchemy import text
        with get_db() as session:
            # Prüfe ob heartbeat_at Spalte existiert
            result = session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'cloud_sync_diagnostics'
                AND column_name = 'heartbeat_at'
            """))
            exists = result.fetchone() is not None
            _HEARTBEAT_COLUMNS_AVAILABLE = exists
            if not exists:
                logger.info("[HEARTBEAT] Spalten nicht verfügbar - Migration migrations/add_heartbeat_to_diagnostics.sql noch nicht angewendet")
            else:
                logger.info("[HEARTBEAT] Spalten verfügbar - Heartbeat-Monitoring aktiv")
            return exists
    except Exception as e:
        logger.warning(f"[HEARTBEAT] Spalten-Check fehlgeschlagen, deaktiviere Heartbeat: {e}")
        _HEARTBEAT_COLUMNS_AVAILABLE = False
        return False


# ==================== SYNC DIAGNOSTICS ====================
class SyncDiagnostics:
    """
    Umfassendes Diagnose-System für Cloud-Synchronisation.
    Erfasst detaillierte Metriken zu jedem Sync-Vorgang.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Setzt alle Diagnose-Daten zurück"""
        self.start_time = None
        self.end_time = None
        self.events = []  # Liste aller Events mit Zeitstempel
        self.api_calls = []  # API-Aufrufe mit Timing
        self.file_operations = []  # Datei-Operationen
        self.errors = []  # Detaillierte Fehler
        self.memory_snapshots = []  # Speicher-Nutzung
        self.current_file_index = 0
        self.total_files = 0
        self.last_successful_file = None
        self.last_successful_time = None
        self.phase = "not_started"
        self.connection_info = {}

    def start(self, connection_info: dict = None):
        """Startet die Diagnose-Erfassung"""
        self.reset()
        self.start_time = datetime.now()
        self.connection_info = connection_info or {}
        self.log_event("sync_started", f"Sync gestartet für Verbindung: {connection_info}")
        self.capture_memory("start")

    def log_event(self, event_type: str, detail: str, extra: dict = None):
        """Loggt ein Event mit Zeitstempel (max 100 Events behalten)"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": self._elapsed_ms(),
            "type": event_type,
            "detail": detail,
            "extra": extra or {}
        }
        self.events.append(event)
        # Begrenze Liste um Speicher zu sparen
        if len(self.events) > 100:
            self.events = self.events[-100:]
        logger.info(f"[SYNC-DIAG] {event_type}: {detail}")

    def log_api_call(self, endpoint: str, method: str, status_code: int,
                     duration_ms: float, response_size: int = 0, error: str = None):
        """Loggt einen API-Aufruf (max 50 Calls behalten)"""
        call = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": self._elapsed_ms(),
            "endpoint": endpoint[:100],  # Kürzen für Übersichtlichkeit
            "method": method,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "response_size": response_size,
            "error": error
        }
        self.api_calls.append(call)
        # Begrenze Liste um Speicher zu sparen
        if len(self.api_calls) > 50:
            self.api_calls = self.api_calls[-50:]

        status_str = f"✅ {status_code}" if status_code == 200 else f"❌ {status_code}"
        logger.info(f"[SYNC-API] {method} {endpoint[:50]}... -> {status_str} ({duration_ms:.0f}ms)")

    def log_file_operation(self, filename: str, operation: str, status: str,
                          file_size: int = 0, duration_ms: float = 0, error: str = None):
        """Loggt eine Datei-Operation (max 50 Operationen behalten)"""
        op = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": self._elapsed_ms(),
            "file_index": self.current_file_index,
            "filename": filename,
            "operation": operation,
            "status": status,
            "file_size": file_size,
            "duration_ms": round(duration_ms, 2),
            "error": error
        }
        self.file_operations.append(op)
        # Begrenze Liste um Speicher zu sparen
        if len(self.file_operations) > 50:
            self.file_operations = self.file_operations[-50:]

        if status == "success":
            self.last_successful_file = filename
            self.last_successful_time = datetime.now()

        status_icon = "✅" if status == "success" else "⏭️" if status == "skipped" else "❌"
        logger.info(f"[SYNC-FILE] {status_icon} [{self.current_file_index}/{self.total_files}] {filename} - {operation}")

    def log_error(self, error_type: str, message: str, exception: Exception = None):
        """Loggt einen Fehler mit vollständigem Traceback (max 30 Fehler behalten)"""
        error = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": self._elapsed_ms(),
            "file_index": self.current_file_index,
            "type": error_type,
            "message": message,
            "exception_type": type(exception).__name__ if exception else None,
            "exception_message": str(exception) if exception else None,
            "traceback": traceback.format_exc() if exception else None
        }
        self.errors.append(error)
        # Begrenze Liste um Speicher zu sparen
        if len(self.errors) > 30:
            self.errors = self.errors[-30:]
        logger.error(f"[SYNC-ERROR] {error_type}: {message}")
        if exception:
            logger.error(f"[SYNC-ERROR] Exception: {exception}")

    def capture_memory(self, label: str = ""):
        """Erfasst aktuelle Speicher- und Disk-Nutzung"""
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": self._elapsed_ms(),
            "label": label,
            "file_index": self.current_file_index,
            "rss_mb": 0,
            "vms_mb": 0,
            "disk_tmp_used_mb": 0,
            "disk_tmp_free_mb": 0,
            "disk_tmp_percent": 0,
            "temp_files_count": 0,
            "temp_files_size_mb": 0
        }

        # Python Memory (wenn psutil verfügbar)
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process()
                mem_info = process.memory_info()
                snapshot["rss_mb"] = round(mem_info.rss / 1024 / 1024, 2)
                snapshot["vms_mb"] = round(mem_info.vms / 1024 / 1024, 2)
            except Exception as e:
                logger.debug(f"Memory capture failed: {e}")

        # Disk Usage (immer verfügbar)
        try:
            disk_info = get_disk_usage()
            snapshot["disk_tmp_used_mb"] = disk_info.get("tmp_used_mb", 0)
            snapshot["disk_tmp_free_mb"] = disk_info.get("tmp_free_mb", 0)
            snapshot["disk_tmp_percent"] = disk_info.get("tmp_percent_used", 0)
            snapshot["temp_files_count"] = disk_info.get("temp_files_count", 0)
            snapshot["temp_files_size_mb"] = disk_info.get("temp_files_size_mb", 0)
        except Exception as e:
            logger.debug(f"Disk usage capture failed: {e}")

        self.memory_snapshots.append(snapshot)
        # Begrenze Liste um Speicher zu sparen
        if len(self.memory_snapshots) > 30:
            self.memory_snapshots = self.memory_snapshots[-30:]
        logger.debug(f"[SYNC-MEM] {label}: RSS={snapshot['rss_mb']}MB, Disk=/tmp {snapshot['disk_tmp_used_mb']}MB used ({snapshot['disk_tmp_percent']}%)")

    def set_phase(self, phase: str):
        """Setzt die aktuelle Phase"""
        self.phase = phase
        self.log_event("phase_change", f"Phase gewechselt zu: {phase}")
        self.capture_memory(f"phase_{phase}")

    def set_file_progress(self, current: int, total: int):
        """Aktualisiert Datei-Fortschritt"""
        self.current_file_index = current
        self.total_files = total

    def finish(self, success: bool, final_stats: dict = None):
        """Beendet die Diagnose-Erfassung"""
        self.end_time = datetime.now()
        self.capture_memory("end")
        self.log_event("sync_finished",
                       f"Sync {'erfolgreich' if success else 'mit Fehlern'} beendet",
                       {"success": success, "stats": final_stats})

    def _elapsed_ms(self) -> int:
        """Berechnet verstrichene Zeit in Millisekunden"""
        if not self.start_time:
            return 0
        return int((datetime.now() - self.start_time).total_seconds() * 1000)

    def get_summary(self) -> dict:
        """Gibt eine Zusammenfassung der Diagnose zurück"""
        total_duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0

        # API-Statistiken
        api_durations = [c["duration_ms"] for c in self.api_calls]
        api_errors = [c for c in self.api_calls if c.get("error") or c.get("status_code", 200) >= 400]

        # Datei-Statistiken
        successful_files = [f for f in self.file_operations if f["status"] == "success"]
        failed_files = [f for f in self.file_operations if f["status"] == "error"]
        skipped_files = [f for f in self.file_operations if f["status"] == "skipped"]

        # Speicher-Statistiken
        if self.memory_snapshots:
            mem_start = self.memory_snapshots[0]["rss_mb"] if self.memory_snapshots else 0
            mem_end = self.memory_snapshots[-1]["rss_mb"] if self.memory_snapshots else 0
            mem_max = max(s["rss_mb"] for s in self.memory_snapshots)
        else:
            mem_start = mem_end = mem_max = 0

        return {
            "duration_seconds": round(total_duration, 2),
            "phase": self.phase,
            "total_files": self.total_files,
            "files_processed": self.current_file_index,
            "files_successful": len(successful_files),
            "files_failed": len(failed_files),
            "files_skipped": len(skipped_files),
            "last_successful_file": self.last_successful_file,
            "last_successful_time": self.last_successful_time.isoformat() if self.last_successful_time else None,
            "api_calls_total": len(self.api_calls),
            "api_calls_failed": len(api_errors),
            "api_avg_duration_ms": round(sum(api_durations) / len(api_durations), 2) if api_durations else 0,
            "api_max_duration_ms": max(api_durations) if api_durations else 0,
            "errors_total": len(self.errors),
            "memory_start_mb": mem_start,
            "memory_end_mb": mem_end,
            "memory_max_mb": mem_max,
            "memory_growth_mb": round(mem_end - mem_start, 2),
            "events_count": len(self.events)
        }

    def get_full_report(self) -> dict:
        """Gibt den vollständigen Diagnose-Bericht zurück"""
        return {
            "summary": self.get_summary(),
            "connection_info": self.connection_info,
            "events": self.events[-100:],  # Letzte 100 Events
            "api_calls": self.api_calls[-50:],  # Letzte 50 API-Calls
            "file_operations": self.file_operations[-100:],  # Letzte 100 Datei-Ops
            "errors": self.errors,  # Alle Fehler
            "memory_snapshots": self.memory_snapshots
        }

    def get_failure_analysis(self) -> dict:
        """Analysiert mögliche Ursachen für Sync-Abbrüche"""
        analysis = {
            "possible_causes": [],
            "recommendations": []
        }

        # Analyse: Timeout-Muster
        slow_api_calls = [c for c in self.api_calls if c["duration_ms"] > 30000]  # > 30s
        if slow_api_calls:
            analysis["possible_causes"].append(
                f"Langsame API-Antworten: {len(slow_api_calls)} Aufrufe > 30s"
            )
            analysis["recommendations"].append(
                "Netzwerkverbindung prüfen oder Timeout erhöhen"
            )

        # Analyse: API-Fehler
        api_errors = [c for c in self.api_calls if c.get("status_code", 200) >= 400]
        if api_errors:
            status_codes = set(c["status_code"] for c in api_errors)
            analysis["possible_causes"].append(
                f"API-Fehler: {len(api_errors)} Fehler mit Codes {status_codes}"
            )
            if 429 in status_codes:
                analysis["recommendations"].append(
                    "Rate-Limiting erkannt - längere Pausen zwischen Anfragen einfügen"
                )
            if 401 in status_codes or 403 in status_codes:
                analysis["recommendations"].append(
                    "Authentifizierungsfehler - Token erneuern oder Berechtigungen prüfen"
                )

        # Analyse: Speicherwachstum
        if self.memory_snapshots:
            mem_growth = self.memory_snapshots[-1]["rss_mb"] - self.memory_snapshots[0]["rss_mb"]
            if mem_growth > 500:  # > 500MB Wachstum
                analysis["possible_causes"].append(
                    f"Hoher Speicherverbrauch: +{mem_growth:.0f}MB während Sync"
                )
                analysis["recommendations"].append(
                    "Batch-Größe reduzieren oder Speicher freigeben"
                )

        # Analyse: Abbruch-Punkt
        if self.current_file_index < self.total_files and self.last_successful_file:
            analysis["possible_causes"].append(
                f"Sync bei Datei {self.current_file_index}/{self.total_files} abgebrochen"
            )
            analysis["last_successful"] = {
                "file": self.last_successful_file,
                "time": self.last_successful_time.isoformat() if self.last_successful_time else None,
                "index": self.current_file_index - 1
            }

        # Analyse: Häufige Fehlertypen
        if self.errors:
            error_types = {}
            for e in self.errors:
                t = e.get("type", "unknown")
                error_types[t] = error_types.get(t, 0) + 1
            analysis["error_distribution"] = error_types

            most_common = max(error_types, key=error_types.get)
            analysis["recommendations"].append(
                f"Häufigster Fehlertyp: {most_common} ({error_types[most_common]}x)"
            )

        return analysis


# Globale Diagnose-Instanz für aktuellen Sync
_current_sync_diagnostics: Optional[SyncDiagnostics] = None

def get_sync_diagnostics() -> Optional[SyncDiagnostics]:
    """Gibt die aktuelle Diagnose-Instanz zurück"""
    return _current_sync_diagnostics

def create_sync_diagnostics() -> SyncDiagnostics:
    """Erstellt eine neue Diagnose-Instanz"""
    global _current_sync_diagnostics
    _current_sync_diagnostics = SyncDiagnostics()
    return _current_sync_diagnostics


# ==================== SYNC KONFIGURATION ====================
# Konfigurierbare Timeouts und Retry-Einstellungen
SYNC_CONFIG = {
    "download_timeout": 120,      # Sekunden für einzelne Downloads
    "api_timeout": 60,            # Sekunden für API-Aufrufe
    "upload_timeout": 180,        # Sekunden für Uploads zu Supabase
    "max_retries": 3,             # Maximale Wiederholungsversuche
    "retry_delay_base": 2,        # Basis-Verzögerung für exponentielles Backoff (Sekunden)
    "db_reconnect_attempts": 3,   # Versuche für DB-Reconnect
    "pause_between_files": 0.3,   # Pause zwischen Dateien (Sekunden)
    "memory_check_interval": 5,   # Alle X Dateien Speicher prüfen
    "cache_clear_interval": 5,    # Alle X Dateien aggressive Cleanup durchführen (reduziert von 10)
    "disk_warning_threshold_mb": 100,  # Warnung wenn weniger als X MB frei
    "disk_critical_threshold_mb": 50,  # Abbruch wenn weniger als X MB frei
    "ram_warning_threshold_mb": 450,   # RAM-Warnung: Extra Cleanup wenn überschritten (Baseline ~350-380MB)
    "ram_critical_threshold_mb": 550,  # RAM-Kritisch: Abbruch wenn überschritten
}


def get_current_ram_mb() -> float:
    """Gibt die aktuelle RAM-Nutzung in MB zurück."""
    if not PSUTIL_AVAILABLE:
        return 0.0
    try:
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except:
        return 0.0


def clear_streamlit_cache():
    """
    Leert den Streamlit-Cache um Speicherüberlauf zu vermeiden.
    Wird während langer Sync-Operationen aufgerufen.
    """
    if not STREAMLIT_AVAILABLE:
        return

    try:
        # Versuche verschiedene Cache-Clear-Methoden
        if hasattr(st, 'cache_data'):
            st.cache_data.clear()
            logger.debug("[CACHE] st.cache_data geleert")

        if hasattr(st, 'cache_resource'):
            st.cache_resource.clear()
            logger.debug("[CACHE] st.cache_resource geleert")

        # Legacy Cache (ältere Streamlit-Versionen)
        if hasattr(st, 'legacy_caching'):
            st.legacy_caching.clear_cache()
            logger.debug("[CACHE] Legacy-Cache geleert")

        # Session State bereinigen - hier liegt oft viel Speicher!
        if hasattr(st, 'session_state'):
            keys_to_clear = []
            for key in st.session_state:
                # Große Daten-Keys identifizieren (Vorschauen, Suchergebnisse, etc.)
                if any(pattern in key.lower() for pattern in [
                    'preview', 'thumbnail', 'search_result', 'document_list',
                    'cached_', 'temp_', 'buffer', 'content', 'file_data'
                ]):
                    keys_to_clear.append(key)

            for key in keys_to_clear:
                try:
                    del st.session_state[key]
                    logger.debug(f"[CACHE] Session-State Key gelöscht: {key}")
                except:
                    pass

            if keys_to_clear:
                logger.info(f"[CACHE] {len(keys_to_clear)} Session-State Keys bereinigt")

        # Garbage Collection ausführen
        import gc
        gc.collect()
        logger.info("[CACHE] Streamlit-Cache und Garbage Collection durchgeführt")

    except Exception as e:
        logger.warning(f"[CACHE] Fehler beim Cache-Leeren: {e}")


def get_disk_usage() -> Dict[str, Any]:
    """
    Ermittelt die Festplattennutzung (wichtig für Streamlit Cloud mit 500MB Limit).
    Gibt Informationen über verfügbaren Speicher in /tmp und Arbeitsverzeichnis zurück.
    """
    import shutil
    import tempfile

    result = {
        "tmp_total_mb": 0,
        "tmp_used_mb": 0,
        "tmp_free_mb": 0,
        "tmp_percent_used": 0,
        "cwd_total_mb": 0,
        "cwd_used_mb": 0,
        "cwd_free_mb": 0,
        "cwd_percent_used": 0,
        "temp_dir": tempfile.gettempdir(),
        "temp_files_count": 0,
        "temp_files_size_mb": 0
    }

    try:
        # /tmp Verzeichnis (Streamlit Cloud Ephemeral Storage)
        tmp_dir = tempfile.gettempdir()
        if os.path.exists(tmp_dir):
            usage = shutil.disk_usage(tmp_dir)
            result["tmp_total_mb"] = round(usage.total / (1024 * 1024), 2)
            result["tmp_used_mb"] = round(usage.used / (1024 * 1024), 2)
            result["tmp_free_mb"] = round(usage.free / (1024 * 1024), 2)
            result["tmp_percent_used"] = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0

            # Zähle temp-Dateien und ihre Größe
            temp_size = 0
            temp_count = 0
            try:
                for entry in os.scandir(tmp_dir):
                    if entry.is_file():
                        temp_count += 1
                        try:
                            temp_size += entry.stat().st_size
                        except:
                            pass
            except:
                pass
            result["temp_files_count"] = temp_count
            result["temp_files_size_mb"] = round(temp_size / (1024 * 1024), 2)

        # Aktuelles Arbeitsverzeichnis
        cwd = os.getcwd()
        if os.path.exists(cwd):
            usage = shutil.disk_usage(cwd)
            result["cwd_total_mb"] = round(usage.total / (1024 * 1024), 2)
            result["cwd_used_mb"] = round(usage.used / (1024 * 1024), 2)
            result["cwd_free_mb"] = round(usage.free / (1024 * 1024), 2)
            result["cwd_percent_used"] = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0

    except Exception as e:
        logger.warning(f"[DISK] Fehler beim Ermitteln der Disk-Nutzung: {e}")
        result["error"] = str(e)

    return result


def cleanup_temp_files(max_age_minutes: int = 30, pattern: str = None) -> Dict[str, Any]:
    """
    Bereinigt temporäre Dateien um Speicherplatz freizugeben.

    Args:
        max_age_minutes: Lösche Dateien älter als X Minuten (Standard: 30)
        pattern: Optional - nur Dateien mit bestimmtem Muster löschen

    Returns:
        Dict mit Informationen über gelöschte Dateien
    """
    import tempfile
    import glob

    result = {
        "files_deleted": 0,
        "bytes_freed": 0,
        "errors": [],
        "temp_dir": tempfile.gettempdir()
    }

    try:
        tmp_dir = tempfile.gettempdir()
        now = datetime.now()
        cutoff_time = now - timedelta(minutes=max_age_minutes)

        # Python-eigene temp files (tmp*, temp*, etc.)
        patterns_to_clean = [
            os.path.join(tmp_dir, "tmp*"),
            os.path.join(tmp_dir, "temp*"),
            os.path.join(tmp_dir, "*.tmp"),
            os.path.join(tmp_dir, "*.temp"),
            os.path.join(tmp_dir, "streamlit*"),  # Streamlit temp files
        ]

        if pattern:
            patterns_to_clean = [os.path.join(tmp_dir, pattern)]

        for file_pattern in patterns_to_clean:
            for filepath in glob.glob(file_pattern):
                try:
                    if os.path.isfile(filepath):
                        # Prüfe Alter der Datei
                        mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                        if mtime < cutoff_time:
                            file_size = os.path.getsize(filepath)
                            os.remove(filepath)
                            result["files_deleted"] += 1
                            result["bytes_freed"] += file_size
                            logger.debug(f"[CLEANUP] Gelöscht: {filepath} ({file_size} Bytes)")
                except PermissionError:
                    pass  # Datei wird gerade verwendet
                except Exception as e:
                    result["errors"].append(f"{filepath}: {str(e)}")

        # Konvertiere zu MB
        result["mb_freed"] = round(result["bytes_freed"] / (1024 * 1024), 2)

        if result["files_deleted"] > 0:
            logger.info(f"[CLEANUP] {result['files_deleted']} Temp-Dateien gelöscht, {result['mb_freed']} MB freigegeben")

    except Exception as e:
        logger.warning(f"[CLEANUP] Fehler beim Bereinigen: {e}")
        result["errors"].append(str(e))

    return result


def aggressive_memory_cleanup(light_mode: bool = False, force_cache_clear: bool = False):
    """
    Führt Speicherbereinigung durch.

    Args:
        light_mode: Wenn True, nur minimale GC (für wenn RAM schon hoch ist)
        force_cache_clear: Wenn True, Cache leeren auch in light_mode (für wenn GC nichts bringt)
    """
    import gc
    import ctypes

    if light_mode and not force_cache_clear:
        # Nur GC, keine weiteren Operationen die RAM brauchen
        gc.collect(generation=2)
        gc.collect(generation=1)
        gc.collect(generation=0)
        return

    # Volle Bereinigung (oder light_mode mit force_cache_clear)
    # 1. Garbage Collection - alle Generationen mehrfach
    gc.collect(generation=0)
    gc.collect(generation=1)
    gc.collect(generation=2)
    gc.collect()
    gc.collect()

    # 2. Streamlit Cache leeren - das befreit den meisten Speicher!
    clear_streamlit_cache()

    # 3. Linecache leeren (klein und schnell)
    try:
        import linecache
        linecache.clearcache()
    except:
        pass

    # 4. malloc_trim auf Linux - gibt freien Heap-Speicher ans OS zurück
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
        logger.debug("[CLEANUP] malloc_trim ausgeführt")
    except:
        pass  # Windows oder andere Plattform

    # 5. Nochmal GC nach Cache-Clear
    gc.collect()

    logger.info("[CLEANUP] Speicherbereinigung durchgeführt (cache_clear=%s)", force_cache_clear)



def update_heartbeat(user_id: int, connection_id: int, current_file: str = None,
                     current_index: int = None, current_step: str = None,
                     step_detail: str = None) -> bool:
    """
    Schnelles Heartbeat-Update für laufende Syncs.
    Wird alle 5-10 Sekunden aufgerufen um zu zeigen, dass der Prozess noch läuft.

    Args:
        user_id: Benutzer-ID
        connection_id: Cloud-Verbindungs-ID
        current_file: Name der aktuell verarbeiteten Datei
        current_index: Index der aktuellen Datei
        current_step: Aktueller Schritt (downloading, ocr, analyzing, etc.)
        step_detail: Details zum aktuellen Schritt

    Returns:
        True wenn erfolgreich, False bei Fehler (oder wenn Spalten nicht verfügbar)
    """
    # Prüfe ob Heartbeat-Spalten verfügbar sind (graceful degradation)
    if not _check_heartbeat_columns_available():
        return False  # Stille Rückkehr wenn Spalten nicht existieren

    try:
        with get_db() as session:
            # Finde laufenden Diagnose-Eintrag
            diag_entry = session.query(CloudSyncDiagnostic).filter(
                CloudSyncDiagnostic.user_id == user_id,
                CloudSyncDiagnostic.connection_id == connection_id,
                CloudSyncDiagnostic.sync_status == "running"
            ).first()

            if diag_entry:
                diag_entry.heartbeat_at = datetime.now()
                if current_file:
                    diag_entry.current_file_name = current_file[:500]
                if current_index is not None:
                    diag_entry.current_file_index = current_index
                if current_step:
                    diag_entry.current_step = current_step[:100]
                if step_detail:
                    diag_entry.current_step_detail = step_detail[:1000]
                session.commit()
                return True
        return False
    except Exception as e:
        logger.warning(f"[HEARTBEAT] Update fehlgeschlagen: {e}")
        return False


def save_diagnostic_to_db(user_id: int, connection_id: int, diag: 'SyncDiagnostics',
                          status: str = "running", error_message: str = None,
                          error_traceback: str = None) -> Optional[int]:
    """
    Speichert Diagnose-Daten in die Datenbank.

    Args:
        user_id: Benutzer-ID
        connection_id: Cloud-Verbindungs-ID
        diag: SyncDiagnostics-Objekt
        status: Sync-Status (running, completed, error, aborted)
        error_message: Fehlermeldung falls vorhanden
        error_traceback: Traceback falls vorhanden

    Returns:
        ID des erstellten/aktualisierten Diagnose-Eintrags
    """
    try:
        with get_db() as session:
            summary = diag.get_summary()
            analysis = diag.get_failure_analysis()
            full_report = diag.get_full_report()

            # Heartbeat-Verfügbarkeit prüfen
            heartbeat_available = _check_heartbeat_columns_available()

            # Prüfen ob bereits ein laufender Eintrag existiert
            existing = session.query(CloudSyncDiagnostic).filter(
                CloudSyncDiagnostic.user_id == user_id,
                CloudSyncDiagnostic.connection_id == connection_id,
                CloudSyncDiagnostic.sync_status == "running"
            ).first()

            if existing:
                # Existierenden Eintrag aktualisieren
                diag_entry = existing
            else:
                # Neuen Eintrag erstellen
                diag_entry = CloudSyncDiagnostic(
                    user_id=user_id,
                    connection_id=connection_id,
                    sync_started_at=diag.start_time or datetime.now()
                )
                session.add(diag_entry)

            # Felder aktualisieren
            diag_entry.sync_status = status
            if status in ["completed", "error", "aborted"]:
                diag_entry.sync_ended_at = datetime.now()

            # Zusammenfassung
            diag_entry.total_files = summary.get("total_files", 0)
            diag_entry.files_processed = summary.get("files_processed", 0)
            diag_entry.files_successful = summary.get("files_successful", 0)
            diag_entry.files_skipped = summary.get("files_skipped", 0)
            diag_entry.files_failed = summary.get("files_failed", 0)
            diag_entry.duration_seconds = summary.get("duration_seconds", 0)

            # Letzte erfolgreiche Datei
            diag_entry.last_successful_file = summary.get("last_successful_file")
            diag_entry.last_successful_index = diag.current_file_index - 1 if diag.current_file_index > 0 else None
            if diag.last_successful_time:
                diag_entry.last_successful_at = diag.last_successful_time

            # Heartbeat und aktueller Status (nur wenn Spalten verfügbar)
            if _check_heartbeat_columns_available():
                diag_entry.heartbeat_at = datetime.now()
                diag_entry.current_file_index = diag.current_file_index
                # current_file_name und current_step werden über update_heartbeat separat gesetzt

            # API-Statistiken
            diag_entry.api_calls_total = summary.get("api_calls_total", 0)
            diag_entry.api_calls_failed = summary.get("api_calls_failed", 0)
            diag_entry.api_avg_duration_ms = summary.get("api_avg_duration_ms", 0)
            diag_entry.api_max_duration_ms = summary.get("api_max_duration_ms", 0)

            # Speicher-Statistiken
            diag_entry.memory_start_mb = summary.get("memory_start_mb", 0)
            diag_entry.memory_end_mb = summary.get("memory_end_mb", 0)
            diag_entry.memory_max_mb = summary.get("memory_max_mb", 0)
            diag_entry.memory_growth_mb = summary.get("memory_growth_mb", 0)

            # Fehleranalyse
            diag_entry.possible_causes = analysis.get("possible_causes", [])
            diag_entry.recommendations = analysis.get("recommendations", [])

            # Vollständige Logs (begrenzt auf die letzten Einträge um DB-Größe zu begrenzen)
            diag_entry.events_log = full_report.get("events", [])[-100:]
            diag_entry.api_calls_log = full_report.get("api_calls", [])[-50:]
            diag_entry.file_operations_log = full_report.get("file_operations", [])[-100:]
            diag_entry.errors_log = full_report.get("errors", [])
            diag_entry.memory_snapshots = full_report.get("memory_snapshots", [])

            # Fehlermeldungen
            diag_entry.error_message = error_message
            diag_entry.error_traceback = error_traceback

            session.commit()
            logger.info(f"[DIAG-DB] Diagnose-Eintrag gespeichert (ID: {diag_entry.id}, Status: {status})")
            return diag_entry.id

    except Exception as e:
        logger.error(f"[DIAG-DB] Fehler beim Speichern der Diagnose: {e}")
        return None


def retry_with_backoff(max_retries: int = 3, base_delay: float = 2.0,
                       exceptions: tuple = (Exception,), diag: 'SyncDiagnostics' = None):
    """
    Decorator für automatische Wiederholung mit exponentiellem Backoff.

    Args:
        max_retries: Maximale Anzahl Wiederholungen
        base_delay: Basis-Verzögerung in Sekunden
        exceptions: Tuple von Exceptions die wiederholt werden sollen
        diag: Optional SyncDiagnostics für Logging
    """
    import time
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"[RETRY] {func.__name__} Versuch {attempt + 1}/{max_retries + 1} "
                            f"fehlgeschlagen: {e}. Warte {delay:.1f}s..."
                        )
                        if diag:
                            diag.log_event("retry",
                                f"Wiederhole {func.__name__} nach {delay:.1f}s (Versuch {attempt + 2})",
                                {"error": str(e), "attempt": attempt + 1})
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"[RETRY] {func.__name__} endgültig fehlgeschlagen nach "
                            f"{max_retries + 1} Versuchen: {e}"
                        )
            raise last_exception
        return wrapper
    return decorator


class DatabaseConnectionManager:
    """
    Verwaltet Datenbank-Verbindungen mit automatischem Recovery.
    """

    def __init__(self):
        self._session = None
        self._reconnect_attempts = 0

    def get_session(self):
        """Gibt eine aktive Session zurück, mit Recovery bei Bedarf"""
        if self._session is None:
            self._session = self._create_session()
        return self._session

    def _create_session(self):
        """Erstellt eine neue Session"""
        from database.db import get_db
        return get_db().__enter__()

    def check_connection(self) -> bool:
        """Prüft ob die Verbindung aktiv ist"""
        if self._session is None:
            return False
        try:
            # Simple Query zum Testen
            from sqlalchemy import text
            self._session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.warning(f"DB-Verbindungscheck fehlgeschlagen: {e}")
            return False

    def reconnect(self, max_attempts: int = 3) -> bool:
        """
        Versucht die Datenbankverbindung wiederherzustellen.

        Returns:
            True wenn erfolgreich, False sonst
        """
        import time

        logger.info("[DB-RECOVERY] Starte Verbindungs-Recovery...")

        for attempt in range(max_attempts):
            try:
                # Alte Session schließen
                if self._session:
                    try:
                        self._session.rollback()
                        self._session.close()
                    except:
                        pass
                    self._session = None

                # Kurze Pause vor Reconnect
                if attempt > 0:
                    delay = 2 ** attempt
                    logger.info(f"[DB-RECOVERY] Warte {delay}s vor Versuch {attempt + 1}...")
                    time.sleep(delay)

                # Neue Session erstellen
                self._session = self._create_session()

                # Verbindung testen
                if self.check_connection():
                    logger.info(f"[DB-RECOVERY] Verbindung wiederhergestellt (Versuch {attempt + 1})")
                    self._reconnect_attempts = 0
                    return True

            except Exception as e:
                logger.error(f"[DB-RECOVERY] Versuch {attempt + 1} fehlgeschlagen: {e}")

        logger.error(f"[DB-RECOVERY] Konnte Verbindung nach {max_attempts} Versuchen nicht wiederherstellen")
        return False

    def safe_commit(self) -> bool:
        """
        Führt einen sicheren Commit durch mit Recovery bei Fehler.

        Returns:
            True wenn erfolgreich, False sonst
        """
        try:
            self._session.commit()
            return True
        except Exception as e:
            logger.error(f"[DB] Commit fehlgeschlagen: {e}")
            try:
                self._session.rollback()
            except:
                pass

            # Versuche Recovery
            if self.reconnect():
                return False  # Commit war nicht erfolgreich, aber Verbindung ist wieder da
            return False

    def safe_rollback(self):
        """Führt einen sicheren Rollback durch"""
        try:
            if self._session:
                self._session.rollback()
        except Exception as e:
            logger.warning(f"[DB] Rollback fehlgeschlagen: {e}")


# ==================== PUBLIC GOOGLE DRIVE KONSTANTEN ====================
# Direkte Download-URL für öffentliche Dateien
GOOGLE_DRIVE_DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={file_id}"
# URL für öffentliche Ordner-Ansicht
GOOGLE_DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/{folder_id}"
# Alternative API für öffentliche Ordner
GOOGLE_DRIVE_PUBLIC_API = "https://www.googleapis.com/drive/v3/files"


class CloudSyncConnectionWrapper:
    """Wrapper für CloudSyncConnection mit vereinfachtem Attributzugriff"""

    def __init__(self, connection: CloudSyncConnection):
        self.id = connection.id
        self.user_id = connection.user_id
        self.provider = connection.provider
        self.provider_name = connection.provider_name
        self.is_active = connection.is_active
        self.sync_interval_minutes = connection.sync_interval_minutes

        # Aliase für einfacheren Zugriff
        self.folder_path = connection.remote_folder_path
        self.folder_id = connection.remote_folder_id
        self.sync_status = connection.status
        self.last_sync = connection.last_sync_at
        self.last_sync_error = connection.last_sync_error

        # Originale Attribute
        self.remote_folder_path = connection.remote_folder_path
        self.remote_folder_id = connection.remote_folder_id
        self.access_token = connection.access_token
        self.status = connection.status
        self.last_sync_at = connection.last_sync_at
        self.total_files_synced = connection.total_files_synced
        self.auto_sync_enabled = connection.auto_sync_enabled
        self.created_at = connection.created_at
        self.updated_at = connection.updated_at
        self.file_extensions = connection.file_extensions
        self.max_file_size_mb = connection.max_file_size_mb


class CloudSyncLogWrapper:
    """Wrapper für CloudSyncLog mit vereinfachtem Attributzugriff"""

    def __init__(self, log: CloudSyncLog):
        self.id = log.id
        self.connection_id = log.connection_id
        self.user_id = log.user_id
        self.status = log.sync_status
        self.created_at = log.synced_at
        self.files_synced = 1 if log.sync_status == "synced" else 0
        self.files_skipped = 1 if log.sync_status == "skipped" else 0
        self.original_filename = log.original_filename
        self.error_message = log.error_message


class CloudSyncService:
    """Service für Cloud-Synchronisation"""

    # API-Endpunkte
    DROPBOX_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
    DROPBOX_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
    DROPBOX_API_URL = "https://api.dropboxapi.com/2"
    DROPBOX_CONTENT_URL = "https://content.dropboxapi.com/2"

    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_API_URL = "https://www.googleapis.com/drive/v3"

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.log_file_path = Path("data/sync_logs")
        self.log_file_path.mkdir(parents=True, exist_ok=True)

    # ==================== OAUTH AUTHENTIFIZIERUNG ====================

    def get_dropbox_auth_url(self, client_id: str, redirect_uri: str) -> str:
        """Erstellt Dropbox OAuth URL"""
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "token_access_type": "offline"
        }
        return f"{self.DROPBOX_AUTH_URL}?{urlencode(params)}"

    def get_google_auth_url(self, client_id: str, redirect_uri: str) -> str:
        """Erstellt Google Drive OAuth URL"""
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "access_type": "offline",
            "prompt": "consent"
        }
        return f"{self.GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_dropbox_code(self, code: str, client_id: str,
                              client_secret: str, redirect_uri: str) -> Dict:
        """Tauscht Dropbox Auth-Code gegen Tokens"""
        response = requests.post(self.DROPBOX_TOKEN_URL, data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri
        })
        return response.json()

    def exchange_google_code(self, code: str, client_id: str,
                             client_secret: str, redirect_uri: str) -> Dict:
        """Tauscht Google Auth-Code gegen Tokens"""
        response = requests.post(self.GOOGLE_TOKEN_URL, data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri
        })
        return response.json()

    def refresh_dropbox_token(self, refresh_token: str, client_id: str,
                              client_secret: str) -> Dict:
        """Erneuert Dropbox Access Token"""
        response = requests.post(self.DROPBOX_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        })
        return response.json()

    def refresh_google_token(self, refresh_token: str, client_id: str,
                             client_secret: str) -> Dict:
        """Erneuert Google Access Token"""
        response = requests.post(self.GOOGLE_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        })
        return response.json()

    # ==================== VERBINDUNG ERSTELLEN ====================

    def create_connection(self, provider: CloudProvider,
                          folder_id: str = None,
                          folder_path: str = None,
                          access_token: str = None,
                          refresh_token: str = None,
                          token_expires_at: datetime = None,
                          local_folder_id: int = None,
                          sync_interval_minutes: int = None,
                          provider_name: str = None) -> 'CloudSyncConnectionWrapper':
        """Erstellt eine neue Cloud-Sync-Verbindung"""
        with get_db() as session:
            connection = CloudSyncConnection(
                user_id=self.user_id,
                provider=provider,
                provider_name=provider_name or provider.value,
                remote_folder_path=folder_path or folder_id or "",
                remote_folder_id=folder_id,
                access_token=access_token or "",
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
                local_folder_id=local_folder_id,
                sync_interval_minutes=sync_interval_minutes,
                auto_sync_enabled=sync_interval_minutes is not None,
                status=SyncStatus.PENDING,
                file_extensions=[".pdf", ".jpg", ".jpeg", ".png", ".gif", ".doc",
                                ".docx", ".xls", ".xlsx", ".txt"]
            )
            session.add(connection)
            session.commit()
            session.refresh(connection)
            # Return wrapped connection with easier attribute access
            return CloudSyncConnectionWrapper(connection)

    def get_connections(self, active_only: bool = False) -> List['CloudSyncConnectionWrapper']:
        """Holt alle Verbindungen eines Benutzers"""
        with get_db() as session:
            query = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.user_id == self.user_id
            )
            if active_only:
                query = query.filter(CloudSyncConnection.is_active == True)
            connections = query.all()
            # Convert to wrapper objects for easier attribute access
            return [CloudSyncConnectionWrapper(c) for c in connections]

    def get_connection(self, connection_id: int) -> Optional['CloudSyncConnectionWrapper']:
        """Holt eine spezifische Verbindung"""
        with get_db() as session:
            conn = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()
            if conn:
                return CloudSyncConnectionWrapper(conn)
            return None

    def update_connection(self, connection_id: int, **kwargs) -> bool:
        """Aktualisiert Verbindungseinstellungen"""
        with get_db() as session:
            connection = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()
            if not connection:
                return False

            for key, value in kwargs.items():
                if hasattr(connection, key):
                    setattr(connection, key, value)

            connection.updated_at = datetime.now()
            session.commit()
            return True

    def delete_connection(self, connection_id: int) -> bool:
        """Löscht eine Verbindung und alle verknüpften Datensätze"""
        with get_db() as session:
            connection = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()
            if not connection:
                return False

            # Zuerst verknüpfte Datensätze löschen (Foreign Key Constraints)
            # 1. CloudSyncLog Einträge
            session.query(CloudSyncLog).filter(
                CloudSyncLog.connection_id == connection_id
            ).delete()

            # 2. CloudSyncDiagnostic Einträge
            session.query(CloudSyncDiagnostic).filter(
                CloudSyncDiagnostic.connection_id == connection_id
            ).delete()

            # Dann die Verbindung selbst löschen
            session.delete(connection)
            session.commit()
            logger.info(f"Cloud-Verbindung {connection_id} und verknüpfte Daten gelöscht")
            return True

    def get_diagnostic_reports(self, limit: int = 20, connection_id: int = None) -> List[Dict]:
        """
        Holt vergangene Diagnose-Berichte aus der Datenbank.

        Args:
            limit: Maximale Anzahl Berichte
            connection_id: Optional - nur für eine bestimmte Verbindung

        Returns:
            Liste von Diagnose-Berichten
        """
        # Heartbeat-Spalten nur wenn verfügbar hinzufügen
        heartbeat_available = _check_heartbeat_columns_available()

        with get_db() as session:
            query = session.query(CloudSyncDiagnostic).filter(
                CloudSyncDiagnostic.user_id == self.user_id
            )

            if connection_id:
                query = query.filter(CloudSyncDiagnostic.connection_id == connection_id)

            reports = query.order_by(CloudSyncDiagnostic.sync_started_at.desc()).limit(limit).all()

            result = []
            for report in reports:
                report_dict = {
                    "id": report.id,
                    "connection_id": report.connection_id,
                    "sync_started_at": report.sync_started_at,
                    "sync_ended_at": report.sync_ended_at,
                    "sync_status": report.sync_status,
                    "total_files": report.total_files,
                    "files_processed": report.files_processed,
                    "files_successful": report.files_successful,
                    "files_skipped": report.files_skipped,
                    "files_failed": report.files_failed,
                    "duration_seconds": report.duration_seconds,
                    "last_successful_file": report.last_successful_file,
                    "last_successful_index": report.last_successful_index,
                    "last_successful_at": report.last_successful_at,
                    "api_calls_total": report.api_calls_total,
                    "api_calls_failed": report.api_calls_failed,
                    "api_avg_duration_ms": report.api_avg_duration_ms,
                    "api_max_duration_ms": report.api_max_duration_ms,
                    "memory_start_mb": report.memory_start_mb,
                    "memory_end_mb": report.memory_end_mb,
                    "memory_max_mb": report.memory_max_mb,
                    "memory_growth_mb": report.memory_growth_mb,
                    "possible_causes": report.possible_causes,
                    "recommendations": report.recommendations,
                    "error_message": report.error_message,
                    "error_traceback": report.error_traceback,
                    "events_log": report.events_log,
                    "api_calls_log": report.api_calls_log,
                    "file_operations_log": report.file_operations_log,
                    "errors_log": report.errors_log,
                    "memory_snapshots": report.memory_snapshots,
                }

                # Heartbeat-Felder nur hinzufügen wenn verfügbar
                if heartbeat_available:
                    report_dict.update({
                        "heartbeat_at": getattr(report, 'heartbeat_at', None),
                        "current_file_name": getattr(report, 'current_file_name', None),
                        "current_file_index": getattr(report, 'current_file_index', None),
                        "current_step": getattr(report, 'current_step', None),
                        "current_step_detail": getattr(report, 'current_step_detail', None),
                    })

                result.append(report_dict)

            return result

    def get_latest_diagnostic(self, connection_id: int = None) -> Optional[Dict]:
        """Holt den neuesten Diagnose-Bericht"""
        reports = self.get_diagnostic_reports(limit=1, connection_id=connection_id)
        return reports[0] if reports else None

    # ==================== DROPBOX API ====================

    def _dropbox_list_folder(self, access_token: str, path: str,
                             cursor: str = None) -> Dict:
        """Listet Dateien in einem Dropbox-Ordner"""
        headers = {"Authorization": f"Bearer {access_token}"}

        if cursor:
            # Fortsetzung eines vorherigen Aufrufs
            response = requests.post(
                f"{self.DROPBOX_API_URL}/files/list_folder/continue",
                headers=headers,
                json={"cursor": cursor}
            )
        else:
            response = requests.post(
                f"{self.DROPBOX_API_URL}/files/list_folder",
                headers=headers,
                json={
                    "path": path if path != "/" else "",
                    "recursive": False,
                    "include_deleted": False,
                    "include_has_explicit_shared_members": False
                }
            )

        return response.json()

    def _dropbox_download_file(self, access_token: str, path: str) -> Tuple[bytes, Dict]:
        """Lädt eine Datei von Dropbox herunter"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Dropbox-API-Arg": json.dumps({"path": path})
        }

        response = requests.post(
            f"{self.DROPBOX_CONTENT_URL}/files/download",
            headers=headers
        )

        metadata = json.loads(response.headers.get("Dropbox-API-Result", "{}"))
        return response.content, metadata

    def _dropbox_get_file_metadata(self, access_token: str, path: str) -> Dict:
        """Holt Metadaten einer Dropbox-Datei"""
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.post(
            f"{self.DROPBOX_API_URL}/files/get_metadata",
            headers=headers,
            json={"path": path}
        )

        return response.json()

    # ==================== PUBLIC DROPBOX API ====================

    def _dropbox_public_list_folder(self, shared_link: str, path: str = "") -> Dict:
        """
        Listet Dateien in einem öffentlich geteilten Dropbox-Ordner.
        Verwendet die Dropbox API für Shared Links (kein OAuth erforderlich).
        """
        try:
            # Dropbox Shared Link Metadata API
            headers = {
                "Content-Type": "application/json",
            }

            # Erst Metadaten des Shared Links holen
            metadata_response = requests.post(
                "https://api.dropboxapi.com/2/sharing/get_shared_link_metadata",
                headers=headers,
                json={
                    "url": shared_link,
                    "path": path
                },
                timeout=30
            )

            if metadata_response.status_code != 200:
                # Versuche alternative Web-Scraping Methode
                return self._dropbox_public_scrape(shared_link)

            metadata = metadata_response.json()

            # Wenn es ein Ordner ist, Liste den Inhalt
            if metadata.get(".tag") == "folder":
                list_response = requests.post(
                    "https://api.dropboxapi.com/2/files/list_folder",
                    headers=headers,
                    json={
                        "shared_link": {"url": shared_link},
                        "path": path
                    },
                    timeout=30
                )

                if list_response.status_code == 200:
                    data = list_response.json()
                    files = []
                    for entry in data.get("entries", []):
                        files.append({
                            "id": entry.get("id", ""),
                            "name": entry.get("name", ""),
                            "path": entry.get("path_display", ""),
                            "mimeType": "application/vnd.dropbox.folder" if entry.get(".tag") == "folder" else self._guess_mime_type(entry.get("name", "")),
                            "size": entry.get("size", 0)
                        })
                    return {"files": files, "success": True}

            return {"files": [], "success": True, "message": "Kein Ordner oder leer"}

        except Exception as e:
            logger.error(f"Dropbox Public API Fehler: {e}")
            return self._dropbox_public_scrape(shared_link)

    def _dropbox_public_scrape(self, shared_link: str) -> Dict:
        """
        Fallback: Web-Scraping für öffentliche Dropbox-Ordner.
        """
        try:
            # Füge ?dl=0 hinzu für Web-Ansicht
            if "?dl=" not in shared_link:
                shared_link = shared_link.rstrip("/") + "?dl=0"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }

            response = requests.get(shared_link, headers=headers, timeout=30, allow_redirects=True)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}", "success": False}

            html = response.text
            files = []
            seen = set()

            # Dropbox verwendet JSON-Daten im HTML
            # Suche nach Datei-Einträgen
            import re

            # Pattern für Dropbox Datei-Einträge
            # Format: {"filename":"xxx","bytes":123,"icon":"page_white_acrobat",...}
            file_pattern = r'"filename"\s*:\s*"([^"]+)"[^}]*"bytes"\s*:\s*(\d+)'
            for match in re.finditer(file_pattern, html):
                name = match.group(1)
                size = int(match.group(2))
                if name not in seen:
                    seen.add(name)
                    files.append({
                        "id": name,
                        "name": name,
                        "path": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": size
                    })

            # Alternative: Suche nach sl-preview Links
            preview_pattern = r'href="(/previews/[^"]+)"[^>]*>([^<]+)<'
            for match in re.finditer(preview_pattern, html):
                name = match.group(2).strip()
                if name and name not in seen and len(name) > 2:
                    seen.add(name)
                    files.append({
                        "id": name,
                        "name": name,
                        "path": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            if files:
                logger.info(f"Dropbox Scraping: {len(files)} Dateien gefunden")
                return {"files": files, "success": True}
            else:
                logger.warning("Dropbox Scraping: Keine Dateien gefunden")
                return {"files": [], "success": True}

        except Exception as e:
            logger.error(f"Dropbox Scraping Fehler: {e}")
            return {"error": str(e), "success": False}

    def _dropbox_public_download_file(self, shared_link: str, path: str) -> Tuple[bytes, bool]:
        """
        Lädt eine Datei von einem öffentlich geteilten Dropbox-Ordner herunter.
        """
        try:
            # Dropbox Direct Download Link
            download_url = shared_link.replace("?dl=0", "?dl=1").replace("www.dropbox.com", "dl.dropboxusercontent.com")

            if path:
                # Wenn Pfad angegeben, füge ihn hinzu
                download_url = f"{download_url}&path={path}"

            response = requests.get(download_url, timeout=60, allow_redirects=True)

            if response.status_code == 200:
                return response.content, True
            else:
                logger.error(f"Dropbox Download fehlgeschlagen: {response.status_code}")
                return b'', False

        except Exception as e:
            logger.error(f"Dropbox Download Fehler: {e}")
            return b'', False

    # ==================== GOOGLE DRIVE API ====================

    def _google_list_folder(self, access_token: str, folder_id: str = None,
                            page_token: str = None) -> Dict:
        """Listet Dateien in einem Google Drive-Ordner"""
        headers = {"Authorization": f"Bearer {access_token}"}

        params = {
            "pageSize": 100,
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, md5Checksum)"
        }

        if folder_id:
            params["q"] = f"'{folder_id}' in parents and trashed = false"
        else:
            params["q"] = "trashed = false"

        if page_token:
            params["pageToken"] = page_token

        response = requests.get(
            f"{self.GOOGLE_API_URL}/files",
            headers=headers,
            params=params
        )

        return response.json()

    def _google_download_file(self, access_token: str, file_id: str) -> bytes:
        """Lädt eine Datei von Google Drive herunter"""
        headers = {"Authorization": f"Bearer {access_token}"}

        response = requests.get(
            f"{self.GOOGLE_API_URL}/files/{file_id}",
            headers=headers,
            params={"alt": "media"}
        )

        return response.content

    def _google_get_folder_id_from_link(self, link: str) -> Optional[str]:
        """Extrahiert Folder-ID aus Google Drive Link oder Text"""
        import re

        if not link:
            return None

        # Format: https://drive.google.com/drive/folders/FOLDER_ID
        # oder: https://drive.google.com/drive/u/0/folders/FOLDER_ID
        parsed = urlparse(link)
        path_parts = parsed.path.split("/")

        try:
            if "folders" in path_parts:
                idx = path_parts.index("folders")
                if idx + 1 < len(path_parts):
                    folder_id = path_parts[idx + 1].split("?")[0]
                    if len(folder_id) > 10:
                        logger.info(f"Folder-ID aus URL extrahiert: {folder_id}")
                        return folder_id
        except:
            pass

        # Fallback: Suche nach "Folder-ID: XXXX" im Text (für Copy-Paste Fehler)
        folder_id_match = re.search(r'Folder-ID:\s*([a-zA-Z0-9_-]{20,})', link)
        if folder_id_match:
            folder_id = folder_id_match.group(1)
            logger.info(f"Folder-ID aus 'Folder-ID:' Pattern extrahiert: {folder_id}")
            return folder_id

        # Fallback: Suche nach /folders/XXXX im Text
        folders_match = re.search(r'/folders/([a-zA-Z0-9_-]{20,})', link)
        if folders_match:
            folder_id = folders_match.group(1)
            logger.info(f"Folder-ID aus '/folders/' Pattern extrahiert: {folder_id}")
            return folder_id

        # Fallback: Wenn der String selbst wie eine Folder-ID aussieht
        if re.match(r'^[a-zA-Z0-9_-]{20,}$', link.strip()):
            folder_id = link.strip()
            logger.info(f"String direkt als Folder-ID verwendet: {folder_id}")
            return folder_id

        logger.warning(f"Keine Folder-ID gefunden in: {link[:100]}...")
        return None

    # ==================== PUBLIC GOOGLE DRIVE API ====================

    def _get_google_api_key(self) -> Optional[str]:
        """Holt den Google API Key aus Streamlit Secrets oder Umgebungsvariablen"""
        # Versuche Streamlit Secrets
        try:
            import streamlit as st
            if hasattr(st, 'secrets'):
                # Versuche verschiedene Formate
                if 'GOOGLE_API_KEY' in st.secrets:
                    return st.secrets['GOOGLE_API_KEY']
                if 'google' in st.secrets and 'api_key' in st.secrets['google']:
                    return st.secrets['google']['api_key']
        except Exception:
            pass

        # Fallback auf Umgebungsvariable
        return os.environ.get('GOOGLE_API_KEY')

    def _google_api_list_folder(self, folder_id: str, api_key: str) -> Dict:
        """
        Listet Dateien über die offizielle Google Drive API.
        Zuverlässigste Methode wenn ein API Key verfügbar ist.
        """
        try:
            items = []
            token = None
            BASE = "https://www.googleapis.com/drive/v3/files"

            while True:
                params = {
                    "q": f"'{folder_id}' in parents and trashed=false",
                    "fields": "nextPageToken, files(id,name,mimeType,size)",
                    "pageSize": 1000,
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                    "key": api_key,
                }
                if token:
                    params["pageToken"] = token

                response = requests.get(BASE, params=params, timeout=30)

                if response.status_code == 403:
                    logger.warning("Google API: Zugriff verweigert (403) - Key ungültig oder Ordner nicht öffentlich")
                    return {"error": "API Key ungültig oder Ordner nicht öffentlich", "success": False}
                elif response.status_code == 404:
                    logger.warning("Google API: Ordner nicht gefunden (404)")
                    return {"error": "Ordner nicht gefunden", "success": False}

                response.raise_for_status()
                data = response.json()

                for file_info in data.get("files", []):
                    items.append({
                        "id": file_info.get("id"),
                        "name": file_info.get("name"),
                        "mimeType": file_info.get("mimeType", "application/octet-stream"),
                        "size": int(file_info.get("size", 0)) if file_info.get("size") else 0
                    })

                token = data.get("nextPageToken")
                if not token:
                    break

            logger.info(f"Google API: {len(items)} Dateien/Ordner gefunden in {folder_id}")
            return {"files": items, "success": True}

        except requests.exceptions.RequestException as e:
            logger.error(f"Google API Fehler: {e}")
            return {"error": str(e), "success": False}

    def _google_public_list_folder(self, folder_id: str) -> Dict:
        """
        Listet Dateien in einem öffentlich freigegebenen Google Drive-Ordner.
        Verwendet mehrere Methoden in Reihenfolge der Zuverlässigkeit.
        """
        logger.info(f"_google_public_list_folder aufgerufen für: {folder_id}")

        # Methode 0: Versuche die offizielle Google Drive API (beste Methode)
        api_key = self._get_google_api_key()
        logger.info(f"API Key verfügbar: {bool(api_key)}")
        if api_key:
            logger.info(f"Verwende Google Drive API mit API Key: {api_key[:10]}...")
            api_result = self._google_api_list_folder(folder_id, api_key)
            logger.info(f"API Ergebnis: success={api_result.get('success')}, files={len(api_result.get('files', []))}")
            if api_result.get("success") and api_result.get("files") is not None:
                return api_result
            logger.warning(f"API-Methode fehlgeschlagen: {api_result.get('error')}, versuche Fallback...")

        # Methode 1: Versuche die Embed-API (zuverlässiger als Web-Scraping)
        embed_result = self._google_public_list_folder_embed(folder_id)
        if embed_result.get("success") and embed_result.get("files"):
            return embed_result

        # Methode 2: Fallback auf Web-Scraping der öffentlichen Seite
        return self._google_public_list_folder_scrape(folder_id)

    def _google_public_list_folder_embed(self, folder_id: str) -> Dict:
        """
        Listet Dateien über die Google Drive Embed-Ansicht.
        Diese Methode ist zuverlässiger, da sie ein einfacheres HTML-Format verwendet.
        """
        try:
            # Die Embed-URL zeigt eine vereinfachte Ansicht
            embed_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            response = requests.get(embed_url, headers=headers, timeout=30, allow_redirects=True)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}", "success": False}

            html_content = response.text
            files = []
            seen_ids = set()

            # Die Embed-Ansicht hat ein einfacheres Format
            soup = BeautifulSoup(html_content, 'html.parser')

            # Suche nach flip-entry Elementen (Dateien und Ordner)
            entries = soup.find_all(['div', 'tr'], class_=re.compile(r'flip-entry|goog-inline-block'))

            for entry in entries:
                # Finde die ID
                file_id = entry.get('id', '')
                if not file_id or len(file_id) < 20:
                    # Suche in Links
                    link = entry.find('a', href=True)
                    if link:
                        href = link.get('href', '')
                        # Extrahiere ID aus verschiedenen URL-Formaten
                        id_match = re.search(r'(?:id=|/d/|folders/)([a-zA-Z0-9_-]{20,})', href)
                        if id_match:
                            file_id = id_match.group(1)

                if not file_id or len(file_id) < 20 or file_id in seen_ids:
                    continue

                # Finde den Namen
                name_elem = entry.find(class_=re.compile(r'flip-entry-title|entry-title'))
                if name_elem:
                    name = name_elem.get_text(strip=True)
                else:
                    name = entry.get_text(strip=True)[:100]  # Fallback

                if not name or len(name) < 1:
                    continue

                seen_ids.add(file_id)

                # Bestimme den Typ
                is_folder = 'folder' in entry.get('class', []) or 'folder' in str(entry).lower()
                mime_type = "application/vnd.google-apps.folder" if is_folder else self._guess_mime_type(name)

                files.append({
                    "id": file_id,
                    "name": name,
                    "mimeType": mime_type,
                    "size": 0
                })

            # Alternative: Suche nach Links direkt
            if not files:
                all_links = soup.find_all('a', href=re.compile(r'(file/d/|folders/|id=)'))
                for link in all_links:
                    href = link.get('href', '')
                    id_match = re.search(r'(?:id=|/d/|folders/)([a-zA-Z0-9_-]{20,})', href)
                    if id_match:
                        file_id = id_match.group(1)
                        if file_id not in seen_ids:
                            name = link.get_text(strip=True) or f"item_{file_id[:8]}"
                            if len(name) > 1:
                                seen_ids.add(file_id)
                                is_folder = 'folders/' in href
                                files.append({
                                    "id": file_id,
                                    "name": name,
                                    "mimeType": "application/vnd.google-apps.folder" if is_folder else self._guess_mime_type(name),
                                    "size": 0
                                })

            if files:
                logger.info(f"Embed-Methode: {len(files)} Dateien/Ordner gefunden")
                return {"files": files, "success": True}

            return {"files": [], "success": False}

        except Exception as e:
            logger.warning(f"Embed-Methode fehlgeschlagen: {e}")
            return {"error": str(e), "success": False}

    def _google_public_list_folder_scrape(self, folder_id: str) -> Dict:
        """
        Listet Dateien via Web-Scraping der öffentlichen Ordner-Seite.
        Fallback-Methode wenn Embed nicht funktioniert.
        """
        try:
            # Versuche, die öffentliche Ordnerseite zu laden
            url = GOOGLE_DRIVE_FOLDER_URL.format(folder_id=folder_id)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            }

            response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)

            if response.status_code != 200:
                return {"error": f"HTTP {response.status_code}: Ordner nicht zugänglich"}

            response_text = response.text
            response_text_lower = response_text.lower()

            # Prüfe ob Ordner existiert
            if 'sorry, the file you have requested does not exist' in response_text_lower:
                return {"error": "Ordner nicht gefunden. Bitte prüfen Sie die URL."}

            # Prüfe auf explizite Zugriffsverweigerung
            if 'you need access' in response_text_lower or 'zugriff anfordern' in response_text_lower:
                return {"error": "Keine Berechtigung. Bitte den Ordner öffentlich freigeben."}

            # ZUERST versuchen, Dateien zu parsen - "sign in" kann auch auf öffentlichen Seiten erscheinen
            files = self._parse_google_drive_folder_page(response_text)

            if not files:
                # Alternative Methode: Versuche JSON-Daten aus der Seite zu extrahieren
                files = self._extract_drive_data_from_html(response_text)

            # Wenn Dateien gefunden wurden, ist der Ordner zugänglich
            if files:
                return {"files": files, "success": True}

            # Keine Dateien gefunden - jetzt prüfen ob es ein Zugriffsproblem ist
            # Prüfe auf Weiterleitung zur Anmeldeseite (URL-basiert, nicht content-basiert)
            if 'accounts.google.com' in response.url:
                return {
                    "error": "Ordner erfordert Anmeldung. Bitte stellen Sie sicher, dass der Ordner öffentlich freigegeben ist: "
                             "Rechtsklick → Freigeben → 'Jeder mit dem Link' auswählen"
                }

            # Prüfe auf spezifische Fehlermeldungen die auf private Ordner hindeuten
            private_indicators = [
                'request access',
                'zugriff beantragen',
                'not have permission',
                'keine berechtigung',
                'private folder',
                'privater ordner'
            ]

            if any(indicator in response_text_lower for indicator in private_indicators):
                return {
                    "error": "Ordner ist privat. Bitte den Ordner öffentlich freigeben: "
                             "Rechtsklick → Freigeben → 'Jeder mit dem Link' auswählen"
                }

            # Ordner scheint leer zu sein oder Format nicht erkannt
            logger.warning(f"Keine Dateien gefunden in Ordner {folder_id}. "
                          f"Möglicherweise ist der Ordner leer oder das Format hat sich geändert.")

            # Speichere HTML für Debugging (nur in Dev-Umgebung)
            debug_path = Path("data/debug")
            debug_path.mkdir(parents=True, exist_ok=True)
            debug_file = debug_path / f"gdrive_debug_{folder_id[:10]}.html"
            try:
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(response_text[:50000])  # Nur die ersten 50KB
                logger.info(f"Debug-HTML gespeichert unter: {debug_file}")
            except Exception:
                pass

            return {"files": [], "success": True}

        except requests.exceptions.Timeout:
            return {"error": "Zeitüberschreitung beim Laden des Ordners"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Netzwerkfehler: {str(e)}"}
        except Exception as e:
            logger.error(f"Fehler beim Laden des öffentlichen Ordners: {e}")
            return {"error": f"Fehler: {str(e)}"}

    def _parse_google_drive_folder_page(self, html_content: str) -> List[Dict]:
        """
        Parsed die Google Drive Ordnerseite und extrahiert Datei- und Ordner-Informationen.
        """
        files = []

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Methode 1: Suche nach Links mit file/d/ (Dateien)
            file_links = soup.find_all('a', href=re.compile(r'(file/d/|open\?id=|uc\?id=)'))

            for link in file_links:
                href = link.get('href', '')
                file_id = None

                if 'file/d/' in href:
                    match = re.search(r'file/d/([a-zA-Z0-9_-]+)', href)
                    if match:
                        file_id = match.group(1)
                elif 'id=' in href:
                    match = re.search(r'id=([a-zA-Z0-9_-]+)', href)
                    if match:
                        file_id = match.group(1)

                if file_id and file_id not in [f.get('id') for f in files]:
                    name = link.get_text(strip=True) or f"file_{file_id}"
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            # Methode 2: Suche nach Links mit folders/ (Unterordner)
            # Ignoriere Navigation/UI-Links
            ignore_names = ['anmelden', 'sign in', 'login', 'signin', 'abmelden',
                           'sign out', 'logout', 'hilfe', 'help', 'support',
                           'drive', 'google', 'home', 'settings', 'einstellungen']

            folder_links = soup.find_all('a', href=re.compile(r'folders/'))
            for link in folder_links:
                href = link.get('href', '')
                match = re.search(r'folders/([a-zA-Z0-9_-]+)', href)
                if match:
                    folder_id = match.group(1)
                    # Google Drive IDs sind typischerweise 25+ Zeichen lang
                    if len(folder_id) < 20:
                        continue
                    if folder_id not in [f.get('id') for f in files]:
                        name = link.get_text(strip=True) or f"folder_{folder_id}"
                        # Filtere UI/Navigation-Elemente aus
                        name_lower = name.lower()
                        if any(ignore in name_lower for ignore in ignore_names):
                            continue
                        # Nur hinzufügen wenn es nach einem echten Ordnernamen aussieht
                        if name and len(name) > 1 and not name.startswith('folder_'):
                            files.append({
                                "id": folder_id,
                                "name": name,
                                "mimeType": "application/vnd.google-apps.folder",
                                "size": 0
                            })

            # Methode 3: Suche nach data-id Attributen
            elements_with_data_id = soup.find_all(attrs={"data-id": True})
            for elem in elements_with_data_id:
                file_id = elem.get('data-id')
                # Validiere ID-Länge (Google IDs sind 20+ Zeichen)
                if not file_id or len(file_id) < 20:
                    continue
                if file_id not in [f.get('id') for f in files]:
                    name = elem.get_text(strip=True) or elem.get('data-tooltip', '') or f"item_{file_id}"
                    # Filtere UI-Elemente
                    name_lower = name.lower()
                    if any(ignore in name_lower for ignore in ignore_names):
                        continue
                    # Bestimme ob Ordner oder Datei
                    is_folder = 'folder' in elem.get('class', []) or not '.' in name
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": "application/vnd.google-apps.folder" if is_folder else self._guess_mime_type(name),
                        "size": 0
                    })

        except Exception as e:
            logger.error(f"Fehler beim Parsen der Drive-Seite: {e}")

        return files

    def _extract_drive_data_from_html(self, html_content: str) -> List[Dict]:
        """
        Extrahiert Datei-Informationen aus eingebetteten JSON-Daten in der Google Drive Seite.
        Verwendet mehrere Strategien, da Google das Format regelmäßig ändert.
        """
        files = []
        seen_ids = set()

        def is_valid_name(name):
            """Prüft ob ein Name ein gültiger Datei/Ordnername ist"""
            if not name or len(name) < 2 or len(name) > 200:
                return False
            # Filtere URLs, JS-Code und System-Strings
            invalid = ['http', 'https', 'clients', '.com', '.google',
                       'sign in', 'anmelden', 'null', 'undefined',
                       'function', 'return', 'var ', 'const ', 'window.',
                       '();', '{}', 'prototype', 'throw', 'catch',
                       'script', 'style', 'meta', 'link']
            name_lower = name.lower()
            if any(inv in name_lower for inv in invalid):
                return False
            # Muss mindestens einen Buchstaben enthalten
            if not re.search(r'[a-zA-ZäöüÄÖÜß]', name):
                return False
            return True

        def is_file_extension(name):
            """Prüft ob der Name eine Dateiendung hat"""
            return bool(re.search(r'\.\w{2,5}$', name))

        try:
            # ============ NEUE STRATEGIE: Suche nach Google's Datenstrukturen ============

            # Google Drive verwendet oft dieses Format in Script-Tags:
            # null,["FILE_ID","FILENAME",["MIMETYPE"],...
            # oder: ["FILE_ID",["PARENT_ID","FILENAME",...

            # Strategie 0: Suche nach MIME-Type-Zuordnungen im HTML
            # Format: "FILE_ID"... "application/vnd.google-apps.folder" oder andere MIME-Types
            mime_patterns = [
                (r'"([a-zA-Z0-9_-]{25,})"[^"]{0,200}"application/vnd\.google-apps\.folder"', 'folder'),
                (r'"([a-zA-Z0-9_-]{25,})"[^"]{0,200}"application/pdf"', 'application/pdf'),
                (r'"([a-zA-Z0-9_-]{25,})"[^"]{0,200}"image/(?:jpeg|png|gif)"', 'image'),
            ]

            id_to_type = {}
            for pattern, file_type in mime_patterns:
                for match in re.finditer(pattern, html_content):
                    file_id = match.group(1)
                    if file_id not in id_to_type:
                        id_to_type[file_id] = file_type

            # Strategie 1: Suche nach Dateinamen mit Erweiterungen
            ext_pattern = r'"([a-zA-Z0-9_-]{20,})"[,\]\[null"]*"([^"]+\.(?:pdf|jpg|jpeg|png|gif|doc|docx|xls|xlsx|ppt|pptx|txt|csv|zip|PDF|JPG|PNG|DOC|XLS))"'
            for file_id, name in re.findall(ext_pattern, html_content):
                if file_id not in seen_ids and is_valid_name(name):
                    seen_ids.add(file_id)
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            # Strategie 2: Name mit Erweiterung gefolgt von ID (umgekehrtes Format)
            rev_pattern = r'"([^"]+\.(?:pdf|jpg|jpeg|png|doc|docx|xls|xlsx|txt|PDF|JPG|PNG))"[,\]\[null"]*"([a-zA-Z0-9_-]{20,})"'
            for name, file_id in re.findall(rev_pattern, html_content):
                if file_id not in seen_ids and is_valid_name(name):
                    seen_ids.add(file_id)
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": self._guess_mime_type(name),
                        "size": 0
                    })

            # Strategie 3: Suche alle .pdf Erwähnungen ZUERST (vor Ordnern)
            pdf_names = re.findall(r'"([^"]{3,80}\.pdf)"', html_content, re.IGNORECASE)
            for name in pdf_names:
                if is_valid_name(name) and name not in [f.get('name') for f in files]:
                    # Suche ID in der Nähe
                    idx = html_content.find(f'"{name}"')
                    if idx >= 0:
                        context = html_content[max(0,idx-150):idx+150]
                        id_match = re.search(r'"([a-zA-Z0-9_-]{25,})"', context)
                        if id_match:
                            file_id = id_match.group(1)
                            if file_id not in seen_ids:
                                seen_ids.add(file_id)
                                files.append({
                                    "id": file_id,
                                    "name": name,
                                    "mimeType": "application/pdf",
                                    "size": 0
                                })

            # Strategie 4: Suche nach data-id Attributen mit Namen in aria-label/title
            for match in re.finditer(r'data-id="([a-zA-Z0-9_-]{20,})"', html_content):
                file_id = match.group(1)
                if file_id not in seen_ids:
                    # Hole größeren Kontext um das Attribut
                    start = max(0, match.start() - 500)
                    end = min(len(html_content), match.end() + 500)
                    context = html_content[start:end]

                    # Suche nach aria-label, data-tooltip oder title
                    label = re.search(r'(?:aria-label|data-tooltip|title)="([^"]+)"', context)
                    if label and is_valid_name(label.group(1)):
                        name = label.group(1)
                        seen_ids.add(file_id)

                        # Bestimme Typ basierend auf MIME-Type-Map oder Dateiendung
                        if file_id in id_to_type:
                            if id_to_type[file_id] == 'folder':
                                mime_type = "application/vnd.google-apps.folder"
                            else:
                                mime_type = id_to_type[file_id]
                        elif is_file_extension(name):
                            mime_type = self._guess_mime_type(name)
                        else:
                            mime_type = "application/vnd.google-apps.folder"

                        files.append({
                            "id": file_id,
                            "name": name,
                            "mimeType": mime_type,
                            "size": 0
                        })

            # Strategie 5: Kompakte JSON-Struktur ["ID","Name"]
            compact_pattern = r'\["([a-zA-Z0-9_-]{25,})",\s*"([^"]{2,100})"'
            for file_id, name in re.findall(compact_pattern, html_content):
                if file_id not in seen_ids and is_valid_name(name):
                    # Zusätzliche Prüfung: Name sollte keine JS-Syntax sein
                    if not re.match(r'^[a-z]+\(|^[A-Z_]+$|^\d+$', name):
                        seen_ids.add(file_id)

                        # Bestimme Typ
                        if file_id in id_to_type:
                            if id_to_type[file_id] == 'folder':
                                mime_type = "application/vnd.google-apps.folder"
                            else:
                                mime_type = id_to_type[file_id]
                        elif is_file_extension(name):
                            mime_type = self._guess_mime_type(name)
                        else:
                            mime_type = "application/vnd.google-apps.folder"

                        files.append({
                            "id": file_id,
                            "name": name,
                            "mimeType": mime_type,
                            "size": 0
                        })

            # Strategie 6: Suche nach Ordner-Links in href
            folder_pattern = r'href="[^"]*?/folders/([a-zA-Z0-9_-]{20,})[^"]*"[^>]*>([^<]+)<'
            for file_id, name in re.findall(folder_pattern, html_content):
                name = name.strip()
                if file_id not in seen_ids and is_valid_name(name):
                    seen_ids.add(file_id)
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": "application/vnd.google-apps.folder",
                        "size": 0
                    })

            # Logge Ergebnis für Debugging
            if files:
                folders = len([f for f in files if f.get('mimeType') == 'application/vnd.google-apps.folder'])
                docs = len(files) - folders
                logger.info(f"Gefunden: {len(files)} Einträge ({folders} Ordner, {docs} Dateien) via HTML-Extraktion")
            else:
                logger.warning(f"Keine Dateien via HTML-Extraktion gefunden. HTML-Länge: {len(html_content)}")

        except Exception as e:
            logger.error(f"Fehler beim Extrahieren von Drive-Daten: {e}")

        return files

    def _extract_from_json(self, data, files: List[Dict], seen_ids: set, depth: int = 0):
        """Rekursive Extraktion von Dateien aus JSON-Daten"""
        if depth > 10:  # Maximale Rekursionstiefe
            return

        if isinstance(data, dict):
            # Prüfe ob dieses Dict eine Datei/Ordner-Info enthält
            if 'id' in data and 'name' in data:
                file_id = data['id']
                name = data['name']
                if file_id not in seen_ids and len(file_id) >= 20:
                    seen_ids.add(file_id)
                    mime_type = data.get('mimeType', self._guess_mime_type(name))
                    files.append({
                        "id": file_id,
                        "name": name,
                        "mimeType": mime_type,
                        "size": data.get('size', 0)
                    })
            # Rekursiv durch alle Werte
            for value in data.values():
                self._extract_from_json(value, files, seen_ids, depth + 1)

        elif isinstance(data, list):
            for item in data:
                self._extract_from_json(item, files, seen_ids, depth + 1)

    def _guess_mime_type(self, filename: str) -> str:
        """Schätzt MIME-Type basierend auf Dateinamen"""
        ext = Path(filename).suffix.lower() if '.' in filename else ''
        mime_map = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.txt': 'text/plain',
            '.csv': 'text/csv'
        }
        return mime_map.get(ext, 'application/octet-stream')

    def _google_public_download_file(self, file_id: str, max_retries: int = None) -> Tuple[bytes, bool]:
        """
        Lädt eine Datei von einem öffentlichen Google Drive herunter.
        Mit konfigurierbarem Timeout und Retry-Logik.

        Args:
            file_id: Google Drive Datei-ID
            max_retries: Maximale Wiederholungsversuche (default: aus SYNC_CONFIG)

        Returns:
            Tuple von (file_content, success)
        """
        import time

        if max_retries is None:
            max_retries = SYNC_CONFIG.get("max_retries", 3)

        timeout = SYNC_CONFIG.get("download_timeout", 120)
        base_delay = SYNC_CONFIG.get("retry_delay_base", 2)

        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Direkte Download-URL
                download_url = GOOGLE_DRIVE_DOWNLOAD_URL.format(file_id=file_id)

                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }

                # Erste Anfrage - kann eine Bestätigungsseite zurückgeben
                session = requests.Session()

                logger.debug(f"[DOWNLOAD] Versuch {attempt + 1}/{max_retries + 1} für {file_id} (Timeout: {timeout}s)")

                response = session.get(download_url, headers=headers, stream=True, timeout=timeout)

                # Prüfe auf Virus-Scan-Warnung (große Dateien)
                if 'download_warning' in response.url or b'confirm=' in response.content[:1000]:
                    # Extrahiere Bestätigungs-Token
                    confirm_token = None

                    for key, value in response.cookies.items():
                        if key.startswith('download_warning'):
                            confirm_token = value
                            break

                    if not confirm_token:
                        # Versuche Token aus HTML zu extrahieren
                        match = re.search(r'confirm=([a-zA-Z0-9_-]+)', response.text)
                        if match:
                            confirm_token = match.group(1)

                    if confirm_token:
                        # Zweite Anfrage mit Bestätigung
                        confirm_url = f"{download_url}&confirm={confirm_token}"
                        response = session.get(confirm_url, headers=headers, stream=True, timeout=timeout)

                # Prüfe ob Download erfolgreich
                content_type = response.headers.get('Content-Type', '')

                if 'text/html' in content_type:
                    # Wahrscheinlich eine Fehlerseite
                    if 'Access denied' in response.text or 'denied' in response.text.lower():
                        logger.warning(f"Zugriff verweigert für Datei {file_id}")
                        return b'', False
                    elif 'quota' in response.text.lower():
                        logger.warning(f"Download-Quota überschritten für Datei {file_id}")
                        # Bei Quota-Fehler länger warten
                        if attempt < max_retries:
                            delay = base_delay * (4 ** attempt)  # Längere Wartezeit bei Quota
                            logger.info(f"[QUOTA] Warte {delay}s vor erneutem Versuch...")
                            time.sleep(delay)
                            continue
                        return b'', False

                # Lade vollständigen Inhalt
                content = response.content

                if len(content) == 0:
                    if attempt < max_retries:
                        logger.warning(f"[DOWNLOAD] Leere Antwort für {file_id}, versuche erneut...")
                        time.sleep(base_delay * (2 ** attempt))
                        continue
                    return b'', False

                logger.debug(f"[DOWNLOAD] Erfolgreich: {len(content)} Bytes für {file_id}")
                return content, True

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(f"[DOWNLOAD] Timeout bei Versuch {attempt + 1} für {file_id}")
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"[DOWNLOAD] Warte {delay}s vor Retry...")
                    time.sleep(delay)
                else:
                    logger.error(f"[DOWNLOAD] Timeout nach {max_retries + 1} Versuchen für {file_id}")

            except requests.exceptions.ConnectionError as e:
                last_error = e
                logger.warning(f"[DOWNLOAD] Verbindungsfehler bei Versuch {attempt + 1} für {file_id}: {e}")
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"[DOWNLOAD] Warte {delay}s vor Retry...")
                    time.sleep(delay)
                else:
                    logger.error(f"[DOWNLOAD] Verbindung fehlgeschlagen nach {max_retries + 1} Versuchen")

            except Exception as e:
                last_error = e
                logger.error(f"[DOWNLOAD] Fehler bei Versuch {attempt + 1} für {file_id}: {e}")
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)

        logger.error(f"[DOWNLOAD] Endgültig fehlgeschlagen für {file_id}: {last_error}")
        return b'', False

    def _collect_dropbox_files_public(self, connection: CloudSyncConnection,
                                       session) -> List[Dict]:
        """
        Sammelt Dateien aus einem öffentlich geteilten Dropbox-Ordner.
        """
        files = []
        shared_link = connection.remote_folder_path

        if not shared_link:
            logger.error("Kein Dropbox Shared Link angegeben")
            return files

        logger.info(f"Lade öffentlichen Dropbox-Ordner: {shared_link}")

        # Lade Ordnerinhalt
        response = self._dropbox_public_list_folder(shared_link)

        if "error" in response:
            logger.error(f"Fehler beim Laden des Dropbox-Ordners: {response['error']}")
            return files

        file_list = response.get("files", [])
        logger.info(f"Gefunden: {len(file_list)} Einträge in Dropbox-Ordner")

        for file_info in file_list:
            mime_type = file_info.get("mimeType", "")
            filename = file_info.get("name", "")
            file_path = file_info.get("path", filename)

            # Ordner überspringen (keine rekursive Unterstützung für öffentliche Dropbox)
            if 'folder' in mime_type.lower():
                logger.info(f"Unterordner übersprungen: {filename}")
                continue

            ext = Path(filename).suffix.lower()

            # Dateiendung prüfen
            if connection.file_extensions and ext and ext not in connection.file_extensions:
                continue

            # Prüfen ob bereits synchronisiert
            from database.extended_models import CloudSyncLog
            existing_log = session.query(CloudSyncLog).filter(
                CloudSyncLog.connection_id == connection.id,
                CloudSyncLog.remote_file_id == file_path
            ).first()

            if existing_log:
                continue

            files.append({
                "name": filename,
                "path": file_path,
                "id": file_path,
                "size": file_info.get("size", 0),
                "hash": None,
                "modified": None,
                "mime_type": mime_type,
                "provider": "dropbox_public",
                "shared_link": shared_link
            })

            logger.info(f"Datei gefunden: {filename}")

        logger.info(f"Insgesamt {len(files)} Dateien in öffentlichem Dropbox-Ordner gefunden")
        return files

    def _collect_google_drive_files_public(self, connection: CloudSyncConnection,
                                            session) -> List[Dict]:
        """
        Sammelt Dateien aus einem öffentlichen Google Drive-Ordner.
        Durchsucht REKURSIV alle Unterordner.
        """
        files = []

        # Versuche Folder-ID zu extrahieren
        folder_id = None

        logger.info(f"Google Drive Public: remote_folder_id={connection.remote_folder_id}, remote_folder_path={connection.remote_folder_path}")

        # Prüfe ob remote_folder_id eine URL ist oder eine echte ID
        if connection.remote_folder_id:
            if 'drive.google.com' in connection.remote_folder_id:
                # Es ist eine URL, extrahiere die ID
                folder_id = self._google_get_folder_id_from_link(connection.remote_folder_id)
                logger.info(f"Extrahierte Folder-ID aus remote_folder_id URL: {folder_id}")
            elif len(connection.remote_folder_id) > 10 and not connection.remote_folder_id.startswith('http'):
                # Sieht wie eine echte Folder-ID aus
                folder_id = connection.remote_folder_id
                logger.info(f"Verwende remote_folder_id als Folder-ID: {folder_id}")

        # Fallback auf remote_folder_path
        if not folder_id and connection.remote_folder_path:
            folder_id = self._google_get_folder_id_from_link(connection.remote_folder_path)
            logger.info(f"Extrahierte Folder-ID aus remote_folder_path: {folder_id}")

        if not folder_id:
            logger.error("Keine Ordner-ID gefunden - weder in remote_folder_id noch remote_folder_path")
            return files

        logger.info(f"Starte rekursive Sammlung mit Folder-ID: {folder_id}")

        # Rekursiv alle Dateien sammeln
        self._collect_public_folder_recursive(
            folder_id=folder_id,
            folder_path="",  # Root-Ordner
            connection=connection,
            session=session,
            files=files
        )

        logger.info(f"Insgesamt {len(files)} Dateien in öffentlichem Ordner gefunden")
        return files

    def _collect_public_folder_recursive(self, folder_id: str, folder_path: str,
                                          connection: CloudSyncConnection,
                                          session, files: List[Dict],
                                          depth: int = 0, max_depth: int = 50):
        """
        Sammelt rekursiv Dateien aus öffentlichen Google Drive Ordnern.

        Args:
            folder_id: Google Drive Ordner-ID
            folder_path: Aktueller Pfad für die Kategorisierung (z.B. "Versicherung/Leben")
            connection: CloudSyncConnection
            session: DB Session
            files: Liste zum Sammeln der Dateien
            depth: Aktuelle Rekursionstiefe
            max_depth: Maximale Rekursionstiefe (Standard: 50)
        """
        if depth > max_depth:
            logger.debug(f"Ordnertiefe {depth} erreicht bei: {folder_path}")
            return

        logger.info(f"Durchsuche Ordner: {folder_path or 'Root'} (ID: {folder_id})")

        # Lade Ordnerinhalt
        response = self._google_public_list_folder(folder_id)

        if "error" in response:
            logger.error(f"Fehler beim Laden des Ordners {folder_path}: {response['error']}")
            return

        file_list = response.get("files", [])
        logger.info(f"Gefunden: {len(file_list)} Einträge in {folder_path or 'Root'}")

        for file_info in file_list:
            mime_type = file_info.get("mimeType", "")
            filename = file_info.get("name", "")
            file_id = file_info.get("id", "")

            logger.debug(f"Prüfe: {filename} (MIME: {mime_type}, ID: {file_id})")

            # Unterordner rekursiv durchsuchen
            is_folder = mime_type == "application/vnd.google-apps.folder"
            has_no_extension = '.' not in filename
            if is_folder or (has_no_extension and not mime_type.startswith("application/")):
                # Könnte ein Ordner sein - versuche rekursiv zu laden
                subfolder_path = f"{folder_path}/{filename}" if folder_path else filename
                logger.info(f"Unterordner gefunden: {subfolder_path}")

                self._collect_public_folder_recursive(
                    folder_id=file_id,
                    folder_path=subfolder_path,
                    connection=connection,
                    session=session,
                    files=files,
                    depth=depth + 1,
                    max_depth=max_depth
                )
                continue

            # Google Docs/Sheets etc. überspringen
            if mime_type.startswith("application/vnd.google-apps"):
                logger.debug(f"Überspringe Google App-Datei: {filename} ({mime_type})")
                continue

            ext = Path(filename).suffix.lower()

            # Dateiendung prüfen
            if connection.file_extensions and ext and ext not in connection.file_extensions:
                logger.debug(f"Überspringe wegen Dateiendung: {filename} ({ext} nicht in {connection.file_extensions})")
                continue

            # Prüfen ob bereits synchronisiert
            existing_log = session.query(CloudSyncLog).filter(
                CloudSyncLog.connection_id == connection.id,
                CloudSyncLog.remote_file_id == file_id
            ).first()

            if existing_log:
                logger.debug(f"Überspringe bereits synchronisiert: {filename}")
                continue

            logger.info(f"Datei erkannt (wird importiert): {filename} ({mime_type})")

            # Vollständigen Pfad für die Datei erstellen
            full_path = f"{folder_path}/{filename}" if folder_path else filename

            files.append({
                "name": filename,
                "path": full_path,  # WICHTIG: Vollständiger Pfad für Kategorisierung
                "id": file_id,
                "size": file_info.get("size", 0),
                "hash": None,
                "modified": None,
                "mime_type": mime_type,
                "provider": "google_drive_public",
                "source_folder": folder_path  # Quellordner für Dokumenten-Intelligenz
            })

            logger.info(f"Datei gefunden: {full_path}")

        return files

    # ==================== SYNCHRONISATION ====================

    def sync_connection(self, connection_id: int,
                        process_documents: bool = True) -> Dict[str, Any]:
        """
        Führt Synchronisation für eine Verbindung durch (ohne Fortschrittsanzeige)
        """
        # Sammle alle Updates und gib nur das finale Ergebnis zurück
        final_result = None
        for progress in self.sync_connection_with_progress(connection_id, process_documents):
            final_result = progress
        return final_result or {"success": False, "error": "Keine Ergebnisse"}

    def sync_connection_with_progress(self, connection_id: int,
                                       process_documents: bool = True,
                                       batch_size: int = 0,
                                       batch_offset: int = 0,
                                       enable_diagnostics: bool = True):
        """
        Führt Synchronisation mit Fortschritts-Updates durch (Generator).

        Args:
            connection_id: ID der Cloud-Verbindung
            process_documents: Ob Dokumente verarbeitet werden sollen
            batch_size: Maximale Anzahl Dateien pro Durchlauf (0 = alle)
            batch_offset: Ab welcher Datei begonnen werden soll
            enable_diagnostics: Aktiviert detaillierte Diagnose-Erfassung

        Yields:
            Dict mit Fortschrittsinformationen:
            - phase: 'scanning', 'downloading', 'completed', 'error'
            - current_file: Name der aktuell verarbeiteten Datei
            - current_file_size: Größe der aktuellen Datei
            - files_total: Gesamtanzahl gefundener Dateien
            - files_processed: Bisher verarbeitete Dateien
            - files_synced: Erfolgreich synchronisierte Dateien
            - files_skipped: Übersprungene Dateien
            - progress_percent: Fortschritt in Prozent (0-100)
            - elapsed_seconds: Verstrichene Zeit
            - estimated_remaining_seconds: Geschätzte Restzeit
            - success: True wenn abgeschlossen und erfolgreich
            - error: Fehlermeldung falls vorhanden
            - batch_info: Informationen zum Batch-Modus
            - diagnostics: Diagnose-Zusammenfassung (wenn aktiviert)
        """
        import time
        start_time = time.time()

        # Speichere connection_id für Heartbeat-Updates in Unterfunktionen
        self._current_connection_id = connection_id

        # Diagnose-System initialisieren
        diag = None
        if enable_diagnostics:
            diag = create_sync_diagnostics()
            diag.start({
                "connection_id": connection_id,
                "batch_size": batch_size,
                "batch_offset": batch_offset,
                "process_documents": process_documents
            })

        result = {
            "phase": "initializing",
            "current_file": None,
            "current_file_size": 0,
            "files_total": 0,
            "files_processed": 0,
            "files_synced": 0,
            "files_skipped": 0,
            "files_error": 0,
            "progress_percent": 0,
            "elapsed_seconds": 0,
            "estimated_remaining_seconds": None,
            "success": False,
            "new_files": 0,
            "skipped_files": 0,
            "errors": [],
            "error": None,
            "synced_files": [],
            "batch_info": {
                "batch_size": batch_size,
                "batch_offset": batch_offset,
                "has_more": False,
                "next_offset": 0,
                "total_files_found": 0
            },
            "diagnostics_live": None  # Live-Diagnose-Daten für Debug-Modus
        }

        def add_live_diagnostics(res: dict) -> dict:
            """Fügt aktuelle Live-Diagnose-Daten zum Ergebnis hinzu"""
            if diag and enable_diagnostics:
                res["diagnostics_live"] = {
                    "events": diag.events[-20:] if diag.events else [],  # Letzte 20 Events
                    "api_calls": diag.api_calls[-10:] if diag.api_calls else [],  # Letzte 10 API-Calls
                    "file_operations": diag.file_operations[-10:] if diag.file_operations else [],
                    "errors": diag.errors[-10:] if diag.errors else [],
                    "memory_snapshots": diag.memory_snapshots[-5:] if diag.memory_snapshots else [],
                    "current_file_index": diag.current_file_index,
                    "total_files": diag.total_files,
                    "phase": diag.phase,
                    "last_successful_file": diag.last_successful_file,
                    "elapsed_ms": diag._elapsed_ms()
                }
            return res.copy()

        yield add_live_diagnostics(result)

        with get_db() as session:
            connection = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.id == connection_id,
                CloudSyncConnection.user_id == self.user_id
            ).first()

            if not connection:
                result["phase"] = "error"
                result["error"] = "Verbindung nicht gefunden"
                result["errors"].append(result["error"])
                yield add_live_diagnostics(result)
                return

            if not connection.is_active:
                result["phase"] = "error"
                result["error"] = "Verbindung ist deaktiviert"
                result["errors"].append(result["error"])
                yield add_live_diagnostics(result)
                return

            # Prüfen ob Access Token vorhanden (außer bei öffentlichen Ordnern)
            is_public_google_drive = (
                connection.provider == CloudProvider.GOOGLE_DRIVE and
                not connection.access_token and
                (connection.remote_folder_id or connection.remote_folder_path)
            )

            is_public_dropbox = (
                connection.provider == CloudProvider.DROPBOX and
                not connection.access_token and
                connection.remote_folder_path and
                ('dropbox.com' in connection.remote_folder_path)
            )

            if not connection.access_token and not is_public_google_drive and not is_public_dropbox:
                result["phase"] = "error"
                result["error"] = "Kein Access Token konfiguriert. Bitte API-Konfiguration in Einstellungen prüfen."
                result["errors"].append(result["error"])
                result["success"] = True  # Nicht als Fehler behandeln, nur Hinweis
                yield add_live_diagnostics(result)
                return

            # Status auf "syncing" setzen
            connection.status = SyncStatus.SYNCING
            session.commit()

            try:
                # Phase 1: Dateien scannen
                result["phase"] = "scanning"
                if diag:
                    diag.set_phase("scanning")
                yield add_live_diagnostics(result)

                try:
                    scan_start = time.time()
                    if connection.provider == CloudProvider.DROPBOX:
                        # Öffentliche oder authentifizierte Dropbox
                        if is_public_dropbox:
                            if diag:
                                diag.log_event("scan_start", "Starte Dropbox Public Scan")
                            files_to_sync = self._collect_dropbox_files_public(connection, session)
                        else:
                            if diag:
                                diag.log_event("scan_start", "Starte Dropbox API Scan")
                            files_to_sync = self._collect_dropbox_files(connection, session)
                    elif connection.provider == CloudProvider.GOOGLE_DRIVE:
                        # Öffentliche Ordner verwenden andere Methode
                        if is_public_google_drive:
                            logger.info("Starte öffentliche Google Drive Sammlung...")
                            if diag:
                                diag.log_event("scan_start", "Starte Google Drive Public Scan")
                            files_to_sync = self._collect_google_drive_files_public(connection, session)
                            logger.info(f"Sammlung abgeschlossen: {len(files_to_sync)} Dateien")
                        else:
                            if diag:
                                diag.log_event("scan_start", "Starte Google Drive API Scan")
                            files_to_sync = self._collect_google_drive_files(connection, session)
                    else:
                        result["phase"] = "error"
                        result["error"] = f"Provider {connection.provider} nicht unterstützt"
                        result["errors"].append(result["error"])
                        if diag:
                            diag.log_error("unsupported_provider", result["error"])
                        yield add_live_diagnostics(result)
                        return

                    scan_duration = (time.time() - scan_start) * 1000
                    if diag:
                        diag.log_event("scan_complete",
                                       f"Scan abgeschlossen: {len(files_to_sync)} Dateien in {scan_duration:.0f}ms",
                                       {"files_found": len(files_to_sync), "duration_ms": scan_duration})

                except Exception as collect_error:
                    logger.error(f"Fehler beim Sammeln der Dateien: {collect_error}")
                    if diag:
                        diag.log_error("scan_error", str(collect_error), collect_error)
                    result["phase"] = "error"
                    result["error"] = f"Fehler beim Scannen: {str(collect_error)}"
                    result["errors"].append(result["error"])
                    yield add_live_diagnostics(result)
                    return

                result["files_total"] = len(files_to_sync)
                logger.info(f"Dateien gefunden: {result['files_total']}")
                if diag:
                    diag.set_file_progress(0, result["files_total"])

                # Batch-Info speichern
                result["batch_info"]["total_files_found"] = len(files_to_sync)

                # Batch-Modus: Nur einen Teil der Dateien verarbeiten
                # WICHTIG: Der Offset wird NICHT mehr verwendet, da bereits synchronisierte
                # Dateien automatisch durch den Sync-Log-Filter entfernt werden.
                # Der batch_size begrenzt nur, wie viele Dateien pro Durchlauf verarbeitet werden.
                if batch_size > 0:
                    total_files = len(files_to_sync)
                    # Auf batch_size begrenzen (Offset wird ignoriert, da Sync-Filter aktiv)
                    if len(files_to_sync) > batch_size:
                        files_to_sync = files_to_sync[:batch_size]
                        result["batch_info"]["has_more"] = True
                        result["batch_info"]["next_offset"] = batch_size  # Nur für UI-Anzeige
                    else:
                        result["batch_info"]["has_more"] = False

                    result["files_total"] = len(files_to_sync)
                    logger.info(f"Batch-Modus: Verarbeite {len(files_to_sync)} von {total_files} Dateien")

                if result["files_total"] == 0:
                    result["phase"] = "completed"
                    result["success"] = True
                    result["error"] = None
                    connection.status = SyncStatus.COMPLETED
                    connection.last_sync_at = datetime.now()
                    session.commit()
                    yield add_live_diagnostics(result)
                    return

                result["phase"] = "downloading"
                if diag:
                    diag.set_phase("downloading")
                yield add_live_diagnostics(result)

                # Konfiguration für Pausen und Checks
                pause_between_files = SYNC_CONFIG.get("pause_between_files", 0.3)
                memory_check_interval = SYNC_CONFIG.get("memory_check_interval", 5)
                cache_clear_interval = SYNC_CONFIG.get("cache_clear_interval", 10)
                db_check_interval = 10  # Alle X Dateien DB-Verbindung prüfen
                diag_save_interval = 5  # Alle X Dateien Diagnose in DB speichern
                consecutive_errors = 0
                max_consecutive_errors = 5  # Nach X Fehlern hintereinander abbrechen

                # Initiale Diagnose-Speicherung in DB
                if diag and enable_diagnostics:
                    save_diagnostic_to_db(self.user_id, connection_id, diag, status="running")
                    diag.log_event("diag_save", "Initiale Diagnose in DB gespeichert")

                # INITIAL RAM CHECK: Wenn RAM schon hoch ist, Cache SOFORT leeren!
                initial_ram = get_current_ram_mb()
                if initial_ram > 320:
                    logger.warning(f"[RAM-INITIAL] RAM bereits bei {initial_ram:.1f}MB - leere Cache vor Sync!")
                    if diag:
                        diag.log_event("ram_initial_cleanup", f"RAM bei Start: {initial_ram:.1f}MB - Cache wird geleert")
                    clear_streamlit_cache()
                    import gc
                    gc.collect()
                    gc.collect()
                    new_ram = get_current_ram_mb()
                    freed = initial_ram - new_ram
                    logger.info(f"[RAM-INITIAL] Nach Cleanup: {new_ram:.1f}MB (freed: {freed:.1f}MB)")
                    if diag:
                        diag.log_event("ram_initial_after", f"RAM nach initial cleanup: {new_ram:.1f}MB (freed: {freed:.1f}MB)")

                # Phase 2: Dateien herunterladen und importieren
                for idx, file_info in enumerate(files_to_sync):
                    file_start_time = time.time()
                    elapsed = file_start_time - start_time
                    result["elapsed_seconds"] = elapsed
                    result["current_file"] = file_info.get("name", "Unbekannt")
                    result["current_file_size"] = file_info.get("size", 0)
                    result["files_processed"] = idx
                    result["source_folder"] = file_info.get("source_folder", "")

                    # Diagnose: Datei-Fortschritt aktualisieren
                    if diag:
                        diag.set_file_progress(idx + 1, result["files_total"])
                        # Speicher prüfen nach Intervall
                        if idx % memory_check_interval == 0:
                            diag.capture_memory(f"file_{idx}")

                    # Speicherbereinigung alle X Dateien
                    if idx > 0 and idx % cache_clear_interval == 0:
                        # Prüfe RAM vor Cleanup um zu entscheiden welcher Modus
                        pre_cleanup_ram = get_current_ram_mb()
                        use_light = pre_cleanup_ram > 350  # Bei hohem RAM nur light cleanup

                        aggressive_memory_cleanup(light_mode=use_light)

                        if diag:
                            post_cleanup_ram = get_current_ram_mb()
                            freed = pre_cleanup_ram - post_cleanup_ram
                            diag.log_event("cleanup",
                                           f"Cleanup bei Datei {idx}: {pre_cleanup_ram:.0f}→{post_cleanup_ram:.0f}MB (freed: {freed:.0f}MB, light={use_light})")
                            # capture_memory nur wenn RAM niedrig genug (sonst verbraucht es selbst RAM)
                            if post_cleanup_ram < 380:
                                diag.capture_memory(f"after_cleanup_{idx}")

                        # Disk-Space Check nach Cleanup
                        disk_warning_mb = SYNC_CONFIG.get("disk_warning_threshold_mb", 100)
                        disk_critical_mb = SYNC_CONFIG.get("disk_critical_threshold_mb", 50)
                        disk_info = get_disk_usage()
                        tmp_free_mb = disk_info.get("tmp_free_mb", 999999)

                        if tmp_free_mb < disk_critical_mb:
                            # Kritisch wenig Speicherplatz - Abbruch
                            error_msg = f"Kritisch wenig Speicherplatz: {tmp_free_mb:.1f}MB frei (min: {disk_critical_mb}MB)"
                            logger.error(f"[DISK-CRITICAL] {error_msg}")
                            if diag:
                                diag.log_error("disk_space_critical", error_msg, None)
                            result["phase"] = "error"
                            result["error"] = error_msg
                            result["errors"].append(error_msg)
                            # Diagnose speichern vor Abbruch
                            if diag and enable_diagnostics:
                                save_diagnostic_to_db(self.user_id, connection_id, diag,
                                                      status="error", error_message=error_msg)
                            break

                        elif tmp_free_mb < disk_warning_mb:
                            # Warnung - aber weiter machen mit extra Cleanup
                            logger.warning(f"[DISK-WARNING] Wenig Speicherplatz: {tmp_free_mb:.1f}MB frei")
                            if diag:
                                diag.log_event("disk_space_warning",
                                               f"Wenig Speicherplatz: {tmp_free_mb:.1f}MB frei - extra Cleanup")
                            # Zusätzlicher Temp-File Cleanup
                            cleanup_temp_files(max_age_minutes=5)

                    # Diagnose periodisch in DB speichern (für den Fall eines Abbruchs)
                    if diag and enable_diagnostics and idx > 0 and idx % diag_save_interval == 0:
                        save_diagnostic_to_db(self.user_id, connection_id, diag, status="running")
                        diag.log_event("diag_save", f"Diagnose in DB gespeichert bei Datei {idx}")

                    # Datenbankverbindung prüfen (alle X Dateien)
                    if idx > 0 and idx % db_check_interval == 0:
                        try:
                            from sqlalchemy import text
                            session.execute(text("SELECT 1"))
                            if diag:
                                diag.log_event("db_check", f"DB-Verbindung OK bei Datei {idx}")
                        except Exception as db_err:
                            logger.warning(f"[DB-CHECK] Verbindung unterbrochen bei Datei {idx}: {db_err}")
                            if diag:
                                diag.log_error("db_connection_lost", f"Verbindung unterbrochen bei Datei {idx}", db_err)

                            # Versuche Recovery
                            try:
                                session.rollback()
                                # Warte kurz und versuche Reconnect
                                time.sleep(2)
                                session.execute(text("SELECT 1"))
                                logger.info("[DB-CHECK] Verbindung wiederhergestellt")
                                if diag:
                                    diag.log_event("db_reconnect", "DB-Verbindung wiederhergestellt")
                            except Exception as reconnect_err:
                                logger.error(f"[DB-CHECK] Reconnect fehlgeschlagen: {reconnect_err}")
                                if diag:
                                    diag.log_error("db_reconnect_failed", "Reconnect fehlgeschlagen", reconnect_err)
                                # Beende Sync aber speichere was wir haben
                                result["phase"] = "error"
                                result["error"] = f"Datenbankverbindung verloren bei Datei {idx}"
                                result["errors"].append(result["error"])
                                break

                    # Fortschritt berechnen
                    if result["files_total"] > 0:
                        result["progress_percent"] = int((idx / result["files_total"]) * 100)

                        # Restzeit schätzen
                        if idx > 0:
                            avg_time_per_file = elapsed / idx
                            remaining_files = result["files_total"] - idx
                            result["estimated_remaining_seconds"] = avg_time_per_file * remaining_files

                    # VOR großen Dateien (>1MB): RAM prüfen und ggf. cleanen
                    file_size_mb = file_info.get("size", 0) / (1024 * 1024)
                    if file_size_mb > 1.0:
                        pre_ram = get_current_ram_mb()
                        if pre_ram > 300:  # Wenn RAM schon bei 300+ MB, vor großer Datei cleanen
                            logger.info(f"[PRE-FILE] Große Datei ({file_size_mb:.1f}MB), RAM={pre_ram:.1f}MB - cleanup vor Download")
                            aggressive_memory_cleanup(light_mode=True)
                            if diag:
                                diag.log_event("pre_file_cleanup",
                                               f"Cleanup vor großer Datei ({file_size_mb:.1f}MB), RAM war {pre_ram:.1f}MB")

                    # Status: Download startet
                    result["current_step"] = "downloading"
                    result["current_step_detail"] = f"Lade {file_info.get('name')} herunter..."

                    # HEARTBEAT: Aktuellen Verarbeitungsstand in DB speichern
                    update_heartbeat(
                        self.user_id, connection_id,
                        current_file=file_info.get('name'),
                        current_index=idx,
                        current_step="downloading",
                        step_detail=f"Lade herunter: {file_info.get('name')} ({file_info.get('size', 0)} Bytes)"
                    )

                    if diag:
                        diag.log_event("file_start",
                                       f"Starte Datei {idx+1}/{result['files_total']}: {file_info.get('name')}",
                                       {"file_size": file_info.get("size", 0)})
                    yield add_live_diagnostics(result)

                    # Datei verarbeiten mit Fehler-Isolation
                    file_success = False
                    try:
                        sync_status, processing_steps = self._process_file_with_status(
                            connection, session, file_info, process_documents, result
                        )
                        file_success = (sync_status in ["synced", "skipped"])

                        file_duration = (time.time() - file_start_time) * 1000

                        # Yield für jeden Verarbeitungsschritt
                        for step in processing_steps:
                            result["current_step"] = step.get("step", "processing")
                            result["current_step_detail"] = step.get("detail", "")
                            yield add_live_diagnostics(result)

                        if sync_status == "synced":
                            result["files_synced"] += 1
                            result["synced_files"].append(file_info.get("name"))
                            # Diagnose: Erfolgreiche Datei
                            if diag:
                                diag.log_file_operation(
                                    file_info.get("name"), "import", "success",
                                    file_info.get("size", 0), file_duration
                                )
                            # Commit nach jedem erfolgreichen Import!
                            try:
                                session.commit()
                            except Exception as commit_err:
                                logger.error(f"Commit Fehler für {file_info.get('name')}: {commit_err}")
                                if diag:
                                    diag.log_error("commit_error", str(commit_err), commit_err)
                                session.rollback()
                                result["files_error"] += 1
                                result["errors"].append(f"{file_info.get('name')}: Commit fehlgeschlagen")
                        elif sync_status == "skipped":
                            result["files_skipped"] += 1
                            # Diagnose: Übersprungene Datei
                            if diag:
                                diag.log_file_operation(
                                    file_info.get("name"), "skip", "skipped",
                                    file_info.get("size", 0), file_duration
                                )
                        else:
                            result["files_error"] += 1
                            # Rollback bei Fehler, damit nächste Datei funktioniert
                            try:
                                session.rollback()
                            except:
                                pass
                            # Füge letzten Fehler-Schritt zu Fehlerliste hinzu
                            error_detail = "Unbekannter Fehler"
                            for step in reversed(processing_steps):
                                if step.get("step") == "error" or "❌" in step.get("detail", ""):
                                    error_detail = step.get("detail", error_detail)
                                    break
                            result["errors"].append(f"{file_info.get('name')}: {error_detail}")
                            # Diagnose: Fehler bei Datei
                            if diag:
                                diag.log_file_operation(
                                    file_info.get("name"), "import", "error",
                                    file_info.get("size", 0), file_duration, error_detail
                                )

                    except Exception as e:
                        logger.error(f"Fehler beim Import von {file_info.get('name')}: {e}")
                        result["files_error"] += 1
                        result["errors"].append(f"{file_info.get('name')}: {str(e)}")
                        # Diagnose: Exception bei Datei
                        if diag:
                            diag.log_error("file_exception", f"Datei {file_info.get('name')}: {str(e)}", e)
                            diag.log_file_operation(
                                file_info.get("name"), "import", "error",
                                file_info.get("size", 0), 0, str(e)
                            )
                        # Rollback bei Exception
                        try:
                            session.rollback()
                        except:
                            pass

                    # Fehler-Tracking für Abbruch bei zu vielen aufeinanderfolgenden Fehlern
                    if file_success:
                        consecutive_errors = 0  # Reset bei Erfolg
                    else:
                        consecutive_errors += 1
                        logger.warning(f"[ERROR-TRACK] Aufeinanderfolgende Fehler: {consecutive_errors}/{max_consecutive_errors}")

                        if consecutive_errors >= max_consecutive_errors:
                            logger.error(f"[ERROR-TRACK] Abbruch nach {consecutive_errors} aufeinanderfolgenden Fehlern")
                            if diag:
                                diag.log_error("consecutive_errors",
                                    f"Abbruch nach {consecutive_errors} aufeinanderfolgenden Fehlern",
                                    None)
                            result["error"] = f"Zu viele aufeinanderfolgende Fehler ({consecutive_errors})"
                            result["errors"].append(result["error"])
                            break

                    # RAM-Check nach JEDER Datei - kritisch für Streamlit Cloud
                    current_ram = get_current_ram_mb()
                    ram_warning_mb = SYNC_CONFIG.get("ram_warning_threshold_mb", 450)
                    ram_critical_mb = SYNC_CONFIG.get("ram_critical_threshold_mb", 550)

                    if current_ram > ram_critical_mb:
                        # Kritisch hoher RAM - Abbruch um Crash zu vermeiden
                        error_msg = f"RAM kritisch hoch: {current_ram:.1f}MB (max: {ram_critical_mb}MB) - Abbruch bei Datei {idx}"
                        logger.error(f"[RAM-CRITICAL] {error_msg}")
                        if diag:
                            diag.log_error("ram_critical", error_msg, None)
                            diag.capture_memory(f"ram_critical_{idx}")
                        result["phase"] = "error"
                        result["error"] = error_msg
                        result["errors"].append(error_msg)
                        # Diagnose speichern vor Abbruch
                        if diag and enable_diagnostics:
                            save_diagnostic_to_db(self.user_id, connection_id, diag,
                                                  status="error", error_message=error_msg)
                        break

                    elif current_ram > ram_warning_mb:
                        # RAM hoch - versuche erst leichte GC
                        logger.warning(f"[RAM-WARNING] RAM hoch: {current_ram:.1f}MB - führe light cleanup durch")
                        if diag:
                            diag.log_event("ram_warning", f"RAM bei {current_ram:.1f}MB - light cleanup")

                        # Erst versuchen: NUR Garbage Collection
                        aggressive_memory_cleanup(light_mode=True)

                        # Prüfe ob Cleanup geholfen hat
                        new_ram = get_current_ram_mb()
                        freed = current_ram - new_ram

                        # Wenn light_mode nichts befreit UND RAM nahe kritisch: Cache leeren!
                        if freed < 5 and new_ram > (ram_warning_mb + 20):
                            logger.warning(f"[RAM-ESCALATE] Light cleanup ineffektiv (freed {freed:.1f}MB), RAM noch {new_ram:.1f}MB - leere Cache!")
                            if diag:
                                diag.log_event("ram_escalate", f"Light cleanup ineffektiv, Cache wird geleert")
                            aggressive_memory_cleanup(light_mode=True, force_cache_clear=True)
                            new_ram = get_current_ram_mb()
                            freed = current_ram - new_ram

                        if diag:
                            diag.log_event("ram_after_cleanup", f"RAM: {new_ram:.1f}MB (freed: {freed:.1f}MB)")
                            # KEINE capture_memory hier - das braucht selbst RAM!

                    elif current_ram > (ram_warning_mb - 50):
                        # RAM moderat hoch - nur schnelle GC nach jeder Datei
                        import gc
                        gc.collect(generation=0)  # Nur junge Objekte, sehr schnell
                        gc.collect(generation=1)

                    # Kurze Pause zwischen Dateien um API-Limits zu vermeiden
                    # (besonders wichtig für Supabase Storage)
                    if idx < len(files_to_sync) - 1:  # Nicht nach letzter Datei
                        time.sleep(pause_between_files)

                # Phase 3: Abschluss
                result["phase"] = "completed"
                if diag:
                    diag.set_phase("completed")
                result["files_processed"] = result["files_total"]
                result["progress_percent"] = 100
                result["new_files"] = result["files_synced"]
                result["skipped_files"] = result["files_skipped"]
                result["success"] = len(result["errors"]) == 0
                result["elapsed_seconds"] = time.time() - start_time
                result["estimated_remaining_seconds"] = 0

                # Status aktualisieren
                connection.status = SyncStatus.COMPLETED
                connection.last_sync_at = datetime.now()
                connection.last_sync_error = None
                connection.total_files_synced += result["files_synced"]

                # Diagnose abschließen
                if diag:
                    diag.finish(result["success"], {
                        "files_synced": result["files_synced"],
                        "files_skipped": result["files_skipped"],
                        "files_error": result["files_error"],
                        "elapsed_seconds": result["elapsed_seconds"]
                    })
                    # Finale Diagnose in DB speichern
                    if enable_diagnostics:
                        final_status = "completed" if result["success"] else "error"
                        save_diagnostic_to_db(
                            self.user_id, connection_id, diag,
                            status=final_status,
                            error_message=result.get("error")
                        )

            except Exception as e:
                logger.error(f"Sync-Fehler für Verbindung {connection_id}: {e}")
                import traceback
                error_tb = traceback.format_exc()
                if diag:
                    diag.log_error("sync_exception", f"Allgemeiner Sync-Fehler: {str(e)}", e)
                    diag.finish(False, {"error": str(e)})
                    # Fehler-Diagnose in DB speichern
                    if enable_diagnostics:
                        save_diagnostic_to_db(
                            self.user_id, connection_id, diag,
                            status="error",
                            error_message=str(e),
                            error_traceback=error_tb
                        )
                connection.status = SyncStatus.ERROR
                connection.last_sync_error = str(e)
                result["phase"] = "error"
                result["error"] = str(e)
                result["errors"].append(str(e))

            session.commit()

        # Cache am Ende leeren
        clear_streamlit_cache()

        # Sync-Log schreiben
        self._write_sync_log(connection_id, result)

        # Wenn Fehler vorhanden, erste Fehlermeldung setzen
        if result["errors"] and not result["error"]:
            result["error"] = result["errors"][0]

        # Diagnose-Zusammenfassung ans Ergebnis anhängen (vollständiger Bericht am Ende)
        if diag:
            result["diagnostics"] = diag.get_summary()
            result["diagnostics_analysis"] = diag.get_failure_analysis()
            result["diagnostics_full_report"] = diag.get_full_report()

        yield add_live_diagnostics(result)

    def _collect_dropbox_files(self, connection: CloudSyncConnection,
                                session) -> List[Dict]:
        """Sammelt alle zu synchronisierenden Dropbox-Dateien"""
        files = []
        cursor = connection.last_cursor
        has_more = True

        while has_more:
            response = self._dropbox_list_folder(
                connection.access_token,
                connection.remote_folder_path,
                cursor
            )

            if "error" in response:
                break

            entries = response.get("entries", [])

            for entry in entries:
                if entry.get(".tag") != "file":
                    continue

                filename = entry.get("name", "")
                ext = Path(filename).suffix.lower()

                # Dateiendung prüfen
                if connection.file_extensions and ext not in connection.file_extensions:
                    continue

                # Dateigröße prüfen
                file_size = entry.get("size", 0)
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024
                if file_size > max_size:
                    continue

                # Prüfen ob bereits synchronisiert
                content_hash = entry.get("content_hash")
                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == content_hash
                ).first()

                if existing_log:
                    continue

                files.append({
                    "name": filename,
                    "path": entry.get("path_display"),
                    "id": entry.get("id"),
                    "size": file_size,
                    "hash": content_hash,
                    "modified": entry.get("server_modified"),
                    "provider": "dropbox"
                })

            cursor = response.get("cursor")
            has_more = response.get("has_more", False)

        # Cursor speichern
        if cursor:
            connection.last_cursor = cursor

        return files

    def _collect_google_drive_files(self, connection: CloudSyncConnection,
                                     session) -> List[Dict]:
        """Sammelt alle zu synchronisierenden Google Drive-Dateien"""
        files = []

        # Versuche Folder-ID zu extrahieren (kann URL oder echte ID sein)
        folder_id = None
        if connection.remote_folder_id:
            if 'drive.google.com' in connection.remote_folder_id:
                folder_id = self._google_get_folder_id_from_link(connection.remote_folder_id)
            elif len(connection.remote_folder_id) > 10 and not connection.remote_folder_id.startswith('http'):
                folder_id = connection.remote_folder_id

        if not folder_id and connection.remote_folder_path:
            folder_id = self._google_get_folder_id_from_link(connection.remote_folder_path)

        page_token = None
        has_more = True

        while has_more:
            response = self._google_list_folder(
                connection.access_token,
                folder_id,
                page_token
            )

            if "error" in response:
                break

            file_list = response.get("files", [])

            for file_info in file_list:
                mime_type = file_info.get("mimeType", "")
                if mime_type.startswith("application/vnd.google-apps"):
                    continue

                filename = file_info.get("name", "")
                ext = Path(filename).suffix.lower()

                # Dateiendung prüfen
                if connection.file_extensions and ext not in connection.file_extensions:
                    continue

                # Dateigröße prüfen
                file_size = int(file_info.get("size", 0))
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024
                if file_size > max_size:
                    continue

                # Prüfen ob bereits synchronisiert
                file_hash = file_info.get("md5Checksum")
                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == file_hash
                ).first()

                if existing_log:
                    continue

                files.append({
                    "name": filename,
                    "path": filename,
                    "id": file_info.get("id"),
                    "size": file_size,
                    "hash": file_hash,
                    "modified": file_info.get("modifiedTime"),
                    "mime_type": mime_type,
                    "provider": "google_drive"
                })

            page_token = response.get("nextPageToken")
            has_more = page_token is not None

        return files

    def _process_file(self, connection: CloudSyncConnection, session,
                      file_info: Dict, process_documents: bool) -> str:
        """
        Verarbeitet eine einzelne Datei (Wrapper ohne Status-Rückgabe).

        Returns:
            'synced', 'skipped', oder 'error'
        """
        status, _ = self._process_file_with_status(connection, session, file_info, process_documents, {})
        return status

    def _process_file_with_status(self, connection: CloudSyncConnection, session,
                                   file_info: Dict, process_documents: bool,
                                   progress_result: Dict) -> Tuple[str, List[Dict]]:
        """
        Verarbeitet eine einzelne Datei mit detaillierten Status-Updates.

        Returns:
            Tuple von (status: 'synced'/'skipped'/'error', processing_steps: Liste von Status-Updates)
        """
        import gc
        processing_steps = []
        file_content = None  # Initialisieren für finally-Block

        try:
            provider = file_info.get("provider", "")
            filename = file_info.get("name", "unknown")

            logger.info(f"Verarbeite Datei: {filename} (Provider: {provider})")

            # Schritt 1: Download
            processing_steps.append({
                "step": "downloading",
                "detail": f"📥 Lade herunter: {filename}"
            })

            if provider == "dropbox":
                file_content, metadata = self._dropbox_download_file(
                    connection.access_token,
                    file_info.get("path")
                )
            elif provider == "google_drive_public":
                logger.info(f"Starte öffentlichen Download für: {filename}")
                file_content, success = self._google_public_download_file(
                    file_info.get("id")
                )
                if not success:
                    logger.error(f"Download fehlgeschlagen für {filename}")
                    processing_steps.append({
                        "step": "error",
                        "detail": f"❌ Download fehlgeschlagen: {filename}"
                    })
                    return "error", processing_steps
                logger.info(f"Download erfolgreich: {len(file_content)} Bytes")
            else:
                file_content = self._google_download_file(
                    connection.access_token,
                    file_info.get("id")
                )

            processing_steps.append({
                "step": "downloaded",
                "detail": f"✅ Heruntergeladen: {len(file_content):,} Bytes"
            })

            # WICHTIG: Content-Hash berechnen für Duplikat-Erkennung!
            import hashlib
            content_hash = hashlib.sha256(file_content).hexdigest()

            # Quellordner-Pfad für intelligente Kategorisierung
            source_folder_path = file_info.get("source_folder") or file_info.get("path") or ""

            logger.info(f"Importiere Datei: {filename} aus Ordner: {source_folder_path}")

            # Schritt 2: Speichern
            processing_steps.append({
                "step": "saving",
                "detail": f"💾 Speichere Datei lokal..."
            })

            # Dokument erstellen mit Status-Tracking
            doc, import_steps = self._import_file_with_status(
                session, connection,
                filename,
                file_content,
                file_info.get("size", len(file_content)),
                content_hash,  # Berechneter Hash statt file_info.get("hash") das None war!
                source_folder_path,
                process_documents
            )

            # Import-Schritte hinzufügen
            processing_steps.extend(import_steps)

            # Sync-Log erstellen
            modified_time = file_info.get("modified")
            if modified_time and isinstance(modified_time, str):
                try:
                    modified_time = datetime.fromisoformat(modified_time.replace("Z", "+00:00"))
                except:
                    modified_time = None

            sync_log = CloudSyncLog(
                connection_id=connection.id,
                user_id=self.user_id,
                remote_file_path=file_info.get("path") or file_info.get("name"),
                remote_file_id=file_info.get("id"),
                remote_file_hash=content_hash,  # Berechneter Hash!
                file_size=file_info.get("size"),
                file_modified_at=modified_time,
                document_id=doc.id if doc else None,
                local_file_path=doc.file_path if doc else None,
                sync_status="synced",
                original_filename=file_info.get("name"),
                mime_type=file_info.get("mime_type") or self._get_mime_type(file_info.get("name"))
            )
            session.add(sync_log)

            processing_steps.append({
                "step": "completed",
                "detail": f"✅ Fertig: {filename}"
            })

            return "synced", processing_steps

        except Exception as e:
            logger.error(f"Fehler beim Verarbeiten von {file_info.get('name')}: {e}")
            processing_steps.append({
                "step": "error",
                "detail": f"❌ Fehler: {str(e)}"
            })
            return "error", processing_steps

        finally:
            # WICHTIG: Explizite Speicherfreigabe nach jeder Datei
            # Dies verhindert Speicherakkumulation bei großen Syncs
            if file_content is not None:
                del file_content
                file_content = None

            # Garbage Collection für diese einzelne Datei - alle Generationen
            gc.collect(generation=0)
            gc.collect(generation=1)
            gc.collect(generation=2)
            gc.collect()

            # malloc_trim um Speicher ans OS zurückzugeben
            try:
                import ctypes
                libc = ctypes.CDLL("libc.so.6")
                libc.malloc_trim(0)
            except:
                pass

    def _sync_dropbox(self, connection: CloudSyncConnection,
                      session, process_documents: bool) -> Dict:
        """Synchronisiert Dropbox-Ordner"""
        result = {
            "files_found": 0,
            "files_synced": 0,
            "files_skipped": 0,
            "files_error": 0,
            "errors": [],
            "synced_files": []
        }

        cursor = connection.last_cursor
        has_more = True

        while has_more:
            response = self._dropbox_list_folder(
                connection.access_token,
                connection.remote_folder_path,
                cursor
            )

            if "error" in response:
                result["errors"].append(response.get("error_summary", "Dropbox API Fehler"))
                break

            entries = response.get("entries", [])

            for entry in entries:
                if entry.get(".tag") != "file":
                    continue

                result["files_found"] += 1

                # Dateiendung prüfen
                filename = entry.get("name", "")
                ext = Path(filename).suffix.lower()

                if connection.file_extensions and ext not in connection.file_extensions:
                    result["files_skipped"] += 1
                    continue

                # Dateigröße prüfen
                file_size = entry.get("size", 0)
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024

                if file_size > max_size:
                    result["files_skipped"] += 1
                    continue

                # Prüfen ob bereits synchronisiert (über Hash)
                content_hash = entry.get("content_hash")

                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == content_hash
                ).first()

                if existing_log:
                    result["files_skipped"] += 1
                    continue

                # Datei herunterladen und importieren
                try:
                    file_content, metadata = self._dropbox_download_file(
                        connection.access_token,
                        entry.get("path_display")
                    )

                    # Dokument erstellen
                    doc = self._import_file(
                        session, connection, filename, file_content,
                        file_size, content_hash, entry.get("path_display"),
                        process_documents
                    )

                    # Sync-Log erstellen
                    sync_log = CloudSyncLog(
                        connection_id=connection.id,
                        user_id=self.user_id,
                        remote_file_path=entry.get("path_display"),
                        remote_file_id=entry.get("id"),
                        remote_file_hash=content_hash,
                        file_size=file_size,
                        file_modified_at=datetime.fromisoformat(
                            entry.get("server_modified", "").replace("Z", "+00:00")
                        ) if entry.get("server_modified") else None,
                        document_id=doc.id if doc else None,
                        local_file_path=doc.file_path if doc else None,
                        sync_status="synced",
                        original_filename=filename,
                        mime_type=self._get_mime_type(filename)
                    )
                    session.add(sync_log)

                    result["files_synced"] += 1
                    result["synced_files"].append(filename)

                except Exception as e:
                    logger.error(f"Fehler beim Import von {filename}: {e}")
                    result["files_error"] += 1
                    result["errors"].append(f"{filename}: {str(e)}")

            # Cursor für nächste Seite
            cursor = response.get("cursor")
            has_more = response.get("has_more", False)

        # Cursor speichern für Delta-Sync
        if cursor:
            connection.last_cursor = cursor

        return result

    def _sync_google_drive(self, connection: CloudSyncConnection,
                           session, process_documents: bool) -> Dict:
        """Synchronisiert Google Drive-Ordner"""
        result = {
            "files_found": 0,
            "files_synced": 0,
            "files_skipped": 0,
            "files_error": 0,
            "errors": [],
            "synced_files": []
        }

        # Folder-ID aus Pfad/Link extrahieren (kann URL oder echte ID sein)
        folder_id = None
        if connection.remote_folder_id:
            if 'drive.google.com' in connection.remote_folder_id:
                folder_id = self._google_get_folder_id_from_link(connection.remote_folder_id)
            elif len(connection.remote_folder_id) > 10 and not connection.remote_folder_id.startswith('http'):
                folder_id = connection.remote_folder_id

        if not folder_id and connection.remote_folder_path:
            folder_id = self._google_get_folder_id_from_link(connection.remote_folder_path)

        page_token = None
        has_more = True

        while has_more:
            response = self._google_list_folder(
                connection.access_token,
                folder_id,
                page_token
            )

            if "error" in response:
                result["errors"].append(response.get("error", {}).get("message", "Google API Fehler"))
                break

            files = response.get("files", [])

            for file_info in files:
                # Google Docs/Sheets etc. überspringen (nur echte Dateien)
                mime_type = file_info.get("mimeType", "")
                if mime_type.startswith("application/vnd.google-apps"):
                    continue

                result["files_found"] += 1

                filename = file_info.get("name", "")
                ext = Path(filename).suffix.lower()

                # Dateiendung prüfen
                if connection.file_extensions and ext not in connection.file_extensions:
                    result["files_skipped"] += 1
                    continue

                # Dateigröße prüfen
                file_size = int(file_info.get("size", 0))
                max_size = (connection.max_file_size_mb or 50) * 1024 * 1024

                if file_size > max_size:
                    result["files_skipped"] += 1
                    continue

                # Prüfen ob bereits synchronisiert
                file_hash = file_info.get("md5Checksum")

                existing_log = session.query(CloudSyncLog).filter(
                    CloudSyncLog.connection_id == connection.id,
                    CloudSyncLog.remote_file_hash == file_hash
                ).first()

                if existing_log:
                    result["files_skipped"] += 1
                    continue

                # Datei herunterladen und importieren
                try:
                    file_content = self._google_download_file(
                        connection.access_token,
                        file_info.get("id")
                    )

                    doc = self._import_file(
                        session, connection, filename, file_content,
                        file_size, file_hash, file_info.get("id"),
                        process_documents
                    )

                    # Sync-Log erstellen
                    modified_time = file_info.get("modifiedTime")
                    sync_log = CloudSyncLog(
                        connection_id=connection.id,
                        user_id=self.user_id,
                        remote_file_path=filename,
                        remote_file_id=file_info.get("id"),
                        remote_file_hash=file_hash,
                        file_size=file_size,
                        file_modified_at=datetime.fromisoformat(
                            modified_time.replace("Z", "+00:00")
                        ) if modified_time else None,
                        document_id=doc.id if doc else None,
                        local_file_path=doc.file_path if doc else None,
                        sync_status="synced",
                        original_filename=filename,
                        mime_type=mime_type
                    )
                    session.add(sync_log)

                    result["files_synced"] += 1
                    result["synced_files"].append(filename)

                except Exception as e:
                    logger.error(f"Fehler beim Import von {filename}: {e}")
                    result["files_error"] += 1
                    result["errors"].append(f"{filename}: {str(e)}")

            page_token = response.get("nextPageToken")
            has_more = page_token is not None

        return result

    def _import_file(self, session, connection: CloudSyncConnection,
                     filename: str, content: bytes, file_size: int,
                     content_hash: str, remote_path: str,
                     process_documents: bool) -> Optional[Document]:
        """
        Importiert eine Datei ins Dokumentenmanagement mit intelligenter Analyse.

        - Speichert Datei lokal
        - Führt OCR durch (falls PDF/Bild)
        - Analysiert Inhalt und extrahiert Metadaten
        - Erstellt automatisch passende Ordnerstruktur
        - Verknüpft mit Versicherungen/Verträgen
        """
        # Duplikat-Prüfung: Existiert bereits ein Dokument mit gleichem Inhalt?
        if content_hash:
            existing_doc = session.query(Document).filter(
                Document.user_id == self.user_id,
                Document.content_hash == content_hash
            ).first()

            if existing_doc:
                logger.info(f"Duplikat übersprungen: {filename} (Hash: {content_hash[:16]}...)")
                # Dokument als COMPLETED markieren falls PENDING
                if existing_doc.status == DocumentStatus.PENDING:
                    existing_doc.status = DocumentStatus.COMPLETED
                return existing_doc

        # Speicherpfad erstellen
        upload_dir = Path("data/uploads") / str(self.user_id) / "cloud_sync"
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Eindeutigen Dateinamen erstellen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{filename}"
        file_path = upload_dir / safe_filename

        # Datei speichern
        with open(file_path, "wb") as f:
            f.write(content)

        # Dokument in DB erstellen (vorerst mit Basis-Infos)
        doc = Document(
            user_id=self.user_id,
            folder_id=connection.local_folder_id,
            title=Path(filename).stem,
            filename=filename,
            file_path=str(file_path),
            file_size=file_size,
            mime_type=self._get_mime_type(filename),
            content_hash=content_hash,
            status=DocumentStatus.PENDING if process_documents else DocumentStatus.COMPLETED,
            category="Cloud-Import"
        )

        session.add(doc)
        session.flush()  # Um ID zu erhalten

        # Intelligente Dokumentenverarbeitung wenn aktiviert
        if process_documents:
            try:
                self._process_document_intelligent(
                    session, doc, content, remote_path, filename
                )
            except Exception as e:
                logger.error(f"Intelligente Verarbeitung fehlgeschlagen für {filename}: {e}")
                # Fehler nicht propagieren - Dokument wurde bereits gespeichert

        return doc

    def _import_file_with_status(self, session, connection: CloudSyncConnection,
                                  filename: str, content: bytes, file_size: int,
                                  content_hash: str, remote_path: str,
                                  process_documents: bool) -> Tuple[Optional[Document], List[Dict]]:
        """
        Importiert eine Datei mit Status-Updates für die Fortschrittsanzeige.
        Verwendet StorageService für Cloud-Speicher wenn verfügbar.

        Returns:
            Tuple von (Document, Liste von Status-Updates)
        """
        processing_steps = []
        repair_existing_doc = None  # Für Reparatur fehlender Dateien

        # Duplikat-Prüfung: Existiert bereits ein Dokument mit gleichem Inhalt?
        if content_hash:
            existing_doc = session.query(Document).filter(
                Document.user_id == self.user_id,
                Document.content_hash == content_hash
            ).first()

            if existing_doc:
                # WICHTIG: Prüfen ob die Datei tatsächlich existiert!
                file_exists = False
                try:
                    from services.storage_service import get_storage_service
                    storage = get_storage_service()
                    if existing_doc.file_path:
                        if existing_doc.file_path.startswith("cloud://"):
                            # Cloud-Datei prüfen
                            success, _ = storage.download_file(existing_doc.file_path)
                            file_exists = success
                        else:
                            # Lokale Datei prüfen
                            file_exists = Path(existing_doc.file_path).exists()
                except Exception as e:
                    logger.warning(f"Datei-Existenzprüfung fehlgeschlagen: {e}")
                    file_exists = False

                if file_exists:
                    logger.info(f"Duplikat übersprungen: {filename} (Hash: {content_hash[:16]}...)")
                    processing_steps.append({
                        "step": "skipped",
                        "detail": f"⏭️ Übersprungen - Dokument bereits vorhanden als '{existing_doc.title or existing_doc.filename}'"
                    })
                    # Dokument als COMPLETED markieren falls PENDING
                    if existing_doc.status == DocumentStatus.PENDING:
                        existing_doc.status = DocumentStatus.COMPLETED
                    return existing_doc, processing_steps
                else:
                    # Datei fehlt im Storage! Erneut hochladen und Pfad aktualisieren
                    logger.warning(f"Datei fehlt für {existing_doc.filename}, lade erneut hoch...")
                    processing_steps.append({
                        "step": "repair",
                        "detail": f"🔧 Datei fehlt - wird erneut hochgeladen"
                    })
                    # Markieren dass wir ein bestehendes Dokument reparieren
                    repair_existing_doc = existing_doc

        # Verwende Storage Service für hybride Speicherung
        try:
            from services.storage_service import get_storage_service
            storage = get_storage_service()
        except ImportError:
            storage = None

        # Eindeutigen Dateinamen erstellen
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{filename}"

        # Datei speichern (Cloud oder Lokal)
        if storage:
            success, file_path = storage.upload_file(
                file_data=content,
                filename=safe_filename,
                user_id=self.user_id,
                subfolder="cloud_sync",
                content_type=self._get_mime_type(filename)
            )

            if success:
                if file_path.startswith("cloud://"):
                    processing_steps.append({
                        "step": "saved",
                        "detail": f"☁️ Datei in Cloud gespeichert"
                    })
                else:
                    processing_steps.append({
                        "step": "saved",
                        "detail": f"💾 Datei lokal gespeichert"
                    })
            else:
                logger.error(f"Speichern fehlgeschlagen: {file_path}")
                return None, [{"step": "error", "detail": f"❌ Speichern fehlgeschlagen"}]
        else:
            # Fallback: Direkt lokal speichern
            upload_dir = Path("data/uploads") / str(self.user_id) / "cloud_sync"
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = str(upload_dir / safe_filename)

            with open(file_path, "wb") as f:
                f.write(content)

            processing_steps.append({
                "step": "saved",
                "detail": f"💾 Datei lokal gespeichert"
            })

        # Dokument in DB erstellen oder bestehendes aktualisieren
        # is_encrypted=False: Cloud-importierte Dateien werden nicht verschlüsselt
        if repair_existing_doc:
            # Bestehendes Dokument aktualisieren (Reparatur-Modus)
            doc = repair_existing_doc
            doc.file_path = str(file_path)
            processing_steps.append({
                "step": "repaired",
                "detail": f"✅ Dokument repariert - Datei neu verknüpft"
            })
            logger.info(f"Dokument {doc.id} repariert: neuer Pfad {file_path}")
        else:
            # Neues Dokument erstellen
            doc = Document(
                user_id=self.user_id,
                folder_id=connection.local_folder_id,
                title=Path(filename).stem,
                filename=filename,
                file_path=str(file_path),
                file_size=file_size,
                mime_type=self._get_mime_type(filename),
                content_hash=content_hash,
                status=DocumentStatus.PENDING if process_documents else DocumentStatus.COMPLETED,
                category="Cloud-Import",
                is_encrypted=False,
                encryption_iv=None
            )
            session.add(doc)

        session.flush()

        # WICHTIG: Content-Hash für Cache speichern, dann content freigeben
        saved_content_hash = content_hash
        saved_file_path = str(file_path)

        # Content explizit freigeben - ab hier von Disk lesen!
        del content
        content = None
        import gc
        gc.collect()

        # Intelligente Dokumentenverarbeitung wenn aktiviert
        # WICHTIG: Liest jetzt von Disk statt aus Memory!
        if process_documents:
            try:
                intelligent_steps = self._process_document_intelligent_with_status(
                    session, doc, saved_file_path, saved_content_hash, remote_path, filename
                )
                processing_steps.extend(intelligent_steps)
            except Exception as e:
                logger.error(f"Intelligente Verarbeitung fehlgeschlagen für {filename}: {e}")
                processing_steps.append({
                    "step": "processing_error",
                    "detail": f"⚠️ Verarbeitung teilweise fehlgeschlagen"
                })

        return doc, processing_steps

    def _process_document_intelligent_with_status(self, session, doc: Document,
                                                   file_path: str, content_hash: str,
                                                   remote_path: str, filename: str) -> List[Dict]:
        """
        Führt intelligente Dokumentenverarbeitung mit Status-Updates durch.
        Verwendet Cache-Service für OCR-Ergebnisse.
        WICHTIG: Liest Datei von Disk statt aus Memory für bessere RAM-Nutzung!

        Args:
            file_path: Pfad zur gespeicherten Datei (lokal oder cloud://)
            content_hash: Bereits berechneter Hash für Cache-Lookup

        Returns:
            Liste von Status-Updates für Fortschrittsanzeige
        """
        import gc
        processing_steps = []
        ocr_text = ""

        # Cache Service für OCR-Ergebnisse
        try:
            from services.cache_service import get_cache_service
            cache = get_cache_service()
        except ImportError:
            cache = None

        # 1. OCR durchführen (mit Cache-Prüfung)
        processing_steps.append({
            "step": "ocr_starting",
            "detail": f"🔍 Starte Texterkennung (OCR)..."
        })

        # HEARTBEAT: OCR-Start in DB vermerken
        try:
            from services.cloud_sync_service import update_heartbeat
            update_heartbeat(
                self.user_id, getattr(self, '_current_connection_id', None),
                current_file=filename,
                current_step="ocr",
                step_detail=f"OCR startet für: {filename}"
            )
        except:
            pass  # Heartbeat ist optional

        # Prüfe Cache für OCR-Ergebnis
        cached_ocr = None
        if cache and content_hash:
            cached_ocr = cache.get_ocr_result(content_hash)
            if cached_ocr:
                processing_steps.append({
                    "step": "ocr_cached",
                    "detail": f"⚡ OCR aus Cache geladen"
                })
                ocr_text = cached_ocr
                doc.ocr_text = ocr_text
                doc.ocr_confidence = 0.95  # Hohe Konfidenz für Cache

        if not cached_ocr:
            try:
                from services.ocr import OCRService
                from PIL import Image
                import io
                ocr_service = OCRService()

                mime_type = doc.mime_type or self._get_mime_type(filename)

                # WICHTIG: Datei von Disk lesen statt aus Memory
                # Dies reduziert RAM-Verbrauch erheblich
                file_content = None
                try:
                    if file_path.startswith("cloud://"):
                        # Cloud-Datei herunterladen
                        from services.storage_service import get_storage_service
                        storage = get_storage_service()
                        success, file_content = storage.download_file(file_path)
                        if not success:
                            raise Exception(f"Cloud-Download fehlgeschlagen: {file_path}")
                    else:
                        # Lokale Datei lesen
                        with open(file_path, "rb") as f:
                            file_content = f.read()

                    if mime_type == "application/pdf":
                        processing_steps.append({
                            "step": "ocr_pdf",
                            "detail": f"📄 Verarbeite PDF mit OCR..."
                        })
                        # extract_text_from_pdf erwartet bytes und gibt List[Tuple[str, float]] zurück
                        ocr_results = ocr_service.extract_text_from_pdf(file_content)
                        if ocr_results:
                            # Texte aller Seiten zusammenfügen
                            ocr_text = "\n\n".join([text for text, conf in ocr_results if text])
                            avg_confidence = sum([conf for text, conf in ocr_results]) / len(ocr_results) if ocr_results else 0
                            doc.ocr_text = ocr_text
                            doc.ocr_confidence = avg_confidence
                        else:
                            ocr_text = ""
                            doc.ocr_confidence = 0

                        # Cache OCR-Ergebnis
                        if cache and content_hash and ocr_text:
                            cache.set_ocr_result(content_hash, ocr_text)

                        text_length = len(ocr_text)
                        processing_steps.append({
                            "step": "ocr_complete",
                            "detail": f"✅ OCR abgeschlossen: {text_length:,} Zeichen extrahiert"
                        })

                        # HEARTBEAT: PDF-OCR fertig
                        try:
                            update_heartbeat(
                                self.user_id, getattr(self, '_current_connection_id', None),
                                current_step="ocr_complete",
                                step_detail=f"PDF-OCR fertig: {text_length:,} Zeichen aus {filename}"
                            )
                        except:
                            pass

                    elif mime_type.startswith("image/"):
                        processing_steps.append({
                            "step": "ocr_image",
                            "detail": f"🖼️ Verarbeite Bild mit OCR..."
                        })
                        # Bild aus Bytes laden
                        image = Image.open(io.BytesIO(file_content))
                        ocr_text, confidence = ocr_service.extract_text_from_image(image)
                        doc.ocr_text = ocr_text
                        doc.ocr_confidence = confidence
                        # Bild explizit freigeben
                        del image
                        image = None

                        # Cache OCR-Ergebnis
                        if cache and content_hash and ocr_text:
                            cache.set_ocr_result(content_hash, ocr_text)

                        text_length = len(ocr_text)
                        processing_steps.append({
                            "step": "ocr_complete",
                            "detail": f"✅ OCR abgeschlossen: {text_length:,} Zeichen extrahiert"
                        })

                    else:
                        processing_steps.append({
                            "step": "ocr_skipped",
                            "detail": f"⏭️ OCR übersprungen (kein PDF/Bild)"
                        })

                finally:
                    # WICHTIG: File content sofort freigeben nach OCR!
                    if file_content is not None:
                        del file_content
                        file_content = None
                    gc.collect()

            except ImportError:
                logger.warning("OCR Service nicht verfügbar")
                processing_steps.append({
                    "step": "ocr_unavailable",
                    "detail": f"⚠️ OCR Service nicht verfügbar"
                })
            except Exception as e:
                logger.error(f"OCR fehlgeschlagen: {e}")
                processing_steps.append({
                    "step": "ocr_error",
                    "detail": f"⚠️ OCR Fehler: {str(e)[:50]}"
                })

        # 2. Intelligente Analyse mit Document Intelligence Service
        if ocr_text and len(ocr_text) > 50:
            processing_steps.append({
                "step": "analyzing",
                "detail": f"🧠 Analysiere Dokumentinhalt..."
            })

            try:
                from services.document_intelligence_service import DocumentIntelligenceService

                # AI Service laden falls verfügbar
                ai_service = None
                try:
                    from services.ai_service import AIService
                    ai_service = AIService()
                    processing_steps.append({
                        "step": "ai_loaded",
                        "detail": f"🤖 KI-Service geladen"
                    })
                except:
                    pass

                intel_service = DocumentIntelligenceService(
                    self.user_id, ai_service=ai_service
                )

                # Analysiere Dokument
                processing_steps.append({
                    "step": "extracting_metadata",
                    "detail": f"📋 Extrahiere Metadaten..."
                })

                metadata = intel_service.analyze_document(
                    ocr_text,
                    source_folder_path=remote_path,
                    filename=filename
                )

                # Status-Update für gefundene Metadaten
                found_items = []
                if metadata.sender:
                    found_items.append(f"Absender: {metadata.sender}")
                if metadata.document_date:
                    found_items.append(f"Datum: {metadata.document_date.strftime('%d.%m.%Y')}")
                if metadata.insurance_number:
                    found_items.append(f"Vers.-Nr: {metadata.insurance_number}")
                if metadata.document_type:
                    found_items.append(f"Typ: {metadata.document_type}")

                if found_items:
                    processing_steps.append({
                        "step": "metadata_found",
                        "detail": f"✅ Gefunden: {', '.join(found_items[:3])}"
                    })

                # Aktualisiere Dokument mit extrahierten Metadaten
                if metadata.sender:
                    doc.sender = metadata.sender

                if metadata.document_date:
                    doc.document_date = metadata.document_date

                if metadata.insurance_number:
                    doc.insurance_number = metadata.insurance_number

                if metadata.contract_number:
                    doc.contract_number = metadata.contract_number

                if metadata.customer_number:
                    doc.customer_number = metadata.customer_number

                if metadata.amount:
                    doc.invoice_amount = metadata.amount

                if metadata.document_type:
                    doc.category = metadata.document_type.capitalize()

                # 3. Erstelle Ordnerstruktur und verschiebe Dokument
                if metadata.suggested_folder_path:
                    processing_steps.append({
                        "step": "creating_folder",
                        "detail": f"📁 Erstelle Ordner: {metadata.suggested_folder_path}"
                    })

                    folder_id = intel_service.create_folder_structure(
                        metadata.suggested_folder_path
                    )
                    if folder_id:
                        doc.folder_id = folder_id
                        logger.info(f"Dokument {filename} in Ordner {metadata.suggested_folder_path} verschoben")
                        processing_steps.append({
                            "step": "folder_assigned",
                            "detail": f"✅ In Ordner eingeordnet"
                        })

                # 4. Generiere besseren Titel
                title_parts = []
                if metadata.document_date:
                    title_parts.append(metadata.document_date.strftime("%Y-%m-%d"))
                if metadata.sender:
                    title_parts.append(metadata.sender)
                if metadata.document_type:
                    type_names = {
                        "versicherung": "Versicherung",
                        "vertrag": "Vertrag",
                        "rechnung": "Rechnung",
                        "abonnement": "Abo"
                    }
                    title_parts.append(type_names.get(metadata.document_type, ""))
                if metadata.insurance_number:
                    title_parts.append(metadata.insurance_number)

                if title_parts:
                    doc.title = " - ".join([p for p in title_parts if p])
                    processing_steps.append({
                        "step": "title_generated",
                        "detail": f"📝 Titel: {doc.title[:40]}..."
                    })

                doc.status = DocumentStatus.COMPLETED

                processing_steps.append({
                    "step": "analysis_complete",
                    "detail": f"✅ Intelligente Analyse abgeschlossen"
                })

            except ImportError:
                logger.warning("Document Intelligence Service nicht verfügbar")
                processing_steps.append({
                    "step": "intel_unavailable",
                    "detail": f"⚠️ Dokumenten-Intelligenz nicht verfügbar"
                })
            except Exception as e:
                logger.error(f"Dokumenten-Intelligenz fehlgeschlagen: {e}")
                processing_steps.append({
                    "step": "intel_error",
                    "detail": f"⚠️ Analysefehler: {str(e)[:40]}"
                })
        else:
            processing_steps.append({
                "step": "analysis_skipped",
                "detail": f"⏭️ Analyse übersprungen (zu wenig Text)"
            })

        return processing_steps

    def _get_mime_type(self, filename: str) -> str:
        """Ermittelt MIME-Type aus Dateinamen"""
        ext = Path(filename).suffix.lower()
        mime_types = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain",
            ".csv": "text/csv"
        }
        return mime_types.get(ext, "application/octet-stream")

    def _write_sync_log(self, connection_id: int, result: Dict):
        """Schreibt Sync-Ergebnis in Log-Datei"""
        log_file = self.log_file_path / f"sync_{connection_id}_{datetime.now().strftime('%Y%m%d')}.log"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "connection_id": connection_id,
            "user_id": self.user_id,
            "files_found": result.get("files_total", 0),
            "files_synced": result.get("files_synced", 0),
            "files_skipped": result.get("files_skipped", 0),
            "files_error": result.get("files_error", 0),
            "synced_files": result.get("synced_files", []),
            "errors": result.get("errors", [])
        }

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # ==================== SYNC-LOGS ====================

    def get_sync_logs(self, connection_id: int = None,
                      limit: int = 100) -> List[CloudSyncLogWrapper]:
        """Holt Sync-Logs"""
        with get_db() as session:
            query = session.query(CloudSyncLog).filter(
                CloudSyncLog.user_id == self.user_id
            )

            if connection_id:
                query = query.filter(CloudSyncLog.connection_id == connection_id)

            logs = query.order_by(CloudSyncLog.synced_at.desc()).limit(limit).all()
            return [CloudSyncLogWrapper(log) for log in logs]

    def get_sync_statistics(self, connection_id: int = None) -> Dict:
        """Holt Statistiken zur Synchronisation"""
        with get_db() as session:
            query = session.query(CloudSyncLog).filter(
                CloudSyncLog.user_id == self.user_id
            )

            if connection_id:
                query = query.filter(CloudSyncLog.connection_id == connection_id)

            logs = query.all()

            total_synced = len([l for l in logs if l.sync_status == "synced"])
            total_skipped = len([l for l in logs if l.sync_status == "skipped"])
            total_errors = len([l for l in logs if l.sync_status == "error"])
            total_bytes = sum(l.file_size or 0 for l in logs if l.sync_status == "synced")

            return {
                "total_synced": total_synced,
                "total_skipped": total_skipped,
                "total_errors": total_errors,
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / (1024 * 1024), 2)
            }

    def get_log_file_content(self, connection_id: int, date: str = None) -> str:
        """Liest Inhalt einer Log-Datei"""
        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        log_file = self.log_file_path / f"sync_{connection_id}_{date}.log"

        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                return f.read()

        return ""

    # ==================== AUTOMATISCHE SYNCHRONISATION ====================

    def get_connections_due_for_sync(self) -> List[CloudSyncConnection]:
        """Holt Verbindungen die synchronisiert werden müssen"""
        with get_db() as session:
            connections = session.query(CloudSyncConnection).filter(
                CloudSyncConnection.user_id == self.user_id,
                CloudSyncConnection.is_active == True,
                CloudSyncConnection.auto_sync_enabled == True
            ).all()

            due_connections = []
            now = datetime.now()

            for conn in connections:
                if conn.last_sync_at is None:
                    due_connections.append(conn)
                else:
                    next_sync = conn.last_sync_at + timedelta(
                        minutes=conn.sync_interval_minutes or 15
                    )
                    if now >= next_sync:
                        due_connections.append(conn)

            return due_connections

    def sync_all_due(self, process_documents: bool = True) -> Dict[str, Any]:
        """Synchronisiert alle fälligen Verbindungen"""
        results = {
            "connections_synced": 0,
            "total_files_synced": 0,
            "total_files_error": 0,
            "connection_results": []
        }

        due_connections = self.get_connections_due_for_sync()

        for conn in due_connections:
            result = self.sync_connection(conn.id, process_documents)
            results["connections_synced"] += 1
            results["total_files_synced"] += result["files_synced"]
            results["total_files_error"] += result["files_error"]
            results["connection_results"].append({
                "connection_id": conn.id,
                "provider": conn.provider.value,
                "result": result
            })

        return results


# ==================== HELPER FUNKTIONEN ====================

def parse_cloud_link(link: str) -> Tuple[Optional[CloudProvider], Optional[str]]:
    """
    Parsed einen Cloud-Link und gibt Provider und Ordner-ID zurück

    Unterstützte Formate:
    - Dropbox: https://www.dropbox.com/sh/xxx oder https://www.dropbox.com/scl/fo/xxx
    - Google Drive: https://drive.google.com/drive/folders/xxx
    """
    parsed = urlparse(link)

    if "dropbox.com" in parsed.netloc:
        # Dropbox-Link
        path = parsed.path
        return CloudProvider.DROPBOX, path

    elif "drive.google.com" in parsed.netloc:
        # Google Drive-Link
        path_parts = parsed.path.split("/")
        if "folders" in path_parts:
            idx = path_parts.index("folders")
            if idx + 1 < len(path_parts):
                folder_id = path_parts[idx + 1].split("?")[0]
                return CloudProvider.GOOGLE_DRIVE, folder_id

    return None, None
