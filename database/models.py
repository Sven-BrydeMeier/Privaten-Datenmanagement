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

    # Erweiterte dokumenttyp-spezifische Metadaten (JSON)
    # Für Versicherungen: monthly_rate, surrender_value, payout_amount, payout_date, payout_conditions, remaining_payments
    # Für Verträge: renewal_type, auto_renewal, minimum_term
    # Für Kredite: interest_rate, total_amount, remaining_debt
    extended_metadata = Column(JSON, default=dict)

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
    """E-Mail-Nachrichten mit Verfügungs- und Signatur-Erkennung"""
    __tablename__ = 'emails'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))

    message_id = Column(String(255))  # E-Mail Message-ID
    folder = Column(String(100), default="inbox")  # inbox, sent, trash, etc.

    from_address = Column(String(255))
    from_name = Column(String(255))  # Absender-Name
    to_addresses = Column(Text)  # JSON-Array
    cc_addresses = Column(Text)  # JSON-Array
    bcc_addresses = Column(Text)  # JSON-Array (NEU)
    reply_to = Column(String(255))  # Reply-To Header (NEU)
    subject = Column(String(1000))
    body_text = Column(Text)
    body_html = Column(Text)

    received_at = Column(DateTime)
    sent_at = Column(DateTime)
    is_read = Column(Boolean, default=False)
    is_flagged = Column(Boolean, default=False)
    has_attachments = Column(Boolean, default=False)

    # Threading / Konversation
    in_reply_to = Column(String(255))  # In-Reply-To Header
    references = Column(Text)  # References Header (für Thread)
    conversation_id = Column(String(255))  # Konversations-ID

    # Signatur-Erkennung
    signature_detected = Column(Boolean, default=False)
    signature_id = Column(Integer, ForeignKey('email_signatures.id'))
    signature_confidence = Column(Float)  # Erkennungs-Konfidenz

    # Verfügungs-Erkennung (Disposition)
    has_disposition = Column(Boolean, default=False)
    disposition_type = Column(String(100))  # z.B. "verfuegung", "bitte_veranlassen", "frist"
    disposition_confidence = Column(Float)
    disposition_extracted = Column(Boolean, default=False)  # Wurde Verfügung extrahiert?

    # Klassifikation
    classification_folder_id = Column(Integer, ForeignKey('folders.id'))
    classification_tags = Column(JSON)  # Automatisch erkannte Tags
    classification_confidence = Column(Float)
    classification_reason = Column(Text)  # Warum so klassifiziert
    classification_rule_id = Column(Integer, ForeignKey('email_classification_rules.id'))

    # Verarbeitungsstatus
    processing_status = Column(String(50), default="pending")  # pending, processing, completed, error, review
    processing_error = Column(Text)
    processed_at = Column(DateTime)
    needs_review = Column(Boolean, default=False)  # Bei niedriger Konfidenz

    # Für KI-Antwortvorschläge
    needs_response = Column(Boolean, default=False)
    response_draft = Column(Text)
    response_due_date = Column(DateTime)  # Frist für Antwort

    # Priorität
    priority = Column(Integer, default=3)  # 1=höchste, 5=niedrigste

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    signature = relationship("EmailSignature", back_populates="emails")
    dispositions = relationship("EmailDisposition", back_populates="email")
    attachments = relationship("EmailAttachment", back_populates="email")
    classification_rule = relationship("EmailClassificationRule")
    classification_folder = relationship("Folder")

    __table_args__ = (
        Index('idx_email_user_folder', 'user_id', 'folder'),
        Index('idx_email_message_id', 'message_id'),
        Index('idx_email_has_disposition', 'has_disposition'),
        Index('idx_email_processing_status', 'processing_status'),
    )


