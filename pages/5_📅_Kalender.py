"""
Kalender & Fristen - Grafischer Kalender mit Monats-, Wochen- und Tagesansicht
"""
import streamlit as st
from pathlib import Path
import sys
from datetime import datetime, timedelta
import calendar

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import CalendarEvent, EventType, Contact, Document
from utils.helpers import format_date, calculate_days_until, is_deadline_urgent
from utils.components import render_sidebar_cart

st.set_page_config(page_title="Kalender", page_icon="📅", layout="wide")
init_db()

# Sidebar mit Aktentasche
render_sidebar_cart()

user_id = get_current_user_id()

st.title("📅 Kalender & Fristen")

# Session-State initialisieren
if 'calendar_date' not in st.session_state:
    st.session_state.calendar_date = datetime.now()
if 'calendar_view' not in st.session_state:
    st.session_state.calendar_view = 'month'
if 'selected_day' not in st.session_state:
    st.session_state.selected_day = datetime.now().day


def get_event_icon(event_type):
    """Gibt das passende Icon für einen Event-Typ zurück"""
    icons = {
        EventType.DEADLINE: "⏰",
        EventType.BIRTHDAY: "🎂",
        EventType.APPOINTMENT: "📅",
        EventType.REMINDER: "🔔",
        EventType.CONTRACT_END: "📄"
    }
    return icons.get(event_type, "📌")


def get_event_color(event_type):
    """Gibt die passende Farbe für einen Event-Typ zurück"""
    colors = {
        EventType.DEADLINE: "#FF5722",
        EventType.BIRTHDAY: "#E91E63",
        EventType.APPOINTMENT: "#2196F3",
        EventType.REMINDER: "#FF9800",
        EventType.CONTRACT_END: "#9C27B0"
    }
    return colors.get(event_type, "#607D8B")


def render_calendar_cell(day, month, year, events_by_day, is_current_month=True):
    """Rendert eine Kalenderzelle als HTML"""
    if day == 0:
        return '<div class="cal-cell empty"></div>'

    date_obj = datetime(year, month, day)
    is_today = date_obj.date() == datetime.now().date()
    is_selected = day == st.session_state.selected_day and is_current_month
    day_events = events_by_day.get(day, [])

    # CSS-Klassen
    classes = ["cal-cell"]
    if not is_current_month:
        classes.append("other-month")
    if is_today:
        classes.append("today")
    if is_selected:
        classes.append("selected")
    if day_events:
        classes.append("has-events")

    # Event-Punkte
    dots = ""
    if day_events:
        dots = '<div class="event-dots">'
        for event in day_events[:3]:
            color = get_event_color(event.event_type)
            dots += f'<span class="dot" style="background:{color}"></span>'
        if len(day_events) > 3:
            dots += f'<span class="more">+{len(day_events)-3}</span>'
        dots += '</div>'

    return f'''
    <div class="{' '.join(classes)}" onclick="selectDay({day})">
        <div class="day-num">{day}</div>
        {dots}
    </div>
    '''


# Ansichts-Auswahl
col_nav, col_views = st.columns([3, 1])

with col_nav:
    current_date = st.session_state.calendar_date

    col_prev, col_today, col_next, col_month_label = st.columns([1, 1, 1, 3])

    with col_prev:
        if st.button("◀ Zurück", use_container_width=True):
            if st.session_state.calendar_view == 'month':
                st.session_state.calendar_date = current_date.replace(day=1) - timedelta(days=1)
            elif st.session_state.calendar_view == 'week':
                st.session_state.calendar_date = current_date - timedelta(days=7)
            else:
                st.session_state.calendar_date = current_date - timedelta(days=1)
            st.rerun()

    with col_today:
        if st.button("📍 Heute", use_container_width=True):
            st.session_state.calendar_date = datetime.now()
            st.session_state.selected_day = datetime.now().day
            st.rerun()

    with col_next:
        if st.button("Weiter ▶", use_container_width=True):
            if st.session_state.calendar_view == 'month':
                next_month = current_date.replace(day=28) + timedelta(days=4)
                st.session_state.calendar_date = next_month.replace(day=1)
            elif st.session_state.calendar_view == 'week':
                st.session_state.calendar_date = current_date + timedelta(days=7)
            else:
                st.session_state.calendar_date = current_date + timedelta(days=1)
            st.rerun()

    with col_month_label:
        if st.session_state.calendar_view == 'month':
            st.markdown(f"### {current_date.strftime('%B %Y')}")
        elif st.session_state.calendar_view == 'week':
            week_start = current_date - timedelta(days=current_date.weekday())
            week_end = week_start + timedelta(days=6)
            st.markdown(f"### KW {current_date.isocalendar()[1]} ({week_start.strftime('%d.%m.')} - {week_end.strftime('%d.%m.%Y')})")
        else:
            st.markdown(f"### {current_date.strftime('%A, %d. %B %Y')}")

