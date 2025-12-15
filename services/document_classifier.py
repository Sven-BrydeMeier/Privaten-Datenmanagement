"""
Intelligenter Dokumentenklassifikator mit KI-Unterstützung
"""
import re
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import streamlit as st

from database import get_db
from database.models import ClassificationRule, Folder, Document, Property, document_virtual_folders
from config.settings import DOCUMENT_CATEGORIES


# Erweiterte Kategorie-Patterns mit Untertypen
CATEGORY_PATTERNS = {
    'Rechnung': {
        'keywords': ['rechnung', 'invoice', 'zahlungsziel', 'fällig bis', 'rechnungsnummer',
                     'rechnungsbetrag', 'nettobetrag', 'bruttobetrag', 'zahlbar bis'],
        'subtypes': {
            'Strom': ['strom', 'elektrizität', 'kwh', 'stromverbrauch', 'energieversorgung'],
            'Gas': ['gas', 'gasverbrauch', 'erdgas', 'gasabrechnung'],
            'Wasser': ['wasser', 'wasserverbrauch', 'abwasser', 'trinkwasser'],
            'Internet': ['internet', 'dsl', 'glasfaser', 'bandbreite', 'router'],
            'Telefon': ['telefon', 'mobilfunk', 'rufnummer', 'anrufe', 'sms'],
            'Miete': ['miete', 'kaltmiete', 'warmmiete', 'mietvertrag'],
            'Nebenkosten': ['nebenkosten', 'betriebskosten', 'hausgeld', 'nebenkostenabrechnung'],
            'Handwerker': ['handwerker', 'reparatur', 'montage', 'installation', 'wartung'],
        }
    },
    'Versicherung': {
        'keywords': ['versicherung', 'police', 'versicherungsnummer', 'versicherungsschein',
                     'beitrag', 'prämie', 'deckung', 'schadensfall'],
        'subtypes': {
            'KV': ['krankenversicherung', 'krankenkasse', 'gesundheit', 'arzt', 'kranken'],
            'ZusatzKV': ['zusatzversicherung', 'zahnzusatz', 'brillenversicherung', 'heilpraktiker'],
            'Haftpflicht': ['haftpflicht', 'privathaftpflicht', 'haftpflichtversicherung'],
            'Hausrat': ['hausrat', 'hausratversicherung', 'einbruch', 'diebstahl'],
            'Wohngebäude': ['wohngebäude', 'gebäudeversicherung', 'feuer', 'leitungswasser'],
            'KFZ': ['kfz', 'autoversicherung', 'kasko', 'vollkasko', 'teilkasko', 'fahrzeug'],
            'Leben': ['lebensversicherung', 'kapitallebensversicherung', 'risikoleben'],
            'Rente': ['rentenversicherung', 'altersvorsorge', 'riester', 'rürup'],
            'Rechtsschutz': ['rechtsschutz', 'rechtsschutzversicherung', 'anwalt'],
            'Unfall': ['unfallversicherung', 'invalidität', 'unfall'],
        }
    },
    'Vertrag': {
        'keywords': ['vertrag', 'vereinbarung', 'unterzeichnung', 'vertragspartner',
                     'laufzeit', 'kündigung', 'kündigungsfrist'],
        'subtypes': {
            'Mietvertrag': ['mietvertrag', 'mieter', 'vermieter', 'mietobjekt'],
            'Arbeitsvertrag': ['arbeitsvertrag', 'arbeitgeber', 'arbeitnehmer', 'gehalt'],
            'Mobilfunk': ['mobilfunkvertrag', 'handyvertrag', 'tarif'],
            'Internet': ['internetvertrag', 'dsl-vertrag', 'provider'],
            'Strom': ['stromvertrag', 'energievertrag', 'stromlieferung'],
            'Fitness': ['fitnessvertrag', 'studio', 'mitgliedschaft'],
            'Abo': ['abonnement', 'abo', 'streaming', 'zeitschrift'],
        }
    },
    'Darlehen': {
        'keywords': ['darlehen', 'kredit', 'tilgung', 'darlehensnummer', 'zinsen',
                     'annuität', 'restschuld', 'sondertilgung'],
        'subtypes': {
            'Baufinanzierung': ['baufinanzierung', 'immobilienkredit', 'hypothek'],
            'Ratenkredit': ['ratenkredit', 'konsumentenkredit', 'privatkredit'],
            'KFZ-Finanzierung': ['autokredit', 'fahrzeugfinanzierung', 'leasing'],
        }
    },
    'Kontoauszug': {
        'keywords': ['kontoauszug', 'buchungen', 'saldo', 'habenumsatz', 'sollumsatz',
                     'kontostand', 'kontobewegung'],
        'subtypes': {}
    },
    'Lohnabrechnung': {
        'keywords': ['lohnabrechnung', 'gehaltsabrechnung', 'nettobetrag', 'bruttolohn',
                     'sozialversicherung', 'lohnsteuer', 'entgeltabrechnung'],
        'subtypes': {}
    },
    'Steuerbescheid': {
        'keywords': ['steuerbescheid', 'einkommenssteuer', 'finanzamt', 'steuernummer',
                     'veranlagung', 'steuererstattung', 'nachzahlung'],
        'subtypes': {
            'Einkommensteuer': ['einkommensteuer', 'einkommensteuerbescheid'],
            'Grundsteuer': ['grundsteuer', 'grundsteuerbescheid'],
            'Gewerbesteuer': ['gewerbesteuer', 'gewerbesteuerbescheid'],
        }
    },
    'Rentenbescheid': {
        'keywords': ['rentenbescheid', 'rentenversicherung', 'altersrente', 'rentenanspruch',
                     'renteninformation', 'deutsche rentenversicherung'],
        'subtypes': {}
    },
    'Mahnung': {
        'keywords': ['mahnung', 'zahlungserinnerung', 'überfällig', 'mahngebühr',
                     'letzte mahnung', 'inkasso'],
        'subtypes': {}
    },
    'Bescheid': {
        'keywords': ['bescheid', 'behörde', 'amt', 'antrag', 'genehmigung'],
        'subtypes': {}
    },
}

