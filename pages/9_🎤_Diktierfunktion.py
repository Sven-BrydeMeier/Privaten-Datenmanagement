"""
Diktierfunktion - Sprache zu Text und Sprachbefehle
Ermöglicht das Aufnehmen und Transkribieren von Sprache sowie Sprachbefehle
für Kalender, Erinnerungen, Wecker, Timer und To-dos
"""
import streamlit as st
from datetime import datetime
import io

from utils.components import page_header, show_notification
from config.settings import get_settings, DOCUMENT_CATEGORIES
from services.speech_service import get_speech_service
from services.voice_command_service import get_voice_command_service

# Seitenkonfiguration
st.set_page_config(
    page_title="Diktierfunktion",
    page_icon="🎤",
    layout="wide"
)

page_header("🎤 Diktierfunktion", "Sprache aufnehmen, transkribieren und Befehle ausführen")

settings = get_settings()
speech_service = get_speech_service()
voice_command_service = get_voice_command_service()

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
if 'command_result' not in st.session_state:
    st.session_state.command_result = None

# Hole User ID
from database.models import get_session, User
session = get_session()
try:
    user = session.query(User).first()
    user_id = user.id if user else 1
finally:
    session.close()

# Hauptbereich
tab_commands, tab_record, tab_upload, tab_history, tab_todos = st.tabs([
    "🗣️ Sprachbefehle",
    "🎙️ Diktieren",
    "📁 Audio hochladen",
    "📋 Diktate",
    "✅ Aufgaben & Wecker"
])

