"""
Document Intelligence Service
Intelligente Dokumentenanalyse und automatische Kategorisierung

Features:
- Metadaten-Extraktion (Absender, Datum, Nummern)
- Automatische Ordnererstellung basierend auf Dokumenttyp
- Cloud-Ordnernamen als Hinweis für Kategorisierung
- Verknüpfung mit Versicherungen, Verträgen, Abos
"""
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

from database.db import get_db
from database.models import Document, Folder
from database.extended_models import (
    Insurance, InsuranceType, Subscription, SubscriptionInterval
)

logger = logging.getLogger(__name__)


@dataclass
class DocumentMetadata:
    """Extrahierte Metadaten aus einem Dokument"""
    # Absender
    sender: Optional[str] = None
    sender_address: Optional[str] = None

    # Dokumenttyp
    document_type: Optional[str] = None  # versicherung, vertrag, rechnung, etc.
    document_subtype: Optional[str] = None  # lebensversicherung, kfz, etc.

    # Nummern
    insurance_number: Optional[str] = None
    policy_number: Optional[str] = None
    contract_number: Optional[str] = None
    customer_number: Optional[str] = None
    invoice_number: Optional[str] = None
    reference_number: Optional[str] = None

    # Datum
    document_date: Optional[datetime] = None
    effective_date: Optional[datetime] = None  # Gültig ab
    expiry_date: Optional[datetime] = None  # Gültig bis

    # Finanzen
    amount: Optional[float] = None
    monthly_rate: Optional[float] = None
    yearly_rate: Optional[float] = None
    currency: str = "EUR"

    # Lebensversicherung spezifisch
    surrender_value: Optional[float] = None  # Rückkaufwert
    maturity_date: Optional[datetime] = None  # Zuteilungsdatum
    maturity_value: Optional[float] = None  # Zuteilungswert

    # Vertragsdaten
    contract_start: Optional[datetime] = None
    contract_end: Optional[datetime] = None
    notice_period_days: Optional[int] = None

    # Versichertes Objekt
    insured_object: Optional[str] = None  # z.B. Fahrzeug, Haus
    insured_object_details: Optional[Dict] = None  # z.B. Kennzeichen, Adresse

    # Ordner-Hinweise aus Cloud-Pfad
    source_folder_hints: List[str] = field(default_factory=list)

    # Kategorisierung
    suggested_category: Optional[str] = None
    suggested_folder_path: Optional[str] = None
    confidence: float = 0.0


