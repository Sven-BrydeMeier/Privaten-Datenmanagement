"""
Automatisierung
Regelbasierte Dokumentenverarbeitung und Workflows
"""
import streamlit as st
from datetime import datetime

from utils.components import render_sidebar_cart, apply_custom_css
from services.automation_service import get_automation_service
from database.db import get_current_user_id, get_db
from database.models import Document, Notification, CalendarEvent, EventType

# Seitenkonfiguration
st.set_page_config(
    page_title="Automatisierung",
    page_icon="🤖",
    layout="wide"
)

apply_custom_css()
render_sidebar_cart()

st.title("🤖 Automatisierung")
st.caption("Regelbasierte Dokumentenverarbeitung und automatische Workflows")

user_id = get_current_user_id()
automation_service = get_automation_service()

# Tabs
tab_overview, tab_rules, tab_notifications, tab_tasks = st.tabs([
    "📊 Übersicht",
    "⚙️ Regeln",
    "🔔 Benachrichtigungen",
    "📋 Aufgaben"
])

with tab_overview:
    st.subheader("📊 Automatisierungs-Dashboard")

    # Statistiken laden
    stats = automation_service.get_automation_statistics(user_id)

    # KPI-Karten
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "⏰ Aktive Erinnerungen",
            stats["active_reminders"],
            help="Kalendereinträge für Fristen und Erinnerungen"
        )

    with col2:
        st.metric(
            "⚠️ Überfällige Dokumente",
            stats["overdue_documents"],
            delta_color="inverse" if stats["overdue_documents"] > 0 else "off"
        )

    with col3:
        st.metric(
            "🔔 Ungelesene Benachrichtigungen",
            stats["unread_notifications"],
            delta_color="inverse" if stats["unread_notifications"] > 0 else "off"
        )

    with col4:
        st.metric(
            "📁 Unorganisierte Dokumente",
            stats["unorganized_documents"],
            help="Dokumente ohne Ordnerzuweisung"
        )

    st.divider()

    # Schnellaktionen
    st.subheader("⚡ Schnellaktionen")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🔄 Geplante Aufgaben ausführen", type="primary", use_container_width=True):
            with st.spinner("Führe geplante Aufgaben aus..."):
                result = automation_service.run_scheduled_tasks(user_id)
                if result.get("success"):
                    results = result["results"]
                    st.success(
                        f"✅ Fertig!\n"
                        f"- {results['overdue_marked']} als überfällig markiert\n"
                        f"- {results['reminders_sent']} Erinnerungen erstellt"
                    )
                    st.rerun()
                else:
                    st.error(f"❌ {result.get('error')}")

    with col2:
        if st.button("📊 Alle neuen Dokumente verarbeiten", use_container_width=True):
            with st.spinner("Verarbeite neue Dokumente..."):
                # Unverarbeitete Dokumente laden
                with get_db() as session:
                    new_docs = session.query(Document).filter(
                        Document.user_id == user_id,
                        Document.workflow_status == "new",
                        Document.is_deleted == False
                    ).all()

                    processed = 0
                    for doc in new_docs:
                        result = automation_service.process_new_document(doc.id, user_id)
                        if result.get("rules_applied"):
                            processed += 1
                            doc.workflow_status = "processed"
                    session.commit()

                st.success(f"✅ {processed} Dokumente verarbeitet!")
                st.rerun()

    with col3:
        if st.button("🔔 Alle Benachrichtigungen als gelesen markieren", use_container_width=True):
            with get_db() as session:
                notifications = session.query(Notification).filter(
                    Notification.user_id == user_id,
                    Notification.is_read == False
                ).all()

                for n in notifications:
                    n.is_read = True
                session.commit()

            st.success("✅ Alle Benachrichtigungen als gelesen markiert!")
            st.rerun()

    # Letzte Aktivitäten
    st.divider()
    st.subheader("📜 Letzte Automatisierungen")

    with get_db() as session:
        recent_events = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.event_type.in_([EventType.DEADLINE, EventType.REMINDER])
        ).order_by(CalendarEvent.created_at.desc()).limit(10).all()

        if recent_events:
            for event in recent_events:
                col1, col2, col3 = st.columns([0.5, 3, 1])
                with col1:
                    icon = "⏰" if event.event_type == EventType.DEADLINE else "🔔"
                    st.write(icon)
                with col2:
                    st.write(event.title)
                    st.caption(f"Erstellt: {event.created_at.strftime('%d.%m.%Y %H:%M')}")
                with col3:
                    st.caption(event.start_date.strftime('%d.%m.%Y'))
        else:
            st.info("Noch keine automatisierten Ereignisse.")

