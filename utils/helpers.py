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


def parse_date_string(date_str: str) -> Optional[datetime]:
    """
    Parst verschiedene Datumsformate aus KI-Antworten.

    Args:
        date_str: Datumsstring in verschiedenen Formaten

    Returns:
        datetime oder None
    """
    if not date_str:
        return None

    # String bereinigen
    date_str = date_str.strip()

    # Versuche zuerst parse_german_date
    result = parse_german_date(date_str)
    if result:
        return result

    # Zusätzliche Formate für KI-Antworten
    formats = [
        "%Y-%m-%d",           # ISO Format
        "%d.%m.%Y",           # Deutsches Format
        "%d.%m.%y",           # Kurzes deutsches Format
        "%Y/%m/%d",           # Alternativ
        "%d-%m-%Y",           # Mit Bindestrichen
        "%B %d, %Y",          # Englisches Format
        "%d. %B %Y",          # Deutsches ausgeschrieben
        "%d %B %Y",           # Ohne Punkt
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Versuche Regex für YYYY-MM-DD irgendwo im String
    iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if iso_match:
        try:
            return datetime(
                int(iso_match.group(1)),
                int(iso_match.group(2)),
                int(iso_match.group(3))
            )
        except ValueError:
            pass

    # Versuche Regex für DD.MM.YYYY
    german_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', date_str)
    if german_match:
        try:
            day = int(german_match.group(1))
            month = int(german_match.group(2))
            year = int(german_match.group(3))
            if year < 100:
                year += 2000 if year < 50 else 1900
            return datetime(year, month, day)
        except ValueError:
            pass

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


def render_share_buttons(title: str, text: str, url: str = None, key_prefix: str = "share"):
    """
    Rendert Teilen-Buttons für WhatsApp und andere Dienste.

    Funktioniert besonders gut auf Mobilgeräten (Handy, iPad).

    Args:
        title: Titel zum Teilen
        text: Text zum Teilen
        url: Optionale URL
        key_prefix: Prefix für Streamlit-Keys
    """
    import urllib.parse

    # Text für WhatsApp vorbereiten
    share_text = f"{title}\n\n{text}"
    if url:
        share_text += f"\n\n{url}"

    encoded_text = urllib.parse.quote(share_text)

    # WhatsApp Link
    whatsapp_url = f"https://wa.me/?text={encoded_text}"

    # Telegram Link
    telegram_url = f"https://t.me/share/url?text={encoded_text}"

    # E-Mail Link
    email_subject = urllib.parse.quote(title)
    email_body = urllib.parse.quote(text + (f"\n\n{url}" if url else ""))
    email_url = f"mailto:?subject={email_subject}&body={email_body}"

    st.markdown("#### 📤 Teilen")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            f'<a href="{whatsapp_url}" target="_blank" style="text-decoration: none;">'
            f'<button style="background-color: #25D366; color: white; border: none; '
            f'padding: 10px 20px; border-radius: 8px; cursor: pointer; width: 100%;">'
            f'📱 WhatsApp</button></a>',
            unsafe_allow_html=True
        )

    with col2:
        st.markdown(
            f'<a href="{telegram_url}" target="_blank" style="text-decoration: none;">'
            f'<button style="background-color: #0088cc; color: white; border: none; '
            f'padding: 10px 20px; border-radius: 8px; cursor: pointer; width: 100%;">'
            f'✈️ Telegram</button></a>',
            unsafe_allow_html=True
        )

    with col3:
        st.markdown(
            f'<a href="{email_url}" style="text-decoration: none;">'
            f'<button style="background-color: #666; color: white; border: none; '
            f'padding: 10px 20px; border-radius: 8px; cursor: pointer; width: 100%;">'
            f'📧 E-Mail</button></a>',
            unsafe_allow_html=True
        )

    # Native Share API für Mobilgeräte (JavaScript)
    title_escaped = title.replace("'", "\\'")
    text_escaped = text.replace("'", "\\'")
    share_js = f"""
    <script>
    function nativeShare_{key_prefix}() {{
        if (navigator.share) {{
            navigator.share({{
                title: '{title_escaped}',
                text: '{text_escaped}',
                url: '{url or ""}'
            }}).catch(console.error);
        }} else {{
            alert('Native Teilen wird auf diesem Gerät nicht unterstützt. Nutzen Sie die Buttons oben.');
        }}
    }}
    </script>
    <button onclick="nativeShare_{key_prefix}()" style="background-color: #007AFF; color: white;
            border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer;
            width: 100%; margin-top: 10px;">
        📲 Natives Teilen (Mobil)
    </button>
    """
    st.markdown(share_js, unsafe_allow_html=True)


