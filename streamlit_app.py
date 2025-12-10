"""
Privates Dokumentenmanagement - Hauptanwendung
Eine intelligente Dokumentenverwaltung mit KI-Unterstützung
"""
import streamlit as st
from pathlib import Path
import sys

# Projektverzeichnis zum Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent))

from database.db import init_db, get_current_user_id
from config.settings import get_settings

# Seitenkonfiguration
st.set_page_config(
    page_title="Dokumentenmanagement",
    page_icon="📁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Datenbank initialisieren
init_db()

# Custom CSS für besseres UI
st.markdown("""
<style>
    /* Allgemeine Styles */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    /* Status-Indikatoren */
    .status-green {
        display: inline-block;
        width: 12px;
        height: 12px;
        background-color: #28a745;
        border-radius: 50%;
        margin-right: 8px;
    }

    .status-red {
        display: inline-block;
        width: 12px;
        height: 12px;
        background-color: #dc3545;
        border-radius: 50%;
        margin-right: 8px;
    }

    .status-gray {
        display: inline-block;
        width: 12px;
        height: 12px;
        background-color: #6c757d;
        border-radius: 50%;
        margin-right: 8px;
    }

    /* Frist-Warnung */
    .deadline-warning {
        background-color: #fff3cd;
        border-left: 4px solid #ffc107;
        padding: 10px 15px;
        margin: 10px 0;
        border-radius: 4px;
    }

    .deadline-urgent {
        background-color: #f8d7da;
        border-left: 4px solid #dc3545;
        padding: 10px 15px;
        margin: 10px 0;
        border-radius: 4px;
    }

    /* Karten-Style */
    .info-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        border: 1px solid #e9ecef;
    }

    /* Aktentasche-Badge */
    .cart-badge {
        background-color: #007bff;
        color: white;
        border-radius: 10px;
        padding: 2px 8px;
        font-size: 0.8em;
        margin-left: 5px;
    }

    /* Sidebar Navigation */
    .sidebar .sidebar-content {
        background-color: #f8f9fa;
    }

    /* Buttons */
    .stButton>button {
        border-radius: 6px;
    }

    /* Tabellen */
    .dataframe {
        font-size: 0.9em;
    }

    /* Upload-Bereich */
    .uploadedFile {
        border: 2px dashed #007bff;
        border-radius: 8px;
        padding: 20px;
    }
</style>
""", unsafe_allow_html=True)


def render_sidebar():
    """Rendert die Sidebar mit Navigation und Aktentasche"""
    with st.sidebar:
        st.title("📁 Dokumentenmanagement")

        # API-Status anzeigen
        settings = get_settings()
        from services.ai_service import get_ai_service
        ai_service = get_ai_service()

        # Status-Check (gecached)
        if 'api_status' not in st.session_state:
            st.session_state.api_status = ai_service.test_connection()

        status = st.session_state.api_status

        # Status-Anzeige
        st.markdown("### API-Status")
        col1, col2 = st.columns(2)
        with col1:
            if status.get('openai'):
                st.markdown('<span class="status-green"></span> OpenAI', unsafe_allow_html=True)
            elif settings.openai_api_key:
                st.markdown('<span class="status-red"></span> OpenAI', unsafe_allow_html=True)
            else:
                st.markdown('<span class="status-gray"></span> OpenAI', unsafe_allow_html=True)

        with col2:
            if status.get('anthropic'):
                st.markdown('<span class="status-green"></span> Claude', unsafe_allow_html=True)
            elif settings.anthropic_api_key:
                st.markdown('<span class="status-red"></span> Claude', unsafe_allow_html=True)
            else:
                st.markdown('<span class="status-gray"></span> Claude', unsafe_allow_html=True)

        st.divider()

        # Aktentasche-Anzeige
        st.markdown("### 💼 Aktentasche")
        cart_items = st.session_state.get('active_cart_items', [])
        cart_name = st.session_state.get('active_cart_name', 'Aktuelle Aktentasche')

        st.caption(f"**{cart_name}**")
        if cart_items:
            st.info(f"{len(cart_items)} Dokument(e)")
            if st.button("Aktentasche anzeigen", key="show_cart"):
                st.switch_page("pages/4_🔍_Intelligente_Ordner.py")
        else:
            st.caption("Leer")

        st.divider()

        # Schnellzugriff
        st.markdown("### Schnellzugriff")
        if st.button("📄 Neues Dokument", use_container_width=True):
            st.switch_page("pages/2_📄_Dokumentenaufnahme.py")

        if st.button("🔍 Suche", use_container_width=True):
            st.switch_page("pages/3_📁_Dokumente.py")

        st.divider()

        # Footer
        st.caption("v1.0.0 | Privat & Sicher")


def render_dashboard():
    """Rendert das Haupt-Dashboard"""
    user_id = get_current_user_id()

    st.title("📊 Dashboard")
    st.markdown("Willkommen zu Ihrer privaten Dokumentenverwaltung")

    # Übersichtskarten
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        with st.container():
            st.metric("📄 Dokumente", get_document_count(user_id))

    with col2:
        with st.container():
            st.metric("📥 Posteingang", get_inbox_count(user_id))

    with col3:
        with st.container():
            deadline_count = get_upcoming_deadlines_count(user_id)
            st.metric("⏰ Fristen", deadline_count)

    with col4:
        with st.container():
            st.metric("💰 Offene Rechnungen", get_open_invoices_count(user_id))

    st.divider()

    # Fristen-Warnung
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("⏰ Anstehende Fristen")
        deadlines = get_upcoming_deadlines(user_id, limit=5)

        if deadlines:
            for deadline in deadlines:
                days_left = deadline.get('days_left', 0)
                if days_left < 0:
                    css_class = "deadline-urgent"
                    icon = "🔴"
                elif days_left <= 3:
                    css_class = "deadline-urgent"
                    icon = "🟠"
                else:
                    css_class = "deadline-warning"
                    icon = "🟡"

                st.markdown(f"""
                <div class="{css_class}">
                    {icon} <strong>{deadline['title']}</strong><br>
                    <small>Fällig: {deadline['date']} ({deadline['days_text']})</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.success("Keine anstehenden Fristen")

        st.divider()

        # Neueste Dokumente
        st.subheader("📄 Neueste Dokumente")
        recent_docs = get_recent_documents(user_id, limit=5)

        if recent_docs:
            for doc in recent_docs:
                col_doc, col_action = st.columns([4, 1])
                with col_doc:
                    st.markdown(f"**{doc['title']}**")
                    st.caption(f"{doc['category']} | {doc['date']}")
                with col_action:
                    if st.button("📂", key=f"open_{doc['id']}", help="Öffnen"):
                        st.session_state.selected_document = doc['id']
                        st.switch_page("pages/3_📁_Dokumente.py")
        else:
            st.info("Noch keine Dokumente vorhanden")

    with col_right:
        # Geburtstage
        st.subheader("🎂 Geburtstage")
        birthdays = get_upcoming_birthdays(user_id, limit=5)

        if birthdays:
            for bday in birthdays:
                st.markdown(f"""
                <div class="info-card">
                    🎂 <strong>{bday['name']}</strong><br>
                    <small>{bday['date']}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("Keine anstehenden Geburtstage")

        st.divider()

        # Schnellaktionen
        st.subheader("⚡ Schnellaktionen")

        if st.button("📄 Dokument scannen", use_container_width=True):
            st.switch_page("pages/2_📄_Dokumentenaufnahme.py")

        if st.button("📅 Termin erstellen", use_container_width=True):
            st.switch_page("pages/5_📅_Kalender.py")

        if st.button("⚙️ Einstellungen", use_container_width=True):
            st.switch_page("pages/8_⚙️_Einstellungen.py")


# Hilfsfunktionen für Dashboard-Daten
def get_document_count(user_id: int) -> int:
    """Zählt alle Dokumente des Benutzers"""
    from database import get_db, Document
    with get_db() as session:
        return session.query(Document).filter(Document.user_id == user_id).count()


def get_inbox_count(user_id: int) -> int:
    """Zählt Dokumente im Posteingang"""
    from database import get_db, Document, Folder
    with get_db() as session:
        inbox = session.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.name == "Posteingang"
        ).first()
        if inbox:
            return session.query(Document).filter(
                Document.user_id == user_id,
                Document.folder_id == inbox.id
            ).count()
        return 0


def get_upcoming_deadlines_count(user_id: int) -> int:
    """Zählt anstehende Fristen"""
    from database import get_db, CalendarEvent
    from datetime import datetime, timedelta
    with get_db() as session:
        return session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= datetime.now(),
            CalendarEvent.start_date <= datetime.now() + timedelta(days=30)
        ).count()


