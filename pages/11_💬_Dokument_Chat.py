"""
Dokument-Chat
KI-gestützte Konversation über Dokumentinhalte
"""
import streamlit as st
from datetime import datetime

from utils.components import render_sidebar_cart, apply_custom_css
from services.document_chat_service import get_document_chat_service
from database.db import get_current_user_id, get_db
from database.models import Document

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
if 'compare_docs' not in st.session_state:
    st.session_state.compare_docs = []

# Sidebar: Dokumentauswahl
with st.sidebar:
    st.subheader("📄 Dokument auswählen")

    # Dokumente laden
    with get_db() as session:
        documents = session.query(Document).filter(
            Document.user_id == user_id,
            Document.is_deleted == False
        ).order_by(Document.created_at.desc()).limit(50).all()

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
            st.session_state.chat_history = []  # Chat zurücksetzen bei neuem Dokument

        # Schnellaktionen
        st.divider()
        st.write("**⚡ Schnellaktionen:**")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("📝 Zusammenfassung", use_container_width=True):
                with st.spinner("Erstelle Zusammenfassung..."):
                    result = chat_service.get_quick_summary(selected_id, user_id)
                    if result.get("success"):
                        st.session_state.chat_history = result["conversation"]
                        st.rerun()
                    else:
                        st.error(result.get("error"))

        with col2:
            if st.button("✅ Aktionen", use_container_width=True):
                with st.spinner("Analysiere Handlungsbedarf..."):
                    result = chat_service.extract_action_items(selected_id, user_id)
                    if result.get("success"):
                        st.session_state.chat_history = result["conversation"]
                        st.rerun()
                    else:
                        st.error(result.get("error"))

        # Vergleichsmodus
        st.divider()
        st.write("**🔍 Dokumente vergleichen:**")

        compare_options = st.multiselect(
            "Dokumente zum Vergleichen",
            options=list(doc_options.keys()),
            format_func=lambda x: doc_options[x],
            max_selections=3,
            key="compare_selector"
        )

        if len(compare_options) >= 2:
            if st.button("📊 Vergleichen", use_container_width=True):
                with st.spinner("Vergleiche Dokumente..."):
                    result = chat_service.compare_documents(compare_options, user_id)
                    if result.get("success"):
                        st.session_state.comparison_result = result["response"]
                        st.rerun()
                    else:
                        st.error(result.get("error"))
    else:
        st.info("Keine Dokumente vorhanden. Laden Sie zuerst Dokumente hoch.")

# Hauptbereich: Chat
if st.session_state.selected_doc_id:
    # Dokumentinfo anzeigen
    with get_db() as session:
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

    st.divider()

    # Chat-Verlauf anzeigen
    chat_container = st.container()

    with chat_container:
        if not st.session_state.chat_history:
            st.markdown("""
            **💡 Beispielfragen:**
            - *"Was ist der Hauptinhalt dieses Dokuments?"*
            - *"Gibt es wichtige Fristen, die ich beachten muss?"*
            - *"Welcher Betrag wird genannt?"*
            - *"Wer ist der Absender und was will er von mir?"*
            - *"Erkläre mir die wichtigsten Punkte in einfachen Worten."*
            """)
        else:
            for msg in st.session_state.chat_history:
                if msg["role"] == "user":
                    st.markdown(f"**🧑 Sie:** {msg['content']}")
                else:
                    st.markdown(f"**🤖 Assistent:** {msg['content']}")
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
    user_input = st.text_input(
        "Ihre Frage zum Dokument:",
        placeholder="z.B. Was sind die wichtigsten Punkte?",
        key="chat_input"
    )

    col_send, col_clear = st.columns([3, 1])

    with col_send:
        if st.button("📤 Senden", type="primary", use_container_width=True, disabled=not user_input):
            if user_input:
                with st.spinner("Analysiere..."):
                    result = chat_service.chat(
                        document_id=st.session_state.selected_doc_id,
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

    with col1:
        if st.button("💰 Welcher Betrag?", use_container_width=True):
            with st.spinner("..."):
                result = chat_service.chat(
                    st.session_state.selected_doc_id,
                    user_id,
                    "Welche Beträge oder Summen werden in diesem Dokument genannt?",
                    st.session_state.chat_history
                )
                if result.get("success"):
                    st.session_state.chat_history = result["conversation"]
                    st.rerun()

    with col2:
        if st.button("📅 Welche Fristen?", use_container_width=True):
            with st.spinner("..."):
                result = chat_service.chat(
                    st.session_state.selected_doc_id,
                    user_id,
                    "Welche Fristen oder wichtigen Termine werden genannt?",
                    st.session_state.chat_history
                )
                if result.get("success"):
                    st.session_state.chat_history = result["conversation"]
                    st.rerun()

    with col3:
        if st.button("📞 Kontaktdaten?", use_container_width=True):
            with st.spinner("..."):
                result = chat_service.chat(
                    st.session_state.selected_doc_id,
                    user_id,
                    "Welche Kontaktdaten (Telefon, E-Mail, Adresse) werden im Dokument genannt?",
                    st.session_state.chat_history
                )
                if result.get("success"):
                    st.session_state.chat_history = result["conversation"]
                    st.rerun()

else:
    st.info("👈 Bitte wählen Sie ein Dokument aus der Seitenleiste aus.")

# Hinweis zur KI
st.divider()
st.caption(
    "💡 Die Antworten werden von einer KI generiert und können ungenau sein. "
    "Überprüfen Sie wichtige Informationen immer im Originaldokument."
)
