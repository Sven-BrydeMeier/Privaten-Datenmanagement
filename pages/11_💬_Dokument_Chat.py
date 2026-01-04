"""
Dokument-Chat
KI-gestützte Konversation über Dokumentinhalte mit Aktions-Vorschlägen
"""
import streamlit as st
from datetime import datetime
import re

from utils.components import render_sidebar_cart, apply_custom_css
from services.document_chat_service import (
    get_document_chat_service,
    get_document_action_service,
    DocumentChatService
)
from database.db import get_current_user_id, get_db
from database.models import Document, Folder, SmartFolder
from config.settings import DOCUMENT_CATEGORIES

# Seitenkonfiguration
st.set_page_config(
    page_title="Dokument-Chat",
    page_icon="💬",
    layout="wide"
)

apply_custom_css()
render_sidebar_cart()

st.title("💬 Dokument-Chat")
st.caption("Stellen Sie Fragen zu Ihren Dokumenten und erhalten Sie KI-gestützte Antworten")

user_id = get_current_user_id()
chat_service = get_document_chat_service()

# Session State initialisieren
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'selected_doc_id' not in st.session_state:
    st.session_state.selected_doc_id = None
if 'chat_scope' not in st.session_state:
    st.session_state.chat_scope = "single"
if 'chat_scope_ids' not in st.session_state:
    st.session_state.chat_scope_ids = []
if 'compare_docs' not in st.session_state:
    st.session_state.compare_docs = []
if 'pending_action' not in st.session_state:
    st.session_state.pending_action = None
if 'generated_letter' not in st.session_state:
    st.session_state.generated_letter = None


def parse_action_from_response(response: str):
    """Erkennt Aktions-Vorschläge in der KI-Antwort"""
    # Suche nach [AKTION:typ] Markierung
    pattern = r'\[AKTION:(\w+)\]'
    match = re.search(pattern, response)

    if match:
        action_type = match.group(1)
        if action_type in DocumentChatService.ACTION_TYPES:
            action_info = DocumentChatService.ACTION_TYPES[action_type]
            return {
                "type": action_type,
                "template_name": action_info["template"],
                "label": action_info["label"],
                "icon": action_info["icon"]
            }

    # Fallback: Keyword-basierte Erkennung
    response_lower = response.lower()
    for action_type, action_info in DocumentChatService.ACTION_TYPES.items():
        for keyword in action_info["keywords"]:
            if keyword in response_lower and ("möchten" in response_lower or "soll ich" in response_lower):
                return {
                    "type": action_type,
                    "template_name": action_info["template"],
                    "label": action_info["label"],
                    "icon": action_info["icon"]
                }

    return None


def clean_response_text(response: str) -> str:
    """Entfernt Aktions-Marker aus der Antwort für die Anzeige"""
    return re.sub(r'\s*\[AKTION:\w+\]\s*', '', response).strip()