# Bekannte Absender und ihre Zuordnungen
KNOWN_SENDERS = {
    # Telekommunikation
    'telekom': {'folder': 'Verträge/Telekommunikation', 'category': 'Vertrag'},
    'vodafone': {'folder': 'Verträge/Telekommunikation', 'category': 'Vertrag'},
    'o2': {'folder': 'Verträge/Telekommunikation', 'category': 'Vertrag'},
    '1&1': {'folder': 'Verträge/Telekommunikation', 'category': 'Vertrag'},
    'congstar': {'folder': 'Verträge/Telekommunikation', 'category': 'Vertrag'},

    # Energie
    'stadtwerke': {'folder': 'Verträge/Energie', 'category': 'Rechnung'},
    'eon': {'folder': 'Verträge/Energie', 'category': 'Rechnung'},
    'e.on': {'folder': 'Verträge/Energie', 'category': 'Rechnung'},
    'vattenfall': {'folder': 'Verträge/Energie', 'category': 'Rechnung'},
    'rwe': {'folder': 'Verträge/Energie', 'category': 'Rechnung'},
    'enbw': {'folder': 'Verträge/Energie', 'category': 'Rechnung'},

    # Versicherungen
    'allianz': {'folder': 'Versicherungen', 'category': 'Versicherung'},
    'axa': {'folder': 'Versicherungen', 'category': 'Versicherung'},
    'ergo': {'folder': 'Versicherungen', 'category': 'Versicherung'},
    'huk': {'folder': 'Versicherungen', 'category': 'Versicherung'},
    'debeka': {'folder': 'Versicherungen', 'category': 'Versicherung'},
    'generali': {'folder': 'Versicherungen', 'category': 'Versicherung'},
    'signal iduna': {'folder': 'Versicherungen', 'category': 'Versicherung'},
    'aok': {'folder': 'Versicherungen/KV', 'category': 'Versicherung'},
    'barmer': {'folder': 'Versicherungen/KV', 'category': 'Versicherung'},
    'tk': {'folder': 'Versicherungen/KV', 'category': 'Versicherung'},
    'techniker': {'folder': 'Versicherungen/KV', 'category': 'Versicherung'},
    'dak': {'folder': 'Versicherungen/KV', 'category': 'Versicherung'},

    # Banken
    'sparkasse': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},
    'volksbank': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},
    'commerzbank': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},
    'deutsche bank': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},
    'ing': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},
    'dkb': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},
    'comdirect': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},
    'postbank': {'folder': 'Finanzen/Bank', 'category': 'Kontoauszug'},

    # Behörden
    'finanzamt': {'folder': 'Steuern', 'category': 'Steuerbescheid'},
    'deutsche rentenversicherung': {'folder': 'Rentenbescheide', 'category': 'Rentenbescheid'},
    'arbeitsagentur': {'folder': 'Behörden', 'category': 'Bescheid'},
    'jobcenter': {'folder': 'Behörden', 'category': 'Bescheid'},
}