class DocumentIntelligenceService:
    """Service für intelligente Dokumentenanalyse"""

    # Bekannte Versicherungsunternehmen
    INSURANCE_COMPANIES = {
        "allianz": "Allianz",
        "axa": "AXA",
        "huk": "HUK-Coburg",
        "huk-coburg": "HUK-Coburg",
        "ergo": "ERGO",
        "generali": "Generali",
        "zurich": "Zurich",
        "debeka": "Debeka",
        "signal iduna": "Signal Iduna",
        "württembergische": "Württembergische",
        "heidelberger": "Heidelberger Leben",
        "heidelberger leben": "Heidelberger Leben",
        "r+v": "R+V",
        "rv": "R+V",
        "devk": "DEVK",
        "lvm": "LVM",
        "gothaer": "Gothaer",
        "continentale": "Continentale",
        "aachen münchener": "Aachen Münchener",
        "provinzial": "Provinzial",
        "sparkassen": "Sparkassen Versicherung",
        "cosmos": "CosmosDirekt",
        "cosmosdirekt": "CosmosDirekt",
        "check24": "Check24",
        "verti": "Verti",
        "friday": "Friday",
        "wgv": "WGV",
        "barmer": "Barmer",
        "tk": "Techniker Krankenkasse",
        "techniker": "Techniker Krankenkasse",
        "aok": "AOK",
        "dak": "DAK",
        "ikk": "IKK",
        "bkk": "BKK",
        "knappschaft": "Knappschaft",
    }

    # Versicherungstyp-Keywords
    INSURANCE_TYPE_KEYWORDS = {
        InsuranceType.LIFE: [
            "lebensversicherung", "leben", "kapitallebensversicherung",
            "risikolebensversicherung", "rentenversicherung", "altersvorsorge",
            "riester", "rürup", "basisrente"
        ],
        InsuranceType.CAR: [
            "kfz", "kraftfahrzeug", "auto", "fahrzeug", "pkw", "motorrad",
            "kasko", "vollkasko", "teilkasko", "haftpflicht kfz"
        ],
        InsuranceType.HOUSEHOLD: [
            "hausrat", "hausratversicherung", "wohngebäude", "gebäude",
            "elementar", "einbruch", "diebstahl"
        ],
        InsuranceType.LIABILITY: [
            "privathaftpflicht", "haftpflicht privat", "phv",
            "tierhalterhaftpflicht", "hundehaftpflicht"
        ],
        InsuranceType.HEALTH: [
            "krankenversicherung", "krankenkasse", "pkv", "gkv",
            "zusatzversicherung", "zahnzusatz", "brillen"
        ],
        InsuranceType.LEGAL: [
            "rechtsschutz", "rechtsschutzversicherung", "anwaltskosten"
        ],
        InsuranceType.DISABILITY: [
            "berufsunfähigkeit", "bu", "erwerbsminderung", "invalidität"
        ],
        InsuranceType.TRAVEL: [
            "reise", "reiserücktritt", "auslandskranken", "reisekranken"
        ],
        InsuranceType.PET: [
            "tierversicherung", "hundeversicherung", "pferde", "op-versicherung"
        ]
    }

    # Dokumenttyp-Keywords
    DOCUMENT_TYPE_KEYWORDS = {
        "versicherung": [
            "versicherung", "police", "versicherungsschein", "nachtrag",
            "beitrag", "prämie", "deckung", "leistung"
        ],
        "vertrag": [
            "vertrag", "vereinbarung", "konditionen", "laufzeit",
            "kündigung", "kündigungsfrist"
        ],
        "rechnung": [
            "rechnung", "invoice", "zahlungsaufforderung", "mahnung",
            "fällig", "betrag", "summe", "netto", "brutto", "mwst"
        ],
        "kontoauszug": [
            "kontoauszug", "kontostand", "umsatz", "buchung", "saldo"
        ],
        "kaufvertrag": [
            "kaufvertrag", "kaufbeleg", "quittung", "kassenbon", "kauf"
        ],
        "abonnement": [
            "abonnement", "abo", "mitgliedschaft", "subscription",
            "monatlich", "jährlich", "verlängerung"
        ],
        "steuer": [
            "steuer", "steuerbescheid", "finanzamt", "einkommensteuer",
            "lohnsteuer", "umsatzsteuer"
        ],
        "gehalt": [
            "gehaltsabrechnung", "lohnabrechnung", "entgelt", "vergütung"
        ],
        "bank": [
            "bank", "konto", "sparkasse", "volksbank", "commerzbank",
            "deutsche bank", "ing", "dkb", "n26", "comdirect"
        ]
    }

    def __init__(self, user_id: int, ai_service=None):
        self.user_id = user_id
        self.ai_service = ai_service

    def analyze_document(self, ocr_text: str,
                         source_folder_path: Optional[str] = None,
                         filename: Optional[str] = None) -> DocumentMetadata:
        """
        Analysiert ein Dokument und extrahiert Metadaten.

        Args:
            ocr_text: Der extrahierte Text aus dem Dokument
            source_folder_path: Pfad aus Cloud-Ordner (z.B. "Versicherung/Leben/Allianz")
            filename: Originaler Dateiname

        Returns:
            DocumentMetadata mit extrahierten Informationen
        """
        metadata = DocumentMetadata()

        # 1. Analysiere Cloud-Ordner-Pfad für Hinweise
        if source_folder_path:
            metadata.source_folder_hints = self._parse_folder_path(source_folder_path)

        # 2. Extrahiere Absender
        metadata.sender = self._extract_sender(ocr_text)

        # 3. Bestimme Dokumenttyp
        doc_type, subtype = self._determine_document_type(
            ocr_text, metadata.source_folder_hints, metadata.sender
        )
        metadata.document_type = doc_type
        metadata.document_subtype = subtype

        # 4. Extrahiere Nummern
        self._extract_numbers(ocr_text, metadata)

        # 5. Extrahiere Daten
        self._extract_dates(ocr_text, metadata)

        # 6. Extrahiere Beträge
        self._extract_amounts(ocr_text, metadata)

        # 7. Extrahiere versichertes Objekt
        if metadata.document_type == "versicherung":
            self._extract_insured_object(ocr_text, metadata)

        # 8. Berechne Ordnerpfad
        metadata.suggested_folder_path = self._calculate_folder_path(metadata)

        # 9. AI-Analyse falls verfügbar
        if self.ai_service and len(ocr_text) > 100:
            self._enhance_with_ai(ocr_text, metadata)

        return metadata

    def _parse_folder_path(self, path: str) -> List[str]:
        """Parsed Ordnerpfad in Hinweise"""
        hints = []

        # Normalisiere Pfad
        path = path.replace("\\", "/").lower()
        parts = [p.strip() for p in path.split("/") if p.strip()]

        for part in parts:
            # Entferne Sonderzeichen
            clean = re.sub(r'[^\w\s\-äöüß]', '', part)
            if clean and len(clean) > 2:
                hints.append(clean)

        return hints

    def _extract_sender(self, text: str) -> Optional[str]:
        """Extrahiert den Absender aus dem Dokumenttext"""
        text_lower = text.lower()

        # 1. Prüfe auf bekannte Versicherungen
        for key, name in self.INSURANCE_COMPANIES.items():
            if key in text_lower:
                return name

        # 2. Suche nach typischen Absendermustern
        patterns = [
            r'^([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*\s*(?:GmbH|AG|SE|KG|e\.?V\.?))',
            r'Von:\s*(.+?)(?:\n|$)',
            r'Absender:\s*(.+?)(?:\n|$)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                sender = match.group(1).strip()
                if len(sender) > 3 and len(sender) < 100:
                    return sender

        return None

    def _determine_document_type(self, text: str,
                                  folder_hints: List[str],
                                  sender: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Bestimmt Dokumenttyp und Untertyp"""
        text_lower = text.lower()
        hints_lower = [h.lower() for h in folder_hints]

        doc_type = None
        subtype = None
        max_score = 0

        # Prüfe Dokumenttypen
        for dtype, keywords in self.DOCUMENT_TYPE_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 2
                if any(keyword in hint for hint in hints_lower):
                    score += 3  # Ordner-Hinweise gewichten stärker

            if score > max_score:
                max_score = score
                doc_type = dtype

        # Bei Versicherung: bestimme Untertyp
        if doc_type == "versicherung" or any("versicherung" in h for h in hints_lower):
            doc_type = "versicherung"
            subtype = self._determine_insurance_type(text_lower, hints_lower)

        return doc_type, subtype

    def _determine_insurance_type(self, text_lower: str,
                                   hints_lower: List[str]) -> Optional[str]:
        """Bestimmt den Versicherungstyp"""
        max_score = 0
        best_type = None

        for ins_type, keywords in self.INSURANCE_TYPE_KEYWORDS.items():
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 2
                if any(keyword in hint for hint in hints_lower):
                    score += 3

            if score > max_score:
                max_score = score
                best_type = ins_type.value

        return best_type

    def _extract_numbers(self, text: str, metadata: DocumentMetadata):
        """Extrahiert verschiedene Nummern"""

        # Versicherungsnummer
        patterns = [
            r'Versicherungs(?:nummer|schein)?[:\s]*([A-Z0-9\-\/]{5,20})',
            r'Police(?:n)?(?:nummer)?[:\s]*([A-Z0-9\-\/]{5,20})',
            r'Vertrags(?:nummer)?[:\s]*([A-Z0-9\-\/]{5,20})',
            r'(?:VS|VN|PN)[:\s\-]*([0-9]{5,15})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                number = match.group(1).strip()
                if not metadata.insurance_number:
                    metadata.insurance_number = number
                if not metadata.policy_number:
                    metadata.policy_number = number
                break

        # Kundennummer
        patterns = [
            r'Kunden(?:nummer)?[:\s]*([A-Z0-9\-]{5,15})',
            r'Mitglieds(?:nummer)?[:\s]*([A-Z0-9\-]{5,15})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metadata.customer_number = match.group(1).strip()
                break

        # Rechnungsnummer
        patterns = [
            r'Rechnungs(?:nummer)?[:\s]*([A-Z0-9\-\/]{5,20})',
            r'Re\.?\s*Nr\.?[:\s]*([A-Z0-9\-\/]{5,20})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                metadata.invoice_number = match.group(1).strip()
                break

    def _extract_dates(self, text: str, metadata: DocumentMetadata):
        """Extrahiert Datumsangaben"""

        # Deutsches Datumsformat
        date_pattern = r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})'

        # Dokumentdatum (erstes Datum)
        match = re.search(date_pattern, text)
        if match:
            try:
                day, month, year = match.groups()
                year = int(year)
                if year < 100:
                    year += 2000 if year < 50 else 1900
                metadata.document_date = datetime(year, int(month), int(day))
            except:
                pass

        # Vertragsbeginn
        patterns = [
            r'(?:Beginn|Versicherungsbeginn|gültig ab|ab)[:\s]*' + date_pattern,
            r'(?:Start|Laufzeit ab)[:\s]*' + date_pattern,
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    day, month, year = match.groups()
                    year = int(year)
                    if year < 100:
                        year += 2000 if year < 50 else 1900
                    metadata.contract_start = datetime(year, int(month), int(day))
                    break
                except:
                    pass

        # Vertragsende
        patterns = [
            r'(?:Ende|Ablauf|gültig bis|bis)[:\s]*' + date_pattern,
            r'(?:Laufzeit bis|endet am)[:\s]*' + date_pattern,
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    day, month, year = match.groups()
                    year = int(year)
                    if year < 100:
                        year += 2000 if year < 50 else 1900
                    metadata.contract_end = datetime(year, int(month), int(day))
                    break
                except:
                    pass

        # Zuteilungsdatum (Lebensversicherung)
        patterns = [
            r'Zuteilung[:\s]*' + date_pattern,
            r'Fälligkeit[:\s]*' + date_pattern,
            r'Auszahlung[:\s]*' + date_pattern,
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    day, month, year = match.groups()
                    year = int(year)
                    if year < 100:
                        year += 2000 if year < 50 else 1900
                    metadata.maturity_date = datetime(year, int(month), int(day))
                    break
                except:
                    pass

    def _extract_amounts(self, text: str, metadata: DocumentMetadata):
        """Extrahiert Beträge"""

        # Deutsches Zahlenformat: 1.234,56 oder 1234,56
        amount_pattern = r'(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)\s*(?:€|EUR|Euro)'

        def parse_german_number(s: str) -> float:
            """Konvertiert deutsches Zahlenformat"""
            s = s.replace('.', '').replace(',', '.')
            return float(s)

        # Monatliche Rate
        patterns = [
            r'(?:monatlich|Monatsbeitrag|mtl\.?)[:\s]*' + amount_pattern,
            r'(?:Rate|Beitrag)[:\s]*' + amount_pattern + r'[^\n]*(?:monatlich|mtl)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    metadata.monthly_rate = parse_german_number(match.group(1))
                    break
                except:
                    pass

        # Jährliche Rate
        patterns = [
            r'(?:jährlich|Jahresbeitrag|jährl\.?|p\.?\s*a\.?)[:\s]*' + amount_pattern,
            r'(?:Rate|Beitrag)[:\s]*' + amount_pattern + r'[^\n]*(?:jährlich|p\.?\s*a\.?)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    metadata.yearly_rate = parse_german_number(match.group(1))
                    break
                except:
                    pass

        # Rückkaufwert
        patterns = [
            r'(?:Rückkaufwert|Rückkauf)[:\s]*' + amount_pattern,
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    metadata.surrender_value = parse_german_number(match.group(1))
                    break
                except:
                    pass

        # Zuteilungswert
        patterns = [
            r'(?:Zuteilungswert|Ablaufleistung|Auszahlungsbetrag)[:\s]*' + amount_pattern,
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    metadata.maturity_value = parse_german_number(match.group(1))
                    break
                except:
                    pass

        # Allgemeiner Betrag (für Rechnungen)
        patterns = [
            r'(?:Gesamtbetrag|Summe|Betrag|Total)[:\s]*' + amount_pattern,
            r'(?:zu zahlen|zahlbar)[:\s]*' + amount_pattern,
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    metadata.amount = parse_german_number(match.group(1))
                    break
                except:
                    pass

    def _extract_insured_object(self, text: str, metadata: DocumentMetadata):
        """Extrahiert Informationen über das versicherte Objekt"""
        text_lower = text.lower()

        # KFZ
        if metadata.document_subtype == "car" or "kfz" in text_lower:
            details = {}

            # Kennzeichen
            match = re.search(r'Kennzeichen[:\s]*([A-ZÄÖÜ]{1,3}[\s\-]?[A-Z]{1,2}[\s\-]?\d{1,4})', text, re.IGNORECASE)
            if match:
                details["kennzeichen"] = match.group(1).upper()

            # Fahrzeugtyp/Modell
            match = re.search(r'(?:Fahrzeug|Modell|Typ)[:\s]*([A-Za-z0-9\s\-]+)', text, re.IGNORECASE)
            if match:
                details["fahrzeug"] = match.group(1).strip()

            if details:
                metadata.insured_object = details.get("kennzeichen") or details.get("fahrzeug")
                metadata.insured_object_details = details

        # Hausrat/Gebäude
        elif metadata.document_subtype in ["household", "liability"]:
            # Adresse
            match = re.search(r'(?:Versicherungsort|Risikoadresse|Objekt)[:\s]*([A-Za-zäöüß\s\.\-]+\d+[a-z]?[,\s]+\d{5}\s+[A-Za-zäöüß\s]+)', text, re.IGNORECASE)
            if match:
                metadata.insured_object = match.group(1).strip()

    def _calculate_folder_path(self, metadata: DocumentMetadata) -> str:
        """Berechnet den empfohlenen Ordnerpfad"""
        parts = []

        if metadata.document_type == "versicherung":
            parts.append("Versicherungen")

            # Versicherungstyp
            if metadata.document_subtype:
                type_names = {
                    "life": "Lebensversicherung",
                    "car": "KFZ-Versicherung",
                    "household": "Hausrat",
                    "liability": "Haftpflicht",
                    "health": "Krankenversicherung",
                    "legal": "Rechtsschutz",
                    "disability": "Berufsunfähigkeit",
                    "travel": "Reiseversicherung",
                    "pet": "Tierversicherung",
                    "other": "Sonstige"
                }
                parts.append(type_names.get(metadata.document_subtype, "Sonstige"))

            # Versicherungsunternehmen
            if metadata.sender:
                parts.append(metadata.sender)

            # Versicherungsnummer
            if metadata.insurance_number or metadata.policy_number:
                number = metadata.insurance_number or metadata.policy_number
                # Bereinige Nummer für Ordnername
                safe_number = re.sub(r'[<>:"/\\|?*]', '_', number)
                parts.append(safe_number)

        elif metadata.document_type == "vertrag":
            parts.append("Verträge")
            if metadata.sender:
                parts.append(metadata.sender)

        elif metadata.document_type == "abonnement":
            parts.append("Abonnements")
            if metadata.sender:
                parts.append(metadata.sender)

        elif metadata.document_type == "rechnung":
            parts.append("Rechnungen")
            if metadata.sender:
                parts.append(metadata.sender)

        elif metadata.document_type == "steuer":
            parts.append("Steuern")
            if metadata.document_date:
                parts.append(str(metadata.document_date.year))

        elif metadata.document_type == "bank":
            parts.append("Bank")
            if metadata.sender:
                parts.append(metadata.sender)

        else:
            parts.append("Sonstige")

        return "/".join(parts)

    def _enhance_with_ai(self, text: str, metadata: DocumentMetadata):
        """Erweitert Metadaten mit AI-Analyse"""
        try:
            if not self.ai_service:
                return

            # AI für strukturierte Datenextraktion nutzen
            structured = self.ai_service.extract_structured_data(text)

            if structured:
                # Übernehme fehlende Werte
                if not metadata.sender and structured.get("sender"):
                    metadata.sender = structured["sender"]

                if not metadata.document_date and structured.get("document_date"):
                    try:
                        metadata.document_date = datetime.fromisoformat(structured["document_date"])
                    except:
                        pass

                if not metadata.amount and structured.get("amount"):
                    try:
                        metadata.amount = float(structured["amount"])
                    except:
                        pass

                # Vertrauenswürdigkeit erhöhen
                metadata.confidence = min(1.0, metadata.confidence + 0.3)

        except Exception as e:
            logger.error(f"AI-Analyse fehlgeschlagen: {e}")

    def create_folder_structure(self, folder_path: str) -> Optional[int]:
        """
        Erstellt die Ordnerstruktur und gibt die ID des letzten Ordners zurück.

        Args:
            folder_path: Pfad wie "Versicherungen/Lebensversicherung/Allianz/12345"

        Returns:
            ID des letzten (tiefsten) Ordners
        """
        parts = [p.strip() for p in folder_path.split("/") if p.strip()]

        if not parts:
            return None

        with get_db() as session:
            parent_id = None
            current_folder = None

            for part in parts:
                # Suche existierenden Ordner
                query = session.query(Folder).filter(
                    Folder.user_id == self.user_id,
                    Folder.name == part
                )

                if parent_id:
                    query = query.filter(Folder.parent_id == parent_id)
                else:
                    query = query.filter(Folder.parent_id.is_(None))

                current_folder = query.first()

                if not current_folder:
                    # Erstelle neuen Ordner
                    current_folder = Folder(
                        user_id=self.user_id,
                        name=part,
                        parent_id=parent_id,
                        icon=self._get_folder_icon(part)
                    )
                    session.add(current_folder)
                    session.flush()
                    logger.info(f"Ordner erstellt: {part} (Parent: {parent_id})")

                parent_id = current_folder.id

            session.commit()
            return current_folder.id if current_folder else None

    def _get_folder_icon(self, folder_name: str) -> str:
        """Gibt passendes Icon für Ordnername zurück"""
        name_lower = folder_name.lower()

        icons = {
            "versicherung": "🛡️",
            "lebensversicherung": "💚",
            "kfz": "🚗",
            "auto": "🚗",
            "hausrat": "🏠",
            "haftpflicht": "⚖️",
            "kranken": "🏥",
            "rechtsschutz": "⚖️",
            "steuer": "📊",
            "bank": "🏦",
            "vertrag": "📋",
            "vertäge": "📋",
            "rechnung": "🧾",
            "abonnement": "🔄",
            "abo": "🔄",
        }

        for key, icon in icons.items():
            if key in name_lower:
                return icon

        return "📁"

    def process_cloud_document(self, document_id: int,
                                ocr_text: str,
                                source_folder_path: Optional[str] = None,
                                filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Verarbeitet ein aus der Cloud importiertes Dokument intelligent.

        Args:
            document_id: ID des Dokuments in der Datenbank
            ocr_text: Extrahierter Text
            source_folder_path: Ordnerpfad aus der Cloud
            filename: Originaler Dateiname

        Returns:
            Dict mit Verarbeitungsergebnis
        """
        result = {
            "success": False,
            "metadata": None,
            "folder_created": False,
            "folder_id": None,
            "folder_path": None,
            "insurance_linked": False,
            "insurance_id": None,
        }

        try:
            # 1. Analysiere Dokument
            metadata = self.analyze_document(ocr_text, source_folder_path, filename)
            result["metadata"] = metadata.__dict__

            # 2. Erstelle Ordnerstruktur
            if metadata.suggested_folder_path:
                folder_id = self.create_folder_structure(metadata.suggested_folder_path)
                if folder_id:
                    result["folder_created"] = True
                    result["folder_id"] = folder_id
                    result["folder_path"] = metadata.suggested_folder_path

                    # 3. Verschiebe Dokument in Ordner
                    with get_db() as session:
                        doc = session.query(Document).filter(
                            Document.id == document_id
                        ).first()

                        if doc:
                            doc.folder_id = folder_id

                            # Aktualisiere Dokument-Metadaten
                            if metadata.sender:
                                doc.sender = metadata.sender
                            if metadata.document_date:
                                doc.document_date = metadata.document_date
                            if metadata.insurance_number:
                                doc.insurance_number = metadata.insurance_number
                            if metadata.contract_number:
                                doc.contract_number = metadata.contract_number
                            if metadata.amount:
                                doc.invoice_amount = metadata.amount

                            # Generiere Titel aus Metadaten
                            doc.title = self._generate_document_title(metadata, filename)

                            session.commit()

            # 4. Verknüpfe mit Versicherung falls passend
            if metadata.document_type == "versicherung":
                insurance_id = self._link_to_insurance(metadata)
                if insurance_id:
                    result["insurance_linked"] = True
                    result["insurance_id"] = insurance_id

            result["success"] = True

        except Exception as e:
            logger.error(f"Fehler bei Cloud-Dokumentverarbeitung: {e}")
            result["error"] = str(e)

        return result

    def _generate_document_title(self, metadata: DocumentMetadata,
                                  filename: Optional[str]) -> str:
        """Generiert aussagekräftigen Dokumenttitel"""
        parts = []

        # Datum
        if metadata.document_date:
            parts.append(metadata.document_date.strftime("%Y-%m-%d"))

        # Absender
        if metadata.sender:
            parts.append(metadata.sender)

        # Dokumenttyp
        type_names = {
            "versicherung": "Versicherung",
            "vertrag": "Vertrag",
            "rechnung": "Rechnung",
            "abonnement": "Abo",
            "steuer": "Steuer",
            "bank": "Bank"
        }
        if metadata.document_type:
            parts.append(type_names.get(metadata.document_type, metadata.document_type))

        # Nummer
        if metadata.insurance_number:
            parts.append(metadata.insurance_number)
        elif metadata.invoice_number:
            parts.append(metadata.invoice_number)

        if parts:
            return " - ".join(parts)
        elif filename:
            return Path(filename).stem
        else:
            return "Dokument"

    def _link_to_insurance(self, metadata: DocumentMetadata) -> Optional[int]:
        """Verknüpft Dokument mit bestehender Versicherung oder erstellt neue"""

        if not metadata.sender:
            return None

        with get_db() as session:
            # Suche existierende Versicherung
            query = session.query(Insurance).filter(
                Insurance.user_id == self.user_id,
                Insurance.company.ilike(f"%{metadata.sender}%")
            )

            if metadata.policy_number:
                query = query.filter(
                    Insurance.policy_number == metadata.policy_number
                )

            insurance = query.first()

            if insurance:
                # Aktualisiere falls neue Infos
                if metadata.monthly_rate and not insurance.premium_amount:
                    insurance.premium_amount = metadata.monthly_rate
                    insurance.premium_interval = SubscriptionInterval.MONTHLY

                session.commit()
                return insurance.id

        return None

    def get_document_overview(self, document_type: str = None) -> List[Dict]:
        """
        Gibt strukturierte Übersicht über Dokumente zurück.

        Returns:
            Liste von Dokumenten mit Metadaten und Ordner-Links
        """
        with get_db() as session:
            query = session.query(Document).filter(
                Document.user_id == self.user_id,
                Document.is_deleted == False
            )

            if document_type:
                query = query.filter(Document.category == document_type)

            documents = query.order_by(Document.created_at.desc()).all()

            results = []
            for doc in documents:
                results.append({
                    "id": doc.id,
                    "title": doc.title,
                    "sender": doc.sender,
                    "date": doc.document_date,
                    "category": doc.category,
                    "folder_id": doc.folder_id,
                    "insurance_number": doc.insurance_number,
                    "contract_number": doc.contract_number,
                    "amount": doc.invoice_amount,
                    "file_path": doc.file_path,
                })

            return results
