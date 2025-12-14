"""
Vorlagen-System Service
Erstellt und verwaltet Dokumentenvorlagen
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
import re

from database.models import get_session
from database.extended_models import DocumentTemplate


class TemplateService:
    """Service für Dokumentenvorlagen"""

    # Standard-Vorlagen
    DEFAULT_TEMPLATES = [
        {
            "name": "Kündigung Allgemein",
            "category": "letter",
            "content": """{{absender_name}}
{{absender_adresse}}
{{absender_plz}} {{absender_ort}}

{{empfaenger_name}}
{{empfaenger_adresse}}
{{empfaenger_plz}} {{empfaenger_ort}}

{{datum}}

Kündigung {{vertragsart}} - Vertragsnummer: {{vertragsnummer}}

Sehr geehrte Damen und Herren,

hiermit kündige ich den oben genannten Vertrag fristgerecht zum nächstmöglichen Zeitpunkt.

Bitte bestätigen Sie mir den Eingang dieser Kündigung sowie das Datum, zu dem der Vertrag endet.

Mit freundlichen Grüßen

{{unterschrift}}
{{absender_name}}""",
            "placeholders": [
                {"key": "absender_name", "label": "Ihr Name", "type": "text"},
                {"key": "absender_adresse", "label": "Ihre Straße", "type": "text"},
                {"key": "absender_plz", "label": "Ihre PLZ", "type": "text"},
                {"key": "absender_ort", "label": "Ihr Ort", "type": "text"},
                {"key": "empfaenger_name", "label": "Empfänger Name", "type": "text"},
                {"key": "empfaenger_adresse", "label": "Empfänger Straße", "type": "text"},
                {"key": "empfaenger_plz", "label": "Empfänger PLZ", "type": "text"},
                {"key": "empfaenger_ort", "label": "Empfänger Ort", "type": "text"},
                {"key": "datum", "label": "Datum", "type": "date"},
                {"key": "vertragsart", "label": "Vertragsart", "type": "text"},
                {"key": "vertragsnummer", "label": "Vertragsnummer", "type": "text"},
                {"key": "unterschrift", "label": "Unterschrift", "type": "text"}
            ]
        },
        {
            "name": "Widerspruch",
            "category": "letter",
            "content": """{{absender_name}}
{{absender_adresse}}
{{absender_plz}} {{absender_ort}}

{{empfaenger_name}}
{{empfaenger_adresse}}
{{empfaenger_plz}} {{empfaenger_ort}}

{{datum}}

Widerspruch gegen {{bescheid_art}} vom {{bescheid_datum}}
Aktenzeichen: {{aktenzeichen}}

Sehr geehrte Damen und Herren,

hiermit lege ich Widerspruch gegen den oben genannten Bescheid ein.

Begründung:
{{begruendung}}

Ich bitte um Überprüfung und erneute Bescheidung.

Mit freundlichen Grüßen

{{absender_name}}""",
            "placeholders": [
                {"key": "absender_name", "label": "Ihr Name", "type": "text"},
                {"key": "absender_adresse", "label": "Ihre Straße", "type": "text"},
                {"key": "absender_plz", "label": "Ihre PLZ", "type": "text"},
                {"key": "absender_ort", "label": "Ihr Ort", "type": "text"},
                {"key": "empfaenger_name", "label": "Behörde/Empfänger", "type": "text"},
                {"key": "empfaenger_adresse", "label": "Empfänger Straße", "type": "text"},
                {"key": "empfaenger_plz", "label": "Empfänger PLZ", "type": "text"},
                {"key": "empfaenger_ort", "label": "Empfänger Ort", "type": "text"},
                {"key": "datum", "label": "Datum", "type": "date"},
                {"key": "bescheid_art", "label": "Art des Bescheids", "type": "text"},
                {"key": "bescheid_datum", "label": "Datum des Bescheids", "type": "date"},
                {"key": "aktenzeichen", "label": "Aktenzeichen", "type": "text"},
                {"key": "begruendung", "label": "Begründung", "type": "textarea"}
            ]
        },
        {
            "name": "Reklamation",
            "category": "letter",
            "content": """{{absender_name}}
{{absender_adresse}}
{{absender_plz}} {{absender_ort}}

{{empfaenger_name}}
{{empfaenger_adresse}}
{{empfaenger_plz}} {{empfaenger_ort}}

{{datum}}

Reklamation - Bestellnummer: {{bestellnummer}}

Sehr geehrte Damen und Herren,

am {{kaufdatum}} habe ich bei Ihnen folgendes Produkt gekauft/bestellt:

{{produktname}}
Kaufpreis: {{kaufpreis}} €

Leider muss ich folgende Mängel beanstanden:
{{maengel}}

