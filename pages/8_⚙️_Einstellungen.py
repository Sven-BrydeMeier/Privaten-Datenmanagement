"""
Einstellungen - API-Keys, E-Mail-Konfiguration, Sicherheit
"""
import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import User
from config.settings import get_settings, save_settings, Settings
from services.ai_service import get_ai_service
from services.encryption import EncryptionService
from utils.components import render_sidebar_cart, APP_VERSION, APP_NAME, get_version_string

st.set_page_config(page_title="Einstellungen", page_icon="⚙️", layout="wide")
init_db()

# Sidebar mit Aktentasche
render_sidebar_cart()

user_id = get_current_user_id()
settings = get_settings()

st.title("⚙️ Einstellungen")

# Tabs
tab_api, tab_email, tab_security, tab_calendar, tab_ui = st.tabs([
    "🔑 API-Keys",
    "📧 E-Mail",
    "🔒 Sicherheit",
    "📅 Kalender-Sync",
    "🎨 Oberfläche"
])


with tab_api:
    st.subheader("🔑 API-Schlüssel")
    st.markdown("Konfigurieren Sie hier Ihre API-Schlüssel für KI-Dienste und OCR.")

    st.markdown("---")

    # OpenAI
    st.markdown("### OpenAI (ChatGPT)")
    openai_key = st.text_input(
        "OpenAI API-Key",
        value=settings.openai_api_key,
        type="password",
        help="Für Dokumentenanalyse und Antwortvorschläge"
    )

    # Anthropic
    st.markdown("### Anthropic (Claude)")
    anthropic_key = st.text_input(
        "Anthropic API-Key",
        value=settings.anthropic_api_key,
        type="password",
        help="Alternative KI für Dokumentenanalyse"
    )

    # OCR
    st.markdown("### OCR-Service (optional)")
    ocr_key = st.text_input(
        "OCR API-Key",
        value=settings.ocr_api_key,
        type="password",
        help="Falls Sie einen externen OCR-Dienst nutzen möchten"
    )

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("💾 Speichern", type="primary"):
            settings.openai_api_key = openai_key
            settings.anthropic_api_key = anthropic_key
            settings.ocr_api_key = ocr_key
            save_settings(settings)

            # API-Status Cache löschen
            if 'api_status' in st.session_state:
                del st.session_state.api_status

            st.success("Einstellungen gespeichert!")

    with col2:
        if st.button("🔍 Verbindung testen"):
            ai = get_ai_service()
            status = ai.test_connection()

            if status.get('openai'):
                st.success("✓ OpenAI verbunden")
            elif openai_key:
                st.error(f"✗ OpenAI: {status.get('openai_error', 'Fehler')}")

            if status.get('anthropic'):
                st.success("✓ Anthropic verbunden")
            elif anthropic_key:
                st.error(f"✗ Anthropic: {status.get('anthropic_error', 'Fehler')}")


with tab_email:
    st.subheader("📧 E-Mail-Konfiguration")

    col_smtp, col_imap = st.columns(2)

    with col_smtp:
        st.markdown("### SMTP (Senden)")

        smtp_server = st.text_input("SMTP-Server", value=settings.smtp_server, placeholder="smtp.gmail.com")
        smtp_port = st.number_input("SMTP-Port", value=settings.smtp_port, min_value=1, max_value=65535)
        smtp_username = st.text_input("Benutzername/E-Mail", value=settings.smtp_username)
        smtp_password = st.text_input("Passwort", value=settings.smtp_password, type="password")

    with col_imap:
        st.markdown("### IMAP (Empfangen)")

        imap_server = st.text_input("IMAP-Server", value=settings.imap_server, placeholder="imap.gmail.com")
        imap_port = st.number_input("IMAP-Port", value=settings.imap_port, min_value=1, max_value=65535)
        imap_username = st.text_input("Benutzername/E-Mail ", value=settings.imap_username)
        imap_password = st.text_input("Passwort ", value=settings.imap_password, type="password")

    st.markdown("---")

    st.markdown("### Benachrichtigungen")
    notification_email = st.text_input(
        "E-Mail für Benachrichtigungen",
        value=settings.notification_email,
        help="An diese Adresse werden Erinnerungen gesendet"
    )

    col_days = st.columns(2)
    with col_days[0]:
        notify_days = st.multiselect(
            "Fristen-Erinnerung (Tage vorher)",
            options=[1, 2, 3, 5, 7, 14, 30],
            default=settings.notify_days_before_deadline
        )
    with col_days[1]:
        notify_birthday = st.number_input(
            "Geburtstags-Erinnerung (Tage vorher)",
            value=settings.notify_birthday_days_before,
            min_value=0,
            max_value=30
        )

    if st.button("💾 E-Mail-Einstellungen speichern", type="primary"):
        settings.smtp_server = smtp_server
        settings.smtp_port = smtp_port
        settings.smtp_username = smtp_username
        settings.smtp_password = smtp_password
        settings.imap_server = imap_server
        settings.imap_port = imap_port
        settings.imap_username = imap_username
        settings.imap_password = imap_password
        settings.notification_email = notification_email
        settings.notify_days_before_deadline = notify_days
        settings.notify_birthday_days_before = notify_birthday
        save_settings(settings)
        st.success("E-Mail-Einstellungen gespeichert!")

    # Test-E-Mail
    if st.button("📧 Test-E-Mail senden"):
        from utils.helpers import send_email_notification
        if notification_email:
            success = send_email_notification(
                notification_email,
                "Test-E-Mail von Dokumentenmanagement",
                "Dies ist eine Test-E-Mail. Wenn Sie diese erhalten, funktioniert Ihre E-Mail-Konfiguration korrekt.",
                None
            )
            if success:
                st.success("Test-E-Mail gesendet!")
        else:
            st.warning("Bitte geben Sie eine Benachrichtigungs-E-Mail an")


