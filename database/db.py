"""
Datenbankverbindung und Session-Management

Unterstützt:
- SQLite (lokal, Standard)
- PostgreSQL (über DATABASE_URL in Streamlit Secrets oder Umgebungsvariable)
- MySQL (über DATABASE_URL)

Für persistente Daten auf Streamlit Cloud:
1. Erstelle kostenloses Konto bei Supabase, Neon, oder PlanetScale
2. Füge DATABASE_URL in Streamlit Secrets hinzu:
   DATABASE_URL = "postgresql://user:password@host:port/database"
"""
import os
import logging
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import streamlit as st

from config.settings import DATABASE_PATH, DEFAULT_FOLDERS
from .models import Base, User, Folder

logger = logging.getLogger(__name__)

# Import extended models so their tables get registered with Base.metadata
try:
    from .extended_models import (
        Warranty, Insurance, InsuranceClaim, Subscription,
        InventoryItem, CloudSyncConnection, CloudSyncLog,
        DocumentVersion, DocumentTemplate, Vehicle, MileageTrip,
        BackupLog, FamilyGroup, FamilyMember, SharedDocument, DocumentComment
    )
except ImportError:
    # Extended models not available
    pass


def get_database_url() -> str:
    """
    Ermittelt die Datenbank-URL aus verschiedenen Quellen.

    Priorität:
    1. Streamlit Secrets (DATABASE_URL)
    2. Umgebungsvariable (DATABASE_URL)
    3. Lokale SQLite-Datei (Standard)

    Returns:
        Database URL string
    """
    # 1. Versuche Streamlit Secrets
    try:
        if hasattr(st, 'secrets') and 'DATABASE_URL' in st.secrets:
            db_url = st.secrets['DATABASE_URL']
            logger.info("Verwende Datenbank aus Streamlit Secrets")
            return db_url
    except Exception:
        pass

    # 2. Versuche Umgebungsvariable
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        # Heroku-Style postgres:// -> postgresql://
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        logger.info("Verwende Datenbank aus Umgebungsvariable")
        return db_url

    # 3. Fallback auf lokale SQLite
    logger.info("Verwende lokale SQLite-Datenbank")
    return f"sqlite:///{DATABASE_PATH}"


def create_db_engine():
    """
    Erstellt den Datenbank-Engine basierend auf der URL.

    Konfiguriert automatisch die richtigen Optionen für SQLite vs PostgreSQL.
    Unterstützt Supabase mit pgbouncer (Port 6543).
    """
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    db_url = get_database_url()

    if db_url.startswith('sqlite'):
        # SQLite-spezifische Optionen
        eng = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False}
        )
    else:
        # PostgreSQL/MySQL Optionen
        connect_args = {}

        # Prüfe ob pgbouncer verwendet wird (Port 6543 oder ?pgbouncer=true)
        if 'pgbouncer=true' in db_url or ':6543/' in db_url:
            # pgbouncer benötigt spezielle Einstellungen
            connect_args = {
                "options": "-c statement_timeout=60000"
            }
            logger.info("Supabase pgbouncer-Modus erkannt")

        # URL-Parameter sauber verarbeiten (pgbouncer entfernen)
        if '?' in db_url:
            parsed = urlparse(db_url)
            query_params = parse_qs(parsed.query)

            # Entferne pgbouncer Parameter
            query_params.pop('pgbouncer', None)

            # Baue URL neu zusammen
            new_query = urlencode(query_params, doseq=True) if query_params else ''
            db_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment
            ))

        eng = create_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,  # Verbindung vor Nutzung prüfen
            pool_recycle=300,    # Verbindungen alle 5 Minuten recyceln
            pool_size=5,         # Max 5 Verbindungen
            max_overflow=10,     # Max 10 zusätzliche bei Bedarf
            connect_args=connect_args if connect_args else {}
        )

    return eng


# Gecachter Engine (wird nur einmal erstellt)
@st.cache_resource
def get_engine():
    """Gibt den gecachten Datenbank-Engine zurück."""
    return create_db_engine()


# Datenbank-Engine
engine = get_engine()

