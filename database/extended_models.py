"""
Erweiterte SQLAlchemy-Modelle für neue Features
- Garantie-Tracker
- Versicherungs-Manager
- Abo-Verwaltung
- Haushalts-Inventar
- Cloud-Sync
- Dokumenten-Versionierung
- Vorlagen-System
- Kilometerlogbuch
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Float, ForeignKey, JSON, Enum as SQLEnum, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from database.models import Base


# ============== ENUMS ==============

class WarrantyStatus(enum.Enum):
    """Status einer Garantie"""
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"  # < 30 Tage
    EXPIRED = "expired"
    CLAIMED = "claimed"


class InsuranceType(enum.Enum):
    """Versicherungstyp"""
    LIABILITY = "liability"  # Haftpflicht
    HOUSEHOLD = "household"  # Hausrat
    LEGAL = "legal"  # Rechtsschutz
    HEALTH = "health"  # Kranken
    CAR = "car"  # KFZ
    LIFE = "life"  # Leben
    DISABILITY = "disability"  # Berufsunfähigkeit
    TRAVEL = "travel"  # Reise
    PET = "pet"  # Tier
    OTHER = "other"


class SubscriptionInterval(enum.Enum):
    """Abrechnungsintervall"""
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUALLY = "semi_annually"
    ANNUALLY = "annually"


class CloudProvider(enum.Enum):
    """Cloud-Speicher Anbieter"""
    DROPBOX = "dropbox"
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    NEXTCLOUD = "nextcloud"


class SyncStatus(enum.Enum):
    """Synchronisationsstatus"""
    PENDING = "pending"
    SYNCING = "syncing"
    COMPLETED = "completed"
    ERROR = "error"
    PAUSED = "paused"


class TripPurpose(enum.Enum):
    """Fahrtenzweck"""
    BUSINESS = "business"  # Dienstlich
    PRIVATE = "private"  # Privat
    COMMUTE = "commute"  # Arbeitsweg


# ============== GARANTIE-TRACKER ==============

class Warranty(Base):
    """Garantien und Gewährleistungen"""
    __tablename__ = 'warranties'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    inventory_item_id = Column(Integer, ForeignKey('inventory_items.id'))
    document_id = Column(Integer, ForeignKey('documents.id'))

    # Produktinformationen
    product_name = Column(String(500), nullable=False)
    manufacturer = Column(String(255))
    model_number = Column(String(100))
    serial_number = Column(String(100))

    # Kaufinformationen
    purchase_date = Column(DateTime, nullable=False)
    purchase_price = Column(Float)
    currency = Column(String(3), default="EUR")
    retailer = Column(String(255))  # Händler
    receipt_document_id = Column(Integer, ForeignKey('documents.id'))

    # Garantiezeitraum
    warranty_start = Column(DateTime)
    warranty_end = Column(DateTime, nullable=False)
    extended_warranty_end = Column(DateTime)  # Falls Verlängerung gekauft

    # Status
    status = Column(SQLEnum(WarrantyStatus), default=WarrantyStatus.ACTIVE)

    # Kontaktdaten für Garantiefall
    warranty_contact = Column(String(255))
    warranty_phone = Column(String(50))
    warranty_email = Column(String(255))
    warranty_url = Column(String(500))

    # Notizen
    notes = Column(Text)

    # Erinnerung
    reminder_days_before = Column(Integer, default=30)
    reminder_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    inventory_item = relationship("InventoryItem", back_populates="warranty")
    document = relationship("Document", foreign_keys=[document_id])
    receipt_document = relationship("Document", foreign_keys=[receipt_document_id])

    __table_args__ = (
        Index('idx_warranty_user', 'user_id'),
        Index('idx_warranty_end', 'warranty_end'),
        Index('idx_warranty_status', 'status'),
    )


# ============== VERSICHERUNGS-MANAGER ==============

class Insurance(Base):
    """Versicherungspolicen"""
    __tablename__ = 'insurances'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))

    # Versicherungsdaten
    insurance_type = Column(SQLEnum(InsuranceType), nullable=False)
    company = Column(String(255), nullable=False)
    policy_number = Column(String(100))
    policy_name = Column(String(255))

    # Kosten
    premium_amount = Column(Float, nullable=False)
    premium_interval = Column(SQLEnum(SubscriptionInterval), default=SubscriptionInterval.MONTHLY)
    currency = Column(String(3), default="EUR")
    deductible = Column(Float)  # Selbstbeteiligung

    # Deckung
    coverage_amount = Column(Float)  # Deckungssumme
    coverage_description = Column(Text)

    # Laufzeit
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    auto_renew = Column(Boolean, default=True)
    notice_period_days = Column(Integer, default=90)  # Kündigungsfrist

    # Kontakt
    agent_name = Column(String(255))
    agent_phone = Column(String(50))
    agent_email = Column(String(255))
    claims_phone = Column(String(50))  # Schadenhotline

    # Status
    is_active = Column(Boolean, default=True)

    # Notizen
    notes = Column(Text)

    # Erinnerungen
    reminder_days_before = Column(Integer, default=60)
    reminder_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    document = relationship("Document")
    claims = relationship("InsuranceClaim", back_populates="insurance", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_insurance_user', 'user_id'),
        Index('idx_insurance_type', 'insurance_type'),
        Index('idx_insurance_company', 'company'),
    )


class InsuranceClaim(Base):
    """Versicherungs-Schadensmeldungen"""
    __tablename__ = 'insurance_claims'

    id = Column(Integer, primary_key=True)
    insurance_id = Column(Integer, ForeignKey('insurances.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Schadensdaten
    claim_number = Column(String(100))
    incident_date = Column(DateTime, nullable=False)
    report_date = Column(DateTime, default=func.now())
    description = Column(Text, nullable=False)

    # Beträge
    claimed_amount = Column(Float)
    approved_amount = Column(Float)
    paid_amount = Column(Float)
    currency = Column(String(3), default="EUR")

    # Status
    status = Column(String(50), default="submitted")  # submitted, processing, approved, rejected, paid
    status_notes = Column(Text)

    # Dokumente als JSON-Liste von IDs
    document_ids = Column(JSON)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    insurance = relationship("Insurance", back_populates="claims")
    user = relationship("User")

    __table_args__ = (
        Index('idx_claim_insurance', 'insurance_id'),
        Index('idx_claim_status', 'status'),
    )


# ============== ABO-VERWALTUNG ==============

class Subscription(Base):
    """Abonnements und wiederkehrende Zahlungen"""
    __tablename__ = 'subscriptions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))

    # Abodaten
    name = Column(String(255), nullable=False)
    provider = Column(String(255))  # z.B. Netflix, Spotify
    category = Column(String(100))  # entertainment, software, fitness, etc.

    # Kosten
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="EUR")
    billing_interval = Column(SQLEnum(SubscriptionInterval), default=SubscriptionInterval.MONTHLY)

    # Zahlungsmethode
    payment_method = Column(String(100))  # credit_card, direct_debit, paypal
    bank_account_id = Column(Integer, ForeignKey('bank_accounts.id'))

    # Laufzeit
    start_date = Column(DateTime, nullable=False)
    next_billing_date = Column(DateTime)
    end_date = Column(DateTime)
    trial_end_date = Column(DateTime)  # Probezeitraum

    # Kündigung
    cancellation_url = Column(String(500))
    notice_period_days = Column(Integer)
    cancellation_date = Column(DateTime)  # Wenn bereits gekündigt

    # Status
    is_active = Column(Boolean, default=True)
    is_paused = Column(Boolean, default=False)

    # Login-Daten (verschlüsselt speichern!)
    login_email = Column(String(255))
    website_url = Column(String(500))

    # Sharing
    shared_with = Column(JSON)  # Liste von Namen/E-Mails
    max_users = Column(Integer)

    # Notizen
    notes = Column(Text)

    # Erinnerung vor Verlängerung
    reminder_days_before = Column(Integer, default=7)
    reminder_sent = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    document = relationship("Document")
    bank_account = relationship("BankAccount")

    __table_args__ = (
        Index('idx_subscription_user', 'user_id'),
        Index('idx_subscription_active', 'is_active'),
        Index('idx_subscription_next_billing', 'next_billing_date'),
    )


# ============== HAUSHALTS-INVENTAR ==============

class InventoryItem(Base):
    """Haushalts-Inventar"""
    __tablename__ = 'inventory_items'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))  # Kaufbeleg

    # Produktdaten
    name = Column(String(500), nullable=False)
    description = Column(Text)
    category = Column(String(100))  # electronics, furniture, appliances, etc.
    manufacturer = Column(String(255))
    model = Column(String(255))
    serial_number = Column(String(100))

    # Kaufinformationen
    purchase_date = Column(DateTime)
    purchase_price = Column(Float)
    currency = Column(String(3), default="EUR")
    retailer = Column(String(255))

    # Aktueller Wert (für Versicherung)
    current_value = Column(Float)
    depreciation_rate = Column(Float, default=0.1)  # Jährliche Abschreibung

    # Standort
    location = Column(String(255))  # Raum/Bereich
    room = Column(String(100))

    # Zustand
    condition = Column(String(50), default="good")  # new, good, fair, poor

    # Bilder als JSON-Liste von Pfaden
    image_paths = Column(JSON)

    # QR-Code für schnellen Zugriff
    qr_code = Column(String(100))

    # Status
    is_active = Column(Boolean, default=True)  # False = verkauft/entsorgt
    disposed_date = Column(DateTime)
    disposed_reason = Column(String(100))  # sold, donated, discarded, broken

    notes = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    document = relationship("Document")
    warranty = relationship("Warranty", back_populates="inventory_item", uselist=False)

    __table_args__ = (
        Index('idx_inventory_user', 'user_id'),
        Index('idx_inventory_category', 'category'),
        Index('idx_inventory_location', 'location'),
    )


# ============== CLOUD-SYNC ==============

class CloudSyncConnection(Base):
    """Verbindung zu Cloud-Speichern"""
    __tablename__ = 'cloud_sync_connections'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Provider
    provider = Column(SQLEnum(CloudProvider), nullable=False)
    provider_name = Column(String(100))  # Anzeigename

    # Authentifizierung
    access_token = Column(Text)  # Verschlüsselt speichern!
    refresh_token = Column(Text)
    token_expires_at = Column(DateTime)

    # Ordnerkonfiguration
    remote_folder_path = Column(String(1000), nullable=False)  # Pfad im Cloud-Speicher
    remote_folder_id = Column(String(255))  # ID des Ordners (bei manchen APIs)
    local_folder_id = Column(Integer, ForeignKey('folders.id'))  # Zielordner in App

    # Sync-Einstellungen
    auto_sync_enabled = Column(Boolean, default=True)
    sync_interval_minutes = Column(Integer, default=15)
    delete_after_import = Column(Boolean, default=False)  # Aus Cloud löschen nach Import
    auto_process = Column(Boolean, default=True)  # Automatisch durch Workflow

    # Dateifilter
    file_extensions = Column(JSON)  # [".pdf", ".jpg", ".png"]
    max_file_size_mb = Column(Integer, default=50)

    # Status
    status = Column(SQLEnum(SyncStatus), default=SyncStatus.PENDING)
    last_sync_at = Column(DateTime)
    last_sync_error = Column(Text)
    last_cursor = Column(String(500))  # Für Delta-Sync

    # Statistik
    total_files_synced = Column(Integer, default=0)
    total_bytes_synced = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    local_folder = relationship("Folder")
    sync_logs = relationship("CloudSyncLog", back_populates="connection", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_cloud_sync_user', 'user_id'),
        Index('idx_cloud_sync_provider', 'provider'),
        Index('idx_cloud_sync_status', 'status'),
    )


class CloudSyncLog(Base):
    """Protokoll aller synchronisierten Dateien"""
    __tablename__ = 'cloud_sync_logs'

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey('cloud_sync_connections.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Quelldatei
    remote_file_path = Column(String(1000), nullable=False)
    remote_file_id = Column(String(255))
    remote_file_hash = Column(String(64))  # Um Duplikate zu erkennen
    file_size = Column(Integer)
    file_modified_at = Column(DateTime)

    # Zieldatei
    document_id = Column(Integer, ForeignKey('documents.id'))
    local_file_path = Column(String(1000))

    # Status
    sync_status = Column(String(50), default="synced")  # synced, skipped, error, duplicate
    error_message = Column(Text)

    # Verarbeitung
    was_processed = Column(Boolean, default=False)  # Durch Workflow verarbeitet
    processed_at = Column(DateTime)

    # Metadaten
    mime_type = Column(String(100))
    original_filename = Column(String(255))

    synced_at = Column(DateTime, default=func.now())

    # Beziehungen
    connection = relationship("CloudSyncConnection", back_populates="sync_logs")
    user = relationship("User")
    document = relationship("Document")

    __table_args__ = (
        Index('idx_sync_log_connection', 'connection_id'),
        Index('idx_sync_log_remote_hash', 'remote_file_hash'),
        Index('idx_sync_log_date', 'synced_at'),
    )


# ============== DOKUMENTEN-VERSIONIERUNG ==============

class DocumentVersion(Base):
    """Versionierung von Dokumenten"""
    __tablename__ = 'document_versions'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Version
    version_number = Column(Integer, nullable=False)
    version_label = Column(String(100))  # z.B. "v1.0", "Draft", "Final"

    # Datei
    file_path = Column(String(1000), nullable=False)
    file_size = Column(Integer)
    file_hash = Column(String(64))

    # Änderungen
    change_summary = Column(Text)
    changed_by = Column(String(255))

    # Ist dies die aktuelle Version?
    is_current = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    document = relationship("Document")
    user = relationship("User")

    __table_args__ = (
        Index('idx_version_document', 'document_id'),
        Index('idx_version_current', 'document_id', 'is_current'),
    )


# ============== VORLAGEN-SYSTEM ==============

class DocumentTemplate(Base):
    """Dokumentenvorlagen"""
    __tablename__ = 'document_templates'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))  # NULL = System-Vorlage

    # Template-Daten
    name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(100))  # letter, contract, invoice, etc.

    # Inhalt
    content = Column(Text, nullable=False)  # Template mit Platzhaltern
    content_type = Column(String(50), default="text")  # text, html, markdown

    # Platzhalter-Definition
    placeholders = Column(JSON)  # [{"key": "name", "label": "Name", "type": "text"}]

    # Dateianhang (optional)
    template_file_path = Column(String(1000))

    # Verwendung
    times_used = Column(Integer, default=0)
    last_used_at = Column(DateTime)

    # System oder Benutzer
    is_system = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehung
    user = relationship("User")

    __table_args__ = (
        Index('idx_template_user', 'user_id'),
        Index('idx_template_category', 'category'),
    )


# ============== KILOMETERLOGBUCH ==============

class Vehicle(Base):
    """Fahrzeuge für Kilometerlogbuch"""
    __tablename__ = 'vehicles'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Fahrzeugdaten
    name = Column(String(255), nullable=False)
    license_plate = Column(String(20))
    make = Column(String(100))  # Marke
    model = Column(String(100))
    year = Column(Integer)
    vin = Column(String(17))  # Fahrgestellnummer

    # Kilometerstand
    initial_odometer = Column(Integer, default=0)
    current_odometer = Column(Integer)

    # Kosten
    fuel_type = Column(String(50))  # petrol, diesel, electric, hybrid
    avg_consumption = Column(Float)  # l/100km oder kWh/100km

    # Steuerlich relevante Daten
    business_use_percentage = Column(Float)  # Anteil betriebliche Nutzung

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    user = relationship("User")
    trips = relationship("MileageTrip", back_populates="vehicle", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_vehicle_user', 'user_id'),
    )


class MileageTrip(Base):
    """Einzelne Fahrten im Kilometerlogbuch"""
    __tablename__ = 'mileage_trips'

    id = Column(Integer, primary_key=True)
    vehicle_id = Column(Integer, ForeignKey('vehicles.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    document_id = Column(Integer, ForeignKey('documents.id'))  # Verknüpfter Beleg

    # Fahrtdaten
    trip_date = Column(DateTime, nullable=False)
    purpose = Column(SQLEnum(TripPurpose), default=TripPurpose.BUSINESS)
    description = Column(Text)

    # Strecke
    start_location = Column(String(255))
    end_location = Column(String(255))
    route_description = Column(Text)

    # Kilometer
    start_odometer = Column(Integer)
    end_odometer = Column(Integer)
    distance_km = Column(Float, nullable=False)

    # Kosten
    fuel_cost = Column(Float)
    toll_cost = Column(Float)
    parking_cost = Column(Float)
    other_costs = Column(Float)
    currency = Column(String(3), default="EUR")

    # Steuerlich
    is_tax_deductible = Column(Boolean, default=True)
    reimbursement_rate = Column(Float, default=0.30)  # €/km

    # Kontakt/Kunde (für Geschäftsfahrten)
    client_name = Column(String(255))
    project_name = Column(String(255))

    notes = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    vehicle = relationship("Vehicle", back_populates="trips")
    user = relationship("User")
    document = relationship("Document")

    __table_args__ = (
        Index('idx_trip_vehicle', 'vehicle_id'),
        Index('idx_trip_date', 'trip_date'),
        Index('idx_trip_purpose', 'purpose'),
    )


# ============== BACKUP-PROTOKOLL ==============

class BackupLog(Base):
    """Protokoll aller Backups"""
    __tablename__ = 'backup_logs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Backup-Details
    backup_type = Column(String(50), nullable=False)  # full, incremental, documents_only
    backup_path = Column(String(1000))
    backup_size = Column(Integer)  # Bytes

    # Inhalt
    documents_count = Column(Integer, default=0)
    total_items = Column(Integer, default=0)

    # Status
    status = Column(String(50), default="completed")  # in_progress, completed, failed
    error_message = Column(Text)

    # Verschlüsselung
    is_encrypted = Column(Boolean, default=True)

    # Dauer
    started_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime)

    created_at = Column(DateTime, default=func.now())

    # Beziehung
    user = relationship("User")

    __table_args__ = (
        Index('idx_backup_user', 'user_id'),
        Index('idx_backup_date', 'created_at'),
    )


# ============== FAMILIEN-FREIGABE ==============

class FamilyGroup(Base):
    """Familiengruppen für gemeinsame Dokumente"""
    __tablename__ = 'family_groups'

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    name = Column(String(255), nullable=False)
    description = Column(Text)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    owner = relationship("User")
    members = relationship("FamilyMember", back_populates="group", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_family_owner', 'owner_id'),
    )


class FamilyMember(Base):
    """Mitglieder einer Familiengruppe"""
    __tablename__ = 'family_members'

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('family_groups.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))  # Optional: registrierter Benutzer

    name = Column(String(255), nullable=False)
    email = Column(String(255))
    role = Column(String(50), default="member")  # owner, admin, member, viewer

    # Einladung
    invitation_token = Column(String(100))
    invitation_sent_at = Column(DateTime)
    invitation_accepted = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())

    # Beziehungen
    group = relationship("FamilyGroup", back_populates="members")
    user = relationship("User")

    __table_args__ = (
        Index('idx_family_member_group', 'group_id'),
        Index('idx_family_member_user', 'user_id'),
    )


class SharedDocument(Base):
    """Für Familienmitglieder freigegebene Dokumente"""
    __tablename__ = 'shared_documents'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    group_id = Column(Integer, ForeignKey('family_groups.id'), nullable=False)
    shared_by_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Berechtigungen
    can_view = Column(Boolean, default=True)
    can_download = Column(Boolean, default=True)
    can_comment = Column(Boolean, default=True)

    shared_at = Column(DateTime, default=func.now())

    # Beziehungen
    document = relationship("Document")
    group = relationship("FamilyGroup")
    shared_by = relationship("User")

    __table_args__ = (
        Index('idx_shared_doc_group', 'group_id'),
        Index('idx_shared_doc_document', 'document_id'),
    )


class DocumentComment(Base):
    """Kommentare zu Dokumenten"""
    __tablename__ = 'document_comments'

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    parent_id = Column(Integer, ForeignKey('document_comments.id'))  # Für Antworten

    content = Column(Text, nullable=False)

    # Mentions
    mentioned_user_ids = Column(JSON)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Beziehungen
    document = relationship("Document")
    user = relationship("User")
    parent = relationship("DocumentComment", remote_side=[id], backref="replies")

    __table_args__ = (
        Index('idx_comment_document', 'document_id'),
        Index('idx_comment_user', 'user_id'),
    )