class SmartFolder(Base):
    """Intelligente Ordner basierend auf Filterregeln (erweitert mit query_json)"""
    __tablename__ = 'smart_folders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text)
    icon = Column(String(50))
    color = Column(String(7))

    # Alte Filterregeln (Rückwärtskompatibilität)
    # Format: {"category": "Rechnung", "invoice_status": "open", "date_range": {...}}
    filter_rules = Column(JSON, nullable=False)

    # Neue erweiterte Query (JSON-basierte Abfragesprache)
    # Format: {
    #   "operator": "AND",
    #   "conditions": [
    #     {"field": "category", "op": "=", "value": "Rechnung"},
    #     {"field": "invoice_status", "op": "IN", "value": ["open", "overdue"]},
    #     {"field": "document_date", "op": ">=", "value": "2024-01-01"},
    #     {"field": "entity_id", "op": "=", "value": 5},  # Entity-Filter
    #     {"field": "sender", "op": "CONTAINS", "value": "telekom"}
    #   ]
    # }
    query_json = Column(JSON)

    # Entity-Verknüpfung (optional: SmartFolder für bestimmte Entity)
    entity_id = Column(Integer, ForeignKey('entities.id'))

    # Aggregationen anzeigen?
    show_aggregations = Column(Boolean, default=False)
    # Format: ["sum:invoice_amount", "count:category", "avg:ocr_confidence"]
    aggregation_fields = Column(JSON)

    # Sortierung
    sort_by = Column(String(50), default="document_date")
    sort_order = Column(String(4), default="desc")

    # Cache für Performance
    cached_count = Column(Integer)
    cache_updated_at = Column(DateTime)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    entity = relationship("Entity")


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