with tab_security:
    st.subheader("🔒 Sicherheit & Verschlüsselung")

    st.markdown("### Verschlüsselung")
    encryption_enabled = st.checkbox(
        "Dokumentenverschlüsselung aktiviert",
        value=settings.encryption_enabled,
        help="Alle Dokumente werden mit AES-256 verschlüsselt gespeichert"
    )

    st.info("""
    **Verschlüsselungsstatus:**
    - Alle Dokumente werden mit AES-256-GCM verschlüsselt
    - Der Schlüssel wird sicher in Ihrer Session gespeichert
    - Bei Verlust des Schlüssels können Dokumente nicht wiederhergestellt werden
    """)

    st.markdown("---")

    st.markdown("### Passwort ändern")

    with get_db() as session:
        user = session.query(User).get(user_id)

        current_pw = st.text_input("Aktuelles Passwort", type="password")
        new_pw = st.text_input("Neues Passwort", type="password")
        confirm_pw = st.text_input("Passwort bestätigen", type="password")

        if st.button("Passwort ändern"):
            if not current_pw or not new_pw:
                st.error("Bitte alle Felder ausfüllen")
            elif new_pw != confirm_pw:
                st.error("Passwörter stimmen nicht überein")
            elif len(new_pw) < 8:
                st.error("Passwort muss mindestens 8 Zeichen haben")
            else:
                # Aktuelles Passwort prüfen
                if EncryptionService.verify_password(current_pw, user.password_hash):
                    user.password_hash = EncryptionService.hash_password(new_pw)
                    session.commit()
                    st.success("Passwort geändert!")
                else:
                    st.error("Aktuelles Passwort falsch")

    st.markdown("---")

    st.markdown("### Datensicherung")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📥 Daten exportieren"):
            st.info("Export-Funktion wird vorbereitet...")
            # TODO: Implementiere Datenexport

    with col2:
        if st.button("📤 Daten importieren"):
            st.info("Import-Funktion wird vorbereitet...")
            # TODO: Implementiere Datenimport


with tab_calendar:
    st.subheader("📅 Kalender-Synchronisation")

    st.markdown("### Google Kalender")
    google_enabled = st.checkbox(
        "Google Kalender aktivieren",
        value=settings.google_calendar_enabled
    )

    if google_enabled:
        st.text_area(
            "Google Credentials JSON",
            value=settings.google_credentials_json,
            height=150,
            help="Fügen Sie hier Ihre Google API Credentials ein"
        )

        st.info("""
        **So erhalten Sie Google Credentials:**
        1. Gehen Sie zur [Google Cloud Console](https://console.cloud.google.com)
        2. Erstellen Sie ein Projekt und aktivieren Sie die Calendar API
        3. Erstellen Sie OAuth2 Credentials
        4. Laden Sie die JSON-Datei herunter und fügen Sie den Inhalt hier ein
        """)

    st.markdown("---")

    st.markdown("### Microsoft Outlook")
    outlook_enabled = st.checkbox(
        "Outlook Kalender aktivieren",
        value=settings.outlook_enabled
    )

    if outlook_enabled:
        outlook_client_id = st.text_input(
            "Client ID",
            value=settings.outlook_client_id
        )
        outlook_client_secret = st.text_input(
            "Client Secret",
            value=settings.outlook_client_secret,
            type="password"
        )

    if st.button("💾 Kalender-Einstellungen speichern", type="primary"):
        settings.google_calendar_enabled = google_enabled
        settings.outlook_enabled = outlook_enabled
        if outlook_enabled:
            settings.outlook_client_id = outlook_client_id
            settings.outlook_client_secret = outlook_client_secret
        save_settings(settings)
        st.success("Kalender-Einstellungen gespeichert!")


with tab_ui:
    st.subheader("🎨 Oberflächen-Einstellungen")

    st.markdown("### Allgemein")

    language = st.selectbox(
        "Sprache",
        options=["de", "en"],
        format_func=lambda x: {"de": "Deutsch", "en": "English"}.get(x),
        index=0 if settings.language == "de" else 1
    )

    theme = st.selectbox(
        "Farbschema",
        options=["light", "dark"],
        format_func=lambda x: {"light": "Hell", "dark": "Dunkel"}.get(x),
        index=0 if settings.theme == "light" else 1
    )

    items_per_page = st.slider(
        "Elemente pro Seite",
        min_value=10,
        max_value=100,
        value=settings.items_per_page,
        step=10
    )

    if st.button("💾 UI-Einstellungen speichern", type="primary"):
        settings.language = language
        settings.theme = theme
        settings.items_per_page = items_per_page
        save_settings(settings)
        st.success("UI-Einstellungen gespeichert!")

    st.markdown("---")

    st.markdown("### Über diese App")

    st.info(f"""
    **{APP_NAME}**
    {get_version_string()}

    Eine sichere und intelligente Dokumentenverwaltung mit:
    - 🔒 AES-256 Verschlüsselung
    - 🤖 KI-gestützte Dokumentenanalyse
    - 📊 Intelligente Klassifikation
    - 📅 Fristen- und Terminverwaltung
    - 👥 Bon-Teilen für Gruppen

    Entwickelt mit Streamlit, SQLAlchemy und Python.
    """)

    if st.button("🗑️ Cache leeren"):
        st.cache_data.clear()
        st.cache_resource.clear()
        for key in list(st.session_state.keys()):
            if key not in ['user_id', 'settings']:
                del st.session_state[key]
        st.success("Cache geleert!")
        st.rerun()