# Sidebar: Bereichsauswahl
with st.sidebar:
    st.subheader("🎯 Chat-Bereich")

    # Bereichsauswahl
    scope_options = {
        "single": "📄 Einzelnes Dokument",
        "folder": "📁 Ordner",
        "category": "🏷️ Kategorie",
        "smart_folder": "🔍 Intelligenter Ordner",
        "all": "🗄️ Alle Dokumente"
    }

    selected_scope = st.radio(
        "Womit möchten Sie chatten?",
        options=list(scope_options.keys()),
        format_func=lambda x: scope_options[x],
        key="scope_radio"
    )

    if selected_scope != st.session_state.chat_scope:
        st.session_state.chat_scope = selected_scope
        st.session_state.chat_history = []  # Chat zurücksetzen bei Änderung
        st.session_state.chat_scope_ids = []

    st.divider()

    # Dokumente/Ordner basierend auf Bereich laden
    with get_db() as session:
        if selected_scope == "single":
            # Einzelnes Dokument
            st.subheader("📄 Dokument auswählen")

            # Dokumentsuche
            search_query = st.text_input("🔍 Suchen", placeholder="Titel, Absender...")

            query = session.query(Document).filter(
                Document.user_id == user_id,
                Document.is_deleted == False
            )

            if search_query:
                from sqlalchemy import or_
                search_pattern = f"%{search_query}%"
                query = query.filter(
                    or_(
                        Document.title.ilike(search_pattern),
                        Document.filename.ilike(search_pattern),
                        Document.sender.ilike(search_pattern)
                    )
                )

            documents = query.order_by(Document.created_at.desc()).limit(50).all()
            doc_options = {doc.id: f"{doc.title or doc.filename[:30]}..." for doc in documents}

            if doc_options:
                selected_id = st.selectbox(
                    "Dokument wählen",
                    options=list(doc_options.keys()),
                    format_func=lambda x: doc_options[x],
                    key="doc_selector"
                )

                if selected_id != st.session_state.selected_doc_id:
                    st.session_state.selected_doc_id = selected_id
                    st.session_state.chat_scope_ids = [selected_id]
                    st.session_state.chat_history = []
            else:
                st.info("Keine Dokumente gefunden")

        elif selected_scope == "folder":
            # Ordner
            st.subheader("📁 Ordner auswählen")

            folders = session.query(Folder).filter(
                Folder.user_id == user_id
            ).order_by(Folder.name).all()

            folder_options = {f.id: f"📁 {f.name}" for f in folders}

            if folder_options:
                selected_folder = st.selectbox(
                    "Ordner wählen",
                    options=list(folder_options.keys()),
                    format_func=lambda x: folder_options[x],
                    key="folder_selector"
                )

                # Dokumente im Ordner zählen
                folder_docs = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.folder_id == selected_folder,
                    Document.is_deleted == False
                ).all()

                doc_ids = [d.id for d in folder_docs]
                st.session_state.chat_scope_ids = doc_ids
                st.caption(f"📊 {len(doc_ids)} Dokumente im Ordner")
            else:
                st.info("Keine Ordner vorhanden")

        elif selected_scope == "category":
            # Kategorie
            st.subheader("🏷️ Kategorie auswählen")

            selected_cat = st.selectbox(
                "Kategorie wählen",
                options=DOCUMENT_CATEGORIES,
                key="cat_selector"
            )

            cat_docs = session.query(Document).filter(
                Document.user_id == user_id,
                Document.category == selected_cat,
                Document.is_deleted == False
            ).all()

            doc_ids = [d.id for d in cat_docs]
            st.session_state.chat_scope_ids = doc_ids
            st.caption(f"📊 {len(doc_ids)} Dokumente in dieser Kategorie")

        elif selected_scope == "smart_folder":
            # Intelligenter Ordner
            st.subheader("🔍 Intelligenter Ordner")

            smart_folders = session.query(SmartFolder).filter(
                SmartFolder.user_id == user_id
            ).all()

            sf_data = [{"id": sf.id, "name": sf.name, "rules": sf.filter_rules} for sf in smart_folders]

            if sf_data:
                sf_options = {sf["id"]: sf["name"] for sf in sf_data}
                selected_sf = st.selectbox(
                    "Ordner wählen",
                    options=list(sf_options.keys()),
                    format_func=lambda x: sf_options[x],
                    key="sf_selector"
                )

                # Dokumente basierend auf Regeln laden
                selected_rules = next((sf["rules"] for sf in sf_data if sf["id"] == selected_sf), {})

                from sqlalchemy import or_
                query = session.query(Document).filter(
                    Document.user_id == user_id,
                    Document.is_deleted == False
                )

                if selected_rules.get("mode") == "manual":
                    manual_ids = selected_rules.get("manual_docs", [])
                    if manual_ids:
                        query = query.filter(Document.id.in_(manual_ids))
                    else:
                        query = query.filter(False)  # Keine Dokumente
                elif selected_rules.get("search_text"):
                    pattern = f"%{selected_rules['search_text']}%"
                    query = query.filter(
                        or_(
                            Document.title.ilike(pattern),
                            Document.filename.ilike(pattern),
                            Document.sender.ilike(pattern),
                            Document.ocr_text.ilike(pattern)
                        )
                    )

                sf_docs = query.all()
                doc_ids = [d.id for d in sf_docs]
                st.session_state.chat_scope_ids = doc_ids
                st.caption(f"📊 {len(doc_ids)} Dokumente im Ordner")
            else:
                st.info("Keine intelligenten Ordner vorhanden")

        elif selected_scope == "all":
            # Alle Dokumente
            st.subheader("🗄️ Alle Dokumente")

            all_docs = session.query(Document).filter(
                Document.user_id == user_id,
                Document.is_deleted == False
            ).all()

            doc_ids = [d.id for d in all_docs]
            st.session_state.chat_scope_ids = doc_ids
            st.caption(f"📊 Chat mit {len(doc_ids)} Dokumenten")
            st.warning("⚠️ Bei vielen Dokumenten kann die Antwort länger dauern")

    # Schnellaktionen (nur bei Einzeldokument oder wenn IDs vorhanden)
    if st.session_state.chat_scope_ids:
        st.divider()
        st.write("**⚡ Schnellaktionen:**")

        col1, col2 = st.columns(2)

        # Für Einzeldokument: spezifische Aktionen
        if selected_scope == "single" and st.session_state.selected_doc_id:
            with col1:
                if st.button("📝 Zusammenfassung", use_container_width=True):
                    with st.spinner("Erstelle Zusammenfassung..."):
                        result = chat_service.get_quick_summary(st.session_state.selected_doc_id, user_id)
                        if result.get("success"):
                            st.session_state.chat_history = result["conversation"]
                            st.rerun()
                        else:
                            st.error(result.get("error"))

            with col2:
                if st.button("✅ Aktionen", use_container_width=True):
                    with st.spinner("Analysiere Handlungsbedarf..."):
                        result = chat_service.extract_action_items(st.session_state.selected_doc_id, user_id)
                        if result.get("success"):
                            st.session_state.chat_history = result["conversation"]
                            st.rerun()
                        else:
                            st.error(result.get("error"))

            # Direkte Aktions-Buttons
            st.divider()
            st.write("**✉️ Schreiben erstellen:**")

            act_col1, act_col2 = st.columns(2)
            with act_col1:
                if st.button("📝 Kündigung", use_container_width=True, help="Kündigungsschreiben vorbereiten"):
                    st.session_state.pending_action = {
                        "type": "cancellation",
                        "doc_id": st.session_state.selected_doc_id
                    }
                    st.rerun()
            with act_col2:
                if st.button("⚖️ Widerspruch", use_container_width=True, help="Widerspruchsschreiben erstellen"):
                    st.session_state.pending_action = {
                        "type": "objection",
                        "doc_id": st.session_state.selected_doc_id
                    }
                    st.rerun()

            act_col3, act_col4 = st.columns(2)
            with act_col3:
                if st.button("📋 Reklamation", use_container_width=True, help="Reklamation verfassen"):
                    st.session_state.pending_action = {
                        "type": "complaint",
                        "doc_id": st.session_state.selected_doc_id
                    }
                    st.rerun()
            with act_col4:
                if st.button("🏦 SEPA-Widerruf", use_container_width=True, help="Lastschrift widerrufen"):
                    st.session_state.pending_action = {
                        "type": "sepa_revoke",
                        "doc_id": st.session_state.selected_doc_id
                    }
                    st.rerun()

