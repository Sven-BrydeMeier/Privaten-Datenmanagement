"""
Privates Dokumentenmanagement - Hauptanwendung
Eine intelligente Dokumentenverwaltung mit KI-Unterstützung
"""
# WICHTIG: Warnungen für Whoosh FRÜH unterdrücken (vor allen anderen Imports!)
# Whoosh ist nicht vollständig kompatibel mit Python 3.13 (verwendet alte Regex-Syntax)
import warnings
import sys
import os

# Komplett alle Warnungen während des Whoosh-Imports unterdrücken
# Die Warnungen kommen beim Kompilieren der .py zu .pyc, also vor dem Import
_original_showwarning = warnings.showwarning
warnings.showwarning = lambda *args, **kwargs: None

# Auch PYTHONWARNINGS ignorieren
os.environ['PYTHONWARNINGS'] = 'ignore::SyntaxWarning'

# Alle Warnungsfilter setzen
warnings.filterwarnings('ignore', category=SyntaxWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*invalid escape sequence.*')
warnings.filterwarnings('ignore', message=r'.*"is" with.*literal.*')

# Whoosh vorab importieren um Warnungen zu unterdrücken
try:
    # Kompilierung erzwingen während Warnungen unterdrückt sind
    import importlib
    import whoosh
    import whoosh.analysis
    import whoosh.analysis.filters
    import whoosh.analysis.intraword
    import whoosh.codec.whoosh3
    import whoosh.qparser
    import whoosh.index
    import whoosh.fields
    import whoosh.query
except ImportError:
    pass  # Whoosh nicht installiert - OK
except Exception:
    pass  # Andere Fehler ignorieren

# showwarning wiederherstellen
warnings.showwarning = _original_showwarning

# Warnungsfilter für den Rest der App setzen
warnings.filterwarnings('default', category=SyntaxWarning)
warnings.filterwarnings('ignore', category=SyntaxWarning, module=r'.*whoosh.*')
warnings.filterwarnings('ignore', category=DeprecationWarning, module=r'.*whoosh.*')
warnings.filterwarnings('ignore', message=r'.*"is" with.*literal.*')

import streamlit as st
from pathlib import Path
from datetime import datetime, timedelta

# Projektverzeichnis zum Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent))

from database.db import init_db, get_db, get_current_user_id
from database.models import (
    Document, Folder, CalendarEvent, Contact, InvoiceStatus,
    Receipt, EventType, BankAccount
)
from config.settings import get_settings
from utils.components import render_sidebar_with_navigation, apply_custom_css
from utils.helpers import format_currency, format_date, calculate_days_until, get_local_now

# Seitenkonfiguration
st.set_page_config(
    page_title="Dokumentenmanagement",
    page_icon="📁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Datenbank initialisieren
init_db()

# Custom CSS aus gemeinsamer Komponente
apply_custom_css()

# Zusätzliches CSS für Dashboard
st.markdown("""
<style>
    /* KPI Cards */
    .kpi-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        padding: 20px;
        color: white;
        margin-bottom: 10px;
    }

    .kpi-card-green {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
    }

    .kpi-card-orange {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    }

    .kpi-card-blue {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
    }

    .kpi-value {
        font-size: 2.5rem;
        font-weight: bold;
        margin: 0;
    }

    .kpi-label {
        font-size: 0.9rem;
        opacity: 0.9;
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

    .status-orange {
        display: inline-block;
        width: 12px;
        height: 12px;
        background-color: #fd7e14;
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

    /* Deadline Cards */
    .deadline-card {
        background-color: #fff3cd;
        border-left: 4px solid #ffc107;
        padding: 10px 15px;
        margin: 8px 0;
        border-radius: 0 8px 8px 0;
    }

    .deadline-card-urgent {
        background-color: #f8d7da;
        border-left: 4px solid #dc3545;
    }

    .deadline-card-ok {
        background-color: #d4edda;
        border-left: 4px solid #28a745;
    }

    /* Contract Card */
    .contract-card {
        background-color: #e7f3ff;
        border-left: 4px solid #0066cc;
        padding: 10px 15px;
        margin: 8px 0;
        border-radius: 0 8px 8px 0;
    }

    /* Invoice Card */
    .invoice-card {
        background-color: #fff;
        border: 1px solid #dee2e6;
        padding: 12px 15px;
        margin: 8px 0;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }

    /* Info Card */
    .info-card {
        background-color: #f8f9fa;
        padding: 12px;
        border-radius: 8px;
        margin: 5px 0;
    }

    /* Quick Action Button */
    .quick-action {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
        transition: all 0.2s;
    }

    .quick-action:hover {
        background-color: #e9ecef;
        transform: translateY(-2px);
    }
</style>
""", unsafe_allow_html=True)


def render_dashboard():
    """Rendert das Haupt-Dashboard"""
    user_id = get_current_user_id()

    st.title("📊 Dashboard")
    st.markdown("Willkommen zu Ihrer privaten Dokumentenverwaltung")

    # Erinnerung: Lokale Installation für volle Funktionalität
    reminder_key = "local_install_reminder_dismissed"
    reminder_date_key = "local_install_reminder_date"

    # Erinnerung anzeigen wenn nicht abgelehnt und mindestens alle 7 Tage
    show_reminder = False
    if reminder_key not in st.session_state:
        st.session_state[reminder_key] = False
    if reminder_date_key not in st.session_state:
        st.session_state[reminder_date_key] = datetime.now()

    days_since_shown = (datetime.now() - st.session_state[reminder_date_key]).days
    if not st.session_state[reminder_key] or days_since_shown >= 7:
        show_reminder = True
        st.session_state[reminder_date_key] = datetime.now()

    if show_reminder:
        with st.expander("💡 **Hinweis: Erweiterte Funktionen verfügbar**", expanded=False):
            st.markdown("""
            **Folgende Funktionen erfordern eine lokale Installation:**

            | Funktion | Benötigt | Status |
            |----------|----------|--------|
            | 🔍 OCR (Texterkennung) | Tesseract | ⚠️ Nur lokal |
            | 📄 PDF zu Bild | Poppler | ⚠️ Nur lokal |
            | 📷 Barcode-Scan | ZBar | ⚠️ Nur lokal |
            | 🎤 Audio-Aufnahme | System-Audio | ⚠️ Nur lokal |

            **Alternativen in der Cloud:**
            - OCR: OpenAI Vision API (in Einstellungen konfigurieren)
            - Audio: Datei-Upload statt Live-Aufnahme
            - PDF: Textextraktion funktioniert weiterhin

            👉 Für volle Funktionalität: App lokal mit Docker oder direkt ausführen.
            """)
            if st.button("✓ Verstanden, nicht mehr anzeigen"):
                st.session_state[reminder_key] = True
                st.rerun()

    # =====================
    # HAUPT-KPIs (Zeile 1)
    # =====================
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        doc_count = get_document_count(user_id)
        inbox_count = get_inbox_count(user_id)
        st.metric("📄 Dokumente", doc_count, f"+{inbox_count} im Posteingang" if inbox_count > 0 else None)

    with col2:
        open_invoices = get_open_invoices_count(user_id)
        open_amount = get_open_invoices_amount(user_id)
        st.metric("💰 Offene Rechnungen", open_invoices, format_currency(open_amount) if open_amount > 0 else None)

    with col3:
        deadline_count = get_upcoming_deadlines_count(user_id)
        urgent_count = get_urgent_deadlines_count(user_id)
        delta_color = "inverse" if urgent_count > 0 else "off"
        st.metric("⏰ Fristen (30 Tage)", deadline_count, f"{urgent_count} dringend" if urgent_count > 0 else None, delta_color=delta_color)

    with col4:
        contract_count = get_expiring_contracts_count(user_id)
        st.metric("📋 Verträge", contract_count, "auslaufend" if contract_count > 0 else None, delta_color="inverse" if contract_count > 0 else "off")

    with col5:
        month_expenses = get_month_expenses(user_id)
        last_month = get_last_month_expenses(user_id)
        diff = month_expenses - last_month if last_month > 0 else 0
        st.metric("📈 Ausgaben (Monat)", format_currency(month_expenses), f"{'+' if diff >= 0 else ''}{format_currency(diff)}" if last_month > 0 else None)

    st.divider()

    # =====================
    # HAUPTBEREICH
    # =====================
    col_main, col_side = st.columns([2, 1])

    with col_main:
        # Tabs für verschiedene Übersichten
        tab_urgent, tab_invoices, tab_contracts, tab_recent = st.tabs([
            "🚨 Dringend",
            "💳 Offene Rechnungen",
            "📋 Verträge",
            "📄 Neueste Dokumente"
        ])

        with tab_urgent:
            st.subheader("🚨 Dringende Aufgaben")

            # Überfällige Rechnungen
            overdue = get_overdue_invoices(user_id)
            if overdue:
                st.markdown("**⚠️ Überfällige Rechnungen:**")
                for inv in overdue:
                    days_overdue = abs(inv['days_left'])
                    st.markdown(f"""
                    <div class="deadline-card deadline-card-urgent">
                        <strong>{inv['sender']}</strong> - {format_currency(inv['amount'])}<br>
                        <small>🔴 {days_overdue} Tage überfällig | Fällig: {inv['due_date']}</small>
                    </div>
                    """, unsafe_allow_html=True)

            # Dringende Fristen (nächste 7 Tage)
            urgent_deadlines = get_upcoming_deadlines(user_id, days=7)
            if urgent_deadlines:
                st.markdown("**⏰ Fristen in den nächsten 7 Tagen:**")
                for dl in urgent_deadlines:
                    card_class = "deadline-card-urgent" if dl['days_left'] <= 3 else "deadline-card"
                    icon = "🔴" if dl['days_left'] <= 1 else "🟠" if dl['days_left'] <= 3 else "🟡"
                    st.markdown(f"""
                    <div class="deadline-card {card_class}">
                        {icon} <strong>{dl['title']}</strong><br>
                        <small>{dl['days_text']} | {dl['date']}</small>
                    </div>
                    """, unsafe_allow_html=True)

            # Auslaufende Verträge (nächste 30 Tage)
            expiring = get_expiring_contracts(user_id, days=30)
            if expiring:
                st.markdown("**📋 Bald auslaufende Verträge:**")
                for contract in expiring:
                    st.markdown(f"""
                    <div class="contract-card">
                        📋 <strong>{contract['title']}</strong><br>
                        <small>Endet: {contract['end_date']} | Kündigungsfrist: {contract['notice_days']} Tage</small>
                    </div>
                    """, unsafe_allow_html=True)

            if not overdue and not urgent_deadlines and not expiring:
                st.success("✅ Keine dringenden Aufgaben - alles erledigt!")

        with tab_invoices:
            st.subheader("💳 Offene Rechnungen")

            invoices = get_open_invoices(user_id, limit=10)
            if invoices:
                # Summe anzeigen
                total = sum(inv['amount'] for inv in invoices)
                st.info(f"**Gesamt offen:** {format_currency(total)}")

                for inv in invoices:
                    days_left = inv.get('days_left')
                    if days_left is not None:
                        if days_left < 0:
                            status_color = "#dc3545"
                            status_text = f"🔴 {abs(days_left)} Tage überfällig"
                        elif days_left <= 7:
                            status_color = "#fd7e14"
                            status_text = f"🟠 Fällig in {days_left} Tagen"
                        else:
                            status_color = "#28a745"
                            status_text = f"🟢 Fällig in {days_left} Tagen"
                    else:
                        status_color = "#6c757d"
                        status_text = "Kein Fälligkeitsdatum"

                    col_inv, col_btn = st.columns([4, 1])
                    with col_inv:
                        st.markdown(f"""
                        <div class="invoice-card" style="border-left: 4px solid {status_color};">
                            <strong>{inv['sender']}</strong><br>
                            <span style="font-size: 1.2em; font-weight: bold;">{format_currency(inv['amount'])}</span><br>
                            <small>{status_text}</small>
                        </div>
                        """, unsafe_allow_html=True)
                    with col_btn:
                        if st.button("💰", key=f"pay_dash_{inv['id']}", help="Zur Rechnung"):
                            st.switch_page("pages/7_💰_Finanzen.py")
            else:
                st.success("✅ Keine offenen Rechnungen!")

        with tab_contracts:
            st.subheader("📋 Vertragsübersicht")

            contracts = get_all_contracts(user_id)
            if contracts:
                for contract in contracts:
                    days_until_end = contract.get('days_until_end')

                    if days_until_end is not None:
                        if days_until_end < 0:
                            status = "🔴 Abgelaufen"
                            card_style = "border-left: 4px solid #dc3545;"
                        elif days_until_end <= 30:
                            status = f"🟠 Endet in {days_until_end} Tagen"
                            card_style = "border-left: 4px solid #fd7e14;"
                        elif days_until_end <= 90:
                            status = f"🟡 Endet in {days_until_end} Tagen"
                            card_style = "border-left: 4px solid #ffc107;"
                        else:
                            status = f"🟢 Läuft noch {days_until_end} Tage"
                            card_style = "border-left: 4px solid #28a745;"
                    else:
                        status = "⚪ Unbefristet"
                        card_style = "border-left: 4px solid #6c757d;"

                    st.markdown(f"""
                    <div class="invoice-card" style="{card_style}">
                        <strong>{contract['title']}</strong><br>
                        <small>📅 Start: {contract['start_date'] or 'N/A'} | Ende: {contract['end_date'] or 'Unbefristet'}</small><br>
                        <small>⏰ Kündigungsfrist: {contract['notice_days'] or 'N/A'} Tage | {status}</small>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Keine Verträge erfasst")

        with tab_recent:
            st.subheader("📄 Neueste Dokumente")
            recent_docs = get_recent_documents(user_id, limit=10)

            if recent_docs:
                for doc in recent_docs:
                    col_doc, col_action = st.columns([4, 1])
                    with col_doc:
                        category_icon = get_category_icon(doc['category'])
                        st.markdown(f"""
                        <div class="info-card">
                            {category_icon} <strong>{doc['title']}</strong><br>
                            <small>{doc['category']} | {doc['date']} | {doc['sender'] or 'Unbekannt'}</small>
                        </div>
                        """, unsafe_allow_html=True)
                    with col_action:
                        if st.button("📂", key=f"open_{doc['id']}", help="Öffnen"):
                            st.session_state.selected_document = doc['id']
                            st.switch_page("pages/3_📁_Dokumente.py")
            else:
                st.info("Noch keine Dokumente vorhanden")

    with col_side:
        # Geburtstage
        st.subheader("🎂 Geburtstage")
        birthdays = get_upcoming_birthdays(user_id, limit=5)

        if birthdays:
            for bday in birthdays:
                days = bday['days_until']
                if days == 0:
                    badge = "🎉 Heute!"
                elif days == 1:
                    badge = "Morgen"
                else:
                    badge = f"in {days} Tagen"

                st.markdown(f"""
                <div class="info-card">
                    🎂 <strong>{bday['name']}</strong><br>
                    <small>{bday['date']} ({badge})</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("Keine anstehenden Geburtstage")

        st.divider()

        # Finanzübersicht
        st.subheader("💰 Finanzübersicht")

        # Mini-Chart für Monatsausgaben
        monthly_data = get_monthly_expenses_data(user_id, months=6)
        if monthly_data:
            import pandas as pd
            df = pd.DataFrame(monthly_data)
            st.bar_chart(df.set_index('month')['amount'], height=150)

        # Bankkonten-Übersicht
        with get_db() as session:
            accounts = session.query(BankAccount).filter(
                BankAccount.user_id == user_id,
                BankAccount.is_active == True
            ).limit(3).all()

            if accounts:
                st.markdown("**🏦 Ihre Konten:**")
                for acc in accounts:
                    default_mark = "⭐" if acc.is_default else ""
                    st.markdown(f"""
                    <div style="background-color: {acc.color}20; padding: 8px; border-radius: 6px;
                                margin: 4px 0; border-left: 3px solid {acc.color};">
                        {acc.icon} {acc.bank_name} - {acc.account_name} {default_mark}
                    </div>
                    """, unsafe_allow_html=True)

        st.divider()

        # Schnellaktionen
        st.subheader("⚡ Schnellaktionen")

        if st.button("📄 Dokument scannen", use_container_width=True, type="primary"):
            st.switch_page("pages/2_📄_Dokumentenaufnahme.py")

        if st.button("🧾 Bon erfassen", use_container_width=True):
            st.switch_page("pages/7_💰_Finanzen.py")

        if st.button("📅 Kalender", use_container_width=True):
            st.switch_page("pages/5_📅_Kalender.py")

        if st.button("🔍 Suchen", use_container_width=True):
            st.switch_page("pages/4_🔍_Intelligente_Ordner.py")

        if st.button("⚙️ Einstellungen", use_container_width=True):
            st.switch_page("pages/8_⚙️_Einstellungen.py")


# =====================
# HILFSFUNKTIONEN
# =====================

def get_category_icon(category: str) -> str:
    """Gibt ein passendes Icon für die Kategorie zurück"""
    icons = {
        'Rechnung': '🧾',
        'Vertrag': '📋',
        'Brief': '✉️',
        'Bescheid': '📜',
        'Versicherung': '🛡️',
        'Bank': '🏦',
        'Steuer': '💼',
        'Gesundheit': '🏥',
        'Arbeit': '💼',
        'Wohnung': '🏠',
        'Auto': '🚗',
        'Sonstiges': '📄'
    }
    return icons.get(category, '📄')


def get_document_count(user_id: int) -> int:
    """Zählt alle Dokumente des Benutzers"""
    with get_db() as session:
        return session.query(Document).filter(Document.user_id == user_id).count()


def get_inbox_count(user_id: int) -> int:
    """Zählt Dokumente im Posteingang"""
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
    """Zählt anstehende Fristen (30 Tage)"""
    with get_db() as session:
        return session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= datetime.now(),
            CalendarEvent.start_date <= datetime.now() + timedelta(days=30)
        ).count()


def get_urgent_deadlines_count(user_id: int) -> int:
    """Zählt dringende Fristen (7 Tage)"""
    with get_db() as session:
        return session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= datetime.now(),
            CalendarEvent.start_date <= datetime.now() + timedelta(days=7)
        ).count()


def get_open_invoices_count(user_id: int) -> int:
    """Zählt offene Rechnungen"""
    with get_db() as session:
        return session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_status == InvoiceStatus.OPEN
        ).count()


