"""
Diktierfunktion - Sprache zu Text
Ermöglicht das Aufnehmen und Transkribieren von Sprache
"""
import streamlit as st
from datetime import datetime
import io

from utils.components import page_header, show_notification
from config.settings import get_settings, DOCUMENT_CATEGORIES
from services.speech_service import get_speech_service

# Seitenkonfiguration
st.set_page_config(
    page_title="Diktierfunktion",
    page_icon="🎤",
    layout="wide"
)

page_header("🎤 Diktierfunktion", "Sprache aufnehmen und in Text umwandeln")

settings = get_settings()
speech_service = get_speech_service()

# Prüfe API-Konfiguration
if not settings.openai_api_key:
    st.warning(
        "⚠️ OpenAI API-Schlüssel nicht konfiguriert. "
        "Bitte in den Einstellungen hinterlegen für Sprach-zu-Text Funktion."
    )

# Session State initialisieren
if 'transcribed_text' not in st.session_state:
    st.session_state.transcribed_text = ""
if 'audio_bytes' not in st.session_state:
    st.session_state.audio_bytes = None
if 'transcription_done' not in st.session_state:
    st.session_state.transcription_done = False

# Hauptbereich
tab_record, tab_upload, tab_history = st.tabs([
    "🎙️ Aufnehmen",
    "📁 Audio-Datei hochladen",
    "📋 Gespeicherte Diktate"
])

with tab_record:
    st.subheader("Sprache aufnehmen")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.info(
            "💡 **Anleitung:**\n"
            "1. Klicken Sie auf 'Aufnahme starten'\n"
            "2. Sprechen Sie Ihren Text\n"
            "3. Klicken Sie auf 'Aufnahme stoppen'\n"
            "4. Klicken Sie auf 'Transkribieren'\n"
            "5. Bearbeiten und speichern Sie das Ergebnis"
        )

        # Audio Recorder
        try:
            from st_audiorec import st_audiorec

            st.write("**Audio aufnehmen:**")
            audio_bytes = st_audiorec()

            if audio_bytes:
                st.session_state.audio_bytes = audio_bytes
                st.success("✅ Audio aufgenommen!")

                # Audio abspielen zur Kontrolle
                st.audio(audio_bytes, format="audio/wav")

        except ImportError:
            st.error(
                "📦 Audio-Recorder nicht installiert.\n\n"
                "Bitte installieren Sie: `pip install st-audiorec`"
            )

            # Alternative: Datei-Upload
            st.write("**Alternative: Audio-Datei hochladen**")
            uploaded_audio = st.file_uploader(
                "Audio-Datei auswählen",
                type=["wav", "mp3", "m4a", "ogg", "webm"],
                key="record_upload"
            )
            if uploaded_audio:
                st.session_state.audio_bytes = uploaded_audio.read()
                st.audio(st.session_state.audio_bytes)

    with col2:
        st.write("**Einstellungen:**")

        language = st.selectbox(
            "Sprache",
            options=["de", "en", "fr", "es", "it", "nl", "pl", "pt", "ru", "zh"],
            format_func=lambda x: {
                "de": "🇩🇪 Deutsch",
                "en": "🇬🇧 English",
                "fr": "🇫🇷 Français",
                "es": "🇪🇸 Español",
                "it": "🇮🇹 Italiano",
                "nl": "🇳🇱 Nederlands",
                "pl": "🇵🇱 Polski",
                "pt": "🇵🇹 Português",
                "ru": "🇷🇺 Русский",
                "zh": "🇨🇳 中文"
            }.get(x, x),
            index=0
        )

        category = st.selectbox(
            "Kategorie",
            options=["Notiz", "Protokoll", "Memo", "Idee", "Aufgabe"] + DOCUMENT_CATEGORIES
        )

    # Transkription starten
    st.divider()

    col_btn1, col_btn2, col_btn3 = st.columns(3)

    with col_btn1:
        if st.button("🔄 Transkribieren", type="primary", disabled=st.session_state.audio_bytes is None):
            if st.session_state.audio_bytes:
                with st.spinner("Transkribiere Audio..."):
                    result = speech_service.transcribe_audio(
                        st.session_state.audio_bytes,
                        language=language
                    )

                    if "error" in result:
                        st.error(f"❌ Fehler: {result['error']}")
                    else:
                        st.session_state.transcribed_text = result["text"]
                        st.session_state.transcription_done = True
                        st.success("✅ Transkription erfolgreich!")
                        st.rerun()

    with col_btn2:
        if st.button("🗑️ Aufnahme löschen", disabled=st.session_state.audio_bytes is None):
            st.session_state.audio_bytes = None
            st.session_state.transcribed_text = ""
            st.session_state.transcription_done = False
            st.rerun()

    # Transkribierter Text
    if st.session_state.transcription_done or st.session_state.transcribed_text:
        st.divider()
        st.subheader("📝 Transkribierter Text")

        # Editierbarer Text
        edited_text = st.text_area(
            "Text bearbeiten",
            value=st.session_state.transcribed_text,
            height=200,
            key="edited_transcript"
        )

        # Titel für Speicherung
        default_title = f"Diktat vom {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        title = st.text_input("Titel", value=default_title)

        col_save1, col_save2, col_save3 = st.columns(3)

        with col_save1:
            if st.button("💾 Als Dokument speichern", type="primary"):
                if edited_text.strip():
                    result = speech_service.save_transcription(
                        text=edited_text,
                        title=title,
                        category=category,
                        audio_data=st.session_state.audio_bytes
                    )

                    if result.get("success"):
                        show_notification(
                            f"✅ Diktat '{title}' wurde gespeichert!",
                            "success"
                        )
                        # Reset
                        st.session_state.audio_bytes = None
                        st.session_state.transcribed_text = ""
                        st.session_state.transcription_done = False
                        st.rerun()
                    else:
                        st.error(f"❌ Fehler beim Speichern: {result.get('error')}")
                else:
                    st.warning("Bitte geben Sie einen Text ein.")

        with col_save2:
            if st.button("📋 In Zwischenablage"):
                st.code(edited_text)
                st.info("Text oben markieren und kopieren (Strg+C)")

        with col_save3:
            # Download als Textdatei
            if edited_text:
                st.download_button(
                    "⬇️ Als .txt herunterladen",
                    data=edited_text,
                    file_name=f"diktat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain"
                )

