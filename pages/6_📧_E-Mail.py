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

st.set_page_config(page_title="E-Mail", page_icon="📧", layout="wide")
init_db()

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
    tab_inbox, tab_compose, tab_sent, tab_response = st.tabs([
        "📥 Posteingang",
        "✏️ Neue E-Mail",
        "📤 Gesendet",
        "🤖 Antwortvorschläge"
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
                email = session.query(Email).get(st.session_state.view_email_id)
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

        # Dokumente aus Warenkorb anhängen
        cart_items = st.session_state.get('active_cart_items', [])
        if cart_items:
            st.info(f"📎 {len(cart_items)} Dokumente aus Warenkorb können angehängt werden")
            attach_cart = st.checkbox("Warenkorb-Dokumente anhängen")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📤 Senden", type="primary") and to_address and subject:
                attachment_data = []

                # Hochgeladene Anhänge
                for att in attachments:
                    attachment_data.append((att.name, att.read()))

                # Warenkorb-Dokumente
                if cart_items and 'attach_cart' in dir() and attach_cart:
                    from services.encryption import get_encryption_service
                    encryption = get_encryption_service()

                    with get_db() as session:
                        for doc_id in cart_items:
                            doc = session.query(Document).get(doc_id)
                            if doc and doc.file_path:
                                try:
                                    with open(doc.file_path, 'rb') as f:
                                        encrypted = f.read()
                                    decrypted = encryption.decrypt_file(encrypted, doc.encryption_iv, doc.filename)
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