class FolderKeyword(Base):
    """Benutzerdefinierte Keywords für Ordner-Zuordnung"""
    __tablename__ = 'folder_keywords'

    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey('folders.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Keyword und Gewichtung
    keyword = Column(String(255), nullable=False)  # Das Stichwort
    weight = Column(Float, default=1.0)  # Gewichtung (höher = wichtiger)
    is_negative = Column(Boolean, default=False)  # Wenn True: Keyword schließt Ordner aus

    # Optional: Kategorie für zusätzliche Filterung
    category = Column(String(100))

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    folder = relationship("Folder")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('folder_id', 'keyword', name='unique_folder_keyword'),
        Index('idx_folder_keyword', 'keyword'),
        Index('idx_folder_keyword_folder', 'folder_id'),
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


# ============================================================
# ENTITY-SYSTEM: Personen, Fahrzeuge, Lieferanten etc.
# ============================================================

class EntityType(enum.Enum):
    """Typ einer Entität"""
    PERSON = "person"           # Person (z.B. Familienmitglied)
    VEHICLE = "vehicle"         # Fahrzeug
    SUPPLIER = "supplier"       # Lieferant/Dienstleister
    PROPERTY = "property"       # Immobilie (Link zu Property-Tabelle)
    ORGANIZATION = "organization"  # Organisation/Verein
    PROJECT = "project"         # Projekt
    CONTRACT = "contract"       # Vertrag (Multi-Topic)
    ID_DOCUMENT = "id_document" # Ausweisdokument (Personalausweis, Reisepass, Führerschein)


# Assoziationstabelle für Dokument-Entity-Verknüpfungen
document_entities = Table(
    'document_entities',
    Base.metadata,
    Column('document_id', Integer, ForeignKey('documents.id'), primary_key=True),
    Column('entity_id', Integer, ForeignKey('entities.id'), primary_key=True),
    Column('relation_type', String(50)),  # owner, sender, subject, mentioned
    Column('confidence', Float, default=1.0),
    Column('created_at', DateTime, default=func.now())
)


class Entity(Base):
    """Entität für intelligente Zuordnung (Person, Fahrzeug, Lieferant, etc.)"""
    __tablename__ = 'entities'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Typ und Name
    entity_type = Column(SQLEnum(EntityType), nullable=False)
    name = Column(String(255), nullable=False)  # Hauptname
    display_name = Column(String(255))  # Anzeigename (optional)

    # Aliase für Erkennung (JSON-Array)
    # z.B. ["Piet Meier", "P. Meier", "Piet"]
    aliases = Column(JSON, default=list)

    # Metadaten (flexibel je nach Typ)
    # Person: {"birthday": "2015-03-15", "minor": true, "relation": "Sohn"}
    # Vehicle: {"plate": "B-AB 1234", "brand": "VW", "model": "Golf", "vin": "..."}
    # Supplier: {"category": "Handwerker", "industry": "Elektrik"}
    meta = Column(JSON, default=dict)

    # Verknüpfungen
    parent_entity_id = Column(Integer, ForeignKey('entities.id'))  # z.B. Fahrzeug gehört zu Person
    folder_id = Column(Integer, ForeignKey('folders.id'))  # Zugeordneter Ordner

    # Status
    is_active = Column(Boolean, default=True)

    # Statistik
    document_count = Column(Integer, default=0)  # Anzahl verknüpfter Dokumente
    last_document_date = Column(DateTime)  # Datum des letzten Dokuments

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    parent = relationship("Entity", remote_side=[id], backref="children")
    folder = relationship("Folder")
    documents = relationship("Document", secondary=document_entities, backref="entities")

    def add_alias(self, alias: str):
        """Fügt einen Alias hinzu"""
        if self.aliases is None:
            self.aliases = []
        if alias and alias not in self.aliases:
            self.aliases.append(alias)

    def matches_text(self, text: str) -> bool:
        """Prüft ob der Name oder ein Alias im Text vorkommt"""
        text_lower = text.lower()
        if self.name.lower() in text_lower:
            return True
        if self.aliases:
            for alias in self.aliases:
                if alias.lower() in text_lower:
                    return True
        return False

    __table_args__ = (
        Index('idx_entity_user', 'user_id'),
        Index('idx_entity_type', 'entity_type'),
        Index('idx_entity_name', 'name'),
    )


class FeedbackEventType(enum.Enum):
    """Typ eines Feedback-Events"""
    FOLDER_MOVE = "folder_move"         # Dokument in anderen Ordner verschoben
    CATEGORY_CHANGE = "category_change"  # Kategorie geändert
    ENTITY_ASSIGN = "entity_assign"      # Entity zugewiesen
    ENTITY_REMOVE = "entity_remove"      # Entity entfernt
    TAG_ADD = "tag_add"                  # Tag hinzugefügt
    TAG_REMOVE = "tag_remove"            # Tag entfernt
    METADATA_EDIT = "metadata_edit"      # Metadaten korrigiert
    CLASSIFICATION_REJECT = "classification_reject"  # Klassifikation abgelehnt


class FeedbackEvent(Base):
    """Feedback-Event für KI-Lernsystem (speichert Nutzerkorrekturen)"""
    __tablename__ = 'feedback_events'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)

    # Event-Typ und Zeitpunkt
    event_type = Column(SQLEnum(FeedbackEventType), nullable=False)
    created_at = Column(DateTime, default=func.now())

    # Vorher/Nachher-Werte
    old_value = Column(JSON)  # {"folder_id": 5, "folder_name": "Rechnungen"}
    new_value = Column(JSON)  # {"folder_id": 12, "folder_name": "KFZ/Versicherung"}

    # Kontext für Lernen
    document_text_snippet = Column(Text)  # Relevanter Textausschnitt (max 500 Zeichen)
    document_sender = Column(String(500))  # Absender zum Zeitpunkt des Events
    document_category = Column(String(100))  # Kategorie zum Zeitpunkt des Events

    # Wurde die Änderung für Lernen verwendet?
    processed_for_learning = Column(Boolean, default=False)
    processed_at = Column(DateTime)

    # Beziehungen
    user = relationship("User")
    document = relationship("Document")

    __table_args__ = (
        Index('idx_feedback_user', 'user_id'),
        Index('idx_feedback_document', 'document_id'),
        Index('idx_feedback_type', 'event_type'),
        Index('idx_feedback_processed', 'processed_for_learning'),
    )


