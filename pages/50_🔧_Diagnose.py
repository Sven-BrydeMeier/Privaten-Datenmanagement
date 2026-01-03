"""
Diagnose-Seite für Cloud-Services
Zeigt detaillierte Verbindungsinformationen und Fehler
"""
import streamlit as st
import traceback
import sys

st.set_page_config(page_title="Diagnose", page_icon="🔧", layout="wide")
st.title("🔧 Cloud-Services Diagnose")

st.markdown("Diese Seite hilft bei der Fehlersuche für Datenbankverbindungen.")

# Fehlerlog sammeln
error_log = []

def log_error(component: str, error: str, details: str = ""):
    """Fügt Fehler zum Log hinzu"""
    error_log.append(f"[{component}] {error}")
    if details:
        error_log.append(f"  Details: {details}")

def log_success(component: str, message: str):
    """Fügt Erfolg zum Log hinzu"""
    error_log.append(f"[{component}] ✓ {message}")

# Refresh Button
if st.button("🔄 Neu laden"):
    st.rerun()

# ==========================================
# 1. SECRETS PRÜFEN
# ==========================================
st.header("1️⃣ Secrets-Konfiguration")

st.info("**Hinweis:** Secrets müssen in Streamlit Cloud unter 'Settings → Secrets' konfiguriert werden.")

secrets_status = {}
secrets_found = {}

# DATABASE_URL
try:
    db_url = st.secrets.get("DATABASE_URL", None)
    if db_url:
        # Passwort maskieren
        import re
        masked = re.sub(r':([^:@]+)@', ':****@', str(db_url))
        secrets_status["DATABASE_URL"] = f"✅ Vorhanden: `{masked}`"
        secrets_found["DATABASE_URL"] = db_url
        log_success("SECRETS", f"DATABASE_URL gefunden: {masked[:50]}...")
    else:
        secrets_status["DATABASE_URL"] = "❌ Nicht konfiguriert"
        log_error("SECRETS", "DATABASE_URL nicht gefunden!", "Variable existiert nicht in st.secrets")
except FileNotFoundError:
    secrets_status["DATABASE_URL"] = "⚠️ secrets.toml nicht gefunden (normal bei lokalem Start)"
    log_error("SECRETS", "secrets.toml nicht gefunden", "Lokal ist das normal")
except Exception as e:
    secrets_status["DATABASE_URL"] = f"❌ Fehler beim Lesen: {type(e).__name__}: {e}"
    log_error("SECRETS", f"Fehler: {type(e).__name__}", str(e))

# UPSTASH_REDIS_URL
try:
    redis_url = st.secrets.get("UPSTASH_REDIS_URL", None)
    if redis_url:
        import re
        masked = re.sub(r':([^:@]+)@', ':****@', redis_url)
        secrets_status["UPSTASH_REDIS_URL"] = f"✅ Vorhanden: `{masked}`"
    else:
        secrets_status["UPSTASH_REDIS_URL"] = "❌ Nicht konfiguriert"
except Exception as e:
    secrets_status["UPSTASH_REDIS_URL"] = f"❌ Fehler: {e}"

# SUPABASE
try:
    supa_url = st.secrets.get("SUPABASE_URL", None)
    supa_key = st.secrets.get("SUPABASE_KEY", None)
    if supa_url and supa_key:
        secrets_status["SUPABASE_URL"] = f"✅ Vorhanden: `{supa_url}`"
        secrets_status["SUPABASE_KEY"] = f"✅ Vorhanden: `{supa_key[:20]}...`"
    else:
        if not supa_url:
            secrets_status["SUPABASE_URL"] = "❌ Nicht konfiguriert"
        if not supa_key:
            secrets_status["SUPABASE_KEY"] = "❌ Nicht konfiguriert"
except Exception as e:
    secrets_status["SUPABASE"] = f"❌ Fehler: {e}"

for key, status in secrets_status.items():
    st.markdown(f"**{key}:** {status}")

st.divider()

# ==========================================
# 2. DATENBANK-VERBINDUNG
# ==========================================
st.header("2️⃣ Datenbank-Verbindung")