def get_open_invoices_count(user_id: int) -> int:
    """Zählt offene Rechnungen"""
    from database import get_db, Document, InvoiceStatus
    with get_db() as session:
        return session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_status == InvoiceStatus.OPEN
        ).count()


def get_upcoming_deadlines(user_id: int, limit: int = 5) -> list:
    """Holt anstehende Fristen"""
    from database import get_db, CalendarEvent
    from datetime import datetime, timedelta
    from utils.helpers import format_date, calculate_days_until

    deadlines = []
    with get_db() as session:
        events = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= datetime.now() - timedelta(days=7),
            CalendarEvent.start_date <= datetime.now() + timedelta(days=30)
        ).order_by(CalendarEvent.start_date).limit(limit).all()

        for event in events:
            days_left = calculate_days_until(event.start_date)
            if days_left < 0:
                days_text = f"{abs(days_left)} Tage überfällig"
            elif days_left == 0:
                days_text = "Heute!"
            elif days_left == 1:
                days_text = "Morgen"
            else:
                days_text = f"in {days_left} Tagen"

            deadlines.append({
                'id': event.id,
                'title': event.title,
                'date': format_date(event.start_date),
                'days_left': days_left,
                'days_text': days_text,
                'document_id': event.document_id
            })

    return deadlines