Ich fordere Sie auf, {{forderung}}.

Bitte teilen Sie mir innerhalb von 14 Tagen mit, wie Sie weiter verfahren möchten.

Mit freundlichen Grüßen

{{absender_name}}

Anlagen:
- Kaufbeleg""",
            "placeholders": [
                {"key": "absender_name", "label": "Ihr Name", "type": "text"},
                {"key": "absender_adresse", "label": "Ihre Straße", "type": "text"},
                {"key": "absender_plz", "label": "Ihre PLZ", "type": "text"},
                {"key": "absender_ort", "label": "Ihr Ort", "type": "text"},
                {"key": "empfaenger_name", "label": "Händler Name", "type": "text"},
                {"key": "empfaenger_adresse", "label": "Händler Straße", "type": "text"},
                {"key": "empfaenger_plz", "label": "Händler PLZ", "type": "text"},
                {"key": "empfaenger_ort", "label": "Händler Ort", "type": "text"},
                {"key": "datum", "label": "Datum", "type": "date"},
                {"key": "bestellnummer", "label": "Bestellnummer", "type": "text"},
                {"key": "kaufdatum", "label": "Kaufdatum", "type": "date"},
                {"key": "produktname", "label": "Produktname", "type": "text"},
                {"key": "kaufpreis", "label": "Kaufpreis", "type": "number"},
                {"key": "maengel", "label": "Beschreibung der Mängel", "type": "textarea"},
                {"key": "forderung", "label": "Ihre Forderung", "type": "text"}
            ]
        },
        {
            "name": "SEPA-Lastschrift Widerruf",
            "category": "letter",
            "content": """{{absender_name}}
{{absender_adresse}}
{{absender_plz}} {{absender_ort}}

{{bank_name}}
{{bank_adresse}}
{{bank_plz}} {{bank_ort}}

{{datum}}

Widerruf einer SEPA-Lastschrift

Kontoinhaber: {{absender_name}}
IBAN: {{iban}}

Sehr geehrte Damen und Herren,

hiermit widerrufe ich die folgende SEPA-Lastschrift und bitte um Rückbuchung des Betrages:

Betrag: {{betrag}} €
Abbuchungsdatum: {{abbuchungsdatum}}
Empfänger: {{empfaenger}}
Verwendungszweck: {{verwendungszweck}}

Begründung: {{begruendung}}

Bitte buchen Sie den Betrag auf mein Konto zurück.

Mit freundlichen Grüßen