try:
    from database.db import get_database_url, get_database_status
    from sqlalchemy import create_engine, text, inspect
    import re

    # URL aus Secrets direkt lesen
    raw_db_url = secrets_found.get("DATABASE_URL", None)

    if raw_db_url:
        st.markdown("**Aus Secrets gelesene URL:**")
        masked = re.sub(r':([^:@]+)@', ':****@', str(raw_db_url))
        st.code(masked)

        # Prüfe URL-Format
        if ':6543/' in raw_db_url:
            st.success("✅ Port 6543 (Supabase Pooler) erkannt")
        elif ':5432/' in raw_db_url:
            st.warning("⚠️ Port 5432 (Direct Connection) - Kann bei Streamlit Cloud blockiert sein!")

        if 'pgbouncer=true' in raw_db_url:
            st.info("ℹ️ pgbouncer=true Parameter erkannt - wird automatisch verarbeitet")

    # Funktion get_database_url verwenden
    db_url = get_database_url()
    st.markdown("**Von get_database_url() zurückgegeben:**")
    masked_used = re.sub(r':([^:@]+)@', ':****@', str(db_url))
    st.code(masked_used[:100] + "..." if len(masked_used) > 100 else masked_used)

    # WARNUNG wenn SQLite verwendet wird
    if db_url.startswith('sqlite'):
        st.error("""
        🚨 **PROBLEM: SQLite wird verwendet statt PostgreSQL!**

        Das bedeutet: Die `DATABASE_URL` aus den Secrets wird NICHT gelesen.

        **Mögliche Ursachen:**
        1. Secrets sind nicht in Streamlit Cloud konfiguriert
        2. Der Key heißt nicht exakt `DATABASE_URL`
        3. Es gibt Syntaxfehler in der secrets.toml

        **Prüfe in Streamlit Cloud:**
        - Settings → Secrets
        - Stelle sicher dass `DATABASE_URL = "postgresql://..."` korrekt ist
        """)

    # Direkte Verbindung testen
    st.subheader("Verbindungstest:")

    try:
        # URL-Parameter sauber verarbeiten
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        clean_url = db_url

        # Parse URL um Query-Parameter korrekt zu behandeln
        if '?' in clean_url:
            parsed = urlparse(clean_url)
            query_params = parse_qs(parsed.query)

            # Entferne pgbouncer Parameter
            query_params.pop('pgbouncer', None)

            # Baue URL neu zusammen
            new_query = urlencode(query_params, doseq=True) if query_params else ''
            clean_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment
            ))

        log_success("DATABASE", f"Bereinigte URL: {clean_url[:50]}...")

        test_engine = create_engine(
            clean_url,
            pool_pre_ping=True,
            pool_size=1
        )

        with test_engine.connect() as conn:
            # Query die für SQLite und PostgreSQL funktioniert
            if db_url.startswith('sqlite'):
                result = conn.execute(text("SELECT sqlite_version()"))
                version = f"SQLite {result.scalar()}"
                st.warning(f"⚠️ **Verbunden mit lokaler SQLite-Datenbank**")
                st.markdown(f"**Version:** `{version}`")
                st.info("💡 Daten gehen bei App-Neustart verloren! Konfiguriere DATABASE_URL für persistente Daten.")
            else:
                result = conn.execute(text("SELECT version()"))
                version = result.scalar()
                st.success(f"✅ **PostgreSQL verbunden!**")
                st.markdown(f"**Version:** `{version}`")

            # Tabellen auflisten
            inspector = inspect(test_engine)
            tables = inspector.get_table_names()

            if tables:
                st.markdown(f"**{len(tables)} Tabellen gefunden:**")
                cols = st.columns(4)
                for i, table in enumerate(sorted(tables)):
                    cols[i % 4].markdown(f"- `{table}`")
            else:
                st.warning("⚠️ **Keine Tabellen gefunden!**")
                st.markdown("Die Datenbank ist leer. Tabellen werden beim ersten App-Start erstellt.")

                if st.button("🔨 Tabellen jetzt erstellen"):
                    from database.models import Base
                    try:
                        from database.extended_models import ExtendedBase
                        has_extended = True
                    except:
                        has_extended = False

                    Base.metadata.create_all(test_engine)
                    if has_extended:
                        ExtendedBase.metadata.create_all(test_engine)
                    st.success("✅ Tabellen wurden erstellt!")
                    st.rerun()

    except Exception as e:
        st.error(f"❌ **Verbindung fehlgeschlagen!**")
        st.markdown(f"**Fehlertyp:** `{type(e).__name__}`")
        st.markdown(f"**Fehlermeldung:** `{str(e)}`")

        # Fehler loggen
        log_error("DATABASE", f"Verbindung fehlgeschlagen: {type(e).__name__}", str(e))
        log_error("DATABASE", "Traceback", traceback.format_exc())

        # Hilfreiche Tipps basierend auf Fehler
        error_str = str(e).lower()
        if "password" in error_str or "authentication" in error_str:
            st.warning("💡 **Tipp:** Passwort überprüfen! Stelle sicher, dass `[YOUR-PASSWORD]` durch das echte Passwort ersetzt wurde.")
            log_error("DATABASE", "Vermutlich falsches Passwort")
        elif "timeout" in error_str or "timed out" in error_str:
            st.warning("💡 **Tipp:** Verbindungs-Timeout. Prüfe ob die IP von Streamlit Cloud erlaubt ist (Supabase: Database → Settings → Allowed IP addresses).")
            log_error("DATABASE", "Timeout - IP-Freigabe prüfen")
        elif "could not connect" in error_str or "connection refused" in error_str:
            st.warning("💡 **Tipp:** Server nicht erreichbar. Prüfe die URL und den Port (6543 für Pooler, 5432 für Direct).")
            log_error("DATABASE", "Server nicht erreichbar")
        elif "ssl" in error_str:
            st.warning("💡 **Tipp:** SSL-Fehler. Versuche `?sslmode=require` am Ende der URL hinzuzufügen.")
            log_error("DATABASE", "SSL-Fehler")

        with st.expander("🔍 Vollständiger Traceback"):
            st.code(traceback.format_exc())

