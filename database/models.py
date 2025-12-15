"""
SQLAlchemy-Modelle für die Dokumentenmanagement-App
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Float, ForeignKey, LargeBinary, JSON, Enum as SQLEnum,
    Table, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()


# Re-export get_session für einfachere Imports
def get_session():
    """Wrapper für database.db.get_session()"""
    from database.db import get_session as _get_session
    return _get_session()


class DocumentStatus(enum.Enum):
    """Status eines Dokuments"""
    PENDING = "pending"          # Noch nicht verarbeitet
    PROCESSING = "processing"    # Wird verarbeitet
    COMPLETED = "completed"      # Verarbeitung abgeschlossen
    ERROR = "error"              # Fehler bei Verarbeitung


class InvoiceStatus(enum.Enum):
    """Status einer Rechnung"""
    OPEN = "open"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class EventType(enum.Enum):
    """Typ eines Kalendereintrags"""
    DEADLINE = "deadline"
    BIRTHDAY = "birthday"
    APPOINTMENT = "appointment"
    REMINDER = "reminder"
    CONTRACT_END = "contract_end"


# Assoziationstabelle für Dokument-Tags
document_tags = Table(
    'document_tags',
    Base.metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

# Assoziationstabelle für virtuelle Ordner-Zuordnungen (Dokument kann in mehreren Ordnern sein)
document_virtual_folders = Table(
    'document_virtual_folders',
    Base.metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('folder_id', Integer, ForeignKey('folders.id'), primary_key=True),
    Column('is_primary', Boolean, default=False),  # Hauptordner
    Column('created_at', DateTime, default=func.now())
)


class Property(Base):
    """Immobilien-Modell für Zuordnung von Dokumenten zu Objekten"""
    __tablename__ = 'properties'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Adressdaten
    name = Column(String(255))  # Kurzname z.B. "Mietwohnung Berlin"
    street = Column(String(255))
    house_number = Column(String(20))
    postal_code = Column(String(10))
    city = Column(String(100))
    country = Column(String(100), default="Deutschland")

    # Typ
    property_type = Column(String(50))  # Eigentum, Miete, Gewerbe
    usage = Column(String(50))  # Selbstgenutzt, Vermietet

    # Referenzen
    owner = Column(String(255))  # Eigentümer/Vermieter
    management = Column(String(255))  # Hausverwaltung

    # Zeitraum
    acquired_date = Column(DateTime)  # Kauf/Einzugsdatum
    sold_date = Column(DateTime)  # Verkauf/Auszugsdatum

    # Notizen
    notes = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    documents = relationship("Document", back_populates="property")

    @property
    def full_address(self):
        """Gibt die vollständige Adresse zurück"""
        parts = []
        if self.street:
            addr = self.street
            if self.house_number:
                addr += f" {self.house_number}"
            parts.append(addr)
        if self.postal_code or self.city:
            parts.append(f"{self.postal_code or ''} {self.city or ''}".strip())
        return ", ".join(parts) if parts else self.name

    __table_args__ = (
        Index('idx_property_user', 'user_id'),
        Index('idx_property_address', 'street', 'postal_code', 'city'),
    )


class User(Base):
    """Benutzermodell"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255))
    created_at = Column(DateTime, default=func.now())
    last_login = Column(DateTime)
    is_active = Column(Boolean, default=True)
    encryption_key_hash = Column(String(255))  # Für Dokumentenverschlüsselung

    # Beziehungen
    documents = relationship("Document", back_populates="user")
    folders = relationship("Folder", back_populates="user")
    contacts = relationship("Contact", back_populates="user")
    carts = relationship("Cart", back_populates="user")
    bank_accounts = relationship("BankAccount", back_populates="user")