def get_open_invoices_amount(user_id: int) -> float:
    """Summe aller offenen Rechnungen"""
    with get_db() as session:
        result = session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_status == InvoiceStatus.OPEN,
            Document.invoice_amount.isnot(None)
        ).all()
        return sum(doc.invoice_amount or 0 for doc in result)


def get_expiring_contracts_count(user_id: int) -> int:
    """Zählt auslaufende Verträge (90 Tage)"""
    with get_db() as session:
        return session.query(Document).filter(
            Document.user_id == user_id,
            Document.contract_end.isnot(None),
            Document.contract_end >= datetime.now(),
            Document.contract_end <= datetime.now() + timedelta(days=90)
        ).count()


def get_month_expenses(user_id: int) -> float:
    """Ausgaben des aktuellen Monats"""
    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)

    with get_db() as session:
        # Bons
        receipts = session.query(Receipt).filter(
            Receipt.user_id == user_id,
            Receipt.date >= month_start
        ).all()
        receipt_total = sum(r.total_amount or 0 for r in receipts)

        # Bezahlte Rechnungen
        invoices = session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_status == InvoiceStatus.PAID,
            Document.invoice_paid_date >= month_start
        ).all()
        invoice_total = sum(i.invoice_amount or 0 for i in invoices)

        return receipt_total + invoice_total