class ClassificationExplanation(Base):
    """Erklärung für Klassifikationsentscheidung (Explainability)"""
    __tablename__ = 'classification_explanations'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False, unique=True)

    # Entscheidungsfaktoren (JSON)
    # {"keyword_matches": [{"keyword": "rechnung", "weight": 0.8, "category": "Rechnung"}],
    #  "sender_match": {"sender": "Telekom", "confidence": 0.9},
    #  "rule_matches": [{"rule_id": 5, "confidence": 0.7}],
    #  "ai_suggestion": {"category": "Vertrag", "confidence": 0.6}}
    decision_factors = Column(JSON, nullable=False)

    # Zusammenfassung für Benutzer
    summary = Column(Text)  # "Eingeordnet wegen: Rechnung erkannt, Absender 'Telekom' bekannt"

    # Finale Entscheidung
    final_category = Column(String(100))
    final_folder_id = Column(Integer, ForeignKey('folders.id'))
    final_confidence = Column(Float)

    # Alternative Vorschläge
    alternatives = Column(JSON)  # [{"folder_id": 10, "name": "Verträge", "confidence": 0.4}]

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    document = relationship("Document")
    final_folder = relationship("Folder")

    __table_args__ = (
        Index('idx_explanation_document', 'document_id'),
    )


# ============================================================
# FELD-ANNOTATION SYSTEM: Lernende Felderkennung
# ============================================================

class FieldType(enum.Enum):
    """Typ eines markierten Feldes"""
    SENDER = "sender"                   # Absender
    SENDER_ADDRESS = "sender_address"   # Absender-Adresse
    RECIPIENT = "recipient"             # Empfänger
    DATE = "date"                       # Dokumentendatum
    DUE_DATE = "due_date"               # Fälligkeitsdatum/Frist
    AMOUNT = "amount"                   # Betrag
    INVOICE_NUMBER = "invoice_number"   # Rechnungsnummer
    CUSTOMER_NUMBER = "customer_number" # Kundennummer
    REFERENCE = "reference"             # Aktenzeichen/Referenz
    IBAN = "iban"                       # IBAN
    BIC = "bic"                         # BIC
    SUBJECT = "subject"                 # Betreff
    CONTRACT_NUMBER = "contract_number" # Vertragsnummer
    CUSTOM = "custom"                   # Benutzerdefiniert


class FieldAnnotation(Base):
    """Markierung eines Feldes auf einem Dokument (für Lernzwecke)"""
    __tablename__ = 'field_annotations'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Feldtyp
    field_type = Column(SQLEnum(FieldType), nullable=False)
    custom_field_name = Column(String(100))  # Falls field_type == CUSTOM

    # Position auf der Seite (prozentual 0.0-1.0 für Skalierbarkeit)
    page_number = Column(Integer, default=1)  # Seitennummer (1-basiert)
    x_percent = Column(Float, nullable=False)  # Linke Kante (0.0-1.0)
    y_percent = Column(Float, nullable=False)  # Obere Kante (0.0-1.0)
    width_percent = Column(Float, nullable=False)  # Breite (0.0-1.0)
    height_percent = Column(Float, nullable=False)  # Höhe (0.0-1.0)

    # Extrahierter Text aus dem markierten Bereich
    extracted_text = Column(Text)

    # Vom Benutzer korrigierter/bestätigter Wert
    confirmed_value = Column(Text)

    # Status
    is_confirmed = Column(Boolean, default=False)  # Benutzer hat bestätigt

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    document = relationship("Document")
    user = relationship("User")

    __table_args__ = (
        Index('idx_annotation_document', 'document_id'),
        Index('idx_annotation_field_type', 'field_type'),
    )


class LayoutTemplate(Base):
    """Gelerntes Layout-Template für automatische Felderkennung"""
    __tablename__ = 'layout_templates'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Identifikation des Templates
    name = Column(String(255), nullable=False)  # z.B. "Telekom Rechnung"

    # Erkennungsmerkmale
    sender_pattern = Column(String(500))  # Regex oder exakter Match für Absender
    keywords = Column(JSON)  # Schlüsselwörter die das Layout identifizieren

    # Gelernte Feldpositionen (JSON)
    # Format: {
    #   "sender": {"page": 1, "x": 0.05, "y": 0.02, "w": 0.4, "h": 0.08},
    #   "amount": {"page": 1, "x": 0.7, "y": 0.3, "w": 0.2, "h": 0.03},
    #   "due_date": {"page": 1, "x": 0.6, "y": 0.25, "w": 0.15, "h": 0.02}
    # }
    field_positions = Column(JSON, nullable=False)

    # Statistik
    times_used = Column(Integer, default=0)  # Wie oft erfolgreich angewandt
    times_corrected = Column(Integer, default=0)  # Wie oft korrigiert
    confidence = Column(Float, default=0.5)  # Vertrauen (0.0-1.0)

    # Basiert auf welchen Dokumenten
    source_document_ids = Column(JSON)  # Liste der Dokument-IDs für Training

    # Status
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehung
    user = relationship("User")

    __table_args__ = (
        Index('idx_layout_template_user', 'user_id'),
        Index('idx_layout_template_sender', 'sender_pattern'),
    )