class Folder(Base):
    """Ordnerstruktur für Dokumente"""
    __tablename__ = 'folders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey('folders.id'), nullable=True)
    is_system = Column(Boolean, default=False)  # Systemordner können nicht gelöscht werden
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    icon = Column(String(50))  # Emoji oder Icon-Name
    color = Column(String(7))  # Hex-Farbcode

    # Beziehungen
    user = relationship("User", back_populates="folders")
    parent = relationship("Folder", remote_side=[id], backref="children")
    documents = relationship("Document", back_populates="folder")

    __table_args__ = (
        UniqueConstraint('user_id', 'name', 'parent_id', name='unique_folder_name'),
    )


class Document(Base):
    """Hauptmodell für Dokumente"""
    __tablename__ = 'documents'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    folder_id = Column(Integer, ForeignKey('folders.id'))

    # Basisdaten
    title = Column(String(500))
    filename = Column(String(255), nullable=False)
    file_path = Column(String(1000))  # Pfad zur verschlüsselten Datei
    file_size = Column(Integer)
    mime_type = Column(String(100))

    # Verschlüsselung
    is_encrypted = Column(Boolean, default=True)
    encryption_iv = Column(LargeBinary)  # Initialisierungsvektor

    # Duplikaterkennung
    content_hash = Column(String(64), index=True)  # SHA-256 Hash des Inhalts

    # Status
    status = Column(SQLEnum(DocumentStatus), default=DocumentStatus.PENDING)
    processing_error = Column(Text)

    # OCR & Extraktion
    ocr_text = Column(Text)  # Volltext aus OCR
    ocr_confidence = Column(Float)  # Konfidenz der OCR

    # Extrahierte Metadaten
    sender = Column(String(500))          # Absender
    sender_address = Column(Text)          # Absender-Adresse
    document_date = Column(DateTime)       # Dokumentendatum
    subject = Column(String(1000))         # Betreff
    category = Column(String(100))         # Kategorie
    ai_summary = Column(Text)              # KI-generierte Zusammenfassung

    # Referenznummern
    reference_number = Column(String(100))  # Aktenzeichen
    customer_number = Column(String(100))   # Kundennummer
    insurance_number = Column(String(100))  # Versicherungsnummer
    processing_number = Column(String(100)) # Bearbeitungsnummer

    # Rechnungsspezifisch
    invoice_number = Column(String(100))    # Rechnungsnummer
    invoice_amount = Column(Float)
    invoice_currency = Column(String(3), default="EUR")
    invoice_status = Column(SQLEnum(InvoiceStatus))
    invoice_due_date = Column(DateTime)
    invoice_paid_date = Column(DateTime)
    paid_with_bank_account = Column(String(200))  # Name des Bankkontos für Zahlung
    iban = Column(String(34))
    bic = Column(String(11))
    bank_name = Column(String(200))         # Name der Bank des Rechnungsstellers

    # Vertragsspezifisch
    contract_number = Column(String(100))
    contract_start = Column(DateTime)
    contract_end = Column(DateTime)
    contract_notice_period = Column(Integer)  # Kündigungsfrist in Tagen

    # Zeitstempel
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Workflow-Status
    workflow_status = Column(String(50), default="new")  # new, in_review, action_required, waiting, completed, archived

    # Soft Delete (Papierkorb)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime)  # Wann wurde das Dokument gelöscht
    previous_folder_id = Column(Integer)  # Vorheriger Ordner vor Löschung

    # Immobilien-Zuordnung
    property_id = Column(Integer, ForeignKey('properties.id'))
    property_address = Column(String(500))  # Extrahierte Adresse aus Dokument (Leistungsort)

    # Beziehungen
    user = relationship("User", back_populates="documents")
    folder = relationship("Folder", back_populates="documents")
    property = relationship("Property", back_populates="documents")
    virtual_folders = relationship("Folder", secondary=document_virtual_folders, backref="virtual_documents")
    tags = relationship("Tag", secondary=document_tags, back_populates="documents")
    calendar_events = relationship("CalendarEvent", back_populates="document")
    notes = relationship("DocumentNote", back_populates="document", cascade="all, delete-orphan")
    shares = relationship("DocumentShare", back_populates="document", cascade="all, delete-orphan")

    # Indizes für schnelle Suche
    __table_args__ = (
        Index('idx_document_sender', 'sender'),
        Index('idx_document_category', 'category'),
        Index('idx_document_date', 'document_date'),
        Index('idx_document_user_folder', 'user_id', 'folder_id'),
        Index('idx_document_deleted', 'is_deleted', 'deleted_at'),
    )