with col_views:
    view_options = {
        'month': '📅 Monat',
        'week': '📆 Woche',
        'day': '📋 Tag'
    }
    selected_view = st.radio(
        "Ansicht",
        options=list(view_options.keys()),
        format_func=lambda x: view_options[x],
        index=list(view_options.keys()).index(st.session_state.calendar_view),
        horizontal=True,
        label_visibility="collapsed"
    )
    if selected_view != st.session_state.calendar_view:
        st.session_state.calendar_view = selected_view
        st.rerun()

st.divider()

# Hauptbereich: Kalender + Termine
col_calendar, col_events = st.columns([2, 1])

with col_calendar:
    year = current_date.year
    month = current_date.month

    # Ereignisse laden
    with get_db() as session:
        if st.session_state.calendar_view == 'month':
            month_start = datetime(year, month, 1)
            if month == 12:
                month_end = datetime(year + 1, 1, 1)
            else:
                month_end = datetime(year, month + 1, 1)
        elif st.session_state.calendar_view == 'week':
            week_start = current_date - timedelta(days=current_date.weekday())
            month_start = week_start
            month_end = week_start + timedelta(days=7)
        else:
            month_start = current_date.replace(hour=0, minute=0, second=0)
            month_end = month_start + timedelta(days=1)

        events = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= month_start,
            CalendarEvent.start_date < month_end
        ).all()

        # Ereignisse nach Tag gruppieren
        events_by_day = {}
        all_events = []
        for event in events:
            day = event.start_date.day
            if day not in events_by_day:
                events_by_day[day] = []
            events_by_day[day].append(event)
            all_events.append({
                'id': event.id,
                'title': event.title,
                'description': event.description,
                'event_type': event.event_type,
                'start_date': event.start_date,
                'document_id': event.document_id
            })

    # Kalender-CSS
    calendar_css = """
    <style>
    .calendar-grid {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 2px;
        background: #f0f0f0;
        border-radius: 8px;
        padding: 4px;
    }
    .calendar-header {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 2px;
        margin-bottom: 4px;
    }
    .cal-header-cell {
        text-align: center;
        font-weight: bold;
        padding: 8px;
        color: #666;
        font-size: 0.9em;
    }
    .cal-cell {
        background: white;
        min-height: 70px;
        padding: 4px;
        border-radius: 4px;
        position: relative;
        cursor: pointer;
        transition: all 0.2s;
    }
    .cal-cell:hover {
        background: #e3f2fd;
    }
    .cal-cell.empty {
        background: transparent;
        cursor: default;
    }
    .cal-cell.today {
        border: 2px solid #1976D2;
    }
    .cal-cell.today .day-num {
        background: #1976D2;
        color: white;
        border-radius: 50%;
        width: 28px;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .cal-cell.selected {
        background: #e3f2fd;
    }
    .cal-cell.has-events {
        background: #fff8e1;
    }
    .cal-cell.other-month {
        opacity: 0.4;
    }
    .day-num {
        font-size: 1.1em;
        font-weight: 500;
        margin-bottom: 4px;
    }
    .event-dots {
        display: flex;
        gap: 3px;
        flex-wrap: wrap;
        margin-top: 4px;
    }
    .dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        display: inline-block;
    }
    .more {
        font-size: 0.7em;
        color: #666;
    }
    .week-view-row {
        display: grid;
        grid-template-columns: 60px repeat(7, 1fr);
        gap: 2px;
        margin-bottom: 2px;
    }
    .time-slot {
        font-size: 0.8em;
        color: #666;
        padding: 4px;
        text-align: right;
    }
    .week-cell {
        background: white;
        min-height: 40px;
        padding: 4px;
        border-radius: 4px;
        font-size: 0.85em;
    }
    .day-view-event {
        background: #e3f2fd;
        border-left: 4px solid #1976D2;
        padding: 12px;
        margin: 8px 0;
        border-radius: 4px;
    }
    </style>
    """
    st.markdown(calendar_css, unsafe_allow_html=True)

    if st.session_state.calendar_view == 'month':
        # Monatsansicht
        weekdays = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

        # Header
        header_html = '<div class="calendar-header">'
        for day in weekdays:
            header_html += f'<div class="cal-header-cell">{day}</div>'
        header_html += '</div>'
        st.markdown(header_html, unsafe_allow_html=True)

        # Kalendertage
        cal = calendar.Calendar(firstweekday=0)
        month_days = cal.monthdayscalendar(year, month)

        # Tage als Buttons in Spalten
        for week in month_days:
            cols = st.columns(7)
            for i, day in enumerate(week):
                with cols[i]:
                    if day != 0:
                        day_events = events_by_day.get(day, [])
                        is_today = datetime(year, month, day).date() == datetime.now().date()

                        # Button-Label mit Events
                        label = f"{day}"
                        if day_events:
                            icons = "".join([get_event_icon(e.event_type) for e in day_events[:2]])
                            label = f"{day} {icons}"

                        btn_type = "primary" if is_today else "secondary"
                        if st.button(label, key=f"day_{day}", use_container_width=True,
                                    type=btn_type if is_today else "secondary"):
                            st.session_state.selected_day = day
                            st.rerun()

    elif st.session_state.calendar_view == 'week':
        # Wochenansicht
        week_start = current_date - timedelta(days=current_date.weekday())
        weekdays = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

        # Header mit Daten
        cols = st.columns(7)
        for i, day_name in enumerate(weekdays):
            day_date = week_start + timedelta(days=i)
            is_today = day_date.date() == datetime.now().date()
            with cols[i]:
                if is_today:
                    st.markdown(f"**{day_name}**  \n**{day_date.strftime('%d.%m.')}** 📍")
                else:
                    st.markdown(f"**{day_name}**  \n{day_date.strftime('%d.%m.')}")

        st.divider()

        # Events pro Tag
        cols = st.columns(7)
        for i in range(7):
            day_date = week_start + timedelta(days=i)
            with cols[i]:
                day_events = [e for e in all_events if e['start_date'].date() == day_date.date()]
                if day_events:
                    for event in day_events:
                        icon = get_event_icon(event['event_type'])
                        color = get_event_color(event['event_type'])
                        st.markdown(f"""
                        <div style="background:{color}20; border-left:3px solid {color};
                                    padding:4px 8px; margin:4px 0; border-radius:4px; font-size:0.85em;">
                            {icon} {event['title'][:20]}
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.caption("—")

    else:
        # Tagesansicht
        st.markdown(f"### 📋 Termine am {current_date.strftime('%d. %B %Y')}")

        day_events = [e for e in all_events if e['start_date'].date() == current_date.date()]

        if day_events:
            for event in sorted(day_events, key=lambda x: x['start_date']):
                icon = get_event_icon(event['event_type'])
                color = get_event_color(event['event_type'])

                with st.container():
                    st.markdown(f"""
                    <div style="background:{color}15; border-left:4px solid {color};
                                padding:16px; margin:12px 0; border-radius:8px;">
                        <div style="font-size:1.2em; font-weight:bold; margin-bottom:8px;">
                            {icon} {event['title']}
                        </div>
                        <div style="color:#666; font-size:0.9em;">
                            🕐 {event['start_date'].strftime('%H:%M') if not event['start_date'].hour == 0 else 'Ganztägig'}
                        </div>
                        {f"<div style='margin-top:8px;'>{event['description']}</div>" if event['description'] else ""}
                    </div>
                    """, unsafe_allow_html=True)

                    if event['document_id']:
                        if st.button(f"📄 Dokument öffnen", key=f"doc_{event['id']}"):
                            st.session_state.view_document_id = event['document_id']
                            st.switch_page("pages/3_📁_Dokumente.py")
        else:
            st.info("Keine Termine an diesem Tag")

        # Neuen Termin für diesen Tag
        with st.expander("➕ Neuen Termin hinzufügen"):
            event_title = st.text_input("Titel", key="new_day_event_title")
            event_type = st.selectbox(
                "Typ",
                options=[e.value for e in EventType],
                format_func=lambda x: {
                    "deadline": "⏰ Frist",
                    "birthday": "🎂 Geburtstag",
                    "appointment": "📅 Termin",
                    "reminder": "🔔 Erinnerung",
                    "contract_end": "📄 Vertragsende"
                }.get(x, x),
                key="new_day_event_type"
            )
            event_desc = st.text_area("Beschreibung", key="new_day_event_desc", height=80)

            if st.button("Termin erstellen", key="create_day_event") and event_title:
                with get_db() as session:
                    new_event = CalendarEvent(
                        user_id=user_id,
                        title=event_title,
                        description=event_desc,
                        event_type=EventType(event_type),
                        start_date=current_date,
                        all_day=True
                    )
                    session.add(new_event)
                    session.commit()
                st.success("Termin erstellt!")
                st.rerun()

with col_events:
    # Termine für den Monat ab heute
    st.markdown("### 📋 Kommende Termine")

    with get_db() as session:
        upcoming = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= datetime.now(),
            CalendarEvent.start_date <= datetime.now() + timedelta(days=30)
        ).order_by(CalendarEvent.start_date).limit(10).all()

        upcoming_events = [{
            'id': e.id,
            'title': e.title,
            'description': e.description,
            'event_type': e.event_type,
            'start_date': e.start_date,
            'document_id': e.document_id
        } for e in upcoming]

    if upcoming_events:
        for event in upcoming_events:
            icon = get_event_icon(event['event_type'])
            days_until = (event['start_date'].date() - datetime.now().date()).days

            if days_until == 0:
                time_str = "Heute"
                urgency = "🔴"
            elif days_until == 1:
                time_str = "Morgen"
                urgency = "🟠"
            elif days_until <= 7:
                time_str = f"in {days_until} Tagen"
                urgency = "🟡"
            else:
                time_str = format_date(event['start_date'])
                urgency = "🟢"

            with st.container():
                col1, col2 = st.columns([1, 5])
                with col1:
                    st.write(urgency)
                with col2:
                    st.markdown(f"**{icon} {event['title']}**")
                    st.caption(f"{time_str}")

                    # Löschen-Button
                    if st.button("🗑️", key=f"del_upcoming_{event['id']}"):
                        with get_db() as sess:
                            sess.query(CalendarEvent).filter(CalendarEvent.id == event['id']).delete()
                            sess.commit()
                        st.rerun()

            st.divider()
    else:
        st.info("Keine anstehenden Termine in den nächsten 30 Tagen")

    # Neuer Termin
    st.markdown("---")
    st.markdown("### ➕ Neuer Termin")

    with st.form("new_event_form"):
        event_title = st.text_input("Titel")
        event_date = st.date_input("Datum", value=datetime.now())
        event_type = st.selectbox(
            "Typ",
            options=[e.value for e in EventType],
            format_func=lambda x: {
                "deadline": "⏰ Frist",
                "birthday": "🎂 Geburtstag",
                "appointment": "📅 Termin",
                "reminder": "🔔 Erinnerung",
                "contract_end": "📄 Vertragsende"
            }.get(x, x)
        )
        event_desc = st.text_area("Beschreibung", height=80)

        if st.form_submit_button("Erstellen", use_container_width=True):
            if event_title:
                with get_db() as session:
                    new_event = CalendarEvent(
                        user_id=user_id,
                        title=event_title,
                        description=event_desc,
                        event_type=EventType(event_type),
                        start_date=datetime.combine(event_date, datetime.min.time()),
                        all_day=True
                    )
                    session.add(new_event)
                    session.commit()
                st.success("Termin erstellt!")
                st.rerun()

st.divider()

# Todos für heute
st.markdown("### ✅ Aufgaben für heute")

today = datetime.now().date()

with get_db() as session:
    today_events = session.query(CalendarEvent).filter(
        CalendarEvent.user_id == user_id,
        CalendarEvent.start_date >= datetime.combine(today, datetime.min.time()),
        CalendarEvent.start_date < datetime.combine(today + timedelta(days=1), datetime.min.time()),
        CalendarEvent.event_type.in_([EventType.DEADLINE, EventType.REMINDER])
    ).all()

    today_todos = [{
        'id': e.id,
        'title': e.title,
        'description': e.description,
        'event_type': e.event_type,
        'document_id': e.document_id
    } for e in today_events]

if today_todos:
    cols = st.columns(min(len(today_todos), 3))
    for i, todo in enumerate(today_todos):
        with cols[i % 3]:
            icon = get_event_icon(todo['event_type'])
            st.markdown(f"""
            <div style="background:#fff3e0; border-left:4px solid #FF9800;
                        padding:12px; border-radius:8px; margin:4px 0;">
                <div style="font-weight:bold;">{icon} {todo['title']}</div>
                {f"<div style='font-size:0.9em; color:#666; margin-top:4px;'>{todo['description']}</div>" if todo['description'] else ""}
            </div>
            """, unsafe_allow_html=True)

            if todo['document_id']:
                if st.button("📄 Dokument", key=f"todo_doc_{todo['id']}"):
                    st.session_state.view_document_id = todo['document_id']
                    st.switch_page("pages/3_📁_Dokumente.py")
else:
    st.success("✅ Keine Aufgaben für heute!")
