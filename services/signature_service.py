"""
Signature Service für E-Mail-Signatur-Erkennung und -Verwaltung

Funktionen:
- Signaturen verwalten (CRUD)
- Signaturen in E-Mails erkennen (Fuzzy Matching, Regex, exakt)
- Standard-Signatur pro Benutzer
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from database.db import get_db
from database.models import EmailSignature

logger = logging.getLogger(__name__)


class SignatureService:
    """Service für E-Mail-Signatur-Erkennung und -Verwaltung"""

    # Standard-Trigger für Signatur-Beginn
    SIGNATURE_TRIGGERS = [
        "mit freundlichen grüßen",
        "mit freundlichem gruß",
        "freundliche grüße",
        "beste grüße",
        "viele grüße",
        "liebe grüße",
        "hochachtungsvoll",
        "mfg",
        "regards",
        "best regards",
        "kind regards",
        "sincerely",
        "--",  # Standard E-Mail-Signatur-Trenner
        "___",  # Alternativer Trenner
    ]

    def __init__(self, user_id: int):
        self.user_id = user_id

    # ============================================================
    # CRUD OPERATIONEN
    # ============================================================

    def get_all_signatures(self) -> List[Dict]:
        """Alle Signaturen des Benutzers laden"""
        with get_db() as session:
            signatures = session.query(EmailSignature).filter(
                EmailSignature.user_id == self.user_id
            ).order_by(EmailSignature.is_default.desc(), EmailSignature.name).all()

            return [self._signature_to_dict(sig) for sig in signatures]

    def get_signature(self, signature_id: int) -> Optional[Dict]:
        """Eine Signatur laden"""
        with get_db() as session:
            sig = session.query(EmailSignature).filter(
                EmailSignature.id == signature_id,
                EmailSignature.user_id == self.user_id
            ).first()
            return self._signature_to_dict(sig) if sig else None

    def get_default_signature(self) -> Optional[Dict]:
        """Standard-Signatur laden"""
        with get_db() as session:
            sig = session.query(EmailSignature).filter(
                EmailSignature.user_id == self.user_id,
                EmailSignature.is_default == True
            ).first()
            return self._signature_to_dict(sig) if sig else None

    def create_signature(
        self,
        name: str,
        email_address: str,
        patterns: List[Dict],
        signature_text: str = None,
        signature_html: str = None,
        is_default: bool = False,
        description: str = None
    ) -> Dict:
        """Neue Signatur erstellen"""
        with get_db() as session:
            # Wenn default, alle anderen auf non-default setzen
            if is_default:
                session.query(EmailSignature).filter(
                    EmailSignature.user_id == self.user_id
                ).update({"is_default": False})

            sig = EmailSignature(
                user_id=self.user_id,
                name=name,
                email_address=email_address,
                patterns=patterns,
                signature_text=signature_text,
                signature_html=signature_html,
                is_default=is_default,
                description=description,
                is_enabled=True
            )
            session.add(sig)
            session.commit()

            logger.info(f"Signatur erstellt: {name} ({email_address})")
            return self._signature_to_dict(sig)

    def update_signature(self, signature_id: int, **kwargs) -> Optional[Dict]:
        """Signatur aktualisieren"""
        with get_db() as session:
            sig = session.query(EmailSignature).filter(
                EmailSignature.id == signature_id,
                EmailSignature.user_id == self.user_id
            ).first()

            if not sig:
                return None

            # Wenn default gesetzt wird, alle anderen auf non-default
            if kwargs.get('is_default'):
                session.query(EmailSignature).filter(
                    EmailSignature.user_id == self.user_id,
                    EmailSignature.id != signature_id
                ).update({"is_default": False})

            # Felder aktualisieren
            for key, value in kwargs.items():
                if hasattr(sig, key):
                    setattr(sig, key, value)

            session.commit()
            logger.info(f"Signatur aktualisiert: {sig.name}")
            return self._signature_to_dict(sig)

    def delete_signature(self, signature_id: int) -> bool:
        """Signatur löschen"""
        with get_db() as session:
            sig = session.query(EmailSignature).filter(
                EmailSignature.id == signature_id,
                EmailSignature.user_id == self.user_id
            ).first()

            if sig:
                session.delete(sig)
                session.commit()
                logger.info(f"Signatur gelöscht: {sig.name}")
                return True
            return False

    def set_default_signature(self, signature_id: int) -> bool:
        """Signatur als Standard setzen"""
        with get_db() as session:
            # Alle auf non-default
            session.query(EmailSignature).filter(
                EmailSignature.user_id == self.user_id
            ).update({"is_default": False})

            # Diese auf default
            result = session.query(EmailSignature).filter(
                EmailSignature.id == signature_id,
                EmailSignature.user_id == self.user_id
            ).update({"is_default": True})

            session.commit()
            return result > 0

    # ============================================================
    # SIGNATUR-ERKENNUNG
    # ============================================================

    def detect_signature(self, email_text: str, email_from: str = None) -> Dict:
        """
        Erkennt Signatur in E-Mail-Text.

        Returns:
            Dict mit:
            - detected: bool
            - signature_id: int (falls erkannt)
            - signature_name: str
            - confidence: float (0.0-1.0)
            - matched_patterns: List[str]
            - signature_start_pos: int (Position im Text)
            - stripped_text: str (Text ohne Signatur)
        """
        result = {
            "detected": False,
            "signature_id": None,
            "signature_name": None,
            "confidence": 0.0,
            "matched_patterns": [],
            "signature_start_pos": -1,
            "stripped_text": email_text
        }

        if not email_text:
            return result

        text_lower = email_text.lower()
        text_normalized = self._normalize_text(email_text)

        # Alle aktiven Signaturen laden
        with get_db() as session:
            signatures = session.query(EmailSignature).filter(
                EmailSignature.user_id == self.user_id,
                EmailSignature.is_enabled == True
            ).all()

            best_match = None
            best_confidence = 0.0
            best_patterns = []

            for sig in signatures:
                confidence, matched = self._match_signature(
                    text_normalized, text_lower, sig, email_from
                )

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = sig
                    best_patterns = matched

            if best_match and best_confidence >= 0.5:
                # Signatur-Start-Position finden
                sig_start = self._find_signature_start(email_text)

                result["detected"] = True
                result["signature_id"] = best_match.id
                result["signature_name"] = best_match.name
                result["confidence"] = best_confidence
                result["matched_patterns"] = best_patterns
                result["signature_start_pos"] = sig_start

                # Text ohne Signatur
                if sig_start > 0:
                    result["stripped_text"] = email_text[:sig_start].strip()

                # Statistik aktualisieren
                best_match.times_detected = (best_match.times_detected or 0) + 1
                best_match.last_detected_at = datetime.now()
                session.commit()

                logger.info(
                    f"Signatur erkannt: {best_match.name} "
                    f"(Konfidenz: {best_confidence:.2f})"
                )

        return result

    def _match_signature(
        self,
        text_normalized: str,
        text_lower: str,
        signature: EmailSignature,
        email_from: str = None
    ) -> Tuple[float, List[str]]:
        """
        Prüft ob Signatur im Text vorkommt.

        Returns:
            Tuple (confidence, matched_patterns)
        """
        patterns = signature.patterns or []
        if not patterns:
            return 0.0, []

        total_weight = 0.0
        matched_weight = 0.0
        matched_patterns = []

        for pattern in patterns:
            pattern_type = pattern.get("type", "contains")
            pattern_value = pattern.get("value", "")
            pattern_weight = pattern.get("weight", 1.0)
            threshold = pattern.get("threshold", 80)

            total_weight += pattern_weight

            if not pattern_value:
                continue

            matched = False
            pattern_lower = pattern_value.lower()

            if pattern_type == "exact":
                # Exakter Match
                matched = pattern_lower in text_lower

            elif pattern_type == "contains":
                # Enthält (case-insensitive)
                matched = pattern_lower in text_lower

            elif pattern_type == "regex":
                # Regex-Match
                try:
                    if re.search(pattern_value, text_normalized, re.IGNORECASE):
                        matched = True
                except re.error:
                    logger.warning(f"Ungültiges Regex-Pattern: {pattern_value}")

            elif pattern_type == "fuzzy":
                # Fuzzy-Match mit rapidfuzz (falls installiert)
                try:
                    from rapidfuzz import fuzz
                    ratio = fuzz.token_set_ratio(pattern_lower, text_lower)
                    if ratio >= threshold:
                        matched = True
                except ImportError:
                    # Fallback: einfacher contains-Check
                    matched = pattern_lower in text_lower

            elif pattern_type == "email":
                # E-Mail-Adresse prüfen (im From-Header oder Text)
                if email_from and pattern_lower in email_from.lower():
                    matched = True
                elif pattern_lower in text_lower:
                    matched = True

            if matched:
                matched_weight += pattern_weight
                matched_patterns.append(pattern_value)

        confidence = matched_weight / total_weight if total_weight > 0 else 0.0
        return confidence, matched_patterns

    def _find_signature_start(self, text: str) -> int:
        """Findet den Beginn der Signatur im Text"""
        text_lower = text.lower()

        # Nach Signatur-Triggern suchen (von hinten nach vorne)
        best_pos = -1

        for trigger in self.SIGNATURE_TRIGGERS:
            pos = text_lower.rfind(trigger)
            if pos > 0:
                # Nur wenn es nicht am Anfang ist
                if best_pos == -1 or pos < best_pos:
                    best_pos = pos

        return best_pos

    def strip_signature(self, email_text: str) -> str:
        """Entfernt Signatur aus E-Mail-Text"""
        result = self.detect_signature(email_text)
        return result.get("stripped_text", email_text)

    # ============================================================
    # HILFSFUNKTIONEN
    # ============================================================

    def _normalize_text(self, text: str) -> str:
        """Normalisiert Text für Vergleich"""
        # Mehrfache Whitespaces zu einem
        text = re.sub(r'\s+', ' ', text)
        # HTML-Entities entfernen (falls vorhanden)
        text = re.sub(r'&\w+;', '', text)
        return text.strip()

    def _signature_to_dict(self, sig: EmailSignature) -> Dict:
        """Konvertiert Signatur-Model zu Dict"""
        if not sig:
            return None
        return {
            "id": sig.id,
            "name": sig.name,
            "description": sig.description,
            "email_address": sig.email_address,
            "is_default": sig.is_default,
            "patterns": sig.patterns or [],
            "signature_text": sig.signature_text,
            "signature_html": sig.signature_html,
            "times_detected": sig.times_detected or 0,
            "last_detected_at": sig.last_detected_at,
            "is_enabled": sig.is_enabled,
            "created_at": sig.created_at,
            "updated_at": sig.updated_at
        }

    # ============================================================
    # VORLAGEN
    # ============================================================

    def create_default_signature_for_email(self, email_address: str, name: str = None) -> Dict:
        """
        Erstellt eine Standard-Signatur basierend auf E-Mail-Adresse.
        Nützlich für initiale Setup.
        """
        if not name:
            # Name aus E-Mail-Adresse extrahieren
            local_part = email_address.split("@")[0]
            name = local_part.replace(".", " ").replace("_", " ").title()

        domain = email_address.split("@")[1] if "@" in email_address else ""

        patterns = [
            {"type": "email", "value": email_address, "weight": 2.0},
            {"type": "contains", "value": name, "weight": 1.5},
        ]

        # Domain-basierte Patterns hinzufügen
        if domain:
            domain_name = domain.split(".")[0]
            patterns.append({
                "type": "contains",
                "value": domain_name,
                "weight": 1.0
            })

        return self.create_signature(
            name=f"Signatur {name}",
            email_address=email_address,
            patterns=patterns,
            is_default=True,
            description=f"Automatisch erstellt für {email_address}"
        )


# Singleton-Instanz-Cache
_signature_services: Dict[int, SignatureService] = {}


def get_signature_service(user_id: int) -> SignatureService:
    """Gibt SignatureService-Instanz für Benutzer zurück"""
    if user_id not in _signature_services:
        _signature_services[user_id] = SignatureService(user_id)
    return _signature_services[user_id]