with tab_upload:
    st.subheader("Audio-Datei hochladen")

    uploaded_file = st.file_uploader(
        "Audio-Datei auswählen",
        type=["wav", "mp3", "m4a", "ogg", "webm", "flac"],
        help="Unterstützte Formate: WAV, MP3, M4A, OGG, WebM, FLAC"
    )

    if uploaded_file:
        st.audio(uploaded_file)

        col1, col2 = st.columns(2)

        with col1:
            upload_language = st.selectbox(
                "Sprache der Aufnahme",
                options=["de", "en", "fr", "es", "it"],
                format_func=lambda x: {
                    "de": "🇩🇪 Deutsch",
                    "en": "🇬🇧 English",
                    "fr": "🇫🇷 Français",
                    "es": "🇪🇸 Español",
                    "it": "🇮🇹 Italiano"
                }.get(x, x),
                key="upload_language"
            )

        with col2:
            upload_category = st.selectbox(
                "Kategorie",
                options=["Notiz", "Protokoll", "Memo", "Idee"] + DOCUMENT_CATEGORIES,
                key="upload_category"
            )

        if st.button("🔄 Datei transkribieren", type="primary"):
            with st.spinner("Transkribiere Audio-Datei..."):
                audio_bytes = uploaded_file.read()
                result = speech_service.transcribe_audio(audio_bytes, language=upload_language)

                if "error" in result:
                    st.error(f"❌ Fehler: {result['error']}")
                else:
                    st.success("✅ Transkription erfolgreich!")

                    st.subheader("📝 Ergebnis")
                    result_text = st.text_area(
                        "Transkribierter Text",
                        value=result["text"],
                        height=200,
                        key="upload_result"
                    )

                    upload_title = st.text_input(
                        "Titel",
                        value=f"Transkription: {uploaded_file.name}",
                        key="upload_title"
                    )

                    col_s1, col_s2 = st.columns(2)

                    with col_s1:
                        if st.button("💾 Speichern", key="save_upload"):
                            save_result = speech_service.save_transcription(
                                text=result_text,
                                title=upload_title,
                                category=upload_category,
                                audio_data=audio_bytes
                            )
                            if save_result.get("success"):
                                st.success(f"✅ Gespeichert als '{upload_title}'")
                            else:
                                st.error(f"❌ {save_result.get('error')}")

                    with col_s2:
                        st.download_button(
                            "⬇️ Als .txt",
                            data=result_text,
                            file_name=f"{uploaded_file.name.rsplit('.', 1)[0]}.txt",
                            mime="text/plain",
                            key="download_upload"
                        )