except Exception as e:
    st.error(f"❌ Allgemeiner Fehler: {e}")
    st.code(traceback.format_exc())

# Speichernutzung anzeigen (PostgreSQL)
st.subheader("📊 Speichernutzung")

try:
    from database.db import get_database_url
    from sqlalchemy import create_engine, text
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    db_url = get_database_url()

    if not db_url.startswith('sqlite'):
        # URL bereinigen
        clean_url = db_url
        if '?' in clean_url:
            parsed = urlparse(clean_url)
            query_params = parse_qs(parsed.query)
            query_params.pop('pgbouncer', None)
            new_query = urlencode(query_params, doseq=True) if query_params else ''
            clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

        test_engine = create_engine(clean_url, pool_pre_ping=True, pool_size=1)

        with test_engine.connect() as conn:
            # Datenbankgröße abfragen
            size_result = conn.execute(text("""
                SELECT pg_size_pretty(pg_database_size(current_database())) as db_size,
                       pg_database_size(current_database()) as db_size_bytes
            """))
            row = size_result.fetchone()
            db_size = row[0] if row else "Unbekannt"
            db_size_bytes = row[1] if row else 0

            # Tabellen-Größen
            tables_result = conn.execute(text("""
                SELECT relname as table_name,
                       pg_size_pretty(pg_total_relation_size(relid)) as size,
                       pg_total_relation_size(relid) as size_bytes
                FROM pg_catalog.pg_statio_user_tables
                ORDER BY pg_total_relation_size(relid) DESC
                LIMIT 10
            """))
            tables = tables_result.fetchall()

            # Dokumenten-Statistik
            doc_result = conn.execute(text("""
                SELECT COUNT(*) as count,
                       COALESCE(SUM(file_size), 0) as total_size
                FROM documents
            """))
            doc_row = doc_result.fetchone()
            doc_count = doc_row[0] if doc_row else 0
            doc_total_size = doc_row[1] if doc_row else 0

            # Anzeige
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("🗄️ Datenbank-Größe", db_size)
            with col2:
                st.metric("📄 Dokumente", f"{doc_count}")
            with col3:
                size_mb = doc_total_size / (1024 * 1024) if doc_total_size else 0
                st.metric("📦 Dateien-Größe", f"{size_mb:.1f} MB")

            # Supabase Free Tier Info
            st.info("ℹ️ **Supabase Free Tier:** 500 MB Datenbank, 1 GB Storage")

            # Fortschrittsbalken für DB-Nutzung (500 MB Limit)
            db_limit_bytes = 500 * 1024 * 1024  # 500 MB
            usage_percent = min((db_size_bytes / db_limit_bytes) * 100, 100)
            st.progress(usage_percent / 100, text=f"Datenbank: {db_size} von 500 MB ({usage_percent:.1f}%)")

            if tables:
                with st.expander("📊 Top 10 Tabellen nach Größe"):
                    for table in tables:
                        st.text(f"• {table[0]}: {table[1]}")
    else:
        st.warning("SQLite - Lokale Datenbank ohne Cloud-Limits")

