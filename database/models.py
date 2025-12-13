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

    # Beziehungen
    user = relationship("User", back_populates="documents")
    folder = relationship("Folder", back_populates="documents")
    tags = relationship("Tag", secondary=document_tags, back_populates="documents")
    calendar_events = relationship("CalendarEvent", back_populates="document")

    # Indizes für schnelle Suche
    __table_args__ = (
        Index('idx_document_sender', 'sender'),
        Index('idx_document_category', 'category'),
        Index('idx_document_date', 'document_date'),
        Index('idx_document_user_folder', 'user_id', 'folder_id'),
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
