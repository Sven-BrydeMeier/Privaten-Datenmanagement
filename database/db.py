"""
Datenbankverbindung und Session-Management
"""
from sqlalchemy import create_engine, event
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


def init_db():
    """Initialisiert die Datenbank und erstellt alle Tabellen"""
    Base.metadata.create_all(bind=engine)


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