def get_last_month_expenses(user_id: int) -> float:
    """Ausgaben des letzten Monats"""
    now = datetime.now()
    if now.month == 1:
        last_month_start = datetime(now.year - 1, 12, 1)
        last_month_end = datetime(now.year, 1, 1)
    else:
        last_month_start = datetime(now.year, now.month - 1, 1)
        last_month_end = datetime(now.year, now.month, 1)

    with get_db() as session:
        receipts = session.query(Receipt).filter(
            Receipt.user_id == user_id,
            Receipt.date >= last_month_start,
            Receipt.date < last_month_end
        ).all()
        receipt_total = sum(r.total_amount or 0 for r in receipts)

        invoices = session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_status == InvoiceStatus.PAID,
            Document.invoice_paid_date >= last_month_start,
            Document.invoice_paid_date < last_month_end
        ).all()
        invoice_total = sum(i.invoice_amount or 0 for i in invoices)

        return receipt_total + invoice_total


def get_monthly_expenses_data(user_id: int, months: int = 6) -> list:
    """Monatliche Ausgaben der letzten X Monate"""
    data = []
    now = datetime.now()

    for i in range(months - 1, -1, -1):
        if now.month - i <= 0:
            year = now.year - 1
            month = 12 + (now.month - i)
        else:
            year = now.year
            month = now.month - i

        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)

        with get_db() as session:
            receipts = session.query(Receipt).filter(
                Receipt.user_id == user_id,
                Receipt.date >= month_start,
                Receipt.date < month_end
            ).all()
            receipt_total = sum(r.total_amount or 0 for r in receipts)

            invoices = session.query(Document).filter(
                Document.user_id == user_id,
                Document.invoice_status == InvoiceStatus.PAID,
                Document.invoice_paid_date >= month_start,
                Document.invoice_paid_date < month_end
            ).all()
            invoice_total = sum(i.invoice_amount or 0 for i in invoices)

        data.append({
            'month': month_start.strftime('%b'),
            'amount': receipt_total + invoice_total
        })

    return data