except Exception as e:
    st.warning(f"Speichernutzung konnte nicht abgefragt werden: {e}")

st.divider()

# ==========================================
# 3. REDIS CACHE
# ==========================================
st.header("3️⃣ Redis Cache (Upstash)")

try:
    from services.cache_service import get_cache_service

    cache = get_cache_service()
    status = cache.get_status()
    st.json(status)

    if status.get('type') == 'redis':
        st.success("✅ Redis ist verbunden!")

        # Test schreiben/lesen
        if st.button("🧪 Cache testen"):
            test_key = "diagnose_test"
            test_value = {"test": "erfolreich", "timestamp": str(st.session_state.get('_test_ts', 'now'))}

            cache.set("diagnose", test_key, test_value, ttl_seconds=60)
            result = cache.get("diagnose", test_key)

            if result == test_value:
                st.success(f"✅ Cache funktioniert! Wert: {result}")
            else:
                st.error(f"❌ Cache-Test fehlgeschlagen. Erwartet: {test_value}, Erhalten: {result}")
    else:
        st.warning("⚠️ Redis nicht verbunden - Memory-Fallback aktiv")
        st.markdown("**Hinweis:** Memory-Cache funktioniert, aber Daten gehen bei Neustart verloren.")

except Exception as e:
    st.error(f"❌ Cache-Fehler: {e}")
    import traceback
    st.code(traceback.format_exc())

st.divider()

# ==========================================
# 4. SUPABASE STORAGE
# ==========================================
st.header("4️⃣ Supabase Storage")

try:
    from services.storage_service import get_storage_service

    storage = get_storage_service()
    status = storage.get_status()
    st.json(status)

    if status.get('type') == 'supabase':
        st.success("✅ Supabase Storage ist verbunden!")

        # Storage-Statistiken
        try:
            bucket_name = status.get('bucket', 'documents')
            from supabase import create_client
            supa_url = st.secrets.get("SUPABASE_URL")
            supa_key = st.secrets.get("SUPABASE_KEY")

            if supa_url and supa_key:
                client = create_client(supa_url, supa_key)
                # Bucket-Dateien auflisten
                stats = {'files': 0, 'size': 0}

                def count_files(prefix=""):
                    try:
                        items = client.storage.from_(bucket_name).list(prefix)
                        for item in items:
                            if item.get('id') is None:  # Ordner
                                count_files(f"{prefix}{item['name']}/")
                            else:  # Datei
                                stats['files'] += 1
                                stats['size'] += item.get('metadata', {}).get('size', 0)
                    except:
                        pass

                count_files()
                total_files = stats['files']
                total_size = stats['size']

                col1, col2 = st.columns(2)
                with col1:
                    st.metric("📁 Dateien im Storage", total_files)
                with col2:
                    size_mb = total_size / (1024 * 1024)
                    st.metric("💾 Storage-Größe", f"{size_mb:.1f} MB")

                # Fortschrittsbalken (1 GB Limit)
                storage_limit = 1024 * 1024 * 1024  # 1 GB
                storage_percent = min((total_size / storage_limit) * 100, 100)
                st.progress(storage_percent / 100, text=f"Storage: {size_mb:.1f} MB von 1 GB ({storage_percent:.1f}%)")

        except Exception as e:
            st.warning(f"Storage-Statistiken nicht verfügbar: {e}")

        # Bucket prüfen
        if st.button("🧪 Storage testen"):
            try:
                test_content = b"Diagnose-Test"
                success, result = storage.upload_file(
                    file_data=test_content,
                    filename="diagnose_test.txt",
                    user_id=0,
                    subfolder="diagnose"
                )

                if success:
                    st.success(f"✅ Upload erfolgreich: {result}")

                    # Wieder löschen
                    storage.delete_file(result)
                    st.info("Test-Datei wurde wieder gelöscht.")
                else:
                    st.error(f"❌ Upload fehlgeschlagen: {result}")
            except Exception as e:
                st.error(f"❌ Storage-Test Fehler: {e}")
    else:
        st.warning("⚠️ Supabase Storage nicht verbunden - Lokaler Fallback aktiv")