class Tag(Base):
    """Tags für Dokumente"""
    __tablename__ = 'tags'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    color = Column(String(7))  # Hex-Farbcode

    documents = relationship("Document", secondary=document_tags, back_populates="tags")


# Alias für Rückwärtskompatibilität
DocumentTag = document_tags


class CalendarEvent(Base):
    """Kalendereinträge"""
    __tablename__ = 'calendar_events'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))
    contact_id = Column(Integer, ForeignKey('contacts.id'))

    title = Column(String(500), nullable=False)
    description = Column(Text)
    event_type = Column(SQLEnum(EventType), default=EventType.REMINDER)

    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    all_day = Column(Boolean, default=True)

    # Wiederholung
    is_recurring = Column(Boolean, default=False)
    recurrence_rule = Column(String(255))  # iCal RRULE Format

    # Erinnerungen
    reminder_sent = Column(Boolean, default=False)
    reminder_days_before = Column(Integer, default=7)

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    document = relationship("Document", back_populates="calendar_events")
    contact = relationship("Contact", back_populates="calendar_events")

    __table_args__ = (
        Index('idx_event_date', 'start_date'),
        Index('idx_event_user', 'user_id'),
    )


class Contact(Base):
    """Kontakte"""
    __tablename__ = 'contacts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    name = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(50))
    address = Column(Text)
    company = Column(String(255))
    birthday = Column(DateTime)
    notes = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User", back_populates="contacts")
    calendar_events = relationship("CalendarEvent", back_populates="contact")


class Email(Base):
    """E-Mail-Nachrichten"""
    __tablename__ = 'emails'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))

    message_id = Column(String(255))  # E-Mail Message-ID
    folder = Column(String(100), default="inbox")  # inbox, sent, trash, etc.

    from_address = Column(String(255))
    to_addresses = Column(Text)  # JSON-Array
    cc_addresses = Column(Text)  # JSON-Array
    subject = Column(String(1000))
    body_text = Column(Text)
    body_html = Column(Text)

    received_at = Column(DateTime)
    sent_at = Column(DateTime)
    is_read = Column(Boolean, default=False)
    is_flagged = Column(Boolean, default=False)
    has_attachments = Column(Boolean, default=False)

    # Für KI-Antwortvorschläge
    needs_response = Column(Boolean, default=False)
    response_draft = Column(Text)

    created_at = Column(DateTime, default=func.now())


class SmartFolder(Base):
    """Intelligente Ordner basierend auf Filterregeln"""
    __tablename__ = 'smart_folders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text)
    icon = Column(String(50))
    color = Column(String(7))

    # Filterregeln als JSON
    # Format: {"category": "Rechnung", "invoice_status": "open", "date_range": {...}}
    filter_rules = Column(JSON, nullable=False)

    # Sortierung
    sort_by = Column(String(50), default="document_date")
    sort_order = Column(String(4), default="desc")

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Cart(Base):
    """Aktentasche für Dokumentensammlungen"""
    __tablename__ = 'carts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)  # Aktuelle Aktentasche

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User", back_populates="carts")
    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    """Dokumente in einer Aktentasche"""
    __tablename__ = 'cart_items'

    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey('carts.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    added_at = Column(DateTime, default=func.now())
    notes = Column(Text)

    cart = relationship("Cart", back_populates="items")
    document = relationship("Document")

    __table_args__ = (
        UniqueConstraint('cart_id', 'document_id', name='unique_cart_document'),
    )


class Receipt(Base):
    """Kassenbons für Finanzverwaltung"""
    __tablename__ = 'receipts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    group_id = Column(Integer, ForeignKey('receipt_groups.id'))
    document_id = Column(Integer, ForeignKey('documents.id'))

    merchant = Column(String(255))
    date = Column(DateTime, nullable=False)
    total_amount = Column(Float, nullable=False)
    currency = Column(String(3), default="EUR")
    category = Column(String(100))

    # Für Gruppenteilung
    paid_by_member_id = Column(Integer, ForeignKey('receipt_group_members.id'))

    # Positionen als JSON (optional)
    items = Column(JSON)  # [{"name": "...", "price": 1.99, "quantity": 1}]

    notes = Column(Text)
    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    group = relationship("ReceiptGroup", back_populates="receipts")
    document = relationship("Document")
    paid_by = relationship("ReceiptGroupMember", foreign_keys=[paid_by_member_id])


class ReceiptGroup(Base):
    """Gruppen für gemeinsames Bon-Teilen"""
    __tablename__ = 'receipt_groups'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)  # Ersteller

    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Zeitraum
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    is_active = Column(Boolean, default=True)

    # Erinnerungen
    reminder_sent = Column(Boolean, default=False)
    last_activity = Column(DateTime, default=func.now())

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    members = relationship("ReceiptGroupMember", back_populates="group", cascade="all, delete-orphan")
    receipts = relationship("Receipt", back_populates="group")