# ============================================================
# E-MAIL PROCESSING MODELLE
# ============================================================

class EmailSignature(Base):
    """E-Mail-Signaturen für Erkennung und Verwaltung"""
    __tablename__ = 'email_signatures'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    name = Column(String(255), nullable=False)  # z.B. "Kanzlei RHM Standard"
    description = Column(Text)

    # Signatur-Identifikation
    email_address = Column(String(255))  # z.B. "meier@ra-rhm.de"
    is_default = Column(Boolean, default=False)  # Standard-Signatur

    # Erkennungs-Patterns (JSON-Array von Mustern)
    # Format: [
    #   {"type": "exact", "value": "Mit freundlichen Grüßen"},
    #   {"type": "contains", "value": "Rechtsanwalt"},
    #   {"type": "regex", "value": "Tel\\.?:\\s*\\+?[0-9\\s/-]+"},
    #   {"type": "fuzzy", "value": "Kanzlei Müller", "threshold": 80}
    # ]
    patterns = Column(JSON, nullable=False)

    # Signatur-Text (für Anzeige/Vorschau)
    signature_text = Column(Text)
    signature_html = Column(Text)

    # Statistik
    times_detected = Column(Integer, default=0)
    last_detected_at = Column(DateTime)

    # Status
    is_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    emails = relationship("Email", back_populates="signature")

    __table_args__ = (
        Index('idx_email_signature_user', 'user_id'),
        Index('idx_email_signature_email', 'email_address'),
    )


class DispositionActionType(enum.Enum):
    """Typen von Verfügungs-Aktionen"""
    MOVE_TO_FOLDER = "move_to_folder"  # In Ordner verschieben
    CREATE_TASK = "create_task"  # Aufgabe erstellen
    SET_DEADLINE = "set_deadline"  # Frist setzen
    ASSIGN_TO = "assign_to"  # Zuweisen an
    CREATE_RESPONSE = "create_response"  # Antwort erstellen
    ARCHIVE = "archive"  # Archivieren
    FILE_TO_CASE = "file_to_case"  # Zu Akte nehmen
    FORWARD = "forward"  # Weiterleiten
    CUSTOM = "custom"  # Benutzerdefiniert


