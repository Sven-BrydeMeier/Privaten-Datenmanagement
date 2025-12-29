"""
Datenbankverbindung und Session-Management
"""
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import streamlit as st

from config.settings import DATABASE_PATH, DEFAULT_FOLDERS
from .models import Base, User, Folder

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


# Datenbank-Engine
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

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


def init_db():
    """Initialisiert die Datenbank und erstellt alle Tabellen"""
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