class ReceiptGroupMember(Base):
    """Mitglieder einer Bon-Teilungsgruppe"""
    __tablename__ = 'receipt_group_members'

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('receipt_groups.id'), nullable=False)

    name = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(50))

    # Individuelle Teilungsquote (Standard: gleichmäßig)
    share_percentage = Column(Float)  # None = gleichmäßig

    # Einladung
    invitation_sent = Column(Boolean, default=False)
    invitation_accepted = Column(Boolean, default=False)
    access_token = Column(String(255))  # Für Gastzugang

    created_at = Column(DateTime, default=func.now())

    group = relationship("ReceiptGroup", back_populates="members")


class ClassificationRule(Base):
    """Selbstlernende Regeln für Dokumentenklassifikation"""
    __tablename__ = 'classification_rules'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Erkennungsmerkmale
    sender_pattern = Column(String(500))     # Regex oder exakter Match
    subject_keywords = Column(JSON)           # Liste von Schlüsselwörtern
    category = Column(String(100))

    # Zielordner
    target_folder_id = Column(Integer, ForeignKey('folders.id'))

    # Statistik
    times_applied = Column(Integer, default=0)
    confidence = Column(Float, default=0.5)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    target_folder = relationship("Folder")

    __table_args__ = (
        Index('idx_rule_sender', 'sender_pattern'),
    )


class SearchIndex(Base):
    """Volltextindex für Dokumente (zusätzlich zu Whoosh)"""
    __tablename__ = 'search_index'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False, unique=True)

    # Indexierte Felder
    content = Column(Text)  # Volltext
    keywords = Column(JSON)  # Extrahierte Schlüsselwörter

    # Metadaten für schnelle Filterung
    amounts = Column(JSON)   # Gefundene Beträge
    ibans = Column(JSON)     # Gefundene IBANs
    dates = Column(JSON)     # Gefundene Daten

    indexed_at = Column(DateTime, default=func.now())

    document = relationship("Document")


class BankAccount(Base):
    """Bankkonten für Zahlungsverfolgung"""
    __tablename__ = 'bank_accounts'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Bank-Informationen
    bank_name = Column(String(255), nullable=False)  # z.B. "Sparkasse", "ING"
    account_name = Column(String(255), nullable=False)  # z.B. "Girokonto", "Tagesgeld"
    iban = Column(String(34))
    bic = Column(String(11))

    # Anzeige
    color = Column(String(7), default="#1976D2")  # Hex-Farbe für UI
    icon = Column(String(50), default="🏦")  # Emoji oder Icon

    # Status
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)  # Standard-Konto für Zahlungen

    # Notizen
    notes = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehung
    user = relationship("User", back_populates="bank_accounts")

    def display_name(self):
        """Anzeigename: Bank - Kontoname"""
        return f"{self.bank_name} - {self.account_name}"

    __table_args__ = (
        UniqueConstraint('user_id', 'bank_name', 'account_name', name='unique_bank_account'),
    )