class EmailDisposition(Base):
    """Verfügungen aus E-Mails extrahiert"""
    __tablename__ = 'email_dispositions'

    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey('emails.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Rohdaten
    raw_text = Column(Text)  # Original-Verfügungstext
    extracted_at = Column(DateTime, default=func.now())

    # Erkennungs-Info
    trigger_keyword = Column(String(255))  # z.B. "Verfügung:", "Bitte veranlassen"
    detection_method = Column(String(50))  # "keyword", "ai", "manual"
    confidence = Column(Float)

    # Strukturierte Aktionen (JSON-Array)
    # Format: [
    #   {"type": "move_to_folder", "target": "Inkasso/Müller", "priority": 1},
    #   {"type": "set_deadline", "date": "2024-12-31", "description": "Frist Klageerwiderung"},
    #   {"type": "assign_to", "person": "Frau Schmidt", "email": "schmidt@ra-rhm.de"},
    #   {"type": "create_task", "title": "Schriftsatz vorbereiten", "due_date": "2024-12-20"}
    # ]
    actions = Column(JSON)

    # Verknüpfungen
    target_folder_id = Column(Integer, ForeignKey('folders.id'))
    target_entity_id = Column(Integer, ForeignKey('entities.id'))  # z.B. Mandant, Akte
    assigned_to_contact_id = Column(Integer, ForeignKey('contacts.id'))

    # Status
    status = Column(String(50), default="open")  # open, in_progress, completed, cancelled
    completed_at = Column(DateTime)
    completed_by = Column(String(255))

    # Audit
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    email = relationship("Email", back_populates="dispositions")
    user = relationship("User")
    target_folder = relationship("Folder")
    target_entity = relationship("Entity")
    assigned_to = relationship("Contact")

    __table_args__ = (
        Index('idx_disposition_email', 'email_id'),
        Index('idx_disposition_status', 'status'),
    )


class EmailAttachment(Base):
    """E-Mail-Anhänge"""
    __tablename__ = 'email_attachments'

    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey('emails.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))  # Verknüpfung zu importiertem Dokument

    # Datei-Info
    filename = Column(String(500), nullable=False)
    mime_type = Column(String(255))
    size = Column(Integer)  # Bytes
    content_hash = Column(String(64))  # SHA-256

    # Speicherort
    storage_path = Column(String(1000))  # Pfad zum gespeicherten Anhang
    is_stored = Column(Boolean, default=False)

    # Extraktion
    extracted_text = Column(Text)  # OCR/Text-Extraktion
    extraction_status = Column(String(50))  # pending, completed, failed, skipped

    # Klassifikation (optional separate vom E-Mail)
    classification_category = Column(String(100))
    classification_confidence = Column(Float)

    # Content-Disposition
    content_disposition = Column(String(50))  # inline, attachment
    content_id = Column(String(255))  # CID für inline-Bilder

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    email = relationship("Email", back_populates="attachments")
    document = relationship("Document")

    __table_args__ = (
        Index('idx_attachment_email', 'email_id'),
        Index('idx_attachment_hash', 'content_hash'),
    )


class EmailClassificationRule(Base):
    """Regeln für E-Mail-Klassifikation"""
    __tablename__ = 'email_classification_rules'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Regel-Priorität (höhere Zahl = wird zuerst geprüft)
    priority = Column(Integer, default=50)

    # Bedingungen (JSON)
    # Format: {
    #   "operator": "AND",  # AND, OR
    #   "conditions": [
    #     {"field": "from_address", "op": "contains", "value": "@telekom.de"},
    #     {"field": "subject", "op": "contains", "value": "Rechnung"},
    #     {"field": "body", "op": "regex", "value": "Rechnungsnummer:\\s*\\d+"},
    #     {"field": "attachment_type", "op": "equals", "value": "application/pdf"}
    #   ]
    # }
    conditions = Column(JSON, nullable=False)

    # Aktionen bei Match
    target_folder_id = Column(Integer, ForeignKey('folders.id'))
    target_folder_path = Column(String(500))  # z.B. "Rechnungen/Telekom"
    assign_tags = Column(JSON)  # ["telekom", "rechnung"]
    assign_category = Column(String(100))
    set_priority = Column(Integer)

    # Verfügungs-Trigger (optional)
    check_disposition = Column(Boolean, default=True)  # Prüfe auf Verfügung

    # Statistik
    times_applied = Column(Integer, default=0)
    last_applied_at = Column(DateTime)

    # Status
    is_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    target_folder = relationship("Folder")

    __table_args__ = (
        Index('idx_email_rule_user', 'user_id'),
        Index('idx_email_rule_priority', 'priority'),
    )


class EmailProcessingLog(Base):
    """Audit-Log für E-Mail-Verarbeitung"""
    __tablename__ = 'email_processing_logs'

    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey('emails.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Schritt
    step = Column(String(100), nullable=False)  # fetch, parse, signature, disposition, classify, store
    status = Column(String(50), nullable=False)  # success, warning, error, skipped

    # Details
    message = Column(Text)
    details = Column(JSON)  # Zusätzliche strukturierte Daten

    # Timing
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    email = relationship("Email")

    __table_args__ = (
        Index('idx_processing_log_email', 'email_id'),
    )