# Hauptbereich: Chat
if st.session_state.chat_scope_ids:
    scope = st.session_state.chat_scope
    scope_ids = st.session_state.chat_scope_ids

    # Bereichsinfo anzeigen
    with get_db() as session:
        if scope == "single" and st.session_state.selected_doc_id:
            doc = session.query(Document).filter_by(id=st.session_state.selected_doc_id).first()
            if doc:
                st.info(f"📄 **Aktives Dokument:** {doc.title or doc.filename}")
                col_info1, col_info2, col_info3 = st.columns(3)
                with col_info1:
                    st.caption(f"Absender: {doc.sender or '-'}")
                with col_info2:
                    st.caption(f"Datum: {doc.document_date.strftime('%d.%m.%Y') if doc.document_date else '-'}")
                with col_info3:
                    st.caption(f"Kategorie: {doc.category or '-'}")
        else:
            # Multi-Dokument-Anzeige
            scope_labels = {
                "folder": "📁 Ordner",
                "category": "🏷️ Kategorie",
                "smart_folder": "🔍 Intelligenter Ordner",
                "all": "🗄️ Gesamte Datenbank"
            }
            st.info(f"**{scope_labels.get(scope, 'Dokumente')}:** {len(scope_ids)} Dokumente ausgewählt")

            # Zeige Liste der Dokumente (max 5)
            with st.expander(f"📄 Enthaltene Dokumente ({len(scope_ids)})"):
                docs = session.query(Document).filter(Document.id.in_(scope_ids[:20])).all()
                for d in docs[:20]:
                    st.caption(f"• {d.title or d.filename} ({d.sender or '—'})")
                if len(scope_ids) > 20:
                    st.caption(f"... und {len(scope_ids) - 20} weitere")

    st.divider()

    # Chat-Verlauf anzeigen
    chat_container = st.container()

    with chat_container:
        if not st.session_state.chat_history:
            if scope == "single":
                st.markdown("""
                **💡 Beispielfragen für Einzeldokument:**
                - *"Was ist der Hauptinhalt dieses Dokuments?"*
                - *"Gibt es wichtige Fristen, die ich beachten muss?"*
                - *"Welcher Betrag wird genannt?"*
                """)
            else:
                st.markdown("""
                **💡 Beispielfragen für mehrere Dokumente:**
                - *"Welche Dokumente sind am wichtigsten?"*
                - *"Gibt es offene Rechnungen?"*
                - *"Fasse alle Dokumente zusammen."*
                - *"Welche Fristen muss ich beachten?"*
                - *"Suche alle Erwähnungen von [Begriff]."*
                """)
        else:
            for i, msg in enumerate(st.session_state.chat_history):
                if msg["role"] == "user":
                    st.markdown(f"**🧑 Sie:** {msg['content']}")
                else:
                    # Prüfen ob Aktions-Vorschlag in der Antwort
                    action = parse_action_from_response(msg['content'])
                    display_text = clean_response_text(msg['content'])

                    st.markdown(f"**🤖 Assistent:** {display_text}")

                    # Aktions-Button anzeigen wenn Aktion erkannt wurde
                    # Nur beim letzten Assistenten-Nachricht
                    if action and i == len(st.session_state.chat_history) - 1:
                        st.markdown("---")
                        action_col1, action_col2, action_col3 = st.columns([2, 1, 1])

                        with action_col1:
                            st.info(f"{action['icon']} **Vorgeschlagene Aktion:** {action['label']}")

                        with action_col2:
                            if st.button(f"✅ {action['label']}", type="primary", key=f"action_btn_{i}"):
                                st.session_state.pending_action = {
                                    "type": action["type"],
                                    "doc_id": st.session_state.selected_doc_id
                                }
                                st.rerun()

                        with action_col3:
                            if st.button("❌ Nein danke", key=f"dismiss_action_{i}"):
                                # Aktion ablehnen, weiter chatten
                                pass

                st.write("")

    # Vergleichsergebnis anzeigen
    if st.session_state.get("comparison_result"):
        st.divider()
        st.subheader("📊 Dokumentenvergleich")
        st.markdown(st.session_state.comparison_result)

        if st.button("Vergleich schließen"):
            del st.session_state.comparison_result
            st.rerun()

    st.divider()

    # Chat-Eingabe
    input_label = "Ihre Frage:" if scope != "single" else "Ihre Frage zum Dokument:"
    input_placeholder = "z.B. Fasse alle Dokumente zusammen" if scope != "single" else "z.B. Was sind die wichtigsten Punkte?"

    user_input = st.text_input(
        input_label,
        placeholder=input_placeholder,
        key="chat_input"
    )

    col_send, col_clear = st.columns([3, 1])

    with col_send:
        if st.button("📤 Senden", type="primary", use_container_width=True, disabled=not user_input):
            if user_input:
                with st.spinner("Analysiere..." if scope == "single" else f"Analysiere {len(scope_ids)} Dokumente..."):
                    # Für Multi-Dokument: document_ids übergeben
                    if scope == "single":
                        result = chat_service.chat(
                            document_id=st.session_state.selected_doc_id,
                            user_id=user_id,
                            message=user_input,
                            conversation_history=st.session_state.chat_history
                        )
                    else:
                        # Multi-Dokument Chat
                        result = chat_service.chat_multi(
                            document_ids=scope_ids,
                            user_id=user_id,
                            message=user_input,
                            conversation_history=st.session_state.chat_history
                        )

                    if result.get("success"):
                        st.session_state.chat_history = result["conversation"]
                        st.rerun()
                    else:
                        st.error(f"❌ {result.get('error')}")

    with col_clear:
        if st.button("🗑️ Chat leeren", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()

    # Vorgeschlagene Fragen
    st.divider()
    st.caption("**Vorgeschlagene Fragen:**")

    col1, col2, col3 = st.columns(3)

    # Angepasste Fragen je nach Scope
    if scope == "single":
        q1 = ("💰 Welcher Betrag?", "Welche Beträge oder Summen werden in diesem Dokument genannt?")
        q2 = ("📅 Welche Fristen?", "Welche Fristen oder wichtigen Termine werden genannt?")
        q3 = ("📞 Kontaktdaten?", "Welche Kontaktdaten (Telefon, E-Mail, Adresse) werden im Dokument genannt?")
    else:
        q1 = ("📊 Übersicht", "Gib mir eine kurze Übersicht über alle Dokumente.")
        q2 = ("💰 Offene Beträge", "Welche offenen Beträge oder Rechnungen gibt es?")
        q3 = ("📅 Fristen", "Welche wichtigen Fristen oder Termine muss ich beachten?")

    with col1:
        if st.button(q1[0], use_container_width=True):
            with st.spinner("..."):
                if scope == "single":
                    result = chat_service.chat(
                        st.session_state.selected_doc_id, user_id, q1[1],
                        st.session_state.chat_history
                    )
                else:
                    result = chat_service.chat_multi(
                        scope_ids, user_id, q1[1],
                        st.session_state.chat_history
                    )
                if result.get("success"):
                    st.session_state.chat_history = result["conversation"]
                    st.rerun()

    with col2:
        if st.button(q2[0], use_container_width=True):
            with st.spinner("..."):
                if scope == "single":
                    result = chat_service.chat(
                        st.session_state.selected_doc_id, user_id, q2[1],
                        st.session_state.chat_history
                    )
                else:
                    result = chat_service.chat_multi(
                        scope_ids, user_id, q2[1],
                        st.session_state.chat_history
                    )
                if result.get("success"):
                    st.session_state.chat_history = result["conversation"]
                    st.rerun()

    with col3:
        if st.button(q3[0], use_container_width=True):
            with st.spinner("..."):
                if scope == "single":
                    result = chat_service.chat(
                        st.session_state.selected_doc_id, user_id, q3[1],
                        st.session_state.chat_history
                    )
                else:
                    result = chat_service.chat_multi(
                        scope_ids, user_id, q3[1],
                        st.session_state.chat_history
                    )
                if result.get("success"):
                    st.session_state.chat_history = result["conversation"]
                    st.rerun()

else:
    st.info("👈 Bitte wählen Sie einen Bereich und Dokumente aus der Seitenleiste aus.")

# ============================================================
# HANDLER FÜR AKTIONS-AUSFÜHRUNG (Kündigung, Widerspruch, etc.)
# ============================================================
if st.session_state.pending_action:
    action = st.session_state.pending_action
    action_type = action["type"]
    doc_id = action["doc_id"]

    action_service = get_document_action_service(user_id)
    action_info = DocumentChatService.ACTION_TYPES.get(action_type, {})

    st.divider()
    st.subheader(f"{action_info.get('icon', '📝')} {action_info.get('label', 'Aktion ausführen')}")

    # Benutzerdaten-Formular anzeigen
    with st.expander("📋 Ihre Absenderdaten (für das Schreiben)", expanded=True):
        col_abs1, col_abs2 = st.columns(2)

        with col_abs1:
            absender_name = st.text_input("Ihr Name", key="letter_absender_name")
            absender_adresse = st.text_input("Ihre Straße", key="letter_absender_adresse")

        with col_abs2:
            absender_plz = st.text_input("PLZ", key="letter_absender_plz")
            absender_ort = st.text_input("Ort", key="letter_absender_ort")

    col_gen, col_cancel = st.columns(2)

    with col_gen:
        if st.button("📝 Schreiben generieren", type="primary", use_container_width=True):
            user_data = {
                "absender_name": absender_name,
                "absender_adresse": absender_adresse,
                "absender_plz": absender_plz,
                "absender_ort": absender_ort
            }

            with st.spinner("Generiere Schreiben..."):
                result = action_service.generate_letter(doc_id, action_type, user_data)

                if result.get("success"):
                    st.session_state.generated_letter = result
                    st.rerun()
                else:
                    st.error(f"❌ Fehler: {result.get('error')}")

    with col_cancel:
        if st.button("❌ Abbrechen", use_container_width=True):
            st.session_state.pending_action = None
            st.rerun()

# ============================================================
# ANZEIGE DES GENERIERTEN SCHREIBENS
# ============================================================
if st.session_state.generated_letter:
    letter = st.session_state.generated_letter

    st.divider()
    st.subheader(f"📄 {letter.get('action_label', 'Schreiben')}")

    # Info zu fehlenden Feldern
    if letter.get("missing_fields"):
        st.warning("⚠️ Einige Felder sind noch nicht ausgefüllt. Bitte ergänzen Sie diese im Text.")
        with st.expander("Fehlende Felder anzeigen"):
            for field in letter["missing_fields"]:
                st.caption(f"• {field['label']} (`{{{{{field['key']}}}}}`)")

    # Schreiben anzeigen und bearbeiten
    letter_content = st.text_area(
        "Schreiben (bearbeitbar)",
        value=letter["letter_content"],
        height=400,
        key="letter_edit_area"
    )

    # Aktionen für das Schreiben
    st.markdown("---")
    st.subheader("📤 Schreiben versenden")

    action_col1, action_col2, action_col3, action_col4 = st.columns(4)

    with action_col1:
        # Download als TXT
        st.download_button(
            "⬇️ Als Text speichern",
            data=letter_content,
            file_name=f"{letter.get('template_name', 'Schreiben').replace(' ', '_')}.txt",
            mime="text/plain",
            use_container_width=True
        )

    with action_col2:
        # Per E-Mail senden
        if st.button("📧 Per E-Mail senden", use_container_width=True):
            st.session_state.show_email_dialog = True
            st.rerun()

    with action_col3:
        # In Dokumente speichern
        if st.button("💾 Als Dokument speichern", use_container_width=True):
            # Hier könnte man das Schreiben als neues Dokument speichern
            st.info("Diese Funktion wird noch implementiert.")

    with action_col4:
        # Schließen
        if st.button("✖️ Schließen", use_container_width=True):
            st.session_state.generated_letter = None
            st.session_state.pending_action = None
            st.rerun()

    # E-Mail Dialog
    if st.session_state.get("show_email_dialog"):
        st.divider()
        st.subheader("📧 E-Mail versenden")

        email_to = st.text_input("Empfänger E-Mail", key="email_to")
        email_subject = st.text_input(
            "Betreff",
            value=letter.get('action_label', 'Anfrage'),
            key="email_subject"
        )

        email_col1, email_col2 = st.columns(2)

        with email_col1:
            if st.button("📤 Senden", type="primary", use_container_width=True):
                if email_to:
                    try:
                        from utils.helpers import send_email
                        from config.settings import get_settings

                        settings = get_settings()

                        if settings.smtp_server and settings.smtp_username:
                            success = send_email(
                                to_email=email_to,
                                subject=email_subject,
                                body=letter_content,
                                from_email=settings.smtp_username
                            )

                            if success:
                                st.success("✅ E-Mail erfolgreich gesendet!")
                                st.session_state.show_email_dialog = False
                            else:
                                st.error("❌ E-Mail konnte nicht gesendet werden.")
                        else:
                            st.warning("⚠️ SMTP nicht konfiguriert. Bitte in Einstellungen einrichten.")
                    except Exception as e:
                        st.error(f"❌ Fehler: {str(e)}")
                else:
                    st.warning("Bitte Empfänger-E-Mail eingeben.")

        with email_col2:
            if st.button("❌ Abbrechen", key="cancel_email", use_container_width=True):
                st.session_state.show_email_dialog = False
                st.rerun()

# Hinweis zur KI
st.divider()
st.caption(
    "💡 Die Antworten werden von einer KI generiert und können ungenau sein. "
    "Überprüfen Sie wichtige Informationen immer im Originaldokument."
)