class WorkflowStatus(enum.Enum):
    """Workflow-Status für Dokumente"""
    NEW = "new"                    # Neu eingetroffen
    IN_REVIEW = "in_review"        # Wird geprüft
    ACTION_REQUIRED = "action_required"  # Aktion erforderlich
    WAITING = "waiting"            # Wartet auf Antwort
    COMPLETED = "completed"        # Erledigt
    ARCHIVED = "archived"          # Archiviert


class DocumentNote(Base):
    """Notizen und Kommentare zu Dokumenten"""
    __tablename__ = 'document_notes'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    content = Column(Text, nullable=False)
    is_private = Column(Boolean, default=False)  # Nur für eigenen Benutzer sichtbar

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    document = relationship("Document", back_populates="notes")
    user = relationship("User")

    __table_args__ = (
        Index('idx_note_document', 'document_id'),
    )


class DocumentShare(Base):
    """Temporäre Freigabe-Links für Dokumente"""
    __tablename__ = 'document_shares'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Einzigartiger Token für den Link
    share_token = Column(String(64), unique=True, nullable=False)

    # Beschreibung/Zweck
    description = Column(String(500))

    # Gültigkeit
    expires_at = Column(DateTime, nullable=False)
    max_views = Column(Integer)  # None = unbegrenzt
    view_count = Column(Integer, default=0)

    # Berechtigungen
    allow_download = Column(Boolean, default=True)

    # Status
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    last_accessed = Column(DateTime)

    # Beziehungen
    document = relationship("Document", back_populates="shares")
    user = relationship("User")

    __table_args__ = (
        Index('idx_share_token', 'share_token'),
        Index('idx_share_expires', 'expires_at'),
    )


class AuditLog(Base):
    """Protokollierung aller wichtigen Aktionen"""
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Was wurde geändert
    entity_type = Column(String(50), nullable=False)  # document, folder, contact, etc.
    entity_id = Column(Integer, nullable=False)

    # Art der Änderung
    action = Column(String(50), nullable=False)  # create, update, delete, view, download, share
    action_detail = Column(String(500))  # Details zur Änderung

    # Vorher/Nachher für Updates
    old_values = Column(JSON)
    new_values = Column(JSON)

    # Metadaten
    ip_address = Column(String(45))
    user_agent = Column(String(500))

    created_at = Column(DateTime, default=func.now())

    # Beziehung
    user = relationship("User")

    __table_args__ = (
        Index('idx_audit_entity', 'entity_type', 'entity_id'),
        Index('idx_audit_user', 'user_id'),
        Index('idx_audit_date', 'created_at'),
    )


class Notification(Base):
    """Benachrichtigungen für Benutzer"""
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Verknüpfung (optional)
    document_id = Column(Integer, ForeignKey('documents.id'))
    event_id = Column(Integer, ForeignKey('calendar_events.id'))

    # Inhalt
    title = Column(String(255), nullable=False)
    message = Column(Text)
    notification_type = Column(String(50))  # deadline, invoice, contract, birthday, reminder

    # Status
    is_read = Column(Boolean, default=False)
    is_sent_email = Column(Boolean, default=False)
    is_sent_push = Column(Boolean, default=False)

    # Timing
    scheduled_for = Column(DateTime)  # Wann soll benachrichtigt werden
    sent_at = Column(DateTime)

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    user = relationship("User")
    document = relationship("Document")
    event = relationship("CalendarEvent")

    __table_args__ = (
        Index('idx_notification_user', 'user_id'),
        Index('idx_notification_scheduled', 'scheduled_for'),
    )


