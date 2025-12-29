"""
Einstellungen - API-Keys, E-Mail-Konfiguration, Sicherheit
"""
import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import User, BankAccount
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
tab_api, tab_email, tab_security, tab_bank, tab_calendar, tab_cloud, tab_ui = st.tabs([
    "🔑 API-Keys",
    "📧 E-Mail",
    "🔒 Sicherheit",
    "🏦 Bankkonten",
    "📅 Kalender-Sync",
    "☁️ Cloud-Sync",
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
        user = session.get(User, user_id)

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


with tab_bank:
    st.subheader("🏦 Bankkonten verwalten")
    st.markdown("Verwalten Sie hier Ihre Bankkonten für die Zahlungsverfolgung bei Rechnungen.")

    # Neues Konto hinzufügen
    with st.expander("➕ Neues Bankkonto hinzufügen", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            new_bank_name = st.text_input(
                "Bank",
                placeholder="z.B. Sparkasse, ING, Volksbank",
                key="new_bank_name"
            )
            new_account_name = st.text_input(
                "Kontobezeichnung",
                placeholder="z.B. Girokonto, Tagesgeld, Geschäftskonto",
                key="new_account_name"
            )

        with col2:
            new_iban = st.text_input(
                "IBAN (optional)",
                placeholder="DE89 3704 0044 0532 0130 00",
                key="new_iban"
            )
            new_bic = st.text_input(
                "BIC (optional)",
                placeholder="COBADEFFXXX",
                key="new_bic"
            )

        col3, col4, col5 = st.columns([1, 1, 2])

        with col3:
            # Farbauswahl
            available_colors = [
                "#1976D2",  # Blau
                "#388E3C",  # Grün
                "#F57C00",  # Orange
                "#7B1FA2",  # Lila
                "#C2185B",  # Pink
                "#00796B",  # Teal
                "#5D4037",  # Braun
                "#455A64",  # Grau-Blau
            ]
            new_color = st.color_picker("Farbe", value="#1976D2", key="new_color")

        with col4:
            # Icon-Auswahl
            icon_options = ["🏦", "💳", "🏧", "💰", "💵", "📊", "🏠", "🚗"]
            new_icon = st.selectbox("Symbol", options=icon_options, key="new_icon")

        with col5:
            new_is_default = st.checkbox("Als Standard-Konto festlegen", key="new_is_default")

        new_notes = st.text_area("Notizen (optional)", key="new_notes", height=68)

        if st.button("💾 Konto hinzufügen", type="primary", key="add_bank_account"):
            if new_bank_name and new_account_name:
                with get_db() as session:
                    # Prüfen ob Konto bereits existiert
                    existing = session.query(BankAccount).filter(
                        BankAccount.user_id == user_id,
                        BankAccount.bank_name == new_bank_name,
                        BankAccount.account_name == new_account_name
                    ).first()

                    if existing:
                        st.error("Ein Konto mit diesem Namen existiert bereits!")
                    else:
                        # Falls neues Konto Standard sein soll, andere zurücksetzen
                        if new_is_default:
                            session.query(BankAccount).filter(
                                BankAccount.user_id == user_id,
                                BankAccount.is_default == True
                            ).update({'is_default': False})

                        new_account = BankAccount(
                            user_id=user_id,
                            bank_name=new_bank_name,
                            account_name=new_account_name,
                            iban=new_iban.replace(" ", "") if new_iban else None,
                            bic=new_bic.replace(" ", "") if new_bic else None,
                            color=new_color,
                            icon=new_icon,
                            is_default=new_is_default,
                            notes=new_notes if new_notes else None
                        )
                        session.add(new_account)
                        session.commit()
                        st.success(f"✅ Konto '{new_bank_name} - {new_account_name}' hinzugefügt!")
                        st.rerun()
            else:
                st.warning("Bitte Bank und Kontobezeichnung eingeben!")

    st.markdown("---")

    # Bestehende Konten anzeigen
    st.markdown("### 📋 Ihre Bankkonten")

    with get_db() as session:
        accounts = session.query(BankAccount).filter(
            BankAccount.user_id == user_id
        ).order_by(BankAccount.is_default.desc(), BankAccount.bank_name).all()

        if accounts:
            for account in accounts:
                with st.container():
                    col_icon, col_info, col_actions = st.columns([0.5, 3, 1.5])

                    with col_icon:
                        st.markdown(
                            f"<div style='font-size: 2rem; background-color: {account.color}20; "
                            f"padding: 10px; border-radius: 10px; text-align: center; "
                            f"border-left: 4px solid {account.color};'>{account.icon}</div>",
                            unsafe_allow_html=True
                        )

                    with col_info:
                        default_badge = " ⭐ Standard" if account.is_default else ""
                        inactive_badge = " 🚫 Inaktiv" if not account.is_active else ""
                        st.markdown(f"**{account.bank_name} - {account.account_name}**{default_badge}{inactive_badge}")

                        info_parts = []
                        if account.iban:
                            # IBAN formatiert anzeigen (gruppiert)
                            formatted_iban = ' '.join([account.iban[i:i+4] for i in range(0, len(account.iban), 4)])
                            info_parts.append(f"IBAN: {formatted_iban}")
                        if account.bic:
                            info_parts.append(f"BIC: {account.bic}")

                        if info_parts:
                            st.caption(" | ".join(info_parts))

                        if account.notes:
                            st.caption(f"📝 {account.notes}")

                    with col_actions:
                        action_cols = st.columns(3)

                        with action_cols[0]:
                            # Bearbeiten
                            if st.button("✏️", key=f"edit_{account.id}", help="Bearbeiten"):
                                st.session_state[f'editing_account_{account.id}'] = True
                                st.rerun()

                        with action_cols[1]:
                            # Standard setzen/entfernen
                            if account.is_default:
                                if st.button("⭐", key=f"undefault_{account.id}", help="Standard entfernen"):
                                    account.is_default = False
                                    session.commit()
                                    st.rerun()
                            else:
                                if st.button("☆", key=f"default_{account.id}", help="Als Standard"):
                                    # Andere zurücksetzen
                                    session.query(BankAccount).filter(
                                        BankAccount.user_id == user_id,
                                        BankAccount.is_default == True
                                    ).update({'is_default': False})
                                    account.is_default = True
                                    session.commit()
                                    st.rerun()

                        with action_cols[2]:
                            # Löschen
                            if st.button("🗑️", key=f"delete_{account.id}", help="Löschen"):
                                st.session_state[f'confirm_delete_{account.id}'] = True
                                st.rerun()

                    # Bearbeitungsformular
                    if st.session_state.get(f'editing_account_{account.id}'):
                        with st.container():
                            st.markdown("---")
                            edit_col1, edit_col2 = st.columns(2)

                            with edit_col1:
                                edit_bank = st.text_input(
                                    "Bank",
                                    value=account.bank_name,
                                    key=f"edit_bank_{account.id}"
                                )
                                edit_account_name = st.text_input(
                                    "Kontobezeichnung",
                                    value=account.account_name,
                                    key=f"edit_account_{account.id}"
                                )
                                edit_color = st.color_picker(
                                    "Farbe",
                                    value=account.color or "#1976D2",
                                    key=f"edit_color_{account.id}"
                                )

                            with edit_col2:
                                edit_iban = st.text_input(
                                    "IBAN",
                                    value=account.iban or "",
                                    key=f"edit_iban_{account.id}"
                                )
                                edit_bic = st.text_input(
                                    "BIC",
                                    value=account.bic or "",
                                    key=f"edit_bic_{account.id}"
                                )
                                icon_options = ["🏦", "💳", "🏧", "💰", "💵", "📊", "🏠", "🚗"]
                                current_icon_index = icon_options.index(account.icon) if account.icon in icon_options else 0
                                edit_icon = st.selectbox(
                                    "Symbol",
                                    options=icon_options,
                                    index=current_icon_index,
                                    key=f"edit_icon_{account.id}"
                                )

                            edit_active = st.checkbox(
                                "Konto aktiv",
                                value=account.is_active,
                                key=f"edit_active_{account.id}"
                            )
                            edit_notes = st.text_area(
                                "Notizen",
                                value=account.notes or "",
                                key=f"edit_notes_{account.id}"
                            )

                            btn_col1, btn_col2 = st.columns(2)
                            with btn_col1:
                                if st.button("💾 Speichern", key=f"save_{account.id}", type="primary"):
                                    account.bank_name = edit_bank
                                    account.account_name = edit_account_name
                                    account.iban = edit_iban.replace(" ", "") if edit_iban else None
                                    account.bic = edit_bic.replace(" ", "") if edit_bic else None
                                    account.color = edit_color
                                    account.icon = edit_icon
                                    account.is_active = edit_active
                                    account.notes = edit_notes if edit_notes else None
                                    session.commit()
                                    del st.session_state[f'editing_account_{account.id}']
                                    st.success("✅ Änderungen gespeichert!")
                                    st.rerun()

                            with btn_col2:
                                if st.button("❌ Abbrechen", key=f"cancel_{account.id}"):
                                    del st.session_state[f'editing_account_{account.id}']
                                    st.rerun()

                    # Löschbestätigung
                    if st.session_state.get(f'confirm_delete_{account.id}'):
                        st.warning(f"⚠️ Konto '{account.bank_name} - {account.account_name}' wirklich löschen?")
                        del_col1, del_col2 = st.columns(2)
                        with del_col1:
                            if st.button("🗑️ Ja, löschen", key=f"confirm_del_{account.id}", type="primary"):
                                session.delete(account)
                                session.commit()
                                del st.session_state[f'confirm_delete_{account.id}']
                                st.success("Konto gelöscht!")
                                st.rerun()
                        with del_col2:
                            if st.button("❌ Abbrechen", key=f"cancel_del_{account.id}"):
                                del st.session_state[f'confirm_delete_{account.id}']
                                st.rerun()

                    st.divider()
        else:
            st.info("📭 Noch keine Bankkonten hinterlegt. Fügen Sie oben Ihr erstes Konto hinzu!")

    # Schnell-Hinzufügen für gängige Banken
    st.markdown("---")
    st.markdown("### 🚀 Schnell-Hinzufügen")
    st.caption("Klicken Sie auf eine Bank, um ein Standardkonto anzulegen:")

    quick_banks = [
        ("🏦 Sparkasse", "Sparkasse", "#FF0000"),
        ("🏦 Volksbank", "Volksbank", "#003399"),
        ("🟧 ING", "ING", "#FF6600"),
        ("🔵 DKB", "DKB", "#0066B3"),
        ("🟢 N26", "N26", "#48D5A4"),
        ("💜 Commerzbank", "Commerzbank", "#FFCC00"),
        ("🔴 Deutsche Bank", "Deutsche Bank", "#0018A8"),
        ("🟡 Postbank", "Postbank", "#FFCC00"),
    ]

    quick_cols = st.columns(4)
    for idx, (label, bank, color) in enumerate(quick_banks):
        with quick_cols[idx % 4]:
            if st.button(label, key=f"quick_{bank}", use_container_width=True):
                with get_db() as session:
                    existing = session.query(BankAccount).filter(
                        BankAccount.user_id == user_id,
                        BankAccount.bank_name == bank,
                        BankAccount.account_name == "Girokonto"
                    ).first()

                    if existing:
                        st.warning(f"Girokonto bei {bank} existiert bereits!")
                    else:
                        new_acc = BankAccount(
                            user_id=user_id,
                            bank_name=bank,
                            account_name="Girokonto",
                            color=color,
                            icon="🏦"
                        )
                        session.add(new_acc)
                        session.commit()
                        st.success(f"✅ Girokonto bei {bank} hinzugefügt!")
                        st.rerun()

    # =====================
    # BANK-SYNC (Nordigen/GoCardless)
    # =====================
    st.markdown("---")
    st.markdown("### 🔄 Bank-Synchronisation")
    st.markdown("Verbinden Sie Ihre Bankkonten, um Transaktionen automatisch abzurufen.")

    # API-Credentials
    with st.expander("🔑 GoCardless/Nordigen API-Credentials", expanded=False):
        st.info("""
        **Kostenlose Registrierung:**
        1. Besuchen Sie [GoCardless Bank Account Data](https://bankaccountdata.gocardless.com/)
        2. Erstellen Sie einen kostenlosen Account
        3. Generieren Sie API-Credentials (Secret ID & Secret Key)
        4. Tragen Sie diese unten ein
        """)

        nordigen_id = st.text_input(
            "Secret ID",
            value=settings.nordigen_secret_id,
            type="password",
            key="nordigen_id"
        )
        nordigen_key = st.text_input(
            "Secret Key",
            value=settings.nordigen_secret_key,
            type="password",
            key="nordigen_key"
        )

        if st.button("💾 API-Credentials speichern", key="save_nordigen"):
            settings.nordigen_secret_id = nordigen_id
            settings.nordigen_secret_key = nordigen_key
            save_settings(settings)
            st.success("✅ API-Credentials gespeichert!")

    # Prüfen ob API konfiguriert
    from services.banking_service import get_nordigen_service
    nordigen = get_nordigen_service()

    if nordigen.is_configured():
        st.success("✅ GoCardless API ist konfiguriert")

        # Bank verbinden
        st.markdown("#### 🏦 Neue Bank verbinden")

        # Banken-Suche
        bank_search = st.text_input(
            "Bank suchen",
            placeholder="z.B. Sparkasse, ING, DKB...",
            key="bank_search"
        )

        if bank_search and len(bank_search) >= 2:
            with st.spinner("Suche Banken..."):
                institutions = nordigen.search_institutions(bank_search, country="DE")

            if institutions:
                st.markdown(f"**{len(institutions)} Banken gefunden:**")

                for inst in institutions[:10]:  # Max 10 anzeigen
                    col_logo, col_name, col_action = st.columns([1, 3, 1])

                    with col_logo:
                        if inst.get("logo"):
                            st.image(inst["logo"], width=40)
                        else:
                            st.write("🏦")

                    with col_name:
                        st.write(f"**{inst['name']}**")
                        st.caption(f"ID: {inst['id']}")

                    with col_action:
                        if st.button("Verbinden", key=f"connect_{inst['id']}"):
                            # Requisition erstellen
                            st.session_state['connecting_bank'] = inst
                            st.rerun()
            else:
                st.warning("Keine Banken gefunden")

        # Verbindungsprozess
        if st.session_state.get('connecting_bank'):
            inst = st.session_state['connecting_bank']
            st.info(f"🔗 Verbindung zu **{inst['name']}** wird hergestellt...")

            # Redirect URL (für lokale Entwicklung)
            redirect_url = settings.nordigen_redirect_url or "http://localhost:8501"

            result = nordigen.create_requisition(
                institution_id=inst['id'],
                redirect_url=redirect_url,
                reference=f"user_{user_id}_{inst['id']}"
            )

            if result and not result.get("error"):
                st.markdown(f"""
                ### 🔐 Bank-Authentifizierung

                Klicken Sie auf den Button, um sich bei Ihrer Bank anzumelden:

                [**→ Zur Bank-Anmeldung**]({result.get('link')})

                Nach erfolgreicher Anmeldung werden Sie zurückgeleitet.
                """)

                # Requisition ID speichern
                st.session_state['pending_requisition'] = result.get('id')

                if st.button("❌ Abbrechen"):
                    del st.session_state['connecting_bank']
                    st.rerun()
            else:
                st.error(f"Fehler: {result.get('error', 'Unbekannter Fehler')}")
                del st.session_state['connecting_bank']

        # Verbundene Konten anzeigen
        st.markdown("---")
        st.markdown("#### 📋 Verbundene Konten")

        from database.models import BankConnection
        with get_db() as session:
            connections = session.query(BankConnection).filter(
                BankConnection.user_id == user_id
            ).all()

            if connections:
                for conn in connections:
                    with st.container():
                        col1, col2, col3 = st.columns([1, 3, 1])

                        with col1:
                            if conn.institution_logo:
                                st.image(conn.institution_logo, width=50)
                            else:
                                st.write("🏦")

                        with col2:
                            status_icon = "🟢" if conn.status == "active" else "🟡" if conn.status == "pending" else "🔴"
                            st.markdown(f"**{conn.institution_name}** {status_icon}")
                            st.caption(f"IBAN: {conn.iban or 'N/A'}")

                            if conn.balance_available is not None:
                                st.write(f"💰 Verfügbar: **{conn.balance_available:,.2f} €**")

                            if conn.last_sync:
                                st.caption(f"Letzte Sync: {conn.last_sync.strftime('%d.%m.%Y %H:%M')}")

                        with col3:
                            if conn.status == "active":
                                if st.button("🔄", key=f"sync_{conn.id}", help="Synchronisieren"):
                                    with st.spinner("Synchronisiere..."):
                                        result = nordigen.sync_connection(conn.id)
                                        if result.get("success"):
                                            st.success(f"✅ {result.get('new_transactions', 0)} neue Transaktionen")
                                            st.rerun()
                                        else:
                                            st.error(result.get("error"))

                            if st.button("🗑️", key=f"del_conn_{conn.id}", help="Entfernen"):
                                session.delete(conn)
                                session.commit()
                                st.success("Verbindung entfernt!")
                                st.rerun()

                        st.divider()
            else:
                st.info("Noch keine Bankkonten verbunden. Suchen Sie oben nach Ihrer Bank.")

    else:
        st.warning("⚠️ GoCardless API nicht konfiguriert. Tragen Sie oben Ihre API-Credentials ein.")


with tab_cloud:
    st.subheader("☁️ Cloud-Synchronisation")
    st.markdown("Verbinden Sie Dropbox oder Google Drive für automatischen Dokumentenimport.")

    # Import Cloud-Sync Service
    try:
        from services.cloud_sync_service import CloudSyncService, CloudProvider, SyncStatus
        CLOUD_AVAILABLE = True
    except ImportError:
        CLOUD_AVAILABLE = False

    if not CLOUD_AVAILABLE:
        st.error("Cloud-Sync Module nicht verfügbar.")
    else:
        cloud_service = CloudSyncService(user_id)

        # Aktive Verbindungen anzeigen
        st.markdown("### 🔗 Aktive Sync-Verbindungen")

        connections = cloud_service.get_connections()
        active_connections = [c for c in connections if c.is_active]

        if active_connections:
            for conn in active_connections:
                provider_icon = "📦" if conn.provider == CloudProvider.DROPBOX else "🔵"
                provider_name = "Dropbox" if conn.provider == CloudProvider.DROPBOX else "Google Drive"
                status_icon = "🟢" if conn.sync_status == SyncStatus.COMPLETED else "🟡" if conn.sync_status == SyncStatus.SYNCING else "🔴"

                with st.container():
                    col_icon, col_info, col_actions = st.columns([0.5, 3, 1.5])

                    with col_icon:
                        st.markdown(f"<div style='font-size: 2rem; text-align: center;'>{provider_icon}</div>", unsafe_allow_html=True)

                    with col_info:
                        sync_type = "Dauerhaft" if conn.sync_interval_minutes else "Einmalig"
                        interval_text = f" (alle {conn.sync_interval_minutes} Min.)" if conn.sync_interval_minutes else ""
                        st.markdown(f"**{provider_name}** {status_icon}")
                        st.caption(f"Ordner: {conn.folder_path or conn.folder_id}")
                        st.caption(f"Typ: {sync_type}{interval_text}")
                        if conn.last_sync:
                            st.caption(f"Letzte Sync: {conn.last_sync.strftime('%d.%m.%Y %H:%M')}")

                    with col_actions:
                        action_cols = st.columns(2)
                        with action_cols[0]:
                            if st.button("🔄", key=f"sync_cloud_{conn.id}", help="Jetzt synchronisieren"):
                                st.session_state[f"syncing_{conn.id}"] = True
                                st.rerun()

                        with action_cols[1]:
                            if st.button("🗑️", key=f"del_cloud_{conn.id}", help="Verbindung löschen"):
                                cloud_service.delete_connection(conn.id)
                                st.success("Verbindung gelöscht!")
                                st.rerun()

                    # Sync-Fortschritt anzeigen wenn aktiv
                    if st.session_state.get(f"syncing_{conn.id}"):
                        def format_time(seconds):
                            if seconds is None or seconds < 0:
                                return "Berechne..."
                            if seconds < 60:
                                return f"{int(seconds)} Sek."
                            elif seconds < 3600:
                                return f"{int(seconds / 60)} Min. {int(seconds % 60)} Sek."
                            else:
                                return f"{int(seconds / 3600)} Std. {int((seconds % 3600) / 60)} Min."

                        def format_size(bytes_size):
                            if bytes_size < 1024:
                                return f"{bytes_size} B"
                            elif bytes_size < 1024 * 1024:
                                return f"{bytes_size / 1024:.1f} KB"
                            return f"{bytes_size / (1024 * 1024):.1f} MB"

                        sync_progress = st.progress(0, text="Initialisiere...")
                        sync_status = st.empty()
                        sync_file = st.empty()
                        sync_stats = st.empty()

                        final_result = None
                        for progress in cloud_service.sync_connection_with_progress(conn.id):
                            final_result = progress
                            phase = progress.get("phase", "")
                            percent = progress.get("progress_percent", 0)
                            sync_progress.progress(percent / 100)

                            if phase == "scanning":
                                sync_status.info("🔍 Scanne Cloud-Ordner...")
                            elif phase == "downloading":
                                total = progress.get("files_total", 0)
                                processed = progress.get("files_processed", 0)
                                elapsed = progress.get("elapsed_seconds", 0)
                                remaining = progress.get("estimated_remaining_seconds")

                                time_text = f"⏱️ {format_time(elapsed)}"
                                if remaining and remaining > 0:
                                    time_text += f" | ⏳ ~{format_time(remaining)}"

                                sync_status.info(f"📥 {processed + 1}/{total} | {time_text}")

                                current_file = progress.get("current_file")
                                if current_file:
                                    sync_file.caption(f"📄 {current_file} ({format_size(progress.get('current_file_size', 0))})")

                                sync_stats.caption(
                                    f"✅ {progress.get('files_synced', 0)} | "
                                    f"⏭️ {progress.get('files_skipped', 0)} | "
                                    f"❌ {progress.get('files_error', 0)}"
                                )
                            elif phase == "completed":
                                sync_progress.progress(1.0, text="✅ Fertig!")
                            elif phase == "error":
                                sync_progress.progress(0, text="❌ Fehler")

                        # Aufräumen
                        del st.session_state[f"syncing_{conn.id}"]
                        sync_file.empty()

                        if final_result and final_result.get("success"):
                            sync_status.success(f"✅ {final_result.get('new_files', 0)} Dateien importiert!")
                        elif final_result:
                            sync_status.error(final_result.get("error", "Fehler"))

                    st.divider()
        else:
            st.info("Keine aktiven Cloud-Verbindungen. Fügen Sie unten eine neue Verbindung hinzu.")

        st.markdown("---")

        # Neue Verbindung hinzufügen
        st.markdown("### ➕ Neue Cloud-Verbindung hinzufügen")

        with st.form("cloud_sync_form"):
            col1, col2 = st.columns(2)

            with col1:
                cloud_provider = st.selectbox(
                    "Cloud-Dienst",
                    options=["dropbox", "google_drive"],
                    format_func=lambda x: "📦 Dropbox" if x == "dropbox" else "🔵 Google Drive"
                )

                folder_link = st.text_input(
                    "Ordner-Link",
                    placeholder="https://www.dropbox.com/scl/fo/... oder https://drive.google.com/drive/folders/...",
                    help="Kopieren Sie den Link zu Ihrem Cloud-Ordner"
                )

            with col2:
                sync_mode = st.radio(
                    "Sync-Modus",
                    options=["once", "interval", "continuous"],
                    format_func=lambda x: {
                        "once": "🔂 Einmalig (nur jetzt importieren)",
                        "interval": "⏱️ Intervall (regelmäßig synchronisieren)",
                        "continuous": "♾️ Dauerhaft (bis Abbruch)"
                    }.get(x),
                    horizontal=False
                )

                if sync_mode == "interval":
                    sync_interval = st.selectbox(
                        "Intervall",
                        options=[5, 15, 30, 60, 120, 360, 720, 1440],
                        format_func=lambda x: {
                            5: "5 Minuten",
                            15: "15 Minuten",
                            30: "30 Minuten",
                            60: "1 Stunde",
                            120: "2 Stunden",
                            360: "6 Stunden",
                            720: "12 Stunden",
                            1440: "24 Stunden"
                        }.get(x),
                        index=2
                    )
                else:
                    sync_interval = None

            st.markdown("---")

            # API-Konfiguration (Expander)
            with st.expander("🔑 API-Konfiguration (optional)"):
                st.info("""
                **Für Dropbox:**
                - [Dropbox App Console](https://www.dropbox.com/developers/apps) besuchen
                - App erstellen und Access Token generieren

                **Für Google Drive:**
                - [Google Cloud Console](https://console.cloud.google.com) besuchen
                - Projekt erstellen, Drive API aktivieren
                - OAuth2 Credentials oder Service Account erstellen
                """)

                if cloud_provider == "dropbox":
                    dropbox_token = st.text_input(
                        "Dropbox Access Token",
                        value=settings.dropbox_access_token if hasattr(settings, 'dropbox_access_token') else "",
                        type="password"
                    )
                else:
                    google_creds = st.text_area(
                        "Google Service Account JSON",
                        value=settings.google_drive_credentials if hasattr(settings, 'google_drive_credentials') else "",
                        height=100
                    )

            submitted = st.form_submit_button("☁️ Verbindung erstellen", type="primary")

            if submitted:
                if not folder_link:
                    st.error("Bitte geben Sie einen Ordner-Link ein.")
                else:
                    # Ordner-ID/Pfad aus Link extrahieren
                    folder_id = folder_link  # Service wird Link parsen

                    # Intervall setzen
                    interval_minutes = None
                    if sync_mode == "interval":
                        interval_minutes = sync_interval
                    elif sync_mode == "continuous":
                        interval_minutes = 5  # Kontinuierlich = alle 5 Minuten

                    try:
                        conn = cloud_service.create_connection(
                            provider=CloudProvider.DROPBOX if cloud_provider == "dropbox" else CloudProvider.GOOGLE_DRIVE,
                            folder_id=folder_id,
                            folder_path=folder_link,
                            sync_interval_minutes=interval_minutes
                        )

                        st.success(f"✅ Cloud-Verbindung erstellt!")

                        # Bei einmalig sofort synchronisieren mit Fortschritt
                        if sync_mode == "once":
                            def fmt_time(s):
                                if s is None or s < 0: return "..."
                                if s < 60: return f"{int(s)}s"
                                return f"{int(s/60)}m {int(s%60)}s"

                            def fmt_size(b):
                                if b < 1024: return f"{b}B"
                                if b < 1024*1024: return f"{b/1024:.1f}KB"
                                return f"{b/1024/1024:.1f}MB"

                            prog_bar = st.progress(0, text="Starte Import...")
                            prog_status = st.empty()
                            prog_file = st.empty()

                            final = None
                            for p in cloud_service.sync_connection_with_progress(conn.id):
                                final = p
                                phase = p.get("phase", "")
                                pct = p.get("progress_percent", 0)
                                prog_bar.progress(pct / 100)

                                if phase == "scanning":
                                    prog_status.info("🔍 Scanne Ordner...")
                                elif phase == "downloading":
                                    t, pr = p.get("files_total", 0), p.get("files_processed", 0)
                                    el, rem = p.get("elapsed_seconds", 0), p.get("estimated_remaining_seconds")
                                    time_str = f"⏱️ {fmt_time(el)}"
                                    if rem and rem > 0: time_str += f" | ⏳ ~{fmt_time(rem)}"
                                    prog_status.info(f"📥 {pr+1}/{t} | {time_str}")
                                    cf = p.get("current_file")
                                    if cf: prog_file.caption(f"📄 {cf} ({fmt_size(p.get('current_file_size',0))})")
                                elif phase == "completed":
                                    prog_bar.progress(1.0, text="✅ Fertig!")
                                elif phase == "error":
                                    prog_bar.progress(0, text="❌ Fehler")

                            prog_file.empty()
                            if final:
                                if final.get("success"):
                                    nf = final.get("new_files", 0)
                                    sf = final.get("synced_files", [])
                                    prog_status.success(f"✅ {nf} Dateien importiert!")
                                    if sf:
                                        with st.expander(f"📋 Importierte Dateien ({len(sf)})"):
                                            for f in sf: st.write(f"• {f}")
                                else:
                                    prog_status.warning(f"⚠️ {final.get('error', 'Bitte API-Token konfigurieren')}")
                        else:
                            st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")

        # Sync-Logs anzeigen
        st.markdown("---")
        st.markdown("### 📋 Sync-Protokoll")

        logs = cloud_service.get_sync_logs(limit=10)
        if logs:
            for log in logs:
                status_icon = "✅" if log.status == "completed" else "❌" if log.status == "failed" else "🔄"
                st.caption(f"{status_icon} {log.created_at.strftime('%d.%m.%Y %H:%M')} - {log.files_synced or 0} Dateien, {log.files_skipped or 0} übersprungen")
        else:
            st.caption("Noch keine Sync-Aktivitäten.")


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

    st.markdown("---")

    st.markdown("### 🗑️ Papierkorb-Einstellungen")

    trash_retention = st.slider(
        "Aufbewahrungszeit (Stunden)",
        min_value=1,
        max_value=720,  # Max 30 Tage
        value=settings.trash_retention_hours,
        step=1,
        help="Dokumente werden nach dieser Zeit automatisch endgültig gelöscht"
    )

    # Vorschlage für gängige Werte
    quick_trash_col = st.columns(5)
    with quick_trash_col[0]:
        if st.button("12h", key="trash_12h"):
            trash_retention = 12
    with quick_trash_col[1]:
        if st.button("24h", key="trash_24h"):
            trash_retention = 24
    with quick_trash_col[2]:
        if st.button("48h", key="trash_48h"):
            trash_retention = 48
    with quick_trash_col[3]:
        if st.button("7 Tage", key="trash_7d"):
            trash_retention = 168
    with quick_trash_col[4]:
        if st.button("30 Tage", key="trash_30d"):
            trash_retention = 720

    auto_cleanup = st.checkbox(
        "Automatische Bereinigung beim App-Start",
        value=settings.auto_cleanup_trash,
        help="Abgelaufene Dokumente werden automatisch gelöscht wenn die App gestartet wird"
    )

    # Papierkorb Statistik
    from services.trash_service import get_trash_service
    trash_service = get_trash_service()
    trash_stats = trash_service.get_trash_stats(user_id)

    if trash_stats["count"] > 0:
        st.info(f"""
        **Papierkorb-Status:**
        - 📄 {trash_stats['count']} Dokument(e) im Papierkorb
        - 💾 {trash_stats['total_size_mb']} MB belegt
        """)

        col_trash1, col_trash2 = st.columns(2)
        with col_trash1:
            if st.button("🔄 Abgelaufene bereinigen", key="cleanup_trash"):
                result = trash_service.cleanup_expired()
                if result["deleted_count"] > 0:
                    st.success(f"✅ {result['deleted_count']} Dokument(e) endgültig gelöscht")
                else:
                    st.info("Keine abgelaufenen Dokumente gefunden")
        with col_trash2:
            if st.button("🗑️ Papierkorb leeren", key="empty_trash"):
                st.session_state['confirm_empty_trash'] = True

        if st.session_state.get('confirm_empty_trash'):
            st.warning("⚠️ Alle Dokumente im Papierkorb werden endgültig gelöscht!")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Ja, alles löschen", key="confirm_empty_yes"):
                    result = trash_service.empty_trash(user_id)
                    del st.session_state['confirm_empty_trash']
                    st.success(result["message"])
                    st.rerun()
            with c2:
                if st.button("❌ Abbrechen", key="confirm_empty_no"):
                    del st.session_state['confirm_empty_trash']
                    st.rerun()

    st.markdown("---")

    st.markdown("### 🔊 Vorlese-Einstellungen (Text-to-Speech)")

    from services.tts_service import TTSService

    tts_voice = st.selectbox(
        "Standard-Stimme",
        options=list(TTSService.VOICES.keys()),
        format_func=lambda x: TTSService.VOICES.get(x, x),
        index=list(TTSService.VOICES.keys()).index(settings.tts_voice) if settings.tts_voice in TTSService.VOICES else 4
    )

    tts_model = st.selectbox(
        "Qualität",
        options=list(TTSService.MODELS.keys()),
        format_func=lambda x: TTSService.MODELS.get(x, x),
        index=0 if settings.tts_model == "tts-1" else 1
    )

    tts_speed = st.slider(
        "Geschwindigkeit",
        min_value=0.5,
        max_value=2.0,
        value=settings.tts_speed,
        step=0.1,
        help="1.0 = normale Geschwindigkeit"
    )

    tts_use_browser = st.checkbox(
        "Browser-TTS als Fallback verwenden",
        value=settings.tts_use_browser,
        help="Verwendet die eingebaute Sprachsynthese des Browsers wenn keine API konfiguriert ist"
    )

    if not settings.openai_api_key:
        st.warning("⚠️ Für OpenAI TTS wird ein API-Schlüssel benötigt (Tab: API-Keys)")

    if st.button("💾 UI-Einstellungen speichern", type="primary"):
        settings.language = language
        settings.theme = theme
        settings.items_per_page = items_per_page
        settings.trash_retention_hours = trash_retention
        settings.auto_cleanup_trash = auto_cleanup
        settings.tts_voice = tts_voice
        settings.tts_model = tts_model
        settings.tts_speed = tts_speed
        settings.tts_use_browser = tts_use_browser
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
