"""
Verschlüsselungsservice für sichere Dokumentenspeicherung
Verwendet AES-256-GCM für authentifizierte Verschlüsselung
"""
import os
import base64
import hashlib
from typing import Tuple, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import streamlit as st


class EncryptionService:
    """Service für Ver- und Entschlüsselung von Dokumenten"""

    # Konstanten
    KEY_SIZE = 32  # 256 bits für AES-256
    NONCE_SIZE = 12  # 96 bits für GCM
    SALT_SIZE = 16  # 128 bits für Key-Derivation
    ITERATIONS = 100000  # PBKDF2 Iterationen

    def __init__(self, master_key: Optional[bytes] = None):
        """
        Initialisiert den Verschlüsselungsservice.

        Args:
            master_key: Optionaler Master-Key. Wenn nicht angegeben,
                        wird ein neuer generiert oder aus der Session geladen.
        """
        self._master_key = master_key

    @property
    def master_key(self) -> bytes:
        """Gibt den Master-Key zurück, lädt oder generiert ihn bei Bedarf"""
        if self._master_key is None:
            if 'encryption_key' in st.session_state:
                self._master_key = base64.b64decode(st.session_state.encryption_key)
            else:
                # Neuen Key generieren (nur für Demo/Entwicklung)
                self._master_key = self.generate_key()
                st.session_state.encryption_key = base64.b64encode(self._master_key).decode('utf-8')
        return self._master_key

    @staticmethod
    def generate_key() -> bytes:
        """Generiert einen sicheren zufälligen Schlüssel"""
        return os.urandom(EncryptionService.KEY_SIZE)

    @staticmethod
    def derive_key_from_password(password: str, salt: bytes = None) -> Tuple[bytes, bytes]:
        """
        Leitet einen Schlüssel aus einem Passwort ab.

        Args:
            password: Das Benutzerpasswort
            salt: Optionales Salt. Wird generiert wenn nicht angegeben.

        Returns:
            Tuple aus (abgeleiteter Schlüssel, Salt)
        """
        if salt is None:
            salt = os.urandom(EncryptionService.SALT_SIZE)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=EncryptionService.KEY_SIZE,
            salt=salt,
            iterations=EncryptionService.ITERATIONS,
            backend=default_backend()
        )

        key = kdf.derive(password.encode('utf-8'))
        return key, salt

    def encrypt(self, data: bytes, associated_data: bytes = None) -> Tuple[bytes, bytes]:
        """
        Verschlüsselt Daten mit AES-256-GCM.

        Args:
            data: Zu verschlüsselnde Daten
            associated_data: Optionale zusätzliche authentifizierte Daten (AAD)

        Returns:
            Tuple aus (verschlüsselte Daten, Nonce)
        """
        nonce = os.urandom(self.NONCE_SIZE)
        aesgcm = AESGCM(self.master_key)

        ciphertext = aesgcm.encrypt(nonce, data, associated_data)
        return ciphertext, nonce

    def decrypt(self, ciphertext: bytes, nonce: bytes, associated_data: bytes = None) -> bytes:
        """
        Entschlüsselt Daten.

        Args:
            ciphertext: Verschlüsselte Daten
            nonce: Der bei der Verschlüsselung verwendete Nonce
            associated_data: Die gleichen AAD wie bei der Verschlüsselung

        Returns:
            Entschlüsselte Daten
        """
        aesgcm = AESGCM(self.master_key)
        return aesgcm.decrypt(nonce, ciphertext, associated_data)

    def _normalize_filename_for_aad(self, filename: str) -> bytes:
        """
        Normalisiert einen Dateinamen für konsistente AAD-Verwendung.
        Stellt sicher, dass Umlaute (ä, ö, ü) konsistent behandelt werden.
        """
        import unicodedata

        # Sicherstellen, dass es ein String ist
        if isinstance(filename, bytes):
            try:
                filename = filename.decode('utf-8')
            except UnicodeDecodeError:
                filename = filename.decode('latin-1')

        # NFC-Normalisierung für konsistente Unicode-Darstellung
        # Dies ist wichtig für Umlaute, die auf verschiedenen Systemen
        # unterschiedlich kodiert sein können (precomposed vs decomposed)
        normalized = unicodedata.normalize('NFC', filename)

        return normalized.encode('utf-8')

    def encrypt_file(self, file_data: bytes, filename: str) -> Tuple[bytes, bytes]:
        """
        Verschlüsselt eine Datei.

        Args:
            file_data: Dateiinhalt
            filename: Dateiname (wird als AAD verwendet)

        Returns:
            Tuple aus (verschlüsselte Daten, Nonce)
        """
        # Dateiname als zusätzliche authentifizierte Daten (mit Unicode-Normalisierung)
        aad = self._normalize_filename_for_aad(filename)
        return self.encrypt(file_data, aad)

    def decrypt_file(self, ciphertext: bytes, nonce: bytes, filename: str) -> bytes:
        """
        Entschlüsselt eine Datei.

        Args:
            ciphertext: Verschlüsselte Datei
            nonce: Der bei der Verschlüsselung verwendete Nonce
            filename: Dateiname (muss mit dem bei Verschlüsselung übereinstimmen)

        Returns:
            Entschlüsselte Datei
        """
        # Gleiche Normalisierung wie bei Verschlüsselung
        aad = self._normalize_filename_for_aad(filename)
        return self.decrypt(ciphertext, nonce, aad)

    @staticmethod
    def hash_password(password: str) -> str:
        """Erstellt einen sicheren Hash eines Passworts"""
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Überprüft ein Passwort gegen einen Hash"""
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

    def encrypt_text(self, text: str) -> Tuple[str, str]:
        """
        Verschlüsselt Text und gibt Base64-kodierte Strings zurück.

        Args:
            text: Zu verschlüsselnder Text

        Returns:
            Tuple aus (Base64-kodierter Ciphertext, Base64-kodierter Nonce)
        """
        ciphertext, nonce = self.encrypt(text.encode('utf-8'))
        return (
            base64.b64encode(ciphertext).decode('utf-8'),
            base64.b64encode(nonce).decode('utf-8')
        )

    def decrypt_text(self, ciphertext_b64: str, nonce_b64: str) -> str:
        """
        Entschlüsselt Base64-kodierten Text.

        Args:
            ciphertext_b64: Base64-kodierter Ciphertext
            nonce_b64: Base64-kodierter Nonce

        Returns:
            Entschlüsselter Text
        """
        ciphertext = base64.b64decode(ciphertext_b64)
        nonce = base64.b64decode(nonce_b64)
        return self.decrypt(ciphertext, nonce).decode('utf-8')


def get_encryption_service() -> EncryptionService:
    """Singleton für den Verschlüsselungsservice"""
    if 'encryption_service' not in st.session_state:
        st.session_state.encryption_service = EncryptionService()
    return st.session_state.encryption_service