class DocumentClassifier:
    """Intelligenter Dokumentenklassifikator mit KI-Unterstützung"""

    def __init__(self, user_id: int):
        self.user_id = user_id

    def classify(self, text: str, metadata: Dict) -> Dict:
        """
        Klassifiziert ein Dokument und gibt alle relevanten Zuordnungen zurück.

        Args:
            text: OCR-Text des Dokuments
            metadata: Extrahierte Metadaten

        Returns:
            Dictionary mit Klassifizierungsergebnissen
        """
        result = {
            'primary_folder_id': None,
            'primary_folder_path': None,
            'virtual_folder_ids': [],
            'category': 'Sonstiges',
            'subcategory': None,
            'confidence': 0.0,
            'detected_sender': None,
            'detected_address': None,
            'property_id': None,
            'suggested_subfolders': [],
            'reasons': []
        }

        text_lower = text.lower() if text else ''

        # 1. Absender erkennen
        sender = self._detect_sender(text_lower, metadata)
        result['detected_sender'] = sender

        # 2. Bekannte Absender prüfen
        sender_match = self._match_known_sender(sender, text_lower)
        if sender_match:
            result['category'] = sender_match['category']
            result['suggested_subfolders'].append(sender_match['folder'])
            result['confidence'] = 0.8
            result['reasons'].append(f"Bekannter Absender: {sender}")

        # 3. Kategorie und Unterkategorie bestimmen
        category, subcategory, cat_confidence = self._determine_category(text_lower)
        if cat_confidence > result['confidence']:
            result['category'] = category
            result['subcategory'] = subcategory
            result['confidence'] = cat_confidence

        # 4. Adresse/Immobilie erkennen
        address = self._extract_address(text)
        if address:
            result['detected_address'] = address
            property_id = self._match_property(address)
            if property_id:
                result['property_id'] = property_id
                result['reasons'].append(f"Immobilie erkannt: {address}")

        # 5. Ordner erstellen/finden
        folder_id, folder_path = self._find_or_create_folder(result)
        result['primary_folder_id'] = folder_id
        result['primary_folder_path'] = folder_path

        # 6. Virtuelle Ordner-Zuordnungen (z.B. Rechnung UND Immobilie)
        result['virtual_folder_ids'] = self._determine_virtual_folders(result)

        # 7. Gelernte Regeln anwenden
        rule_match = self._apply_learned_rules(text, metadata)
        if rule_match and rule_match['confidence'] > result['confidence']:
            result['primary_folder_id'] = rule_match['folder_id']
            result['confidence'] = rule_match['confidence']
            result['reasons'].append(f"Gelernte Regel: {rule_match['reason']}")

        return result

    def _detect_sender(self, text_lower: str, metadata: Dict) -> Optional[str]:
        """Erkennt den Absender aus Text und Metadaten"""
        # Erst aus Metadaten
        if metadata.get('sender'):
            return metadata['sender']

        # Dann aus Briefkopf (erste 500 Zeichen)
        header = text_lower[:500]

        # Typische Absender-Muster
        patterns = [
            r'von:\s*([^\n]+)',
            r'absender:\s*([^\n]+)',
            r'^([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)*)\s*(?:gmbh|ag|kg|ohg|e\.?v\.?|mbh)',
        ]

        for pattern in patterns:
            match = re.search(pattern, header, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()

        return None

    def _match_known_sender(self, sender: Optional[str], text_lower: str) -> Optional[Dict]:
        """Prüft ob der Absender bekannt ist"""
        check_text = (sender or '').lower() + ' ' + text_lower[:1000]

        for known_sender, info in KNOWN_SENDERS.items():
            if known_sender in check_text:
                return info

        return None

    def _determine_category(self, text_lower: str) -> Tuple[str, Optional[str], float]:
        """Bestimmt Kategorie und Unterkategorie"""
        best_category = 'Sonstiges'
        best_subcategory = None
        best_score = 0

        for category, info in CATEGORY_PATTERNS.items():
            # Hauptkategorie-Keywords prüfen
            category_score = 0
            for keyword in info['keywords']:
                if keyword in text_lower:
                    category_score += 1

            if category_score > 0:
                score = category_score / len(info['keywords'])

                # Unterkategorie prüfen
                subcategory = None
                for subcat, sub_keywords in info.get('subtypes', {}).items():
                    for kw in sub_keywords:
                        if kw in text_lower:
                            subcategory = subcat
                            score += 0.2  # Bonus für Unterkategorie
                            break
                    if subcategory:
                        break

                if score > best_score:
                    best_score = score
                    best_category = category
                    best_subcategory = subcategory

        confidence = min(0.95, best_score) if best_score > 0 else 0.1
        return best_category, best_subcategory, confidence

    def _extract_address(self, text: str) -> Optional[str]:
        """Extrahiert Adresse aus dem Text (Leistungsort)"""
        if not text:
            return None

        # Suche nach "Leistungsort", "Objekt", "Lieferadresse" etc.
        address_indicators = [
            r'(?:leistungsort|objekt|lieferadresse|verbrauchsstelle|anschrift|objekt-?adresse)[:\s]+([^\n]{10,100})',
            r'(?:für|bezüglich)[:\s]+(\d{5}\s+[A-Za-zäöüÄÖÜß\-\s]+,?\s+[A-Za-zäöüÄÖÜß\-\s]+\s+\d+)',
        ]

        for pattern in address_indicators:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # Allgemeine Adresse suchen (PLZ + Stadt + Straße)
        address_pattern = r'(\d{5})\s+([A-Za-zäöüÄÖÜß\-\s]+),?\s+([A-Za-zäöüÄÖÜß\-\s]+(?:str(?:aße|\.)?|weg|platz|allee|ring|gasse))\s+(\d+\s*[a-zA-Z]?)'
        match = re.search(address_pattern, text, re.IGNORECASE)
        if match:
            return f"{match.group(3)} {match.group(4)}, {match.group(1)} {match.group(2)}"

        return None

    def _match_property(self, address: str) -> Optional[int]:
        """Findet eine passende Immobilie zur Adresse"""
        if not address:
            return None

        address_lower = address.lower()

        with get_db() as session:
            properties = session.query(Property).filter(
                Property.user_id == self.user_id
            ).all()

            for prop in properties:
                # Verschiedene Adresskomponenten prüfen
                if prop.street and prop.street.lower() in address_lower:
                    return prop.id
                if prop.postal_code and prop.postal_code in address:
                    if prop.city and prop.city.lower() in address_lower:
                        return prop.id
                if prop.full_address and prop.full_address.lower() in address_lower:
                    return prop.id

        return None

    def _find_or_create_folder(self, result: Dict) -> Tuple[Optional[int], Optional[str]]:
        """Findet oder erstellt den passenden Ordner"""
        category = result['category']
        subcategory = result['subcategory']
        suggested = result['suggested_subfolders']

        # Ordnerpfad bestimmen
        if suggested:
            folder_path = suggested[0]
        elif subcategory:
            folder_path = f"{category}/{subcategory}"
        else:
            # Standard-Mapping
            folder_mapping = {
                'Rechnung': 'Rechnungen',
                'Mahnung': 'Rechnungen/Mahnungen',
                'Vertrag': 'Verträge',
                'Versicherung': 'Versicherungen',
                'Kontoauszug': 'Finanzen/Kontoauszüge',
                'Lohnabrechnung': 'Finanzen/Gehalt',
                'Darlehen': 'Darlehen',
                'Steuerbescheid': 'Steuern',
                'Rentenbescheid': 'Rentenbescheide',
                'Bescheid': 'Behörden',
            }
            folder_path = folder_mapping.get(category, 'Posteingang')

        # Ordner finden oder erstellen
        folder_id = self._get_or_create_folder_path(folder_path)

        return folder_id, folder_path

    def _get_or_create_folder_path(self, path: str) -> Optional[int]:
        """Erstellt Ordnerstruktur und gibt die ID des letzten Ordners zurück"""
        parts = path.split('/')
        parent_id = None

        with get_db() as session:
            for part in parts:
                # Ordner suchen
                folder = session.query(Folder).filter(
                    Folder.user_id == self.user_id,
                    Folder.name == part,
                    Folder.parent_id == parent_id
                ).first()

                if not folder:
                    # Ordner erstellen
                    folder = Folder(
                        user_id=self.user_id,
                        name=part,
                        parent_id=parent_id,
                        color="#4CAF50"
                    )
                    session.add(folder)
                    session.flush()

                parent_id = folder.id

            session.commit()
            return parent_id

    def _determine_virtual_folders(self, result: Dict) -> List[int]:
        """Bestimmt zusätzliche virtuelle Ordner-Zuordnungen"""
        virtual_ids = []

        # Wenn Immobilie erkannt, auch in Immobilien-Ordner
        if result.get('property_id'):
            with get_db() as session:
                prop = session.get(Property, result['property_id'])
                if prop:
                    # Ordner für diese Immobilie finden/erstellen
                    folder_path = f"Immobilien/{prop.name or prop.city or 'Unbekannt'}"
                    folder_id = self._get_or_create_folder_path(folder_path)
                    if folder_id and folder_id != result.get('primary_folder_id'):
                        virtual_ids.append(folder_id)

        # Rechnungen auch in Rechnungen-Ordner
        if result['category'] == 'Rechnung' and result.get('primary_folder_id'):
            rechnungen_id = self._get_or_create_folder_path('Rechnungen')
            if rechnungen_id and rechnungen_id != result.get('primary_folder_id'):
                virtual_ids.append(rechnungen_id)

        return virtual_ids

    def _apply_learned_rules(self, text: str, metadata: Dict) -> Optional[Dict]:
        """Wendet gelernte Regeln an"""
        with get_db() as session:
            rules = session.query(ClassificationRule).filter(
                ClassificationRule.user_id == self.user_id
            ).order_by(ClassificationRule.confidence.desc()).all()

            text_lower = (text or '').lower()
            sender = (metadata.get('sender') or '').lower()

            best_match = None
            best_score = 0

            for rule in rules:
                score = 0

                # Absender prüfen
                if rule.sender_pattern:
                    if rule.sender_pattern.lower() in sender:
                        score += 0.5
                    elif rule.sender_pattern.lower() in text_lower[:500]:
                        score += 0.3

                # Schlüsselwörter prüfen
                if rule.subject_keywords:
                    keywords = rule.subject_keywords if isinstance(rule.subject_keywords, list) else []
                    matches = sum(1 for kw in keywords if kw.lower() in text_lower)
                    if keywords:
                        score += 0.5 * (matches / len(keywords))

                if score > best_score and score > 0.4:
                    best_score = score
                    best_match = {
                        'folder_id': rule.target_folder_id,
                        'confidence': min(0.95, score * rule.confidence),
                        'reason': f"Regel: {rule.sender_pattern}"
                    }

            return best_match

    def classify_with_ai(self, text: str, metadata: Dict) -> Dict:
        """Klassifiziert ein Dokument mit KI-Unterstützung"""
        # Erst regelbasierte Klassifikation
        result = self.classify(text, metadata)

        # Wenn Konfidenz niedrig, KI fragen
        if result['confidence'] < 0.5:
            try:
                from services.ai_service import get_ai_service
                ai = get_ai_service()

                # Ordnerstruktur laden
                with get_db() as session:
                    folders = session.query(Folder).filter(
                        Folder.user_id == self.user_id
                    ).all()
                    folder_list = [f.name for f in folders]

                prompt = f"""Analysiere dieses Dokument und bestimme die beste Kategorie und Ordner-Zuordnung.

Dokumenttext (Ausschnitt):
{text[:2000] if text else 'Kein Text verfügbar'}

Verfügbare Ordner: {', '.join(folder_list)}

Antworte im JSON-Format:
{{
    "category": "Kategorie des Dokuments",
    "suggested_folder": "Name des passenden Ordners",
    "subcategory": "Unterkategorie falls zutreffend",
    "confidence": 0.0-1.0,
    "reason": "Begründung"
}}"""

                ai_result = ai.process(prompt)

                # JSON aus Antwort extrahieren
                json_match = re.search(r'\{[^}]+\}', ai_result, re.DOTALL)
                if json_match:
                    ai_data = json.loads(json_match.group())

                    result['category'] = ai_data.get('category', result['category'])
                    result['subcategory'] = ai_data.get('subcategory')
                    result['confidence'] = max(result['confidence'], ai_data.get('confidence', 0.5))
                    result['reasons'].append(f"KI: {ai_data.get('reason', 'Analyse')}")

                    # Ordner finden
                    suggested = ai_data.get('suggested_folder')
                    if suggested:
                        folder_id = self._get_or_create_folder_path(suggested)
                        if folder_id:
                            result['primary_folder_id'] = folder_id
                            result['primary_folder_path'] = suggested

            except Exception as e:
                # KI-Fehler ignorieren, regelbasiertes Ergebnis behalten
                pass

        return result

    def learn_from_move(self, document_id: int, target_folder_id: int):
        """Lernt aus einer Benutzeraktion (Dokument verschieben)"""
        with get_db() as session:
            document = session.get(Document, document_id)
            if not document:
                return

            sender = document.sender
            category = document.category

            # Schlüsselwörter aus Betreff/Text
            keywords = []
            if document.subject:
                words = re.findall(r'\b[A-Za-zäöüÄÖÜß]{4,}\b', document.subject)
                keywords = [w.lower() for w in words[:5]]

            # Existierende Regel suchen oder erstellen
            existing_rule = session.query(ClassificationRule).filter(
                ClassificationRule.user_id == self.user_id,
                ClassificationRule.sender_pattern == sender,
                ClassificationRule.target_folder_id == target_folder_id
            ).first()

            if existing_rule:
                existing_rule.times_applied += 1
                existing_rule.confidence = min(0.99, existing_rule.confidence + 0.1)
                if keywords:
                    existing_keywords = existing_rule.subject_keywords or []
                    existing_rule.subject_keywords = list(set(existing_keywords + keywords))
            else:
                new_rule = ClassificationRule(
                    user_id=self.user_id,
                    sender_pattern=sender,
                    subject_keywords=keywords,
                    category=category,
                    target_folder_id=target_folder_id,
                    times_applied=1,
                    confidence=0.5
                )
                session.add(new_rule)

            session.commit()

    def assign_to_virtual_folders(self, document_id: int, folder_ids: List[int]):
        """Weist ein Dokument mehreren virtuellen Ordnern zu"""
        with get_db() as session:
            document = session.get(Document, document_id)
            if not document:
                return

            for folder_id in folder_ids:
                folder = session.get(Folder, folder_id)
                if folder and folder not in document.virtual_folders:
                    document.virtual_folders.append(folder)

            session.commit()


def get_classifier(user_id: int) -> DocumentClassifier:
    """Factory für DocumentClassifier"""
    return DocumentClassifier(user_id)