def get_overdue_invoices(user_id: int) -> list:
    """Überfällige Rechnungen"""
    invoices = []
    with get_db() as session:
        docs = session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_status == InvoiceStatus.OPEN,
            Document.invoice_due_date.isnot(None),
            Document.invoice_due_date < datetime.now()
        ).order_by(Document.invoice_due_date).all()

        for doc in docs:
            days_left = (doc.invoice_due_date.date() - datetime.now().date()).days
            invoices.append({
                'id': doc.id,
                'sender': doc.sender or doc.title or 'Unbekannt',
                'amount': doc.invoice_amount or 0,
                'due_date': format_date(doc.invoice_due_date),
                'days_left': days_left
            })

    return invoices


def get_open_invoices(user_id: int, limit: int = 10) -> list:
    """Offene Rechnungen"""
    invoices = []
    with get_db() as session:
        docs = session.query(Document).filter(
            Document.user_id == user_id,
            Document.invoice_status == InvoiceStatus.OPEN
        ).order_by(Document.invoice_due_date.asc().nullslast()).limit(limit).all()

        for doc in docs:
            days_left = None
            if doc.invoice_due_date:
                days_left = (doc.invoice_due_date.date() - datetime.now().date()).days

            invoices.append({
                'id': doc.id,
                'sender': doc.sender or doc.title or 'Unbekannt',
                'amount': doc.invoice_amount or 0,
                'due_date': format_date(doc.invoice_due_date) if doc.invoice_due_date else None,
                'days_left': days_left
            })

    return invoices