class RecurringPattern(Base):
    """Erkennung wiederkehrender Rechnungen/Zahlungen"""
    __tablename__ = 'recurring_patterns'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Erkennungsmerkmale
    sender_pattern = Column(String(500))  # Absender-Muster
    amount_min = Column(Float)  # Betragsbereich
    amount_max = Column(Float)
    typical_amount = Column(Float)  # Typischer Betrag

    # Wiederholungsmuster
    frequency = Column(String(20))  # monthly, quarterly, yearly
    typical_day = Column(Integer)  # Typischer Tag im Monat (1-31)

    # Vorhersage
    next_expected = Column(DateTime)
    last_occurrence = Column(DateTime)

    # Statistik
    occurrence_count = Column(Integer, default=0)
    confidence = Column(Float, default=0.5)

    # Beschreibung
    name = Column(String(255))  # z.B. "Miete", "Strom", "Netflix"
    category = Column(String(100))

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehung
    user = relationship("User")

    __table_args__ = (
        Index('idx_recurring_user', 'user_id'),
        Index('idx_recurring_next', 'next_expected'),
    )


class BankConnection(Base):
    """Verbindung zu einer Bank über Nordigen/GoCardless"""
    __tablename__ = 'bank_connections'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    bank_account_id = Column(Integer, ForeignKey('bank_accounts.id'))  # Verknüpfung zu manuellem Konto

    # Nordigen-spezifisch
    institution_id = Column(String(100), nullable=False)  # Nordigen Institution ID
    institution_name = Column(String(255))
    institution_logo = Column(String(500))  # URL zum Logo

    # Requisition (Verbindungsanfrage)
    requisition_id = Column(String(100))
    agreement_id = Column(String(100))

    # Konto-Informationen von Nordigen
    account_id = Column(String(100))  # Nordigen Account ID
    iban = Column(String(34))
    account_name = Column(String(255))
    account_type = Column(String(50))  # checking, savings, etc.
    currency = Column(String(3), default="EUR")

    # Status
    status = Column(String(50), default="pending")  # pending, active, expired, error
    last_sync = Column(DateTime)
    sync_error = Column(Text)

    # Verfügbare Daten
    balance_available = Column(Float)
    balance_booked = Column(Float)

    # Gültigkeit
    valid_until = Column(DateTime)  # Wann läuft die Verbindung ab

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    bank_account = relationship("BankAccount")
    transactions = relationship("BankTransaction", back_populates="connection", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_bank_conn_user', 'user_id'),
        Index('idx_bank_conn_account', 'account_id'),
    )


class BankTransaction(Base):
    """Banktransaktionen von verbundenen Konten"""
    __tablename__ = 'bank_transactions'

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey('bank_connections.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Nordigen Transaction ID
    transaction_id = Column(String(100), unique=True)

    # Transaktionsdaten
    booking_date = Column(DateTime)
    value_date = Column(DateTime)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="EUR")

    # Details
    creditor_name = Column(String(500))  # Empfänger
    creditor_iban = Column(String(34))
    debtor_name = Column(String(500))  # Absender
    debtor_iban = Column(String(34))

    # Verwendungszweck
    remittance_info = Column(Text)  # Verwendungszweck
    reference = Column(String(255))  # Referenz

    # Klassifikation
    category = Column(String(100))  # Automatisch oder manuell zugewiesen
    is_categorized = Column(Boolean, default=False)

    # Verknüpfung zu Dokumenten
    document_id = Column(Integer, ForeignKey('documents.id'))  # Zugeordnete Rechnung
    receipt_id = Column(Integer, ForeignKey('receipts.id'))  # Zugeordneter Bon

    # Status
    is_booked = Column(Boolean, default=True)  # Gebucht vs. Vormerkung
    is_internal = Column(Boolean, default=False)  # Interne Umbuchung

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    connection = relationship("BankConnection", back_populates="transactions")
    user = relationship("User")
    document = relationship("Document")
    receipt = relationship("Receipt")

    __table_args__ = (
        Index('idx_transaction_date', 'booking_date'),
        Index('idx_transaction_user', 'user_id'),
        Index('idx_transaction_connection', 'connection_id'),
    )