# Session-Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_migrations():
    """Führt Datenbankmigrationen durch für neue Spalten und Tabellen"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    with engine.connect() as conn:
        # Migration 1: Neue Spalten zur documents-Tabelle hinzufügen
        if 'documents' in existing_tables:
            existing_columns = [col['name'] for col in inspector.get_columns('documents')]

            # property_id Spalte hinzufügen
            if 'property_id' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE documents ADD COLUMN property_id INTEGER REFERENCES properties(id)'))
                    conn.commit()
                except Exception:
                    pass  # Spalte existiert bereits oder Fehler ignorieren

            # property_address Spalte hinzufügen
            if 'property_address' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE documents ADD COLUMN property_address VARCHAR(500)'))
                    conn.commit()
                except Exception:
                    pass

        # Migration 2: properties Tabelle erstellen (falls nicht existiert)
        if 'properties' not in existing_tables:
            try:
                conn.execute(text('''
                    CREATE TABLE IF NOT EXISTS properties (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        name VARCHAR(255),
                        street VARCHAR(255),
                        house_number VARCHAR(20),
                        postal_code VARCHAR(10),
                        city VARCHAR(100),
                        country VARCHAR(100) DEFAULT 'Deutschland',
                        property_type VARCHAR(50),
                        usage VARCHAR(50),
                        owner VARCHAR(255),
                        management VARCHAR(255),
                        acquired_date DATETIME,
                        sold_date DATETIME,
                        notes TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_property_user ON properties(user_id)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_property_address ON properties(street, postal_code, city)'))
                conn.commit()
            except Exception:
                pass

        # Migration 3: document_virtual_folders Tabelle erstellen
        if 'document_virtual_folders' not in existing_tables:
            try:
                conn.execute(text('''
                    CREATE TABLE IF NOT EXISTS document_virtual_folders (
                        document_id INTEGER NOT NULL REFERENCES documents(id),
                        folder_id INTEGER NOT NULL REFERENCES folders(id),
                        is_primary BOOLEAN DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (document_id, folder_id)
                    )
                '''))
                conn.commit()
            except Exception:
                pass

        # Migration 4: folder_keywords Tabelle für benutzerdefinierte Zuordnungen
        if 'folder_keywords' not in existing_tables:
            try:
                conn.execute(text('''
                    CREATE TABLE IF NOT EXISTS folder_keywords (
                        id INTEGER PRIMARY KEY,
                        folder_id INTEGER NOT NULL REFERENCES folders(id),
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        keyword VARCHAR(255) NOT NULL,
                        weight REAL DEFAULT 1.0,
                        is_negative BOOLEAN DEFAULT 0,
                        category VARCHAR(100),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(folder_id, keyword)
                    )
                '''))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_folder_keyword ON folder_keywords(keyword)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_folder_keyword_folder ON folder_keywords(folder_id)'))
                conn.commit()
            except Exception:
                pass

        # Migration 5: entities Tabelle für Personen, Fahrzeuge, Lieferanten etc.
        if 'entities' not in existing_tables:
            try:
                conn.execute(text('''
                    CREATE TABLE IF NOT EXISTS entities (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        entity_type VARCHAR(50) NOT NULL,
                        name VARCHAR(255) NOT NULL,
                        display_name VARCHAR(255),
                        aliases JSON,
                        meta JSON,
                        parent_entity_id INTEGER REFERENCES entities(id),
                        folder_id INTEGER REFERENCES folders(id),
                        is_active BOOLEAN DEFAULT 1,
                        document_count INTEGER DEFAULT 0,
                        last_document_date DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_entity_user ON entities(user_id)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name)'))
                conn.commit()
            except Exception:
                pass

        # Migration 6: document_entities Assoziationstabelle
        if 'document_entities' not in existing_tables:
            try:
                conn.execute(text('''
                    CREATE TABLE IF NOT EXISTS document_entities (
                        document_id INTEGER NOT NULL REFERENCES documents(id),
                        entity_id INTEGER NOT NULL REFERENCES entities(id),
                        relation_type VARCHAR(50),
                        confidence REAL DEFAULT 1.0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (document_id, entity_id)
                    )
                '''))
                conn.commit()
            except Exception:
                pass

        # Migration 7: feedback_events Tabelle für KI-Lernsystem
        if 'feedback_events' not in existing_tables:
            try:
                conn.execute(text('''
                    CREATE TABLE IF NOT EXISTS feedback_events (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        document_id INTEGER NOT NULL REFERENCES documents(id),
                        event_type VARCHAR(50) NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        old_value JSON,
                        new_value JSON,
                        document_text_snippet TEXT,
                        document_sender VARCHAR(500),
                        document_category VARCHAR(100),
                        processed_for_learning BOOLEAN DEFAULT 0,
                        processed_at DATETIME
                    )
                '''))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback_events(user_id)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_feedback_document ON feedback_events(document_id)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback_events(event_type)'))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_feedback_processed ON feedback_events(processed_for_learning)'))
                conn.commit()
            except Exception:
                pass

        # Migration 8: classification_explanations Tabelle für Explainability
        if 'classification_explanations' not in existing_tables:
            try:
                conn.execute(text('''
                    CREATE TABLE IF NOT EXISTS classification_explanations (
                        id INTEGER PRIMARY KEY,
                        document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id),
                        decision_factors JSON NOT NULL,
                        summary TEXT,
                        final_category VARCHAR(100),
                        final_folder_id INTEGER REFERENCES folders(id),
                        final_confidence REAL,
                        alternatives JSON,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
                conn.execute(text('CREATE INDEX IF NOT EXISTS idx_explanation_document ON classification_explanations(document_id)'))
                conn.commit()
            except Exception:
                pass

        # Migration 9: smart_folders Spalten erweitern
        if 'smart_folders' in existing_tables:
            existing_columns = [col['name'] for col in inspector.get_columns('smart_folders')]

            if 'query_json' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE smart_folders ADD COLUMN query_json JSON'))
                    conn.commit()
                except Exception:
                    pass

            if 'entity_id' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE smart_folders ADD COLUMN entity_id INTEGER REFERENCES entities(id)'))
                    conn.commit()
                except Exception:
                    pass

            if 'show_aggregations' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE smart_folders ADD COLUMN show_aggregations BOOLEAN DEFAULT 0'))
                    conn.commit()
                except Exception:
                    pass

            if 'aggregation_fields' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE smart_folders ADD COLUMN aggregation_fields JSON'))
                    conn.commit()
                except Exception:
                    pass

            if 'cached_count' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE smart_folders ADD COLUMN cached_count INTEGER'))
                    conn.commit()
                except Exception:
                    pass

            if 'cache_updated_at' not in existing_columns:
                try:
                    conn.execute(text('ALTER TABLE smart_folders ADD COLUMN cache_updated_at DATETIME'))
                    conn.commit()
                except Exception:
                    pass


def create_indexes_safely(indexes_info: list):
    """Erstellt alle Indizes sicher mit IF NOT EXISTS"""
    with engine.connect() as conn:
        for idx in indexes_info:
            try:
                columns_str = ', '.join(idx['columns'])
                sql = f"CREATE INDEX IF NOT EXISTS {idx['name']} ON {idx['table']} ({columns_str})"
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Index existiert bereits oder Fehler ignorieren


# Cache für Index-Informationen (wird nur einmal beim Import gefüllt)
_cached_indexes = None


def _collect_index_info():
    """Sammelt Index-Informationen aus den Modellen (nur einmal)"""
    global _cached_indexes
    if _cached_indexes is None:
        _cached_indexes = []
        for table in Base.metadata.tables.values():
            for index in table.indexes:
                columns = [col.name for col in index.columns]
                _cached_indexes.append({
                    'name': index.name,
                    'table': table.name,
                    'columns': columns
                })
    return _cached_indexes


@st.cache_resource
def init_db():
    """Initialisiert die Datenbank und erstellt alle Tabellen (wird nur einmal ausgeführt)"""
    # Index-Informationen sammeln BEVOR wir sie entfernen
    indexes_info = _collect_index_info()

    # Indizes temporär aus den Metadaten entfernen, um Duplikat-Fehler zu vermeiden
    # SQLAlchemy's create_all() versucht sonst, bereits existierende Indizes zu erstellen
    all_indexes = []
    for table in Base.metadata.tables.values():
        all_indexes.extend(list(table.indexes))
        table.indexes.clear()

    try:
        # Tabellen ohne Indizes erstellen
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass  # Tabellen existieren bereits

    # Indizes wieder zu den Metadaten hinzufügen für zukünftige Referenz
    for idx in all_indexes:
        idx.table.indexes.add(idx)

    # Indizes sicher mit IF NOT EXISTS erstellen (aus dem Cache)
    create_indexes_safely(indexes_info)

    # Dann Migrationen für neue Spalten/Tabellen ausführen
    try:
        run_migrations()
    except Exception:
        pass  # Migrationen fehlgeschlagen, aber App soll weiterlaufen


def get_session() -> Session:
    """Gibt eine neue Datenbank-Session zurück"""
    return SessionLocal()


@contextmanager
def get_db():
    """Context Manager für Datenbank-Sessions"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_or_create_user(session: Session, email: str, password_hash: str, name: str = None) -> User:
    """Benutzer abrufen oder erstellen"""
    user = session.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            password_hash=password_hash,
            name=name or email.split('@')[0]
        )
        session.add(user)
        session.commit()

        # Standard-Ordner für neuen Benutzer erstellen
        create_default_folders(session, user.id)

    return user