except Exception as e:
    st.error(f"❌ Storage-Fehler: {e}")
    import traceback
    st.code(traceback.format_exc())

st.divider()

# ==========================================
# 4.5 DOKUMENTEN-DIAGNOSE
# ==========================================
st.header("📄 Dokumenten-Diagnose")

try:
    from database.db import get_db
    from database.models import Document
    import os

    with get_db() as session:
        docs = session.query(Document).order_by(Document.created_at.desc()).limit(50).all()

        if docs:
            st.markdown(f"**Letzte {len(docs)} Dokumente:**")

            # Statistik
            cloud_docs = 0
            local_docs = 0
            missing_docs = 0
            accessible_docs = 0

            doc_issues = []

            for doc in docs:
                file_path = doc.file_path or ""

                if file_path.startswith("cloud://"):
                    cloud_docs += 1
                    # Cloud-Dokument - prüfen ob abrufbar
                    try:
                        storage = get_storage_service()
                        success, _ = storage.download_file(file_path)
                        if success:
                            accessible_docs += 1
                        else:
                            missing_docs += 1
                            doc_issues.append((doc.id, doc.filename, file_path, "Cloud-Datei nicht gefunden"))
                    except Exception as e:
                        missing_docs += 1
                        doc_issues.append((doc.id, doc.filename, file_path, str(e)))
                else:
                    local_docs += 1
                    # Lokales Dokument - prüfen ob Datei existiert
                    if file_path and os.path.exists(file_path):
                        accessible_docs += 1
                    else:
                        missing_docs += 1
                        doc_issues.append((doc.id, doc.filename, file_path, "Lokale Datei nicht gefunden"))

            # Statistik anzeigen
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("☁️ Cloud", cloud_docs)
            with col2:
                st.metric("💾 Lokal", local_docs)
            with col3:
                st.metric("✅ Verfügbar", accessible_docs)
            with col4:
                st.metric("❌ Fehlen", missing_docs, delta=f"-{missing_docs}" if missing_docs > 0 else None, delta_color="inverse")

            if local_docs > 0 and missing_docs > 0:
                st.warning(f"""
                ⚠️ **{local_docs} Dokumente wurden lokal gespeichert!**

                Diese Dateien sind nicht in Supabase Storage und gehen bei App-Neustart verloren.

                **Ursache:** Die Dokumente wurden importiert, bevor der Storage-Bucket korrekt konfiguriert war.

                **Lösung:** Dokumente erneut importieren (nach Bucket-Konfiguration).
                """)

            if doc_issues:
                with st.expander(f"❌ {len(doc_issues)} Dokumente mit Problemen", expanded=True):
                    for doc_id, filename, path, issue in doc_issues[:10]:
                        st.markdown(f"**ID {doc_id}:** `{filename}`")
                        st.caption(f"Pfad: `{path[:80]}...`" if len(path) > 80 else f"Pfad: `{path}`")
                        st.caption(f"Problem: {issue}")
                        st.divider()

                    if len(doc_issues) > 10:
                        st.caption(f"... und {len(doc_issues) - 10} weitere")

                # Bereinigung anbieten
                if st.button("🗑️ Fehlende Dokumente aus Datenbank entfernen"):
                    removed = 0
                    for doc_id, _, _, _ in doc_issues:
                        doc_to_delete = session.query(Document).filter(Document.id == doc_id).first()
                        if doc_to_delete:
                            session.delete(doc_to_delete)
                            removed += 1
                    session.commit()
                    st.success(f"✅ {removed} Dokument-Einträge entfernt. Bitte erneut importieren!")
                    st.rerun()
        else:
            st.info("Keine Dokumente in der Datenbank")

