"""
Diagnose-Seite für Cloud-Services
Zeigt detaillierte Verbindungsinformationen und Fehler
"""
import streamlit as st
import traceback

st.set_page_config(page_title="Diagnose", page_icon="🔧", layout="wide")
st.title("🔧 Cloud-Services Diagnose")

st.markdown("Diese Seite hilft bei der Fehlersuche für Datenbankverbindungen.")

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
    else:
        secrets_status["DATABASE_URL"] = "❌ Nicht konfiguriert"
except FileNotFoundError:
    secrets_status["DATABASE_URL"] = "⚠️ secrets.toml nicht gefunden (normal bei lokalem Start)"
except Exception as e:
    secrets_status["DATABASE_URL"] = f"❌ Fehler beim Lesen: {type(e).__name__}: {e}"

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
        # pgbouncer Parameter entfernen
        clean_url = db_url
        if '?pgbouncer=true' in clean_url:
            clean_url = clean_url.replace('?pgbouncer=true', '')
        elif '&pgbouncer=true' in clean_url:
            clean_url = clean_url.replace('&pgbouncer=true', '')

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

        # Hilfreiche Tipps basierend auf Fehler
        error_str = str(e).lower()
        if "password" in error_str or "authentication" in error_str:
            st.warning("💡 **Tipp:** Passwort überprüfen! Stelle sicher, dass `[YOUR-PASSWORD]` durch das echte Passwort ersetzt wurde.")
        elif "timeout" in error_str or "timed out" in error_str:
            st.warning("💡 **Tipp:** Verbindungs-Timeout. Prüfe ob die IP von Streamlit Cloud erlaubt ist (Supabase: Database → Settings → Allowed IP addresses).")
        elif "could not connect" in error_str or "connection refused" in error_str:
            st.warning("💡 **Tipp:** Server nicht erreichbar. Prüfe die URL und den Port (6543 für Pooler, 5432 für Direct).")
        elif "ssl" in error_str:
            st.warning("💡 **Tipp:** SSL-Fehler. Versuche `?sslmode=require` am Ende der URL hinzuzufügen.")

        with st.expander("🔍 Vollständiger Traceback"):
            st.code(traceback.format_exc())

except Exception as e:
    st.error(f"❌ Allgemeiner Fehler: {e}")
    st.code(traceback.format_exc())

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
