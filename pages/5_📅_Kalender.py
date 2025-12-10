"""
Kalender & Fristen - Termine, Fristen und Geburtstage verwalten
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

st.set_page_config(page_title="Kalender", page_icon="📅", layout="wide")
init_db()

user_id = get_current_user_id()

st.title("📅 Kalender & Fristen")

# Tabs
tab_calendar, tab_deadlines, tab_birthdays, tab_contacts = st.tabs([
    "📅 Kalender",
    "⏰ Fristen",
    "🎂 Geburtstage",
    "👥 Kontakte"
])


with tab_calendar:
    # Kalender-Navigation
    col_nav, col_view = st.columns([1, 4])

    with col_nav:
        # Monat/Jahr-Navigation
        if 'calendar_date' not in st.session_state:
            st.session_state.calendar_date = datetime.now()

        current_date = st.session_state.calendar_date

        col_prev, col_month, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("◀"):
                st.session_state.calendar_date = current_date.replace(day=1) - timedelta(days=1)
                st.rerun()
        with col_month:
            st.markdown(f"**{current_date.strftime('%B %Y')}**")
        with col_next:
            if st.button("▶"):
                next_month = current_date.replace(day=28) + timedelta(days=4)
                st.session_state.calendar_date = next_month.replace(day=1)
                st.rerun()

        # Heute-Button
        if st.button("Heute", use_container_width=True):
            st.session_state.calendar_date = datetime.now()
            st.rerun()

        st.divider()

        # Neuen Termin erstellen
        st.markdown("**➕ Neuer Termin**")

        event_title = st.text_input("Titel", key="new_event_title")
        event_date = st.date_input("Datum", key="new_event_date")
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
            key="new_event_type"
        )
        event_desc = st.text_area("Beschreibung", key="new_event_desc", height=100)

        if st.button("Termin erstellen") and event_title:
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

    with col_view:
        # Kalenderansicht
        year = current_date.year
        month = current_date.month

        # Ereignisse für diesen Monat laden
        with get_db() as session:
            month_start = datetime(year, month, 1)
            if month == 12:
                month_end = datetime(year + 1, 1, 1)
            else:
                month_end = datetime(year, month + 1, 1)

            events = session.query(CalendarEvent).filter(
                CalendarEvent.user_id == user_id,
                CalendarEvent.start_date >= month_start,
                CalendarEvent.start_date < month_end
            ).all()

            # Ereignisse nach Tag gruppieren
            events_by_day = {}
            for event in events:
                day = event.start_date.day
                if day not in events_by_day:
                    events_by_day[day] = []
                events_by_day[day].append(event)

        # Kalender als Tabelle rendern
        cal = calendar.Calendar(firstweekday=0)  # Montag
        month_days = cal.monthdayscalendar(year, month)

        # Wochentage
        st.markdown("| Mo | Di | Mi | Do | Fr | Sa | So |")
        st.markdown("|:--:|:--:|:--:|:--:|:--:|:--:|:--:|")

        for week in month_days:
            row = "|"
            for day in week:
                if day == 0:
                    row += "   |"
                else:
                    day_events = events_by_day.get(day, [])
                    if day_events:
                        # Tag mit Ereignissen hervorheben
                        icons = ""
                        for e in day_events[:2]:
                            if e.event_type == EventType.DEADLINE:
                                icons += "⏰"
                            elif e.event_type == EventType.BIRTHDAY:
                                icons += "🎂"
                            else:
                                icons += "📅"
                        row += f" **{day}**{icons} |"
                    else:
                        row += f" {day} |"
            st.markdown(row)

        # Ereignisliste für ausgewählten Tag
        st.divider()
        st.subheader("Termine diesen Monat")

        if events:
            for event in sorted(events, key=lambda x: x.start_date):
                col1, col2, col3 = st.columns([1, 3, 1])

                with col1:
                    # Icon
                    if event.event_type == EventType.DEADLINE:
                        icon = "⏰"
                    elif event.event_type == EventType.BIRTHDAY:
                        icon = "🎂"
                    elif event.event_type == EventType.CONTRACT_END:
                        icon = "📄"
                    else:
                        icon = "📅"
                    st.write(f"{icon} {format_date(event.start_date)}")

                with col2:
                    st.markdown(f"**{event.title}**")
                    if event.description:
                        st.caption(event.description)

                with col3:
                    if st.button("🗑️", key=f"del_event_{event.id}"):
                        with get_db() as session:
                            session.query(CalendarEvent).filter(CalendarEvent.id == event.id).delete()
                            session.commit()
                        st.rerun()
        else:
            st.info("Keine Termine in diesem Monat")


with tab_deadlines:
    st.subheader("⏰ Fristen-Übersicht")

    # Filter
    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        show_overdue = st.checkbox("Überfällige anzeigen", value=True)
    with col_filter2:
        days_ahead = st.slider("Tage voraus", 7, 90, 30)

    with get_db() as session:
        query = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.event_type.in_([EventType.DEADLINE, EventType.CONTRACT_END])
        )

        if show_overdue:
            query = query.filter(
                CalendarEvent.start_date >= datetime.now() - timedelta(days=30)
            )
        else:
            query = query.filter(CalendarEvent.start_date >= datetime.now())

        query = query.filter(
            CalendarEvent.start_date <= datetime.now() + timedelta(days=days_ahead)
        )

        deadlines = query.order_by(CalendarEvent.start_date).all()

        if deadlines:
            for deadline in deadlines:
                days_left = calculate_days_until(deadline.start_date)

                # Farbe basierend auf Dringlichkeit
                if days_left < 0:
                    color = "🔴"
                    status = f"{abs(days_left)} Tage überfällig"
                elif days_left == 0:
                    color = "🔴"
                    status = "Heute fällig!"
                elif days_left <= 3:
                    color = "🟠"
                    status = f"in {days_left} Tagen"
                elif days_left <= 7:
                    color = "🟡"
                    status = f"in {days_left} Tagen"
                else:
                    color = "🟢"
                    status = f"in {days_left} Tagen"

                with st.container():
                    col1, col2, col3, col4 = st.columns([1, 3, 2, 1])

                    with col1:
                        st.write(color)

                    with col2:
                        st.markdown(f"**{deadline.title}**")
                        st.caption(deadline.description or "")

                    with col3:
                        st.write(f"{format_date(deadline.start_date)}")
                        st.caption(status)

                    with col4:
                        if deadline.document_id:
                            if st.button("📄", key=f"view_doc_{deadline.id}"):
                                st.session_state.view_document_id = deadline.document_id
                                st.switch_page("pages/3_📁_Dokumente.py")

                    st.divider()
        else:
            st.success("Keine anstehenden Fristen!")


with tab_birthdays:
    st.subheader("🎂 Geburtstage")

    col_list, col_upcoming = st.columns([1, 1])

    with col_list:
        st.markdown("**Alle Geburtstage**")

        with get_db() as session:
            contacts = session.query(Contact).filter(
                Contact.user_id == user_id,
                Contact.birthday.isnot(None)
            ).order_by(Contact.name).all()

            for contact in contacts:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"🎂 {contact.name}")
                with col2:
                    if contact.birthday:
                        st.caption(contact.birthday.strftime("%d.%m."))

    with col_upcoming:
        st.markdown("**Anstehende Geburtstage (30 Tage)**")

        today = datetime.now()
        upcoming = []

        with get_db() as session:
            contacts = session.query(Contact).filter(
                Contact.user_id == user_id,
                Contact.birthday.isnot(None)
            ).all()

            for contact in contacts:
                if contact.birthday:
                    bday_this_year = contact.birthday.replace(year=today.year)
                    if bday_this_year < today:
                        bday_this_year = bday_this_year.replace(year=today.year + 1)

                    days_until = (bday_this_year - today).days
                    if 0 <= days_until <= 30:
                        upcoming.append({
                            'name': contact.name,
                            'date': bday_this_year,
                            'days_until': days_until,
                            'age': today.year - contact.birthday.year
                        })

        upcoming.sort(key=lambda x: x['days_until'])

        for bday in upcoming:
            if bday['days_until'] == 0:
                st.success(f"🎉 **{bday['name']}** hat heute Geburtstag! ({bday['age']} Jahre)")
            elif bday['days_until'] <= 3:
                st.warning(f"🎂 **{bday['name']}** in {bday['days_until']} Tagen")
            else:
                st.info(f"🎂 {bday['name']} am {format_date(bday['date'])} (in {bday['days_until']} Tagen)")


with tab_contacts:
    st.subheader("👥 Kontakte verwalten")

    col_form, col_list = st.columns([1, 2])

    with col_form:
        st.markdown("**➕ Neuer Kontakt**")

        contact_name = st.text_input("Name", key="contact_name")
        contact_email = st.text_input("E-Mail", key="contact_email")
        contact_phone = st.text_input("Telefon", key="contact_phone")
        contact_company = st.text_input("Firma", key="contact_company")
        contact_birthday = st.date_input(
            "Geburtstag",
            value=None,
            key="contact_birthday",
            min_value=datetime(1900, 1, 1),
            max_value=datetime.now()
        )
        contact_notes = st.text_area("Notizen", key="contact_notes")

        if st.button("Kontakt speichern") and contact_name:
            with get_db() as session:
                new_contact = Contact(
                    user_id=user_id,
                    name=contact_name,
                    email=contact_email,
                    phone=contact_phone,
                    company=contact_company,
                    birthday=datetime.combine(contact_birthday, datetime.min.time()) if contact_birthday else None,
                    notes=contact_notes
                )
                session.add(new_contact)
                session.commit()

                # Geburtstag als Kalendereintrag
                if contact_birthday:
                    bday_event = CalendarEvent(
                        user_id=user_id,
                        contact_id=new_contact.id,
                        title=f"🎂 Geburtstag: {contact_name}",
                        event_type=EventType.BIRTHDAY,
                        start_date=datetime.combine(contact_birthday, datetime.min.time()),
                        is_recurring=True,
                        recurrence_rule="FREQ=YEARLY"
                    )
                    session.add(bday_event)
                    session.commit()

            st.success("Kontakt gespeichert!")
            st.rerun()

    with col_list:
        st.markdown("**Kontaktliste**")

        search_contact = st.text_input("🔍 Suchen...", key="search_contact")

        with get_db() as session:
            query = session.query(Contact).filter(Contact.user_id == user_id)

            if search_contact:
                query = query.filter(
                    Contact.name.ilike(f'%{search_contact}%') |
                    Contact.email.ilike(f'%{search_contact}%') |
                    Contact.company.ilike(f'%{search_contact}%')
                )

            contacts = query.order_by(Contact.name).all()

            for contact in contacts:
                with st.expander(f"👤 {contact.name}"):
                    if contact.email:
                        st.write(f"📧 {contact.email}")
                    if contact.phone:
                        st.write(f"📱 {contact.phone}")
                    if contact.company:
                        st.write(f"🏢 {contact.company}")
                    if contact.birthday:
                        st.write(f"🎂 {format_date(contact.birthday)}")
                    if contact.notes:
                        st.caption(contact.notes)

                    if st.button("🗑️ Löschen", key=f"del_contact_{contact.id}"):
                        with get_db() as sess:
                            sess.query(Contact).filter(Contact.id == contact.id).delete()
                            sess.commit()
                        st.rerun()