{{absender_name}}""",
            "placeholders": [
                {"key": "absender_name", "label": "Ihr Name", "type": "text"},
                {"key": "absender_adresse", "label": "Ihre Straße", "type": "text"},
                {"key": "absender_plz", "label": "Ihre PLZ", "type": "text"},
                {"key": "absender_ort", "label": "Ihr Ort", "type": "text"},
                {"key": "bank_name", "label": "Bank Name", "type": "text"},
                {"key": "bank_adresse", "label": "Bank Straße", "type": "text"},
                {"key": "bank_plz", "label": "Bank PLZ", "type": "text"},
                {"key": "bank_ort", "label": "Bank Ort", "type": "text"},
                {"key": "datum", "label": "Datum", "type": "date"},
                {"key": "iban", "label": "Ihre IBAN", "type": "text"},
                {"key": "betrag", "label": "Betrag", "type": "number"},
                {"key": "abbuchungsdatum", "label": "Abbuchungsdatum", "type": "date"},
                {"key": "empfaenger", "label": "Lastschrift-Empfänger", "type": "text"},
                {"key": "verwendungszweck", "label": "Verwendungszweck", "type": "text"},
                {"key": "begruendung", "label": "Begründung", "type": "text"}
            ]
        }
    ]

    def __init__(self, user_id: int):
        self.user_id = user_id

    def initialize_default_templates(self):
        """Erstellt Standard-Vorlagen wenn noch keine vorhanden"""
        with get_session() as session:
            existing = session.query(DocumentTemplate).filter(
                DocumentTemplate.is_system == True
            ).count()

            if existing == 0:
                for template_data in self.DEFAULT_TEMPLATES:
                    template = DocumentTemplate(
                        name=template_data["name"],
                        category=template_data["category"],
                        content=template_data["content"],
                        placeholders=template_data["placeholders"],
                        is_system=True,
                        is_active=True
                    )
                    session.add(template)

                session.commit()

    def create_template(self, name: str, content: str, category: str = None,
                        placeholders: List[Dict] = None, **kwargs) -> DocumentTemplate:
        """Erstellt eine neue Vorlage"""
        # Platzhalter aus Content extrahieren wenn nicht angegeben
        if placeholders is None:
            placeholders = self._extract_placeholders(content)

        with get_session() as session:
            template = DocumentTemplate(
                user_id=self.user_id,
                name=name,
                content=content,
                category=category,
                placeholders=placeholders,
                description=kwargs.get("description"),
                content_type=kwargs.get("content_type", "text"),
                is_system=False,
                is_active=True
            )

            session.add(template)
            session.commit()
            session.refresh(template)
            return template

    def get_template(self, template_id: int) -> Optional[DocumentTemplate]:
        """Holt eine Vorlage"""
        with get_session() as session:
            return session.query(DocumentTemplate).filter(
                DocumentTemplate.id == template_id,
                (DocumentTemplate.user_id == self.user_id) | (DocumentTemplate.is_system == True)
            ).first()

    def get_all_templates(self, category: str = None) -> List[DocumentTemplate]:
        """Holt alle verfügbaren Vorlagen"""
        with get_session() as session:
            query = session.query(DocumentTemplate).filter(
                (DocumentTemplate.user_id == self.user_id) | (DocumentTemplate.is_system == True),
                DocumentTemplate.is_active == True
            )

            if category:
                query = query.filter(DocumentTemplate.category == category)

            return query.order_by(DocumentTemplate.name.asc()).all()

    def update_template(self, template_id: int, **kwargs) -> bool:
        """Aktualisiert eine Vorlage"""
        with get_session() as session:
            template = session.query(DocumentTemplate).filter(
                DocumentTemplate.id == template_id,
                DocumentTemplate.user_id == self.user_id
            ).first()

            if not template:
                return False

            for key, value in kwargs.items():
                if hasattr(template, key):
                    setattr(template, key, value)

            # Platzhalter neu extrahieren wenn Content geändert
            if "content" in kwargs and "placeholders" not in kwargs:
                template.placeholders = self._extract_placeholders(kwargs["content"])

            template.updated_at = datetime.now()
            session.commit()
            return True

    def delete_template(self, template_id: int) -> bool:
        """Löscht eine Vorlage"""
        with get_session() as session:
            template = session.query(DocumentTemplate).filter(
                DocumentTemplate.id == template_id,
                DocumentTemplate.user_id == self.user_id,
                DocumentTemplate.is_system == False
            ).first()

            if not template:
                return False

            session.delete(template)
            session.commit()
            return True

    def render_template(self, template_id: int, values: Dict[str, Any]) -> str:
        """Rendert eine Vorlage mit Werten"""
        template = self.get_template(template_id)
        if not template:
            return ""

        content = template.content

        # Platzhalter ersetzen
        for key, value in values.items():
            placeholder = "{{" + key + "}}"
            content = content.replace(placeholder, str(value) if value else "")

        # Verwendungsstatistik aktualisieren
        with get_session() as session:
            t = session.query(DocumentTemplate).filter(
                DocumentTemplate.id == template_id
            ).first()
            if t:
                t.times_used = (t.times_used or 0) + 1
                t.last_used_at = datetime.now()
                session.commit()

        return content

    def _extract_placeholders(self, content: str) -> List[Dict]:
        """Extrahiert Platzhalter aus Content"""
        pattern = r'\{\{(\w+)\}\}'
        matches = re.findall(pattern, content)

        placeholders = []
        seen = set()

        for key in matches:
            if key not in seen:
                seen.add(key)
                placeholders.append({
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "type": "text"
                })

        return placeholders

    def duplicate_template(self, template_id: int, new_name: str = None) -> Optional[DocumentTemplate]:
        """Dupliziert eine Vorlage"""
        original = self.get_template(template_id)
        if not original:
            return None

        return self.create_template(
            name=new_name or f"{original.name} (Kopie)",
            content=original.content,
            category=original.category,
            placeholders=original.placeholders,
            description=original.description,
            content_type=original.content_type
        )

    def get_categories(self) -> List[str]:
        """Holt alle Kategorien"""
        with get_session() as session:
            results = session.query(DocumentTemplate.category).filter(
                (DocumentTemplate.user_id == self.user_id) | (DocumentTemplate.is_system == True),
                DocumentTemplate.is_active == True,
                DocumentTemplate.category != None
            ).distinct().all()

            return [r[0] for r in results if r[0]]

    def search_templates(self, query: str) -> List[DocumentTemplate]:
        """Sucht in Vorlagen"""
        with get_session() as session:
            search_term = f"%{query}%"
            return session.query(DocumentTemplate).filter(
                (DocumentTemplate.user_id == self.user_id) | (DocumentTemplate.is_system == True),
                DocumentTemplate.is_active == True,
                (DocumentTemplate.name.ilike(search_term) |
                 DocumentTemplate.description.ilike(search_term))
            ).all()