except Exception as e:
    st.error(f"❌ Dokumenten-Diagnose Fehler: {e}")
    st.code(traceback.format_exc())

st.divider()

# ==========================================
# 5. ZUSAMMENFASSUNG
# ==========================================
st.header("5️⃣ Zusammenfassung & Empfehlungen")

issues = []

try:
    db_status = get_database_status()
    if not db_status.get('persistent'):
        issues.append("**Datenbank:** Verwende `DATABASE_URL` mit PostgreSQL für persistente Daten")
except:
    issues.append("**Datenbank:** Konnte Status nicht prüfen")

try:
    cache_status = get_cache_service().get_status()
    if cache_status.get('type') != 'redis':
        issues.append("**Cache:** Verwende `UPSTASH_REDIS_URL` für persistenten Cache")
except:
    issues.append("**Cache:** Konnte Status nicht prüfen")

try:
    storage_status = get_storage_service().get_status()
    if storage_status.get('type') != 'supabase':
        issues.append("**Storage:** Verwende `SUPABASE_URL` und `SUPABASE_KEY` für Cloud-Speicher")
except:
    issues.append("**Storage:** Konnte Status nicht prüfen")

if issues:
    st.warning("⚠️ Folgende Punkte sollten konfiguriert werden:")
    for issue in issues:
        st.markdown(f"- {issue}")
else:
    st.success("✅ Alle Cloud-Services sind korrekt konfiguriert!")

# Beispiel-Konfiguration
with st.expander("📋 Beispiel secrets.toml"):
    st.code("""
# Supabase PostgreSQL
DATABASE_URL = "postgresql://postgres.xxxxx:PASSWORT@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

# Upstash Redis
UPSTASH_REDIS_URL = "rediss://default:xxxxx@eu1-xxxxx.upstash.io:6379"

# Supabase Storage
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxxxx"
SUPABASE_STORAGE_BUCKET = "documents"
    """, language="toml")

st.divider()

# ==========================================
# 6. FEHLERLOG ZUM KOPIEREN
# ==========================================
st.header("6️⃣ Fehlerlog (zum Kopieren)")

st.markdown("**Kopiere diesen Text und teile ihn zur Fehleranalyse:**")

# Systeminformationen hinzufügen
error_log.insert(0, "=" * 50)
error_log.insert(1, "DIAGNOSE-LOG")
error_log.insert(2, "=" * 50)
error_log.insert(3, f"Python: {sys.version}")
error_log.insert(4, f"Streamlit Secrets verfügbar: {hasattr(st, 'secrets')}")
try:
    error_log.insert(5, f"Anzahl Secrets: {len(st.secrets) if hasattr(st, 'secrets') else 0}")
    error_log.insert(6, f"Secret Keys: {list(st.secrets.keys()) if hasattr(st, 'secrets') else []}")
except:
    error_log.insert(5, "Secrets konnten nicht gelesen werden")
error_log.insert(7, "=" * 50)

# Log anzeigen
log_text = "\n".join(error_log)
st.code(log_text, language="text")

# Kopier-Button
st.download_button(
    label="📋 Log als Datei herunterladen",
    data=log_text,
    file_name="diagnose_log.txt",
    mime="text/plain"
)