def get_upcoming_deadlines(user_id: int, days: int = 30, limit: int = 10) -> list:
    """Anstehende Fristen"""
    deadlines = []
    with get_db() as session:
        events = session.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_date >= datetime.now(),
            CalendarEvent.start_date <= datetime.now() + timedelta(days=days)
        ).order_by(CalendarEvent.start_date).limit(limit).all()

        for event in events:
            days_left = calculate_days_until(event.start_date)
            if days_left == 0:
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
                'type': event.event_type.value if event.event_type else 'reminder'
            })

    return deadlines


def get_expiring_contracts(user_id: int, days: int = 90) -> list:
    """Auslaufende Verträge"""
    contracts = []
    with get_db() as session:
        docs = session.query(Document).filter(
            Document.user_id == user_id,
            Document.contract_end.isnot(None),
            Document.contract_end >= datetime.now(),
            Document.contract_end <= datetime.now() + timedelta(days=days)
        ).order_by(Document.contract_end).all()

        for doc in docs:
            contracts.append({
                'id': doc.id,
                'title': doc.title or doc.sender or 'Vertrag',
                'end_date': format_date(doc.contract_end),
                'notice_days': doc.contract_notice_period or 'N/A',
                'days_until_end': (doc.contract_end.date() - datetime.now().date()).days
            })

    return contracts