def create_default_folders(session: Session, user_id: int):
    """Erstellt die Standard-Ordnerstruktur für einen neuen Benutzer"""
    for folder_data in DEFAULT_FOLDERS:
        folder = Folder(
            user_id=user_id,
            name=folder_data["name"],
            parent_id=folder_data["parent_id"],
            is_system=folder_data["is_system"]
        )
        session.add(folder)
    session.commit()


def ensure_user_exists(session: Session) -> User:
    """Stellt sicher, dass ein Standardbenutzer existiert (für Einzelnutzer-Modus)"""
    user = session.query(User).first()
    if not user:
        # Standardbenutzer erstellen
        import bcrypt
        password_hash = bcrypt.hashpw("demo".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        user = get_or_create_user(session, "user@local", password_hash, "Benutzer")
    return user


def get_current_user_id() -> int:
    """Gibt die ID des aktuellen Benutzers zurück"""
    if 'user_id' not in st.session_state:
        with get_db() as session:
            user = ensure_user_exists(session)
            st.session_state.user_id = user.id
    return st.session_state.user_id


def get_database_status() -> dict:
    """
    Gibt Informationen über die aktuelle Datenbankverbindung zurück.

    Returns:
        Dict mit:
        - type: 'sqlite', 'postgresql', 'mysql'
        - persistent: True wenn Cloud-DB, False wenn lokale SQLite
        - host: Hostname (bei Cloud-DB) oder Dateipfad (bei SQLite)
        - connected: True wenn Verbindung funktioniert
    """
    db_url = get_database_url()

    status = {
        'type': 'unknown',
        'persistent': False,
        'host': '',
        'connected': False,
        'warning': None
    }

    try:
        if db_url.startswith('sqlite'):
            status['type'] = 'sqlite'
            status['persistent'] = False
            status['host'] = str(DATABASE_PATH)
            status['warning'] = 'Lokale SQLite-Datenbank wird bei Neustart gelöscht!'
        elif db_url.startswith('postgresql'):
            status['type'] = 'postgresql'
            status['persistent'] = True
            # Host aus URL extrahieren (ohne Passwort)
            try:
                from urllib.parse import urlparse
                parsed = urlparse(db_url)
                status['host'] = parsed.hostname or 'unknown'
            except:
                status['host'] = 'cloud'
        elif db_url.startswith('mysql'):
            status['type'] = 'mysql'
            status['persistent'] = True
            try:
                from urllib.parse import urlparse
                parsed = urlparse(db_url)
                status['host'] = parsed.hostname or 'unknown'
            except:
                status['host'] = 'cloud'

        # Verbindung testen
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
            status['connected'] = True

    except Exception as e:
        status['connected'] = False
        status['warning'] = f'Verbindungsfehler: {str(e)}'

    return status