with tab_commands:
    st.subheader("🗣️ Sprachbefehle")

    st.info("""
    **Sprechen Sie Befehle wie:**
    - 📅 *"Erstelle einen Termin für morgen um 14 Uhr Arztbesuch"*
    - ⏰ *"Erinnere mich morgen an die Steuererklärung"*
    - 🔔 *"Stelle einen Wecker für 7 Uhr"*
    - ⏱️ *"Timer für 10 Minuten"*
    - ✅ *"Neue Aufgabe Einkaufen gehen bis Freitag"*
    """)

    col1, col2 = st.columns([2, 1])

    with col1:
        # Audio Recorder für Befehle
        try:
            from st_audiorec import st_audiorec

            st.write("**Befehl aufnehmen:**")
            command_audio = st_audiorec()

            if command_audio:
                st.audio(command_audio, format="audio/wav")

                if st.button("🚀 Befehl ausführen", type="primary", key="exec_voice_cmd"):
                    with st.spinner("Verarbeite Sprachbefehl..."):
                        # Transkribieren
                        trans_result = speech_service.transcribe_audio(command_audio, language="de")

                        if "error" in trans_result:
                            st.error(f"❌ Transkriptionsfehler: {trans_result['error']}")
                        else:
                            st.write(f"**Erkannt:** *\"{trans_result['text']}\"*")

                            # Befehl ausführen
                            cmd_result = voice_command_service.execute_command(
                                trans_result['text'],
                                user_id
                            )

                            st.session_state.command_result = cmd_result

                            if cmd_result['success']:
                                st.success(cmd_result['message'])
                            else:
                                st.warning(cmd_result['message'])

        except ImportError:
            st.error("📦 Audio-Recorder nicht installiert. `pip install st-audiorec`")

            # Alternative: Text-Eingabe
            st.write("**Alternative: Befehl eintippen:**")
            manual_command = st.text_input(
                "Befehl eingeben",
                placeholder="z.B. Erstelle einen Termin für morgen um 15 Uhr Meeting"
            )

            if manual_command and st.button("🚀 Befehl ausführen", key="exec_text_cmd"):
                with st.spinner("Verarbeite Befehl..."):
                    cmd_result = voice_command_service.execute_command(manual_command, user_id)
                    st.session_state.command_result = cmd_result

                    if cmd_result['success']:
                        st.success(cmd_result['message'])
                    else:
                        st.warning(cmd_result['message'])

    with col2:
        st.write("**Erkannte Befehlstypen:**")

        st.markdown("""
        | Symbol | Befehl | Beispiel |
        |--------|--------|----------|
        | 📅 | Termin | *"Termin am Montag"* |
        | ⏰ | Erinnerung | *"Erinnere mich..."* |
        | 🔔 | Wecker | *"Wecker um 7 Uhr"* |
        | ⏱️ | Timer | *"Timer 5 Minuten"* |
        | ✅ | Aufgabe | *"Neue Aufgabe..."* |
        """)

        st.divider()

        # Letzte Befehle anzeigen
        st.write("**Letzte Befehle:**")
        from database.models import VoiceCommand
        session = get_session()
        try:
            recent_cmds = session.query(VoiceCommand).filter_by(
                user_id=user_id
            ).order_by(VoiceCommand.created_at.desc()).limit(5).all()

            if recent_cmds:
                for cmd in recent_cmds:
                    icon = {"calendar": "📅", "reminder": "⏰", "alarm": "🔔",
                            "timer": "⏱️", "todo": "✅"}.get(cmd.command_type, "❓")
                    status = "✓" if cmd.was_successful else "✗"
                    st.caption(f"{icon} {status} {cmd.transcribed_text[:30]}...")
            else:
                st.caption("Noch keine Befehle")
        finally:
            session.close()

    # Manuelle Schnellaktionen
    st.divider()
    st.subheader("⚡ Schnellaktionen")

    quick_col1, quick_col2, quick_col3, quick_col4 = st.columns(4)

    with quick_col1:
        with st.expander("📅 Schnell-Termin"):
            quick_title = st.text_input("Titel", key="quick_cal_title", placeholder="Meeting")
            quick_date = st.date_input("Datum", key="quick_cal_date")
            quick_time = st.time_input("Uhrzeit", key="quick_cal_time")

            if st.button("➕ Termin erstellen", key="quick_cal_btn"):
                from database.models import CalendarEvent, EventType
                session = get_session()
                try:
                    event = CalendarEvent(
                        user_id=user_id,
                        title=quick_title or "Termin",
                        event_type=EventType.APPOINTMENT,
                        start_date=datetime.combine(quick_date, quick_time),
                        all_day=False,
                    )
                    session.add(event)
                    session.commit()
                    st.success(f"✅ Termin erstellt!")
                finally:
                    session.close()

    with quick_col2:
        with st.expander("⏰ Schnell-Erinnerung"):
            rem_title = st.text_input("Woran?", key="quick_rem_title", placeholder="Anruf")
            rem_date = st.date_input("Datum", key="quick_rem_date")
            rem_time = st.time_input("Uhrzeit", key="quick_rem_time")

            if st.button("➕ Erinnerung erstellen", key="quick_rem_btn"):
                from database.models import CalendarEvent, EventType
                session = get_session()
                try:
                    event = CalendarEvent(
                        user_id=user_id,
                        title=f"⏰ {rem_title or 'Erinnerung'}",
                        event_type=EventType.REMINDER,
                        start_date=datetime.combine(rem_date, rem_time),
                        all_day=False,
                    )
                    session.add(event)
                    session.commit()
                    st.success(f"✅ Erinnerung erstellt!")
                finally:
                    session.close()

    with quick_col3:
        with st.expander("🔔 Schnell-Wecker"):
            alarm_title = st.text_input("Bezeichnung", key="quick_alarm_title", placeholder="Aufwachen")
            alarm_time = st.time_input("Uhrzeit", key="quick_alarm_time")
            alarm_tomorrow = st.checkbox("Morgen", value=True, key="quick_alarm_tomorrow")

            if st.button("➕ Wecker stellen", key="quick_alarm_btn"):
                from database.models import Alarm, AlarmType
                alarm_date = datetime.now().date()
                if alarm_tomorrow:
                    from datetime import timedelta
                    alarm_date = alarm_date + timedelta(days=1)

                session = get_session()
                try:
                    alarm = Alarm(
                        user_id=user_id,
                        alarm_type=AlarmType.ALARM,
                        title=alarm_title or "Wecker",
                        trigger_time=datetime.combine(alarm_date, alarm_time),
                        is_active=True,
                    )
                    session.add(alarm)
                    session.commit()
                    st.success(f"✅ Wecker gestellt!")
                finally:
                    session.close()

    with quick_col4:
        with st.expander("✅ Schnell-Aufgabe"):
            todo_title = st.text_input("Aufgabe", key="quick_todo_title", placeholder="Einkaufen")
            todo_due = st.date_input("Fällig am", key="quick_todo_due")
            todo_priority = st.selectbox("Priorität", ["Medium", "Niedrig", "Hoch", "Dringend"], key="quick_todo_prio")

            if st.button("➕ Aufgabe erstellen", key="quick_todo_btn"):
                from database.models import Todo, TodoStatus, TodoPriority
                prio_map = {"Niedrig": TodoPriority.LOW, "Medium": TodoPriority.MEDIUM,
                            "Hoch": TodoPriority.HIGH, "Dringend": TodoPriority.URGENT}

                session = get_session()
                try:
                    todo = Todo(
                        user_id=user_id,
                        title=todo_title or "Aufgabe",
                        status=TodoStatus.OPEN,
                        priority=prio_map.get(todo_priority, TodoPriority.MEDIUM),
                        due_date=datetime.combine(todo_due, datetime.min.time()),
                    )
                    session.add(todo)
                    session.commit()
                    st.success(f"✅ Aufgabe erstellt!")
                finally:
                    session.close()


