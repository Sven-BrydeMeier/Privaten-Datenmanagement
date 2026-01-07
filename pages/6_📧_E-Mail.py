"""
E-Mail - Senden, Empfangen und KI-Antwortvorschläge
"""
import streamlit as st
from pathlib import Path
import sys
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Email, Document
from config.settings import get_settings
from services.ai_service import get_ai_service
from utils.helpers import format_date, send_email_notification
from utils.components import render_sidebar_cart

st.set_page_config(page_title="E-Mail", page_icon="📧", layout="wide")
init_db()

# Sidebar mit Aktentasche
render_sidebar_cart()

user_id = get_current_user_id()
settings = get_settings()

st.title("📧 E-Mail")

# Prüfen ob E-Mail konfiguriert ist
email_configured = bool(settings.smtp_server and settings.smtp_username)

if not email_configured:
    st.warning("⚠️ E-Mail ist nicht konfiguriert. Bitte gehen Sie zu Einstellungen.")
    if st.button("Zu Einstellungen"):
        st.switch_page("pages/8_⚙️_Einstellungen.py")
else:
    # E-Mail-Tabs
    tab_inbox, tab_compose, tab_sent, tab_response, tab_verfuegung = st.tabs([
        "📥 Posteingang",
        "✏️ Neue E-Mail",
        "📤 Gesendet",
        "🤖 Antwortvorschläge",
        "📋 Verfügungen"
    ])

    with tab_inbox:
        st.subheader("📥 Posteingang")

        # E-Mails abrufen
        if st.button("🔄 E-Mails abrufen"):
            with st.spinner("Verbinde mit E-Mail-Server..."):
                try:
                    from imapclient import IMAPClient

                    with IMAPClient(settings.imap_server, port=settings.imap_port, ssl=True) as client:
                        client.login(settings.imap_username, settings.imap_password)
                        client.select_folder('INBOX')

                        # Letzte 20 E-Mails
                        messages = client.search(['ALL'])
                        messages = messages[-20:] if len(messages) > 20 else messages

                        for uid in messages:
                            data = client.fetch([uid], ['ENVELOPE', 'BODY[TEXT]'])
                            envelope = data[uid][b'ENVELOPE']

                            # In Datenbank speichern
                            with get_db() as session:
                                existing = session.query(Email).filter(
                                    Email.message_id == str(envelope.message_id)
                                ).first()

                                if not existing:
                                    email = Email(
                                        user_id=user_id,
                                        message_id=str(envelope.message_id),
                                        folder='inbox',
                                        from_address=str(envelope.from_[0]) if envelope.from_ else '',
                                        to_addresses=json.dumps([str(t) for t in envelope.to or []]),
                                        subject=envelope.subject.decode() if envelope.subject else '',
                                        received_at=envelope.date,
                                        is_read=False
                                    )
                                    session.add(email)
                                session.commit()

                    st.success("E-Mails abgerufen!")
                    st.rerun()

                except Exception as e:
                    st.error(f"Fehler beim Abrufen: {e}")

        # E-Mail-Liste
        with get_db() as session:
            emails = session.query(Email).filter(
                Email.user_id == user_id,
                Email.folder == 'inbox'
            ).order_by(Email.received_at.desc()).limit(50).all()

            if emails:
                for email in emails:
                    col1, col2, col3 = st.columns([3, 2, 1])

                    with col1:
                        icon = "📬" if not email.is_read else "📭"
                        style = "**" if not email.is_read else ""
                        st.markdown(f"{icon} {style}{email.subject or '(Kein Betreff)'}{style}")
                        st.caption(email.from_address)

                    with col2:
                        st.caption(format_date(email.received_at, True) if email.received_at else "")

                    with col3:
                        if st.button("👁️", key=f"view_email_{email.id}"):
                            st.session_state.view_email_id = email.id

                    st.divider()
            else:
                st.info("Keine E-Mails im Posteingang")

        # E-Mail-Detailansicht
        if 'view_email_id' in st.session_state:
            with get_db() as session:
                email = session.get(Email, st.session_state.view_email_id)
                if email:
                    st.divider()
                    st.subheader(email.subject or "(Kein Betreff)")
                    st.write(f"**Von:** {email.from_address}")
                    st.write(f"**Datum:** {format_date(email.received_at, True)}")

                    st.markdown("---")
                    st.text(email.body_text or "Kein Textinhalt")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("↩️ Antworten"):
                            st.session_state.reply_to_email = email.id
                            st.session_state.reply_subject = f"Re: {email.subject}"
                            st.session_state.reply_to = email.from_address
                    with col2:
                        if st.button("🗑️ Löschen"):
                            session.query(Email).filter(Email.id == email.id).delete()
                            session.commit()
                            del st.session_state.view_email_id
                            st.rerun()
                    with col3:
                        if st.button("Schließen"):
                            del st.session_state.view_email_id
                            st.rerun()

                    # Als gelesen markieren
                    if not email.is_read:
                        email.is_read = True
                        session.commit()

    with tab_compose:
        st.subheader("✏️ Neue E-Mail verfassen")

        # Vorausfüllen wenn Antwort
        default_to = st.session_state.get('reply_to', '')
        default_subject = st.session_state.get('reply_subject', '')

        to_address = st.text_input("An", value=default_to)
        cc_address = st.text_input("CC (optional)")
        subject = st.text_input("Betreff", value=default_subject)
        body = st.text_area("Nachricht", height=300)

        # Anhänge
        attachments = st.file_uploader(
            "Anhänge",
            accept_multiple_files=True,
            key="email_attachments"
        )

        # Dokumente aus Aktentasche anhängen
        cart_items = st.session_state.get('active_cart_items', [])
        if cart_items:
            st.info(f"📎 {len(cart_items)} Dokumente aus Aktentasche können angehängt werden")
            attach_cart = st.checkbox("Aktentasche-Dokumente anhängen")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📤 Senden", type="primary") and to_address and subject:
                attachment_data = []

                # Hochgeladene Anhänge
                for att in attachments:
                    attachment_data.append((att.name, att.read()))

                # Aktentasche-Dokumente
                if cart_items and 'attach_cart' in dir() and attach_cart:
                    from services.encryption import get_encryption_service
                    encryption = get_encryption_service()

                    from utils.helpers import get_document_file_content
                    with get_db() as session:
                        for doc_id in cart_items:
                            doc = session.get(Document, doc_id)
                            if doc and doc.file_path:
                                try:
                                    success, result = get_document_file_content(doc.file_path, doc.user_id)
                                    if success:
                                        decrypted = encryption.decrypt_file(result, doc.encryption_iv, doc.filename)
                                        attachment_data.append((doc.filename, decrypted))
                                except:
                                    pass

                success = send_email_notification(
                    to_address,
                    subject,
                    body,
                    attachment_data if attachment_data else None
                )

                if success:
                    # In Gesendet speichern
                    with get_db() as session:
                        sent_email = Email(
                            user_id=user_id,
                            folder='sent',
                            from_address=settings.smtp_username,
                            to_addresses=json.dumps([to_address]),
                            cc_addresses=json.dumps([cc_address]) if cc_address else None,
                            subject=subject,
                            body_text=body,
                            sent_at=datetime.now()
                        )
                        session.add(sent_email)
                        session.commit()

                    st.success("E-Mail gesendet!")

                    # Antwort-State löschen
                    if 'reply_to' in st.session_state:
                        del st.session_state.reply_to
                    if 'reply_subject' in st.session_state:
                        del st.session_state.reply_subject

        with col2:
            if st.button("Verwerfen"):
                if 'reply_to' in st.session_state:
                    del st.session_state.reply_to
                if 'reply_subject' in st.session_state:
                    del st.session_state.reply_subject
                st.rerun()

    with tab_sent:
        st.subheader("📤 Gesendete E-Mails")

        with get_db() as session:
            sent_emails = session.query(Email).filter(
                Email.user_id == user_id,
                Email.folder == 'sent'
            ).order_by(Email.sent_at.desc()).limit(50).all()

            if sent_emails:
                for email in sent_emails:
                    col1, col2 = st.columns([4, 1])

                    with col1:
                        st.markdown(f"📤 **{email.subject or '(Kein Betreff)'}**")
                        to_list = json.loads(email.to_addresses) if email.to_addresses else []
                        st.caption(f"An: {', '.join(to_list)}")

                    with col2:
                        st.caption(format_date(email.sent_at, True) if email.sent_at else "")

                    st.divider()
            else:
                st.info("Keine gesendeten E-Mails")

    with tab_response:
        st.subheader("🤖 KI-Antwortvorschläge")

        ai = get_ai_service()

        if not ai.any_ai_available:
            st.warning("⚠️ Keine KI-API konfiguriert. Bitte fügen Sie API-Keys in den Einstellungen hinzu.")
        else:
            st.markdown("""
            Die KI analysiert eingehende E-Mails und erstellt Antwortvorschläge
            für Nachrichten, die eine Reaktion erfordern.
            """)

            # E-Mails die Antwort brauchen
            with get_db() as session:
                emails_needing_response = session.query(Email).filter(
                    Email.user_id == user_id,
                    Email.folder == 'inbox',
                    Email.needs_response == True
                ).all()

                # Oder: KI analysiert neue E-Mails
                unanalyzed = session.query(Email).filter(
                    Email.user_id == user_id,
                    Email.folder == 'inbox',
                    Email.response_draft.is_(None)
                ).limit(10).all()

                if unanalyzed:
                    if st.button("🔍 E-Mails analysieren"):
                        progress = st.progress(0)
                        for i, email in enumerate(unanalyzed):
                            progress.progress((i + 1) / len(unanalyzed))

                            if email.body_text:
                                needs_response, reason = ai.needs_response(email.body_text)
                                email.needs_response = needs_response

                                if needs_response:
                                    # Antwortvorschlag generieren
                                    draft = ai.generate_response_draft(email.body_text)
                                    email.response_draft = draft

                        session.commit()
                        st.success("Analyse abgeschlossen!")
                        st.rerun()

                # Antwortvorschläge anzeigen
                st.markdown("---")
                st.markdown("**E-Mails mit Antwortvorschlägen**")

                emails_with_drafts = session.query(Email).filter(
                    Email.user_id == user_id,
                    Email.response_draft.isnot(None)
                ).all()

                if emails_with_drafts:
                    for email in emails_with_drafts:
                        with st.expander(f"📧 {email.subject}"):
                            st.markdown("**Original:**")
                            st.caption(email.body_text[:500] if email.body_text else "")

                            st.markdown("**Antwortvorschlag:**")
                            edited_draft = st.text_area(
                                "Bearbeiten",
                                value=email.response_draft,
                                key=f"draft_{email.id}",
                                height=200
                            )

                            col1, col2 = st.columns(2)
                            with col1:
                                if st.button("📤 Als E-Mail senden", key=f"send_draft_{email.id}"):
                                    st.session_state.reply_to = email.from_address
                                    st.session_state.reply_subject = f"Re: {email.subject}"
                                    st.session_state.draft_body = edited_draft
                                    st.switch_page("pages/6_📧_E-Mail.py")

                            with col2:
                                if st.button("🗑️ Vorschlag löschen", key=f"del_draft_{email.id}"):
                                    email.response_draft = None
                                    email.needs_response = False
                                    session.commit()
                                    st.rerun()
                else:
                    st.info("Keine E-Mails mit Antwortvorschlägen")

    with tab_verfuegung:
        st.subheader("📋 Email-Verfügungsverarbeitung")

        st.markdown("""
        Verarbeiten Sie Emails mit Verfügungen automatisch. Emails von autorisierten Absendern
        werden analysiert, Verfügungen extrahiert und Dokumente entsprechend abgelegt.
        """)

        # Einstellungen anzeigen
        with st.expander("⚙️ Einstellungen", expanded=False):
            st.markdown("### Autorisierte Signaturen")
            st.caption("Nur Emails von diesen Absendern werden verarbeitet.")

            # Aktuelle Signaturen
            current_signatures = settings.email_authorized_signatures or []

            # Signaturen anzeigen und bearbeiten
            for i, sig in enumerate(current_signatures):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.text(f"📧 {sig}")
                with col2:
                    if st.button("🗑️", key=f"del_sig_{i}", help="Signatur entfernen"):
                        current_signatures.remove(sig)
                        settings.email_authorized_signatures = current_signatures
                        settings.save()
                        st.rerun()

            # Neue Signatur hinzufügen
            col1, col2 = st.columns([4, 1])
            with col1:
                new_sig = st.text_input(
                    "Neue Signatur",
                    placeholder="email@domain.de oder @domain.de für ganze Domain",
                    key="new_signature_input"
                )
            with col2:
                st.write("")  # Spacing
                if st.button("➕ Hinzufügen", key="add_signature"):
                    if new_sig and new_sig not in current_signatures:
                        current_signatures.append(new_sig)
                        settings.email_authorized_signatures = current_signatures
                        settings.save()
                        st.success(f"Signatur '{new_sig}' hinzugefügt!")
                        st.rerun()

            st.markdown("---")

            st.markdown("### Verfügungsschlüsselwörter")
            st.caption("Schlüsselwörter, die eine Verfügung im Email-Text einleiten.")

            keywords = settings.email_verfuegung_keywords or []
            keywords_text = st.text_area(
                "Schlüsselwörter (eines pro Zeile)",
                value="\n".join(keywords),
                height=150
            )

            st.markdown("---")

            col1, col2 = st.columns(2)
            with col1:
                auto_categorize = st.checkbox(
                    "KI-Kategorisierung aktivieren",
                    value=settings.email_auto_categorize,
                    help="Verwendet ChatGPT zur automatischen Kategorisierung"
                )
                process_attachments = st.checkbox(
                    "Anhänge separat verarbeiten",
                    value=settings.email_process_attachments,
                    help="Speichert Anhänge als separate Dokumente"
                )

            with col2:
                mark_as_read = st.checkbox(
                    "Verarbeitete Emails als gelesen markieren",
                    value=settings.email_mark_as_read
                )
                move_folder = st.text_input(
                    "Emails verschieben nach (IMAP-Ordner)",
                    value=settings.email_move_to_folder,
                    placeholder="z.B. Archiv oder INBOX.Processed"
                )

            if st.button("💾 Einstellungen speichern", type="primary", key="save_verfuegung_settings"):
                settings.email_verfuegung_keywords = [k.strip() for k in keywords_text.split("\n") if k.strip()]
                settings.email_auto_categorize = auto_categorize
                settings.email_process_attachments = process_attachments
                settings.email_mark_as_read = mark_as_read
                settings.email_move_to_folder = move_folder
                settings.save()
                st.success("Einstellungen gespeichert!")

        st.markdown("---")

        # Verfügungsverarbeitung starten
        st.markdown("### 📥 Emails verarbeiten")

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            imap_folder = st.selectbox(
                "IMAP-Ordner",
                options=["INBOX", "INBOX.Neu", "INBOX.Verfuegungen"],
                index=0
            )
        with col2:
            max_emails = st.number_input(
                "Max. Emails",
                min_value=1,
                max_value=100,
                value=20
            )

        # Status
        if not settings.email_authorized_signatures:
            st.warning("⚠️ Keine autorisierten Signaturen konfiguriert. Bitte fügen Sie mindestens eine Signatur hinzu.")

        if st.button("🔄 Emails jetzt verarbeiten", type="primary", disabled=not settings.email_authorized_signatures):
            try:
                from services.email_inbox_service import get_email_inbox_service

                inbox_service = get_email_inbox_service(user_id)

                with st.spinner("Verbinde mit Email-Server..."):
                    # Fortschrittsanzeige
                    progress_bar = st.progress(0, text="Initialisiere...")
                    status_text = st.empty()
                    results_container = st.container()

                    def update_progress(current, total, message):
                        progress_bar.progress(current / total if total > 0 else 0, text=message)
                        status_text.caption(f"{current}/{total}: {message}")

                    # Emails verarbeiten
                    result = inbox_service.process_all_unread(progress_callback=update_progress)

                    progress_bar.progress(1.0, text="✅ Fertig!")

                    # Ergebnisse anzeigen
                    with results_container:
                        if result["processed"] > 0:
                            st.success(f"✅ {result['processed']} Email(s) erfolgreich verarbeitet!")

                            # Verarbeitete Dokumente anzeigen
                            with st.expander(f"📄 Erstellte Dokumente ({len(result['documents'])})", expanded=True):
                                for doc in result["documents"]:
                                    col1, col2 = st.columns([4, 1])
                                    with col1:
                                        st.markdown(f"📄 **{doc['title']}**")
                                        if doc["attachments"] > 0:
                                            st.caption(f"📎 {doc['attachments']} Anhänge")
                                    with col2:
                                        if st.button("Öffnen", key=f"open_doc_{doc['id']}"):
                                            st.session_state.view_document_id = doc["id"]
                                            st.switch_page("pages/3_📁_Dokumente.py")

                        if result["errors"] > 0:
                            st.warning(f"⚠️ {result['errors']} Fehler aufgetreten")
                            with st.expander("Fehlerdetails"):
                                for err in result["error_messages"]:
                                    st.error(err)

                        if result["processed"] == 0 and result["errors"] == 0:
                            st.info("Keine neuen Emails von autorisierten Absendern gefunden.")

            except Exception as e:
                st.error(f"Fehler bei der Email-Verarbeitung: {e}")

        st.markdown("---")

        # Anleitung für Verfügungen
        with st.expander("📖 Anleitung: Verfügungen per Email", expanded=False):
            st.markdown("""
            ### So funktioniert die Email-Verfügungsverarbeitung

            **1. Autorisierte Absender**
            Nur Emails von autorisierten Absendern (Signaturen) werden verarbeitet.
            Standard-Signatur: `meier@ra-rhm.de`

            **2. Verfügungsformat**
            Fügen Sie eine Verfügung in Ihre Email ein:

            ```
            Verfügung:
            Ordner: Verträge
            Kategorie: Vertrag
            Frist: 15.02.2026
            Aktenzeichen: 123/2025
            Notiz: Wichtiger Vertrag zur Prüfung
            ```

            **Unterstützte Felder:**
            - `Ordner:` - Zielordner für das Dokument
            - `Kategorie:` - Dokumentkategorie (Rechnung, Vertrag, etc.)
            - `Frist:` / `Wiedervorlage:` - Fristdatum
            - `Aktenzeichen:` / `Az.:` - Aktenzeichen
            - `Mandant:` / `Kunde:` - Zugehöriger Mandant
            - `Notiz:` - Zusätzliche Anmerkungen

            **3. Ohne Verfügung**
            Wenn keine Verfügung im Text gefunden wird, analysiert ChatGPT
            die Email und kategorisiert sie automatisch.

            **4. Anhänge**
            Anhänge werden separat als Dokumente gespeichert und erhalten
            dieselbe Kategorisierung wie die Email.
            """)