with tab_rules:
    st.subheader("⚙️ Automatisierungsregeln")

    rules = automation_service.get_default_rules()

    st.info(
        "💡 Diese Regeln werden automatisch auf neue Dokumente angewandt. "
        "Sie können sie hier aktivieren oder deaktivieren."
    )

    for rule in rules:
        with st.expander(f"{'✅' if rule['is_active'] else '❌'} {rule['name']}", expanded=False):
            st.write(f"**Beschreibung:** {rule['description']}")

            st.write("**Bedingungen:**")
            for key, value in rule['conditions'].items():
                st.caption(f"• {key}: {value}")

            st.write("**Aktionen:**")
            for key, value in rule['actions'].items():
                st.caption(f"• {key}: {value}")

            # Hinweis: In einer vollständigen Implementierung würden hier
            # Buttons zum Aktivieren/Deaktivieren und Bearbeiten sein
            st.caption("_Regelkonfiguration in zukünftiger Version verfügbar_")

    st.divider()

    # Manuelle Regel testen
    st.subheader("🧪 Regel manuell testen")

    with get_db() as session:
        test_docs = session.query(Document).filter(
            Document.user_id == user_id,
            Document.is_deleted == False
        ).order_by(Document.created_at.desc()).limit(20).all()

        doc_options = {doc.id: f"{doc.title or doc.filename[:40]}" for doc in test_docs}

    if doc_options:
        test_doc_id = st.selectbox(
            "Dokument zum Testen auswählen",
            options=list(doc_options.keys()),
            format_func=lambda x: doc_options[x]
        )

        if st.button("🚀 Regeln auf Dokument anwenden"):
            with st.spinner("Wende Regeln an..."):
                result = automation_service.process_new_document(test_doc_id, user_id)

                if result.get("rules_applied"):
                    st.success(f"✅ Angewandte Regeln: {', '.join(result['rules_applied'])}")
                    if result.get("actions_taken"):
                        st.write("**Durchgeführte Aktionen:**")
                        for action in result["actions_taken"]:
                            st.caption(f"• {action}")
                elif result.get("error"):
                    st.error(result["error"])
                else:
                    st.info("Keine Regeln zutreffend für dieses Dokument.")

with tab_notifications:
    st.subheader("🔔 Benachrichtigungen")

    # Filter
    col1, col2 = st.columns([1, 3])
    with col1:
        show_read = st.checkbox("Gelesene anzeigen", value=False)

    # Benachrichtigungen laden
    with get_db() as session:
        query = session.query(Notification).filter(
            Notification.user_id == user_id
        )

        if not show_read:
            query = query.filter(Notification.is_read == False)

        notifications = query.order_by(
            Notification.created_at.desc()
        ).limit(50).all()

        if notifications:
            for notif in notifications:
                type_icons = {
                    "deadline": "⏰",
                    "invoice": "💰",
                    "contract": "📑",
                    "reminder": "🔔",
                    "document": "📄"
                }
                icon = type_icons.get(notif.notification_type, "📌")
                is_read_icon = "📭" if notif.is_read else "📬"

                col1, col2, col3 = st.columns([0.5, 4, 1])

                with col1:
                    st.write(f"{is_read_icon} {icon}")

                with col2:
                    st.write(f"**{notif.title}**")
                    if notif.message:
                        st.caption(notif.message[:100] + "..." if len(notif.message) > 100 else notif.message)
                    st.caption(f"_{notif.created_at.strftime('%d.%m.%Y %H:%M')}_")

                with col3:
                    if not notif.is_read:
                        if st.button("✓", key=f"read_{notif.id}", help="Als gelesen markieren"):
                            notif.is_read = True
                            session.commit()
                            st.rerun()
        else:
            st.success("✅ Keine ungelesenen Benachrichtigungen!")

with tab_tasks:
    st.subheader("📋 Automatisch erstellte Aufgaben")

    # Anstehende Kalendereinträge (Deadlines, Erinnerungen)
    with get_db() as session:
        upcoming = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= datetime.now(),
            CalendarEvent.event_type.in_([EventType.DEADLINE, EventType.REMINDER])
        ).order_by(CalendarEvent.start_date.asc()).limit(20).all()

        if upcoming:
            # Gruppieren nach Datum
            by_date = {}
            for event in upcoming:
                date_key = event.start_date.strftime('%Y-%m-%d')
                if date_key not in by_date:
                    by_date[date_key] = []
                by_date[date_key].append(event)

            for date_key, events in sorted(by_date.items()):
                date_obj = datetime.strptime(date_key, '%Y-%m-%d')
                days_until = (date_obj - datetime.now()).days

                if days_until == 0:
                    date_label = "🔴 Heute"
                elif days_until == 1:
                    date_label = "🟠 Morgen"
                elif days_until <= 7:
                    date_label = f"🟡 {date_obj.strftime('%A, %d.%m.')}"
                else:
                    date_label = f"🟢 {date_obj.strftime('%d.%m.%Y')}"

                st.write(f"**{date_label}**")

                for event in events:
                    icon = "⏰" if event.event_type == EventType.DEADLINE else "🔔"

                    col1, col2, col3 = st.columns([0.5, 4, 1])

                    with col1:
                        st.write(icon)

                    with col2:
                        st.write(event.title)
                        if event.description:
                            st.caption(event.description[:80])

                    with col3:
                        if event.document_id:
                            if st.button("📄", key=f"view_{event.id}", help="Dokument öffnen"):
                                st.session_state["view_document_id"] = event.document_id
                                st.switch_page("pages/3_📁_Dokumente.py")

                st.write("")  # Abstand

        else:
            st.info("📭 Keine anstehenden automatisierten Aufgaben.")

    # Überfällige Aufgaben
    st.divider()
    st.subheader("⚠️ Überfällige Aufgaben")

    with get_db() as session:
        overdue = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date < datetime.now(),
            CalendarEvent.event_type == EventType.DEADLINE,
            CalendarEvent.reminder_sent == False
        ).order_by(CalendarEvent.start_date.desc()).limit(10).all()

        if overdue:
            for event in overdue:
                days_overdue = (datetime.now() - event.start_date).days

                col1, col2, col3 = st.columns([0.5, 4, 1])

                with col1:
                    st.write("🔴")

                with col2:
                    st.write(f"**{event.title}**")
                    st.caption(f"Überfällig seit {days_overdue} Tag(en)")

                with col3:
                    if st.button("✓ Erledigt", key=f"done_{event.id}"):
                        event.reminder_sent = True
                        session.commit()
                        st.rerun()
        else:
            st.success("✅ Keine überfälligen Aufgaben!")