def get_all_contracts(user_id: int) -> list:
    """Alle Verträge"""
    contracts = []
    with get_db() as session:
        docs = session.query(Document).filter(
            Document.user_id == user_id,
            Document.contract_number.isnot(None) | Document.contract_start.isnot(None) | Document.contract_end.isnot(None)
        ).order_by(Document.contract_end.asc().nullslast()).all()

        for doc in docs:
            days_until_end = None
            if doc.contract_end:
                days_until_end = (doc.contract_end.date() - datetime.now().date()).days

            contracts.append({
                'id': doc.id,
                'title': doc.title or doc.sender or 'Vertrag',
                'start_date': format_date(doc.contract_start) if doc.contract_start else None,
                'end_date': format_date(doc.contract_end) if doc.contract_end else None,
                'notice_days': doc.contract_notice_period,
                'days_until_end': days_until_end
            })

    return contracts


def get_recent_documents(user_id: int, limit: int = 5) -> list:
    """Neueste Dokumente"""
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
                'date': format_date(doc.created_at),
                'sender': doc.sender
            })

    return documents


def get_upcoming_birthdays(user_id: int, limit: int = 5) -> list:
    """Anstehende Geburtstage"""
    birthdays = []
    with get_db() as session:
        contacts = session.query(Contact).filter(
            Contact.user_id == user_id,
            Contact.birthday.isnot(None)
        ).all()

        today = datetime.now()
        for contact in contacts:
            if contact.birthday:
                bday_this_year = contact.birthday.replace(year=today.year)
                if bday_this_year.date() < today.date():
                    bday_this_year = bday_this_year.replace(year=today.year + 1)

                days_until = (bday_this_year.date() - today.date()).days
                if 0 <= days_until <= 30:
                    birthdays.append({
                        'name': contact.name,
                        'date': bday_this_year.strftime("%d. %B"),
                        'days_until': days_until
                    })

        birthdays.sort(key=lambda x: x['days_until'])

    return birthdays[:limit]


# Hauptanwendung
def main():
    # Aktuelle Seite in Session speichern für Navigation-Highlighting
    st.session_state['_current_page'] = 'streamlit_app.py'

    # Neue smarte Navigation rendern
    render_sidebar_with_navigation()

    # Dashboard anzeigen
    render_dashboard()


if __name__ == "__main__":
    main()