with tab_history:
    st.subheader("Gespeicherte Diktate")

    # Lade gespeicherte Transkriptionen
    transcriptions = speech_service.get_saved_transcriptions(limit=50)

    if not transcriptions:
        st.info("📭 Noch keine Diktate gespeichert.")
    else:
        for trans in transcriptions:
            with st.expander(
                f"📄 {trans['title']} - {trans['date'].strftime('%d.%m.%Y %H:%M') if trans['date'] else 'Unbekannt'}"
            ):
                st.write(f"**Kategorie:** {trans['category']}")
                st.write(f"**Vorschau:**")
                st.text(trans['text'] or "Kein Text verfügbar")

                col1, col2 = st.columns(2)
                with col1:
                    if st.button("📖 Vollständig anzeigen", key=f"view_{trans['id']}"):
                        st.session_state[f"show_full_{trans['id']}"] = True

                with col2:
                    if st.button("🗑️ Löschen", key=f"del_{trans['id']}"):
                        from database.models import get_session, Document
                        session = get_session()
                        try:
                            doc = session.query(Document).filter_by(id=trans['id']).first()
                            if doc:
                                session.delete(doc)
                                session.commit()
                                st.success("Gelöscht!")
                                st.rerun()
                        finally:
                            session.close()

                # Vollständiger Text anzeigen
                if st.session_state.get(f"show_full_{trans['id']}"):
                    from database.models import get_session, Document
                    session = get_session()
                    try:
                        doc = session.query(Document).filter_by(id=trans['id']).first()
                        if doc and doc.extracted_text:
                            st.text_area(
                                "Vollständiger Text",
                                value=doc.extracted_text,
                                height=300,
                                key=f"full_text_{trans['id']}"
                            )
                    finally:
                        session.close()

# Sidebar mit Tipps
with st.sidebar:
    st.subheader("💡 Tipps für gute Aufnahmen")
    st.markdown("""
    - **Ruhige Umgebung** - Hintergrundgeräusche minimieren
    - **Deutlich sprechen** - Klare Aussprache verbessert Erkennung
    - **Mikrofon-Abstand** - Ca. 20-30 cm vom Mikrofon entfernt
    - **Satzzeichen** - Sagen Sie "Punkt", "Komma", "Fragezeichen"
    - **Neue Zeile** - Sagen Sie "Neue Zeile" oder "Absatz"
    """)

    st.divider()

    st.subheader("📊 Statistik")
    from database.models import get_session, Document
    session = get_session()
    try:
        count = session.query(Document).filter(
            Document.file_path.like("%/transcriptions/%")
        ).count()
        st.metric("Gespeicherte Diktate", count)
    finally:
        session.close()

    st.divider()

    st.subheader("⚙️ API-Status")
    if settings.openai_api_key:
        st.success("✅ OpenAI API konfiguriert")
    else:
        st.error("❌ OpenAI API nicht konfiguriert")
        st.caption("Einstellungen → API-Schlüssel")