with tab_record:
    st.subheader("🎙️ Sprache diktieren")

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
                st.audio(audio_bytes, format="audio/wav")

        except ImportError:
            st.error(
                "📦 Audio-Recorder nicht installiert.\n\n"
                "Bitte installieren Sie: `pip install st-audiorec`"
            )

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

    if st.session_state.transcription_done or st.session_state.transcribed_text:
        st.divider()
        st.subheader("📝 Transkribierter Text")

        edited_text = st.text_area(
            "Text bearbeiten",
            value=st.session_state.transcribed_text,
            height=200,
            key="edited_transcript"
        )

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
                        st.success(f"✅ Diktat '{title}' wurde gespeichert!")
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
    st.subheader("📋 Gespeicherte Diktate")

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
                        from database.models import Document
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

                if st.session_state.get(f"show_full_{trans['id']}"):
                    from database.models import Document
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

with tab_todos:
    st.subheader("✅ Aufgaben, Wecker & Timer")

    todo_tab, alarm_tab = st.tabs(["📋 Aufgaben", "⏰ Wecker & Timer"])

    with todo_tab:
        from database.models import Todo, TodoStatus, TodoPriority

        session = get_session()
        try:
            # Filter
            filter_col1, filter_col2 = st.columns(2)
            with filter_col1:
                show_completed = st.checkbox("Erledigte anzeigen", value=False)
            with filter_col2:
                sort_by = st.selectbox("Sortieren nach", ["Fälligkeit", "Priorität", "Erstellt"])

            # Aufgaben laden
            query = session.query(Todo).filter_by(user_id=user_id)
            if not show_completed:
                query = query.filter(Todo.status != TodoStatus.COMPLETED)

            if sort_by == "Fälligkeit":
                query = query.order_by(Todo.due_date.asc().nullslast())
            elif sort_by == "Priorität":
                query = query.order_by(Todo.priority.desc())
            else:
                query = query.order_by(Todo.created_at.desc())

            todos = query.all()

            if not todos:
                st.info("📭 Keine Aufgaben vorhanden. Erstellen Sie eine per Sprachbefehl oder Schnellaktion.")
            else:
                for todo in todos:
                    prio_icons = {
                        TodoPriority.LOW: "🟢",
                        TodoPriority.MEDIUM: "🟡",
                        TodoPriority.HIGH: "🟠",
                        TodoPriority.URGENT: "🔴"
                    }
                    status_icon = "✅" if todo.status == TodoStatus.COMPLETED else "⬜"

                    col1, col2, col3 = st.columns([0.5, 4, 1])

                    with col1:
                        if st.checkbox("", value=todo.status == TodoStatus.COMPLETED,
                                       key=f"todo_check_{todo.id}", label_visibility="collapsed"):
                            todo.status = TodoStatus.COMPLETED
                            todo.completed_at = datetime.now()
                            session.commit()
                            st.rerun()

                    with col2:
                        prio = prio_icons.get(todo.priority, "⚪")
                        due = f" (fällig: {todo.due_date.strftime('%d.%m.%Y')})" if todo.due_date else ""
                        voice = " 🎤" if todo.created_by_voice else ""

                        if todo.status == TodoStatus.COMPLETED:
                            st.markdown(f"~~{prio} {todo.title}{due}~~{voice}")
                        else:
                            st.markdown(f"{prio} **{todo.title}**{due}{voice}")

                    with col3:
                        if st.button("🗑️", key=f"del_todo_{todo.id}"):
                            session.delete(todo)
                            session.commit()
                            st.rerun()
        finally:
            session.close()

    with alarm_tab:
        from database.models import Alarm, AlarmType

        session = get_session()
        try:
            alarms = session.query(Alarm).filter_by(
                user_id=user_id,
                is_active=True
            ).order_by(Alarm.trigger_time.asc()).all()

            if not alarms:
                st.info("📭 Keine aktiven Wecker oder Timer.")
            else:
                for alarm in alarms:
                    type_icon = "🔔" if alarm.alarm_type == AlarmType.ALARM else "⏱️"
                    time_str = alarm.trigger_time.strftime('%d.%m.%Y %H:%M')

                    col1, col2, col3 = st.columns([0.5, 4, 1])

                    with col1:
                        st.write(type_icon)

                    with col2:
                        title = alarm.title or ("Wecker" if alarm.alarm_type == AlarmType.ALARM else "Timer")
                        voice = " 🎤" if alarm.created_by_voice else ""
                        st.write(f"**{title}** - {time_str}{voice}")

                        # Timer Countdown
                        if alarm.alarm_type == AlarmType.TIMER:
                            remaining = (alarm.trigger_time - datetime.now()).total_seconds()
                            if remaining > 0:
                                mins, secs = divmod(int(remaining), 60)
                                hours, mins = divmod(mins, 60)
                                if hours > 0:
                                    st.caption(f"Noch {hours}h {mins}m {secs}s")
                                else:
                                    st.caption(f"Noch {mins}m {secs}s")
                            else:
                                st.caption("⏰ Zeit abgelaufen!")

                    with col3:
                        if st.button("🗑️", key=f"del_alarm_{alarm.id}"):
                            session.delete(alarm)
                            session.commit()
                            st.rerun()
        finally:
            session.close()

