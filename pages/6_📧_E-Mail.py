"""
E-Mail - Senden, Empfangen, Verfügungen und KI-Antwortvorschläge
"""
import streamlit as st
from pathlib import Path
import sys
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import Email, Document, EmailSignature, EmailDisposition, EmailClassificationRule
from config.settings import get_settings
from services.ai_service import get_ai_service
from services.signature_service import get_signature_service
from services.disposition_service import get_disposition_engine
from services.email_processing_service import get_email_processing_service
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
    # Services initialisieren
    signature_service = get_signature_service(user_id)
    disposition_engine = get_disposition_engine(user_id)
    email_processor = get_email_processing_service(user_id)

    # E-Mail-Tabs
    tab_inbox, tab_compose, tab_dispositions, tab_signatures, tab_rules, tab_sent, tab_response = st.tabs([
        "📥 Posteingang",
        "✏️ Neue E-Mail",
        "📋 Verfügungen",
        "✍️ Signaturen",
        "📐 Regeln",
        "📤 Gesendet",
        "🤖 Antwortvorschläge"
    ])

    with tab_inbox:
        st.subheader("📥 Posteingang")

        # Filter-Optionen
        col_filter1, col_filter2, col_filter3 = st.columns([2, 2, 1])
        with col_filter1:
            filter_type = st.selectbox(
                "Anzeigen",
                ["Alle", "Nur mit Verfügung", "Review erforderlich", "Ungelesen"],
                key="inbox_filter"
            )
        with col_filter2:
            search_query = st.text_input("Suche", placeholder="Betreff, Absender...", key="inbox_search")
        with col_filter3:
            st.write("")  # Spacer
            st.write("")
            if st.button("🔄 Abrufen & Verarbeiten"):
                with st.spinner("Rufe E-Mails ab und verarbeite..."):
                    try:
                        result = email_processor.fetch_and_process_all(max_count=30)
                        st.success(
                            f"✅ {result['fetched']} abgerufen, "
                            f"{result['processed']} verarbeitet, "
                            f"{result['dispositions_found']} Verfügungen"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")

        # E-Mail-Liste
        with get_db() as session:
            from sqlalchemy import or_

            query = session.query(Email).filter(
                Email.user_id == user_id,
                Email.folder == 'inbox'
            )

            # Filter anwenden
            if filter_type == "Nur mit Verfügung":
                query = query.filter(Email.has_disposition == True)
            elif filter_type == "Review erforderlich":
                query = query.filter(Email.needs_review == True)
            elif filter_type == "Ungelesen":
                query = query.filter(Email.is_read == False)

            # Suche anwenden
            if search_query:
                search_pattern = f"%{search_query}%"
                query = query.filter(or_(
                    Email.subject.ilike(search_pattern),
                    Email.from_address.ilike(search_pattern),
                    Email.body_text.ilike(search_pattern)
                ))

            emails = query.order_by(Email.received_at.desc()).limit(50).all()

            if emails:
                for email_item in emails:
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

                    with col1:
                        # Status-Icons
                        icons = []
                        if not email_item.is_read:
                            icons.append("📬")
                        else:
                            icons.append("📭")
                        if getattr(email_item, 'has_disposition', False):
                            icons.append("📋")
                        if getattr(email_item, 'needs_review', False):
                            icons.append("⚠️")
                        if getattr(email_item, 'signature_detected', False):
                            icons.append("✍️")

                        icon_str = " ".join(icons)
                        style = "**" if not email_item.is_read else ""
                        st.markdown(f"{icon_str} {style}{email_item.subject or '(Kein Betreff)'}{style}")
                        st.caption(f"{email_item.from_address}")

                    with col2:
                        # Verfügungs-Typ
                        if getattr(email_item, 'has_disposition', False):
                            disp_type = getattr(email_item, 'disposition_type', '') or ''
                            st.caption(f"📋 {disp_type[:15]}")
                        else:
                            st.caption("")

                    with col3:
                        st.caption(format_date(email_item.received_at, True) if email_item.received_at else "")

                    with col4:
                        if st.button("👁️", key=f"view_email_{email_item.id}"):
                            st.session_state.view_email_id = email_item.id

                    st.divider()
            else:
                st.info("Keine E-Mails gefunden")

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

    # ============================================================
    # TAB: VERFÜGUNGEN
    # ============================================================
    with tab_dispositions:
        st.subheader("📋 Verfügungen")
        st.markdown("Erkannte Verfügungen und Anweisungen aus E-Mails")

        # Filter
        disp_filter = st.selectbox(
            "Status",
            ["Offen", "Erledigt", "Alle"],
            key="disp_filter"
        )

        with get_db() as session:
            query = session.query(EmailDisposition).filter(
                EmailDisposition.user_id == user_id
            )

            if disp_filter == "Offen":
                query = query.filter(EmailDisposition.status == "open")
            elif disp_filter == "Erledigt":
                query = query.filter(EmailDisposition.status == "completed")

            dispositions = query.order_by(EmailDisposition.created_at.desc()).limit(50).all()

            if dispositions:
                for disp in dispositions:
                    # E-Mail-Details laden
                    email_obj = session.get(Email, disp.email_id) if disp.email_id else None

                    with st.container():
                        col1, col2, col3 = st.columns([3, 1, 1])

                        with col1:
                            status_icon = "🟢" if disp.status == "open" else "✅"
                            st.markdown(f"{status_icon} **{disp.trigger_keyword or 'Verfügung'}**")
                            if email_obj:
                                st.caption(f"📧 {email_obj.subject or 'Kein Betreff'}")
                            if disp.raw_text:
                                st.text(disp.raw_text[:200] + "..." if len(disp.raw_text or "") > 200 else disp.raw_text)

                        with col2:
                            if disp.confidence:
                                st.metric("Konfidenz", f"{disp.confidence:.0%}")
                            st.caption(format_date(disp.created_at) if disp.created_at else "")

                        with col3:
                            if disp.status == "open":
                                if st.button("✅ Erledigt", key=f"complete_disp_{disp.id}"):
                                    disposition_engine.complete_disposition(disp.id)
                                    st.rerun()

                        # Aktionen anzeigen
                        if disp.actions:
                            with st.expander("📝 Erkannte Aktionen"):
                                for action in disp.actions:
                                    action_type = action.get("type", "unknown")
                                    if action_type == "move_to_folder":
                                        st.write(f"📁 In Ordner verschieben: **{action.get('target')}**")
                                    elif action_type == "set_deadline":
                                        st.write(f"📅 Frist: **{action.get('date_str') or action.get('date')}**")
                                    elif action_type == "assign_to":
                                        st.write(f"👤 Zuweisen an: **{action.get('person')}**")
                                    elif action_type == "create_task":
                                        st.write(f"✓ Aufgabe: **{action.get('title')}**")
                                    elif action_type == "create_response":
                                        st.write(f"↩️ Antwort erforderlich")

                        st.divider()
            else:
                st.info("Keine Verfügungen gefunden")

    # ============================================================
    # TAB: SIGNATUREN
    # ============================================================
    with tab_signatures:
        st.subheader("✍️ Signatur-Verwaltung")
        st.markdown("Verwalten Sie E-Mail-Signaturen für die automatische Erkennung")

        col_list, col_edit = st.columns([1, 2])

        with col_list:
            st.markdown("**Vorhandene Signaturen**")

            signatures = signature_service.get_all_signatures()

            for sig in signatures:
                icon = "⭐" if sig.get("is_default") else "✍️"
                enabled = "✅" if sig.get("is_enabled") else "❌"
                if st.button(
                    f"{icon} {sig['name']} {enabled}",
                    key=f"sig_{sig['id']}",
                    use_container_width=True
                ):
                    st.session_state.edit_signature_id = sig['id']

            st.divider()
            if st.button("➕ Neue Signatur", use_container_width=True):
                st.session_state.edit_signature_id = "new"

        with col_edit:
            edit_id = st.session_state.get('edit_signature_id')

            if edit_id == "new":
                st.markdown("### Neue Signatur erstellen")

                sig_name = st.text_input("Name", placeholder="z.B. Kanzlei Standard")
                sig_email = st.text_input("E-Mail-Adresse", placeholder="z.B. meier@ra-rhm.de")
                sig_is_default = st.checkbox("Als Standard-Signatur setzen")

                st.markdown("**Erkennungs-Muster**")
                st.caption("Texte, die in der Signatur vorkommen")

                pattern_text = st.text_area(
                    "Muster (eines pro Zeile)",
                    placeholder="Mit freundlichen Grüßen\nRechtsanwalt Meier\nra-rhm.de",
                    height=100
                )

                if st.button("💾 Speichern", type="primary"):
                    if sig_name and sig_email:
                        patterns = []
                        for line in pattern_text.strip().split("\n"):
                            if line.strip():
                                patterns.append({
                                    "type": "contains",
                                    "value": line.strip(),
                                    "weight": 1.0
                                })
                        # E-Mail-Adresse als Pattern hinzufügen
                        patterns.append({
                            "type": "email",
                            "value": sig_email,
                            "weight": 2.0
                        })

                        signature_service.create_signature(
                            name=sig_name,
                            email_address=sig_email,
                            patterns=patterns,
                            is_default=sig_is_default
                        )
                        st.success("✅ Signatur erstellt!")
                        del st.session_state.edit_signature_id
                        st.rerun()
                    else:
                        st.error("Bitte Name und E-Mail-Adresse eingeben")

            elif edit_id:
                sig = signature_service.get_signature(edit_id)
                if sig:
                    st.markdown(f"### {sig['name']} bearbeiten")

                    sig_name = st.text_input("Name", value=sig['name'])
                    sig_email = st.text_input("E-Mail-Adresse", value=sig.get('email_address', ''))
                    sig_is_default = st.checkbox("Standard-Signatur", value=sig.get('is_default', False))
                    sig_enabled = st.checkbox("Aktiv", value=sig.get('is_enabled', True))

                    st.markdown("**Statistik**")
                    st.write(f"Erkannt: {sig.get('times_detected', 0)} mal")
                    if sig.get('last_detected_at'):
                        st.write(f"Zuletzt: {format_date(sig['last_detected_at'])}")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("💾 Speichern", type="primary"):
                            signature_service.update_signature(
                                edit_id,
                                name=sig_name,
                                email_address=sig_email,
                                is_default=sig_is_default,
                                is_enabled=sig_enabled
                            )
                            st.success("✅ Gespeichert!")
                            st.rerun()
                    with col2:
                        if st.button("🗑️ Löschen"):
                            signature_service.delete_signature(edit_id)
                            del st.session_state.edit_signature_id
                            st.rerun()
                    with col3:
                        if st.button("Abbrechen"):
                            del st.session_state.edit_signature_id
                            st.rerun()
            else:
                st.info("Wählen Sie eine Signatur aus oder erstellen Sie eine neue")

    # ============================================================
    # TAB: KLASSIFIKATIONSREGELN
    # ============================================================
    with tab_rules:
        st.subheader("📐 E-Mail-Klassifikationsregeln")
        st.markdown("Regeln für automatische Ordner-Zuweisung und Tags")

        col_rules, col_edit = st.columns([1, 2])

        with col_rules:
            st.markdown("**Vorhandene Regeln**")

            with get_db() as session:
                rules = session.query(EmailClassificationRule).filter(
                    EmailClassificationRule.user_id == user_id
                ).order_by(EmailClassificationRule.priority.desc()).all()

                for rule in rules:
                    enabled = "✅" if rule.is_enabled else "❌"
                    if st.button(
                        f"{enabled} {rule.name} (P:{rule.priority})",
                        key=f"rule_{rule.id}",
                        use_container_width=True
                    ):
                        st.session_state.edit_rule_id = rule.id

            st.divider()
            if st.button("➕ Neue Regel", use_container_width=True):
                st.session_state.edit_rule_id = "new"

        with col_edit:
            edit_rule_id = st.session_state.get('edit_rule_id')

            if edit_rule_id == "new":
                st.markdown("### Neue Regel erstellen")

                rule_name = st.text_input("Regelname", placeholder="z.B. Telekom-Rechnungen")
                rule_priority = st.slider("Priorität", 1, 100, 50)

                st.markdown("**Bedingungen**")
                cond_field = st.selectbox("Feld", ["from_address", "subject", "body"])
                cond_op = st.selectbox("Operator", ["contains", "equals", "startswith", "regex"])
                cond_value = st.text_input("Wert", placeholder="z.B. @telekom.de")

                st.markdown("**Aktionen**")
                target_folder = st.text_input("Ziel-Ordner", placeholder="z.B. Rechnungen/Telekom")
                assign_tags = st.text_input("Tags (kommagetrennt)", placeholder="telekom, rechnung")

                if st.button("💾 Regel erstellen", type="primary"):
                    if rule_name and cond_value:
                        with get_db() as session:
                            new_rule = EmailClassificationRule(
                                user_id=user_id,
                                name=rule_name,
                                priority=rule_priority,
                                conditions={
                                    "operator": "AND",
                                    "conditions": [{
                                        "field": cond_field,
                                        "op": cond_op,
                                        "value": cond_value
                                    }]
                                },
                                target_folder_path=target_folder,
                                assign_tags=[t.strip() for t in assign_tags.split(",") if t.strip()] if assign_tags else None,
                                is_enabled=True
                            )
                            session.add(new_rule)
                            session.commit()
                        st.success("✅ Regel erstellt!")
                        del st.session_state.edit_rule_id
                        st.rerun()
                    else:
                        st.error("Bitte Name und Bedingung eingeben")

            elif edit_rule_id:
                with get_db() as session:
                    rule = session.get(EmailClassificationRule, edit_rule_id)
                    if rule:
                        st.markdown(f"### {rule.name} bearbeiten")

                        st.write(f"**Priorität:** {rule.priority}")
                        st.write(f"**Ziel-Ordner:** {rule.target_folder_path or '-'}")
                        st.write(f"**Tags:** {', '.join(rule.assign_tags or [])}")
                        st.write(f"**Angewandt:** {rule.times_applied or 0} mal")

                        col1, col2 = st.columns(2)
                        with col1:
                            new_enabled = st.checkbox("Aktiv", value=rule.is_enabled)
                            if new_enabled != rule.is_enabled:
                                rule.is_enabled = new_enabled
                                session.commit()
                                st.rerun()
                        with col2:
                            if st.button("🗑️ Löschen"):
                                session.delete(rule)
                                session.commit()
                                del st.session_state.edit_rule_id
                                st.rerun()
            else:
                st.info("Wählen Sie eine Regel aus oder erstellen Sie eine neue")

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