def get_recent_documents(user_id: int, limit: int = 5) -> list:
    """Holt die neuesten Dokumente"""
    from database import get_db, Document
    from utils.helpers import format_date

    documents = []
    with get_db() as session:
        docs = session.query(Document).filter(
            Document.user_id == user_id
        ).order_by(Document.created_at.desc()).limit(limit).all()

        for doc in docs:
            documents.append({
                'id': doc.id,
                'title': doc.title or doc.filename,
                'category': doc.category or 'Nicht kategorisiert',
                'date': format_date(doc.created_at)
            })

    return documents


def get_upcoming_birthdays(user_id: int, limit: int = 5) -> list:
    """Holt anstehende Geburtstage"""
    from database import get_db, Contact
    from datetime import datetime
    from utils.helpers import format_date

    birthdays = []
    with get_db() as session:
        contacts = session.query(Contact).filter(
            Contact.user_id == user_id,
            Contact.birthday.isnot(None)
        ).all()

        today = datetime.now()
        for contact in contacts:
            if contact.birthday:
                # Geburtstag dieses Jahr
                bday_this_year = contact.birthday.replace(year=today.year)
                if bday_this_year < today:
                    bday_this_year = bday_this_year.replace(year=today.year + 1)

                days_until = (bday_this_year - today).days
                if 0 <= days_until <= 30:
                    birthdays.append({
                        'name': contact.name,
                        'date': bday_this_year.strftime("%d. %B"),
                        'days_until': days_until
                    })

        # Nach Tagen sortieren
        birthdays.sort(key=lambda x: x['days_until'])

    return birthdays[:limit]


# Hauptanwendung
def main():
    render_sidebar()
    render_dashboard()


if __name__ == "__main__":
    main()