# Sidebar mit Tipps und Statistiken
with st.sidebar:
    st.subheader("💡 Sprachbefehl-Tipps")
    st.markdown("""
    **Termine:**
    - *"Termin morgen 14 Uhr Arzt"*
    - *"Meeting am Montag um 10"*

    **Erinnerungen:**
    - *"Erinnere mich an Anruf"*
    - *"Nicht vergessen: Medikamente"*

    **Wecker:**
    - *"Wecker 7 Uhr"*
    - *"Weck mich um 6:30"*

    **Timer:**
    - *"Timer 10 Minuten"*
    - *"30 Sekunden Timer"*

    **Aufgaben:**
    - *"Neue Aufgabe Einkaufen"*
    - *"Todo bis Freitag: Bericht"*
    """)

    st.divider()

    st.subheader("📊 Statistik")
    session = get_session()
    try:
        from database.models import Todo, Alarm, VoiceCommand, Document

        todo_count = session.query(Todo).filter_by(user_id=user_id, status=TodoStatus.OPEN).count()
        alarm_count = session.query(Alarm).filter_by(user_id=user_id, is_active=True).count()
        voice_count = session.query(VoiceCommand).filter_by(user_id=user_id).count()
        dict_count = session.query(Document).filter(Document.file_path.like("%/transcriptions/%")).count()

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Offene Aufgaben", todo_count)
            st.metric("Aktive Wecker", alarm_count)
        with col2:
            st.metric("Sprachbefehle", voice_count)
            st.metric("Diktate", dict_count)
    finally:
        session.close()

    st.divider()

    st.subheader("⚙️ API-Status")
    if settings.openai_api_key:
        st.success("✅ OpenAI API konfiguriert")
    else:
        st.error("❌ OpenAI API nicht konfiguriert")
        st.caption("Einstellungen → API-Schlüssel")
