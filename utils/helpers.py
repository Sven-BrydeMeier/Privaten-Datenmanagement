"""
Allgemeine Hilfsfunktionen
"""
import re
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import streamlit as st


def format_currency(amount: float, currency: str = "EUR") -> str:
    """Formatiert einen Betrag als Währung"""
    symbols = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}
    symbol = symbols.get(currency, currency)

    # Deutsche Formatierung
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} {symbol}"


def format_date(date: Optional[datetime], include_time: bool = False) -> str:
    """Formatiert ein Datum im deutschen Format"""
    if date is None:
        return "-"

    if include_time:
        return date.strftime("%d.%m.%Y %H:%M")
    return date.strftime("%d.%m.%Y")


def parse_german_date(date_str: str) -> Optional[datetime]:
    """Parst ein deutsches Datum"""
    formats = [
        "%d.%m.%Y",
        "%d.%m.%y",
        "%Y-%m-%d",
        "%d/%m/%Y"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue

    return None


def generate_share_link(document_id: int, expires_hours: int = 168) -> str:
    """
    Generiert einen Freigabelink für ein Dokument.

    Args:
        document_id: Dokument-ID
        expires_hours: Gültigkeit in Stunden (Standard: 7 Tage)

    Returns:
        Freigabe-Token
    """
    # Token generieren
    random_part = uuid.uuid4().hex[:16]
    timestamp = datetime.now().isoformat()
    data = f"{document_id}:{timestamp}:{random_part}"

    # Hash für Verifizierung
    token_hash = hashlib.sha256(data.encode()).hexdigest()[:32]
    token = f"{document_id}_{random_part}_{token_hash}"

    # In Session speichern (in Produktion: Datenbank)
    if 'share_links' not in st.session_state:
        st.session_state.share_links = {}

    st.session_state.share_links[token] = {
        'document_id': document_id,
        'created_at': datetime.now(),
        'expires_at': datetime.now() + timedelta(hours=expires_hours)
    }

    return token


def verify_share_link(token: str) -> Optional[int]:
    """
    Verifiziert einen Freigabelink.

    Args:
        token: Das Token

    Returns:
        Dokument-ID wenn gültig, sonst None
    """
    if 'share_links' not in st.session_state:
        return None

    link_data = st.session_state.share_links.get(token)
    if not link_data:
        return None

    if datetime.now() > link_data['expires_at']:
        # Abgelaufen
        del st.session_state.share_links[token]
        return None

    return link_data['document_id']


def send_email_notification(
    to_email: str,
    subject: str,
    body: str,
    attachments: list = None
) -> bool:
    """
    Sendet eine E-Mail-Benachrichtigung.

    Args:
        to_email: Empfänger
        subject: Betreff
        body: Inhalt
        attachments: Optionale Anhänge

    Returns:
        True wenn erfolgreich
    """
    from config.settings import get_settings
    settings = get_settings()

    if not settings.smtp_server or not settings.smtp_username:
        st.warning("E-Mail ist nicht konfiguriert")
        return False

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg['From'] = settings.smtp_username
        msg['To'] = to_email
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Anhänge hinzufügen
        if attachments:
            for filename, data in attachments:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(data)
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{filename}"'
                )
                msg.attach(part)

        # Senden
        with smtplib.SMTP(settings.smtp_server, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)

        return True

    except Exception as e:
        st.error(f"E-Mail-Versand fehlgeschlagen: {e}")
        return False


def calculate_days_until(date: datetime) -> int:
    """Berechnet Tage bis zu einem Datum"""
    if date is None:
        return 0
    delta = date.date() - datetime.now().date()
    return delta.days


def is_deadline_urgent(deadline: datetime, warning_days: int = 7) -> bool:
    """Prüft ob eine Frist dringend ist"""
    days = calculate_days_until(deadline)
    return 0 <= days <= warning_days


def is_deadline_overdue(deadline: datetime) -> bool:
    """Prüft ob eine Frist überschritten ist"""
    return calculate_days_until(deadline) < 0


def extract_iban(text: str) -> Optional[str]:
    """Extrahiert eine IBAN aus Text"""
    pattern = r'\b([A-Z]{2}\d{2}\s*(?:\d{4}\s*){4,7}\d{1,4})\b'
    match = re.search(pattern, text.upper())
    if match:
        return match.group(1).replace(' ', '')
    return None


def validate_iban(iban: str) -> bool:
    """Validiert eine IBAN (einfache Prüfung)"""
    iban = iban.replace(' ', '').upper()

    # Längenprüfung
    if len(iban) < 15 or len(iban) > 34:
        return False

    # Format: 2 Buchstaben + 2 Ziffern + Rest
    if not re.match(r'^[A-Z]{2}\d{2}[A-Z0-9]+$', iban):
        return False

    return True


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Kürzt Text auf maximale Länge"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def sanitize_filename(filename: str) -> str:
    """Bereinigt einen Dateinamen"""
    # Ungültige Zeichen entfernen
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')

    # Führende/nachfolgende Leerzeichen und Punkte entfernen
    filename = filename.strip('. ')

    # Maximale Länge
    if len(filename) > 200:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:200] + ('.' + ext if ext else '')

    return filename or 'unnamed'


def get_file_icon(mime_type: str) -> str:
    """Gibt ein passendes Icon für einen MIME-Typ zurück"""
    icons = {
        'application/pdf': '📄',
        'image/jpeg': '🖼️',
        'image/png': '🖼️',
        'image/gif': '🖼️',
        'text/plain': '📝',
        'application/msword': '📃',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '📃',
        'application/vnd.ms-excel': '📊',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '📊',
    }
    return icons.get(mime_type, '📎')
