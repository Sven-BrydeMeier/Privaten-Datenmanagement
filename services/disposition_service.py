"""
Disposition Service für Verfügungserkennung in E-Mails

Funktionen:
- Erkennung von Verfügungen (Keywords, Muster, KI)
- Extraktion von strukturierten Aktionen
- Speicherung und Verwaltung von Verfügungen
"""

import re
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from database.db import get_db
from database.models import EmailDisposition, Email

logger = logging.getLogger(__name__)


class DispositionEngine:
    """Engine zur Erkennung und Verarbeitung von Verfügungen in E-Mails"""

    # Deutsche Verfügungs-Keywords (Trigger)
    DISPOSITION_TRIGGERS = {
        # Höchste Priorität - explizite Verfügungen
        "verfügung:": {"priority": 100, "type": "verfuegung"},
        "verfügung": {"priority": 95, "type": "verfuegung"},
        "ich verfüge": {"priority": 95, "type": "verfuegung"},
        "hiermit verfüge ich": {"priority": 95, "type": "verfuegung"},

        # Hohe Priorität - Anweisungen
        "bitte veranlassen": {"priority": 90, "type": "anweisung"},
        "bitte veranlassen sie": {"priority": 90, "type": "anweisung"},
        "ich bitte um": {"priority": 85, "type": "bitte"},
        "ich bitte sie": {"priority": 85, "type": "bitte"},
        "bitte erledigen": {"priority": 85, "type": "anweisung"},

        # Mittlere Priorität - Akten/Ablage
        "bitte zu den akten": {"priority": 80, "type": "ablage"},
        "zu den akten": {"priority": 75, "type": "ablage"},
        "bitte ablegen": {"priority": 75, "type": "ablage"},
        "zur akte": {"priority": 75, "type": "ablage"},
        "zur akte nehmen": {"priority": 80, "type": "ablage"},

        # Fristen
        "frist:": {"priority": 85, "type": "frist"},
        "frist bis": {"priority": 85, "type": "frist"},
        "termin:": {"priority": 80, "type": "termin"},
        "bis zum": {"priority": 70, "type": "frist"},
        "spätestens bis": {"priority": 75, "type": "frist"},

        # Weiterleitungen
        "bitte weiterleiten an": {"priority": 80, "type": "weiterleitung"},
        "zur kenntnisnahme an": {"priority": 70, "type": "weiterleitung"},
        "zur bearbeitung an": {"priority": 80, "type": "weiterleitung"},

        # Antworten
        "bitte antworten": {"priority": 75, "type": "antwort"},
        "antwort erforderlich": {"priority": 80, "type": "antwort"},
        "um antwort wird gebeten": {"priority": 75, "type": "antwort"},

        # Wiedervorlage
        "wiedervorlage": {"priority": 80, "type": "wiedervorlage"},
        "wv:": {"priority": 80, "type": "wiedervorlage"},
        "zur wiedervorlage": {"priority": 80, "type": "wiedervorlage"},

        # Niedrigere Priorität - allgemeine Bitten
        "bitte prüfen": {"priority": 65, "type": "pruefung"},
        "bitte beachten": {"priority": 60, "type": "hinweis"},
        "bitte bearbeiten": {"priority": 70, "type": "bearbeitung"},
    }

    # Muster für Datumsextraktion (deutsch)
    DATE_PATTERNS = [
        r'(\d{1,2})\.(\d{1,2})\.(\d{4})',  # 31.12.2024
        r'(\d{1,2})\.(\d{1,2})\.(\d{2})',   # 31.12.24
        r'(\d{1,2})\.\s*(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\s*(\d{4})',
        r'bis\s+zum\s+(\d{1,2})\.(\d{1,2})\.(\d{4})',
        r'frist[:\s]+(\d{1,2})\.(\d{1,2})\.(\d{4})',
    ]

    # Muster für Personenzuweisung
    ASSIGNEE_PATTERNS = [
        r'(?:an|für|herr|frau|kollege|kollegin)\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)',
        r'zur\s+bearbeitung\s+(?:an\s+)?([A-ZÄÖÜ][a-zäöüß]+)',
        r'([A-ZÄÖÜ][a-zäöüß]+)\s+soll',
    ]

    def __init__(self, user_id: int):
        self.user_id = user_id
        self._ai_service = None

    @property
    def ai_service(self):
        """Lazy-Loading des AI-Service"""
        if self._ai_service is None:
            try:
                from services.ai_service import get_ai_service
                self._ai_service = get_ai_service()
            except ImportError:
                self._ai_service = None
        return self._ai_service

    # ============================================================
    # VERFÜGUNGSERKENNUNG
    # ============================================================

    def detect_disposition(self, email_text: str, subject: str = None) -> Dict:
        """
        Erkennt Verfügung in E-Mail-Text.

        Returns:
            Dict mit:
            - has_disposition: bool
            - disposition_type: str
            - trigger_keyword: str
            - confidence: float
            - raw_text: str (extrahierter Verfügungstext)
            - actions: List[Dict] (strukturierte Aktionen)
        """
        result = {
            "has_disposition": False,
            "disposition_type": None,
            "trigger_keyword": None,
            "confidence": 0.0,
            "raw_text": None,
            "actions": [],
            "detection_method": "keyword"
        }

        if not email_text:
            return result

        text_lower = email_text.lower()

        # 1. Nach Trigger-Keywords suchen
        best_trigger = None
        best_priority = 0
        best_position = -1

        for trigger, config in self.DISPOSITION_TRIGGERS.items():
            pos = text_lower.find(trigger)
            if pos >= 0:
                if config["priority"] > best_priority:
                    best_priority = config["priority"]
                    best_trigger = trigger
                    best_position = pos
                    result["disposition_type"] = config["type"]

        if best_trigger:
            result["has_disposition"] = True
            result["trigger_keyword"] = best_trigger
            result["confidence"] = min(best_priority / 100.0, 1.0)

            # Verfügungstext extrahieren
            raw_text = self._extract_disposition_text(email_text, best_position)
            result["raw_text"] = raw_text

            # Aktionen extrahieren (regelbasiert)
            result["actions"] = self._extract_actions(raw_text, email_text)

            logger.info(
                f"Verfügung erkannt: '{best_trigger}' "
                f"(Typ: {result['disposition_type']}, Konfidenz: {result['confidence']:.2f})"
            )

        # 2. Bei niedriger Konfidenz oder keinem Match: KI-Analyse (optional)
        if result["confidence"] < 0.7 and self.ai_service and self.ai_service.any_ai_available:
            ai_result = self._analyze_with_ai(email_text, subject)
            if ai_result and ai_result.get("has_disposition"):
                # KI-Ergebnis hat Vorrang bei höherer Konfidenz
                if ai_result.get("confidence", 0) > result["confidence"]:
                    result.update(ai_result)
                    result["detection_method"] = "ai"

        return result

    def _extract_disposition_text(self, text: str, trigger_pos: int) -> str:
        """Extrahiert den Verfügungstext ab dem Trigger"""
        if trigger_pos < 0:
            return ""

        # Text ab Trigger bis zum Ende oder bis zu einem Abschluss
        remaining = text[trigger_pos:]

        # Nach typischen Abschluss-Markern suchen
        end_markers = [
            "\n\n",  # Doppelter Zeilenumbruch
            "mit freundlichen grüßen",
            "freundliche grüße",
            "beste grüße",
            "mfg",
            "--",
            "___",
        ]

        end_pos = len(remaining)
        remaining_lower = remaining.lower()

        for marker in end_markers:
            pos = remaining_lower.find(marker)
            if pos > 0 and pos < end_pos:
                end_pos = pos

        return remaining[:end_pos].strip()

    def _extract_actions(self, disposition_text: str, full_text: str) -> List[Dict]:
        """Extrahiert strukturierte Aktionen aus dem Verfügungstext"""
        actions = []
        text_lower = disposition_text.lower()

        # 1. Ordner/Akte erkennen
        folder_match = re.search(
            r'(?:akte|ordner|zu den akten|zur akte)[:\s]+([^\n,\.]+)',
            text_lower
        )
        if folder_match:
            actions.append({
                "type": "move_to_folder",
                "target": folder_match.group(1).strip(),
                "confidence": 0.8
            })

        # 2. Fristen erkennen
        for pattern in self.DATE_PATTERNS:
            date_match = re.search(pattern, disposition_text, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(0)
                parsed_date = self._parse_german_date(date_str)
                if parsed_date:
                    actions.append({
                        "type": "set_deadline",
                        "date": parsed_date.isoformat(),
                        "date_str": date_str,
                        "confidence": 0.85
                    })
                    break

        # 3. Personenzuweisung erkennen
        for pattern in self.ASSIGNEE_PATTERNS:
            assignee_match = re.search(pattern, disposition_text, re.IGNORECASE)
            if assignee_match:
                actions.append({
                    "type": "assign_to",
                    "person": assignee_match.group(1).strip(),
                    "confidence": 0.7
                })
                break

        # 4. Wiedervorlage erkennen
        wv_match = re.search(
            r'(?:wiedervorlage|wv)[:\s]+(\d{1,2})\.(\d{1,2})\.(\d{2,4})',
            text_lower
        )
        if wv_match:
            date_str = f"{wv_match.group(1)}.{wv_match.group(2)}.{wv_match.group(3)}"
            parsed_date = self._parse_german_date(date_str)
            if parsed_date:
                actions.append({
                    "type": "create_reminder",
                    "date": parsed_date.isoformat(),
                    "description": "Wiedervorlage",
                    "confidence": 0.9
                })

        # 5. Aufgabe erkennen
        task_keywords = ["erledigen", "bearbeiten", "prüfen", "vorbereiten", "erstellen"]
        for keyword in task_keywords:
            if keyword in text_lower:
                # Aufgabenbeschreibung extrahieren
                task_match = re.search(
                    rf'(?:bitte\s+)?{keyword}[:\s]+([^\n\.]+)',
                    text_lower
                )
                if task_match:
                    actions.append({
                        "type": "create_task",
                        "title": task_match.group(1).strip().capitalize(),
                        "keyword": keyword,
                        "confidence": 0.75
                    })
                    break

        # 6. Antwort erforderlich
        if any(kw in text_lower for kw in ["antwort", "antworten", "beantworten", "rückmeldung"]):
            actions.append({
                "type": "create_response",
                "description": "Antwort erforderlich",
                "confidence": 0.7
            })

        return actions

    def _analyze_with_ai(self, email_text: str, subject: str = None) -> Optional[Dict]:
        """Analysiert E-Mail mit KI zur Verfügungserkennung"""
        if not self.ai_service or not self.ai_service.any_ai_available:
            return None

        try:
            prompt = f"""Analysiere diese E-Mail auf Verfügungen oder Anweisungen.

Betreff: {subject or 'Kein Betreff'}

E-Mail-Text:
{email_text[:3000]}

Prüfe ob die E-Mail eine Verfügung, Anweisung oder Bitte enthält.
Antworte NUR mit JSON in diesem Format:
{{
    "has_disposition": true/false,
    "disposition_type": "verfuegung" | "anweisung" | "bitte" | "frist" | "ablage" | null,
    "confidence": 0.0-1.0,
    "raw_text": "Der relevante Verfügungstext",
    "actions": [
        {{"type": "move_to_folder", "target": "Ordnername"}},
        {{"type": "set_deadline", "date": "YYYY-MM-DD", "description": "Beschreibung"}},
        {{"type": "assign_to", "person": "Name"}},
        {{"type": "create_task", "title": "Aufgabe"}},
        {{"type": "create_response", "description": "Antwort erforderlich"}}
    ]
}}"""

            response = self.ai_service.chat(prompt)
            if response:
                # JSON aus Antwort extrahieren
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    result = json.loads(json_match.group())
                    return result
        except Exception as e:
            logger.warning(f"KI-Analyse für Verfügung fehlgeschlagen: {e}")

        return None

    def _parse_german_date(self, date_str: str) -> Optional[datetime]:
        """Parst deutsches Datum"""
        # Monatsnamen
        months = {
            'januar': 1, 'februar': 2, 'märz': 3, 'april': 4,
            'mai': 5, 'juni': 6, 'juli': 7, 'august': 8,
            'september': 9, 'oktober': 10, 'november': 11, 'dezember': 12
        }

        try:
            # Format: DD.MM.YYYY
            match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})', date_str)
            if match:
                day = int(match.group(1))
                month = int(match.group(2))
                year = int(match.group(3))
                if year < 100:
                    year += 2000
                return datetime(year, month, day)

            # Format: DD. Monat YYYY
            for month_name, month_num in months.items():
                if month_name in date_str.lower():
                    match = re.search(rf'(\d{{1,2}})\.\s*{month_name}\s*(\d{{4}})', date_str.lower())
                    if match:
                        return datetime(int(match.group(2)), month_num, int(match.group(1)))
        except (ValueError, AttributeError):
            pass

        return None

    # ============================================================
    # VERFÜGUNGSVERWALTUNG
    # ============================================================

    def save_disposition(
        self,
        email_id: int,
        detection_result: Dict
    ) -> Optional[int]:
        """Speichert erkannte Verfügung in der Datenbank"""
        if not detection_result.get("has_disposition"):
            return None

        with get_db() as session:
            disposition = EmailDisposition(
                email_id=email_id,
                user_id=self.user_id,
                raw_text=detection_result.get("raw_text"),
                trigger_keyword=detection_result.get("trigger_keyword"),
                detection_method=detection_result.get("detection_method", "keyword"),
                confidence=detection_result.get("confidence"),
                actions=detection_result.get("actions", []),
                status="open"
            )
            session.add(disposition)

            # Email aktualisieren
            email = session.get(Email, email_id)
            if email:
                email.has_disposition = True
                email.disposition_type = detection_result.get("disposition_type")
                email.disposition_confidence = detection_result.get("confidence")
                email.disposition_extracted = True

            session.commit()

            logger.info(f"Verfügung gespeichert für E-Mail {email_id}")
            return disposition.id

        return None

    def get_dispositions(
        self,
        status: str = None,
        limit: int = 50
    ) -> List[Dict]:
        """Lädt Verfügungen des Benutzers"""
        with get_db() as session:
            query = session.query(EmailDisposition).filter(
                EmailDisposition.user_id == self.user_id
            )

            if status:
                query = query.filter(EmailDisposition.status == status)

            dispositions = query.order_by(
                EmailDisposition.created_at.desc()
            ).limit(limit).all()

            return [self._disposition_to_dict(d) for d in dispositions]

    def get_open_dispositions(self) -> List[Dict]:
        """Lädt offene Verfügungen"""
        return self.get_dispositions(status="open")

    def complete_disposition(self, disposition_id: int, completed_by: str = None) -> bool:
        """Markiert Verfügung als erledigt"""
        with get_db() as session:
            disposition = session.query(EmailDisposition).filter(
                EmailDisposition.id == disposition_id,
                EmailDisposition.user_id == self.user_id
            ).first()

            if disposition:
                disposition.status = "completed"
                disposition.completed_at = datetime.now()
                disposition.completed_by = completed_by
                session.commit()
                return True

        return False

    def _disposition_to_dict(self, d: EmailDisposition) -> Dict:
        """Konvertiert Disposition zu Dict"""
        return {
            "id": d.id,
            "email_id": d.email_id,
            "raw_text": d.raw_text,
            "trigger_keyword": d.trigger_keyword,
            "detection_method": d.detection_method,
            "confidence": d.confidence,
            "actions": d.actions or [],
            "status": d.status,
            "created_at": d.created_at,
            "completed_at": d.completed_at,
            "completed_by": d.completed_by
        }


# Singleton-Cache
_disposition_engines: Dict[int, DispositionEngine] = {}


def get_disposition_engine(user_id: int) -> DispositionEngine:
    """Gibt DispositionEngine für Benutzer zurück"""
    if user_id not in _disposition_engines:
        _disposition_engines[user_id] = DispositionEngine(user_id)
    return _disposition_engines[user_id]
