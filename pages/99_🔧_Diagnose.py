"""
Diagnose-Seite für Cloud-Services
Zeigt detaillierte Verbindungsinformationen und Fehler
"""
import streamlit as st

st.set_page_config(page_title="Diagnose", page_icon="🔧", layout="wide")
st.title("🔧 Cloud-Services Diagnose")

st.markdown("Diese Seite hilft bei der Fehlersuche für Datenbankverbindungen.")

# ==========================================
# 1. SECRETS PRÜFEN
# ==========================================
st.header("1️⃣ Secrets-Konfiguration")

secrets_status = {}

# DATABASE_URL
try:
    db_url = st.secrets.get("DATABASE_URL", None)
    if db_url:
        # Passwort maskieren
        import re
        masked = re.sub(r':([^:@]+)@', ':****@', db_url)
        secrets_status["DATABASE_URL"] = f"✅ Vorhanden: `{masked}`"
    else:
        secrets_status["DATABASE_URL"] = "❌ Nicht konfiguriert"
except Exception as e:
    secrets_status["DATABASE_URL"] = f"❌ Fehler: {e}"

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
    from database.db import get_database_url, create_db_engine, get_database_status

    db_url = get_database_url()
    st.markdown(f"**Verwendete URL:** `{db_url[:50]}...`" if len(db_url) > 50 else f"**Verwendete URL:** `{db_url}`")

    status = get_database_status()
    st.json(status)

    if status.get('connected'):
        st.success("✅ Datenbank ist verbunden!")

        # Tabellen prüfen
        st.subheader("Tabellen in der Datenbank:")
        try:
            from sqlalchemy import inspect
            engine = create_db_engine()
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            if tables:
                for table in tables:
                    st.markdown(f"- `{table}`")
            else:
                st.warning("⚠️ Keine Tabellen gefunden!")

                if st.button("🔨 Tabellen jetzt erstellen"):
                    from database.models import Base
                    from database.extended_models import ExtendedBase
                    Base.metadata.create_all(engine)
                    ExtendedBase.metadata.create_all(engine)
                    st.success("✅ Tabellen wurden erstellt!")
                    st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Prüfen der Tabellen: {e}")
    else:
        st.error("❌ Datenbank nicht verbunden!")
        st.markdown(f"**Fehler:** {status.get('error', 'Unbekannt')}")

except Exception as e:
    st.error(f"❌ Datenbank-Fehler: {e}")
    import traceback
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