class TodoStatus(enum.Enum):
    """Status einer Aufgabe"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TodoPriority(enum.Enum):
    """Priorität einer Aufgabe"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Todo(Base):
    """To-Do Aufgaben"""
    __tablename__ = 'todos'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Inhalt
    title = Column(String(500), nullable=False)
    description = Column(Text)

    # Status und Priorität
    status = Column(SQLEnum(TodoStatus), default=TodoStatus.OPEN)
    priority = Column(SQLEnum(TodoPriority), default=TodoPriority.MEDIUM)

    # Termine
    due_date = Column(DateTime)  # Fälligkeitsdatum
    reminder_date = Column(DateTime)  # Erinnerung

    # Kategorisierung
    category = Column(String(100))
    tags = Column(JSON)  # Liste von Tags

    # Verknüpfungen (optional)
    document_id = Column(Integer, ForeignKey('documents.id'))
    event_id = Column(Integer, ForeignKey('calendar_events.id'))

    # Wiederholung
    is_recurring = Column(Boolean, default=False)
    recurrence_rule = Column(String(255))  # iCal RRULE

    # Erstellung per Sprache
    created_by_voice = Column(Boolean, default=False)
    original_voice_text = Column(Text)  # Original-Transkription

    # Zeitstempel
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    document = relationship("Document")
    event = relationship("CalendarEvent")

    __table_args__ = (
        Index('idx_todo_user', 'user_id'),
        Index('idx_todo_status', 'status'),
        Index('idx_todo_due', 'due_date'),
    )


class AlarmType(enum.Enum):
    """Typ eines Alarms"""
    ALARM = "alarm"        # Wecker
    TIMER = "timer"        # Countdown-Timer
    REMINDER = "reminder"  # Erinnerung


class Alarm(Base):
    """Wecker und Timer"""
    __tablename__ = 'alarms'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Typ und Inhalt
    alarm_type = Column(SQLEnum(AlarmType), default=AlarmType.ALARM)
    title = Column(String(255))
    message = Column(Text)

    # Zeitpunkt
    trigger_time = Column(DateTime, nullable=False)  # Wann soll der Alarm ausgelöst werden
    duration_seconds = Column(Integer)  # Für Timer: ursprüngliche Dauer

    # Wiederholung (für Wecker)
    is_recurring = Column(Boolean, default=False)
    recurrence_days = Column(JSON)  # [0,1,2,3,4,5,6] für Wochentage (0=Montag)

    # Sound
    sound = Column(String(100), default="default")  # Alarmton

    # Status
    is_active = Column(Boolean, default=True)
    is_triggered = Column(Boolean, default=False)
    triggered_at = Column(DateTime)
    snoozed_until = Column(DateTime)  # Schlummerfunktion

    # Erstellung per Sprache
    created_by_voice = Column(Boolean, default=False)
    original_voice_text = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehung
    user = relationship("User")

    __table_args__ = (
        Index('idx_alarm_user', 'user_id'),
        Index('idx_alarm_trigger', 'trigger_time'),
        Index('idx_alarm_active', 'is_active'),
    )


class VoiceCommand(Base):
    """Protokoll aller Sprachbefehle"""
    __tablename__ = 'voice_commands'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Original-Text
    transcribed_text = Column(Text, nullable=False)

    # Erkannter Befehl
    command_type = Column(String(50))  # calendar, reminder, alarm, timer, todo
    parsed_data = Column(JSON)  # Extrahierte Daten

    # Ergebnis
    was_successful = Column(Boolean, default=False)
    result_message = Column(Text)
    created_entity_type = Column(String(50))  # Welcher Typ wurde erstellt
    created_entity_id = Column(Integer)  # ID der erstellten Entität

    # Fehler
    error_message = Column(Text)

    created_at = Column(DateTime, default=func.now())

    # Beziehung
    user = relationship("User")

    __table_args__ = (
        Index('idx_voice_cmd_user', 'user_id'),
        Index('idx_voice_cmd_type', 'command_type'),
    )