def create_share_text_for_documents(documents: list) -> str:
    """
    Erstellt einen Teilen-Text für eine Liste von Dokumenten.

    Args:
        documents: Liste von Document-Objekten oder Dicts

    Returns:
        Formatierter Text zum Teilen
    """
    lines = ["📁 Dokumentenübersicht", ""]

    for i, doc in enumerate(documents, 1):
        if hasattr(doc, 'title'):
            # Document-Objekt
            name = doc.title or doc.filename
            category = doc.category or "Unkategorisiert"
            date = format_date(doc.document_date or doc.created_at)
            amount = format_currency(doc.invoice_amount) if doc.invoice_amount else None
        else:
            # Dict
            name = doc.get('title') or doc.get('filename', 'Unbekannt')
            category = doc.get('category', 'Unkategorisiert')
            date = doc.get('date', '-')
            amount = doc.get('amount')

        line = f"{i}. {name}"
        if category:
            line += f" [{category}]"
        if date:
            line += f" - {date}"
        if amount:
            line += f" - {amount}"
        lines.append(line)

    lines.append("")
    lines.append(f"Erstellt am: {format_date(datetime.now(), include_time=True)}")

    return "\n".join(lines)


def create_share_text_for_receipt(receipt_data: dict) -> str:
    """
    Erstellt einen Teilen-Text für einen Kassenbon.

    Args:
        receipt_data: Bon-Daten Dict

    Returns:
        Formatierter Text zum Teilen
    """
    lines = ["🧾 Kassenbon", ""]

    if receipt_data.get('merchant'):
        lines.append(f"📍 {receipt_data['merchant']}")

    if receipt_data.get('date'):
        date = receipt_data['date']
        if isinstance(date, datetime):
            date = format_date(date)
        lines.append(f"📅 {date}")

    lines.append("")

    # Positionen
    if receipt_data.get('items'):
        lines.append("Positionen:")
        for item in receipt_data['items']:
            name = item.get('name', 'Artikel')
            price = item.get('price', 0)
            qty = item.get('quantity', 1)
            if qty > 1:
                lines.append(f"  • {name} x{qty}: {format_currency(price * qty)}")
            else:
                lines.append(f"  • {name}: {format_currency(price)}")
        lines.append("")

    if receipt_data.get('total'):
        lines.append(f"💰 Gesamt: {format_currency(receipt_data['total'])}")

    if receipt_data.get('category'):
        lines.append(f"📂 Kategorie: {receipt_data['category']}")

    return "\n".join(lines)


def create_share_text_for_expense_split(group_name: str, members: list, expenses: list) -> str:
    """
    Erstellt einen Teilen-Text für eine Ausgabenaufteilung.

    Args:
        group_name: Name der Gruppe
        members: Liste der Mitglieder
        expenses: Liste der Ausgaben

    Returns:
        Formatierter Text zum Teilen
    """
    lines = [f"👥 Ausgabenaufteilung: {group_name}", ""]

    total = sum(e.get('amount', 0) for e in expenses)
    per_person = total / len(members) if members else 0

    lines.append(f"💰 Gesamtausgaben: {format_currency(total)}")
    lines.append(f"👤 Pro Person: {format_currency(per_person)}")
    lines.append("")

    lines.append("Ausgaben:")
    for expense in expenses:
        name = expense.get('description', 'Ausgabe')
        amount = expense.get('amount', 0)
        paid_by = expense.get('paid_by', 'Unbekannt')
        lines.append(f"  • {name}: {format_currency(amount)} (bezahlt von {paid_by})")

    lines.append("")
    lines.append("Ausgleich nötig:")

    # Einfache Berechnung wer wem schuldet
    if members and expenses:
        payments = {m: 0 for m in members}
        for expense in expenses:
            paid_by = expense.get('paid_by')
            if paid_by in payments:
                payments[paid_by] += expense.get('amount', 0)

        for member in members:
            diff = payments.get(member, 0) - per_person
            if diff > 0.01:
                lines.append(f"  ✅ {member} bekommt {format_currency(diff)} zurück")
            elif diff < -0.01:
                lines.append(f"  ❌ {member} schuldet {format_currency(abs(diff))}")

    return "\n".join(lines)
