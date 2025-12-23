"""
Intelligenter Dokumentenklassifikator mit KI-Unterstützung und Explainability
"""
import re
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import streamlit as st

from database import get_db
from database.models import (
    ClassificationRule, Folder, Document, Property, document_virtual_folders,
    Entity, EntityType, FeedbackEvent, FeedbackEventType, ClassificationExplanation
)
from config.settings import DOCUMENT_CATEGORIES


# Erweiterte Kategorie-Patterns mit Untertypen
# WICHTIG: Reihenfolge bestimmt Priorität - spezifischere Kategorien zuerst!
CATEGORY_PATTERNS = {
    # ============================================================
    # HÖCHSTE PRIORITÄT: Sehr spezifische Dokumenttypen
    # ============================================================
    'BWA': {
        'keywords': ['bwa', 'betriebswirtschaftliche auswertung', 'summen- und saldenliste',
                     'gewinn- und verlustrechnung', 'g+v', 'guv', 'bilanz', 'jahresabschluss',
                     'einnahmen-überschuss', 'eür', 'buchführung', 'fibu', 'sachkontenliste',
                     'offene posten', 'debitorenliste', 'kreditorenliste', 'kostenstellenrechnung'],
        'subtypes': {},
        'priority': 100,  # Höchste Priorität
        'folder': 'Buchhaltung/BWA'
    },
    'Buchhaltung': {
        'keywords': ['buchungsbeleg', 'buchungssatz', 'steuerkonto', 'umsatzsteuer-voranmeldung',
                     'ust-va', 'zusammenfassende meldung', 'dauerfristverlängerung',
                     'abschreibung', 'afa', 'anlagenspiegel', 'kassenbuch', 'rechnungseingang',
                     'rechnungsausgang', 'buchhalter', 'steuerberater'],
        'subtypes': {
            'USt': ['umsatzsteuer', 'vorsteuer', 'ust-id', 'mehrwertsteuer'],
            'Lohn': ['lohnbuchhaltung', 'lohnjournal', 'sv-meldung', 'beitragsnachweis'],
        },
        'priority': 95,
        'folder': 'Buchhaltung'
    },
    'Angebot': {
        'keywords': ['angebot', 'kostenvoranschlag', 'preisangebot', 'offerte',
                     'angebotsnummer', 'gültig bis', 'unverbindlich'],
        'subtypes': {},
        'priority': 80,
        'folder': 'Geschäftlich/Angebote'
    },
    'Lieferschein': {
        'keywords': ['lieferschein', 'lieferung', 'wareneingang', 'warenausgang',
                     'packzettel', 'versandbestätigung', 'sendungsnummer'],
        'subtypes': {},
        'priority': 75,
        'folder': 'Geschäftlich/Lieferscheine'
    },
    # ============================================================
    # MITTLERE PRIORITÄT: Standard-Dokumenttypen
    # ============================================================
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
        },
        'priority': 50
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
            'KFZ': ['kfz-versicherung', 'autoversicherung', 'kasko', 'vollkasko', 'teilkasko', 'kfz-haftpflicht'],
            'Leben': ['lebensversicherung', 'kapitallebensversicherung', 'risikoleben'],
            'Rente': ['rentenversicherung', 'altersvorsorge', 'riester', 'rürup'],
            'Rechtsschutz': ['rechtsschutz', 'rechtsschutzversicherung', 'anwalt'],
            'Unfall': ['unfallversicherung', 'invalidität', 'unfall'],
        },
        'priority': 50
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

    def classify(self, text: str, metadata: Dict, save_explanation: bool = True) -> Dict:
        """
        Klassifiziert ein Dokument und gibt alle relevanten Zuordnungen zurück.

        Args:
            text: OCR-Text des Dokuments
            metadata: Extrahierte Metadaten
            save_explanation: Ob die Erklärung gespeichert werden soll

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
            'reasons': [],
            'matched_entities': [],  # Erkannte Entities
            'decision_factors': {    # Für Explainability
                'keyword_matches': [],
                'sender_match': None,
                'rule_matches': [],
                'entity_matches': [],
                'user_keywords': [],
                'ai_suggestion': None
            },
            'alternatives': []  # Alternative Zuordnungen
        }

        text_lower = text.lower() if text else ''

        # 1. Absender erkennen
        sender = self._detect_sender(text_lower, metadata)
        result['detected_sender'] = sender

        # 2. HÖCHSTE PRIORITÄT: Benutzerdefinierte Ordner-Keywords prüfen
        keyword_match = self._match_folder_keywords(text_lower)
        if keyword_match and keyword_match['confidence'] > 0.3:
            result['primary_folder_id'] = keyword_match['folder_id']
            result['confidence'] = keyword_match['confidence']
            result['reasons'].append(f"Benutzer-Keywords: {', '.join(keyword_match['matches'][:3])}")
            result['decision_factors']['user_keywords'] = keyword_match['matches']

        # 3. Bekannte Absender prüfen
        sender_match = self._match_known_sender(sender, text_lower)
        if sender_match and result['confidence'] < 0.8:
            result['category'] = sender_match['category']
            result['suggested_subfolders'].append(sender_match['folder'])
            result['confidence'] = max(result['confidence'], 0.8)
            result['reasons'].append(f"Bekannter Absender: {sender}")
            result['decision_factors']['sender_match'] = {
                'sender': sender,
                'folder': sender_match['folder'],
                'category': sender_match['category'],
                'confidence': 0.8
            }

        # 4. Kategorie und Unterkategorie bestimmen (mit Prioritätssystem)
        category, subcategory, cat_confidence, matched_keywords = self._determine_category_with_keywords(text_lower)
        if cat_confidence > result['confidence'] or not result.get('category') or result['category'] == 'Sonstiges':
            result['category'] = category
            result['subcategory'] = subcategory
            if not result['primary_folder_id']:
                result['confidence'] = max(result['confidence'], cat_confidence)
            result['decision_factors']['keyword_matches'] = matched_keywords

        # 5. Entities erkennen (Personen, Fahrzeuge, etc.)
        entity_matches = self._match_entities(text_lower)
        if entity_matches:
            result['matched_entities'] = entity_matches
            result['decision_factors']['entity_matches'] = entity_matches
            for entity in entity_matches:
                result['reasons'].append(f"Entity erkannt: {entity['name']} ({entity['type']})")

        # 6. Adresse/Immobilie erkennen
        address = self._extract_address(text)
        if address:
            result['detected_address'] = address
            property_id = self._match_property(address)
            if property_id:
                result['property_id'] = property_id
                result['reasons'].append(f"Immobilie erkannt: {address}")

        # 7. Ordner erstellen/finden
        folder_id, folder_path = self._find_or_create_folder(result)
        result['primary_folder_id'] = folder_id
        result['primary_folder_path'] = folder_path

        # 8. Virtuelle Ordner-Zuordnungen (z.B. Rechnung UND Immobilie)
        result['virtual_folder_ids'] = self._determine_virtual_folders(result)

        # 9. Gelernte Regeln anwenden
        rule_match = self._apply_learned_rules(text, metadata)
        if rule_match:
            result['decision_factors']['rule_matches'].append(rule_match)
            if rule_match['confidence'] > result['confidence']:
                result['primary_folder_id'] = rule_match['folder_id']
                result['confidence'] = rule_match['confidence']
                result['reasons'].append(f"Gelernte Regel: {rule_match['reason']}")

        # 10. Alternative Ordner vorschlagen
        result['alternatives'] = self._get_alternative_folders(result, text_lower)

        return result

    def _determine_category_with_keywords(self, text_lower: str) -> Tuple[str, Optional[str], float, List[Dict]]:
        """Bestimmt Kategorie und gibt auch die gefundenen Keywords zurück"""
        best_category = 'Sonstiges'
        best_subcategory = None
        best_score = 0
        best_priority = 0
        all_matches = []

        sorted_categories = sorted(
            CATEGORY_PATTERNS.items(),
            key=lambda x: x[1].get('priority', 50),
            reverse=True
        )

        for category, info in sorted_categories:
            priority = info.get('priority', 50)
            category_score = 0
            matched_keywords = []

            for keyword in info['keywords']:
                if keyword in text_lower:
                    category_score += 1
                    matched_keywords.append({
                        'keyword': keyword,
                        'category': category,
                        'weight': 1.0
                    })

            if category_score > 0:
                base_score = category_score / len(info['keywords'])
                priority_bonus = priority / 1000

                subcategory = None
                for subcat, sub_keywords in info.get('subtypes', {}).items():
                    for kw in sub_keywords:
                        if kw in text_lower:
                            subcategory = subcat
                            base_score += 0.2
                            matched_keywords.append({
                                'keyword': kw,
                                'category': category,
                                'subcategory': subcat,
                                'weight': 1.2
                            })
                            break
                    if subcategory:
                        break

                final_score = base_score + priority_bonus
                all_matches.extend(matched_keywords)

                if final_score > best_score or (priority > best_priority and category_score >= 2):
                    best_score = final_score
                    best_priority = priority
                    best_category = category
                    best_subcategory = subcategory

        confidence = min(0.95, best_score) if best_score > 0 else 0.1
        return best_category, best_subcategory, confidence, all_matches

    def _match_entities(self, text_lower: str) -> List[Dict]:
        """Erkennt Entities (Personen, Fahrzeuge, Lieferanten) im Text"""
        matches = []

        try:
            with get_db() as session:
                entities = session.query(Entity).filter(
                    Entity.user_id == self.user_id,
                    Entity.is_active == True
                ).all()

                for entity in entities:
                    if entity.matches_text(text_lower):
                        matches.append({
                            'id': entity.id,
                            'name': entity.name,
                            'type': entity.entity_type.value if entity.entity_type else 'unknown',
                            'folder_id': entity.folder_id
                        })

                        # Bei Fahrzeug: Kennzeichen prüfen
                        if entity.entity_type == EntityType.VEHICLE:
                            meta = entity.meta or {}
                            plate = meta.get('plate', '')
                            if plate and plate.lower().replace(' ', '').replace('-', '') in text_lower.replace(' ', '').replace('-', ''):
                                matches[-1]['matched_by'] = 'plate'
                                matches[-1]['confidence'] = 0.95

        except Exception:
            pass

        return matches

    def _get_alternative_folders(self, result: Dict, text_lower: str) -> List[Dict]:
        """Gibt alternative Ordner-Zuordnungen zurück"""
        alternatives = []

        try:
            with get_db() as session:
                # Top 3 häufigste Ordner für diese Kategorie
                if result['category']:
                    from sqlalchemy import func
                    folder_counts = session.query(
                        Folder.id, Folder.name, func.count(Document.id).label('doc_count')
                    ).join(Document, Document.folder_id == Folder.id).filter(
                        Document.category == result['category'],
                        Folder.user_id == self.user_id
                    ).group_by(Folder.id).order_by(func.count(Document.id).desc()).limit(3).all()

                    for folder_id, folder_name, count in folder_counts:
                        if folder_id != result.get('primary_folder_id'):
                            alternatives.append({
                                'folder_id': folder_id,
                                'folder_name': folder_name,
                                'reason': f'{count} ähnliche Dokumente',
                                'confidence': min(0.7, count / 20)
                            })
        except Exception:
            pass

        return alternatives[:3]

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
        """Bestimmt Kategorie und Unterkategorie mit Prioritätssystem"""
        best_category = 'Sonstiges'
        best_subcategory = None
        best_score = 0
        best_priority = 0

        # Sortiere Kategorien nach Priorität (höchste zuerst)
        sorted_categories = sorted(
            CATEGORY_PATTERNS.items(),
            key=lambda x: x[1].get('priority', 50),
            reverse=True
        )

        for category, info in sorted_categories:
            priority = info.get('priority', 50)

            # Hauptkategorie-Keywords prüfen
            category_score = 0
            matched_keywords = []
            for keyword in info['keywords']:
                if keyword in text_lower:
                    category_score += 1
                    matched_keywords.append(keyword)

            if category_score > 0:
                # Score normalisieren
                base_score = category_score / len(info['keywords'])

                # Prioritäts-Bonus: Hochprioritäre Kategorien gewinnen bei gleichem Score
                priority_bonus = priority / 1000  # max 0.1 Bonus

                # Unterkategorie prüfen
                subcategory = None
                for subcat, sub_keywords in info.get('subtypes', {}).items():
                    for kw in sub_keywords:
                        if kw in text_lower:
                            subcategory = subcat
                            base_score += 0.2  # Bonus für Unterkategorie
                            break
                    if subcategory:
                        break

                final_score = base_score + priority_bonus

                # Bei höherer Priorität oder besserem Score: Update
                if final_score > best_score or (priority > best_priority and category_score >= 2):
                    best_score = final_score
                    best_priority = priority
                    best_category = category
                    best_subcategory = subcategory

        confidence = min(0.95, best_score) if best_score > 0 else 0.1
        return best_category, best_subcategory, confidence

    def _match_folder_keywords(self, text_lower: str) -> Optional[Dict]:
        """Prüft benutzerdefinierte Ordner-Keywords aus der Datenbank"""
        try:
            from database.models import FolderKeyword
        except ImportError:
            return None

        with get_db() as session:
            # Alle Keywords des Benutzers laden
            keywords = session.query(FolderKeyword).filter(
                FolderKeyword.user_id == self.user_id
            ).all()

            if not keywords:
                return None

            # Scores pro Ordner sammeln
            folder_scores = {}

            for kw in keywords:
                if kw.keyword.lower() in text_lower:
                    folder_id = kw.folder_id
                    if folder_id not in folder_scores:
                        folder_scores[folder_id] = {'score': 0, 'matches': [], 'negative': 0}

                    if kw.is_negative:
                        folder_scores[folder_id]['negative'] += kw.weight
                    else:
                        folder_scores[folder_id]['score'] += kw.weight
                        folder_scores[folder_id]['matches'].append(kw.keyword)

            if not folder_scores:
                return None

            # Beste Übereinstimmung finden (Score minus negative)
            best_folder = None
            best_score = 0

            for folder_id, data in folder_scores.items():
                net_score = data['score'] - data['negative']
                if net_score > best_score:
                    best_score = net_score
                    best_folder = folder_id

            if best_folder and best_score >= 1.0:  # Mindestens 1 Match
                folder = session.get(Folder, best_folder)
                if folder:
                    return {
                        'folder_id': best_folder,
                        'folder_name': folder.name,
                        'confidence': min(0.95, best_score / 3),  # Normalisieren
                        'matches': folder_scores[best_folder]['matches']
                    }

        return None

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
        from sqlalchemy.exc import IntegrityError

        parts = [p.strip() for p in path.split('/') if p.strip()]
        if not parts:
            return None

        parent_id = None

        # Jeden Ordner einzeln in eigener Transaktion erstellen
        for part in parts:
            folder_id = self._get_or_create_single_folder(part, parent_id)
            if folder_id is None:
                return None
            parent_id = folder_id

        return parent_id

    def _get_or_create_single_folder(self, name: str, parent_id: Optional[int]) -> Optional[int]:
        """Erstellt oder findet einen einzelnen Ordner (atomare Operation)"""
        from sqlalchemy.exc import IntegrityError

        # Erst versuchen, existierenden Ordner zu finden
        try:
            with get_db() as session:
                folder = session.query(Folder).filter(
                    Folder.user_id == self.user_id,
                    Folder.name == name,
                    Folder.parent_id == parent_id
                ).first()
                if folder:
                    return folder.id
        except Exception:
            pass

        # Ordner existiert nicht - versuchen zu erstellen
        try:
            with get_db() as session:
                folder = Folder(
                    user_id=self.user_id,
                    name=name,
                    parent_id=parent_id,
                    color="#4CAF50"
                )
                session.add(folder)
                session.commit()
                return folder.id
        except IntegrityError:
            # Wurde zeitgleich von anderem Prozess erstellt - nochmal suchen
            pass
        except Exception:
            pass

        # Fallback: Nochmal suchen nach Race Condition
        try:
            with get_db() as session:
                folder = session.query(Folder).filter(
                    Folder.user_id == self.user_id,
                    Folder.name == name,
                    Folder.parent_id == parent_id
                ).first()
                if folder:
                    return folder.id
        except Exception:
            pass

        return None

    def _determine_virtual_folders(self, result: Dict) -> List[int]:
        """Bestimmt zusätzliche virtuelle Ordner-Zuordnungen"""
        virtual_ids = []

        try:
            # Wenn Immobilie erkannt, auch in Immobilien-Ordner
            if result.get('property_id'):
                try:
                    with get_db() as session:
                        prop = session.get(Property, result['property_id'])
                        if prop:
                            # Ordner für diese Immobilie finden/erstellen
                            folder_path = f"Immobilien/{prop.name or prop.city or 'Unbekannt'}"
                            folder_id = self._get_or_create_folder_path(folder_path)
                            if folder_id and folder_id != result.get('primary_folder_id'):
                                virtual_ids.append(folder_id)
                except Exception:
                    pass

            # Rechnungen auch in Rechnungen-Ordner
            if result.get('category') == 'Rechnung' and result.get('primary_folder_id'):
                try:
                    rechnungen_id = self._get_or_create_folder_path('Rechnungen')
                    if rechnungen_id and rechnungen_id != result.get('primary_folder_id'):
                        virtual_ids.append(rechnungen_id)
                except Exception:
                    pass
        except Exception:
            pass

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
        from sqlalchemy.exc import IntegrityError

        for folder_id in folder_ids:
            try:
                with get_db() as session:
                    document = session.get(Document, document_id)
                    if not document:
                        return

                    folder = session.get(Folder, folder_id)
                    if not folder:
                        continue

                    # Prüfen ob bereits verknüpft (via SQL statt Relationship)
                    from sqlalchemy import select
                    existing = session.execute(
                        select(document_virtual_folders).where(
                            document_virtual_folders.c.document_id == document_id,
                            document_virtual_folders.c.folder_id == folder_id
                        )
                    ).first()

                    if not existing:
                        document.virtual_folders.append(folder)
                        session.commit()
            except IntegrityError:
                # Duplikat-Eintrag ignorieren (bereits zugeordnet)
                pass
            except Exception:
                pass


    def save_classification_explanation(self, document_id: int, result: Dict):
        """Speichert die Erklärung für eine Klassifikationsentscheidung"""
        try:
            with get_db() as session:
                # Prüfen ob bereits existiert
                existing = session.query(ClassificationExplanation).filter(
                    ClassificationExplanation.document_id == document_id
                ).first()

                # Zusammenfassung erstellen
                summary_parts = []
                if result['decision_factors'].get('sender_match'):
                    summary_parts.append(f"Absender '{result['decision_factors']['sender_match']['sender']}' erkannt")
                if result['decision_factors'].get('keyword_matches'):
                    keywords = [m['keyword'] for m in result['decision_factors']['keyword_matches'][:3]]
                    summary_parts.append(f"Keywords: {', '.join(keywords)}")
                if result['decision_factors'].get('entity_matches'):
                    entities = [e['name'] for e in result['decision_factors']['entity_matches']]
                    summary_parts.append(f"Entities: {', '.join(entities)}")
                if result['decision_factors'].get('rule_matches'):
                    summary_parts.append("Gelernte Regel angewendet")

                summary = " | ".join(summary_parts) if summary_parts else "Standardklassifikation"

                if existing:
                    existing.decision_factors = result['decision_factors']
                    existing.summary = summary
                    existing.final_category = result['category']
                    existing.final_folder_id = result.get('primary_folder_id')
                    existing.final_confidence = result['confidence']
                    existing.alternatives = result.get('alternatives', [])
                else:
                    explanation = ClassificationExplanation(
                        document_id=document_id,
                        decision_factors=result['decision_factors'],
                        summary=summary,
                        final_category=result['category'],
                        final_folder_id=result.get('primary_folder_id'),
                        final_confidence=result['confidence'],
                        alternatives=result.get('alternatives', [])
                    )
                    session.add(explanation)

                session.commit()
        except Exception as e:
            pass  # Fehler ignorieren, Klassifikation soll weiterlaufen

    def record_feedback(self, document_id: int, event_type: FeedbackEventType,
                       old_value: Dict, new_value: Dict, text_snippet: str = None):
        """Zeichnet ein Feedback-Event auf für das Lernsystem"""
        try:
            with get_db() as session:
                document = session.get(Document, document_id)
                if not document:
                    return

                feedback = FeedbackEvent(
                    user_id=self.user_id,
                    document_id=document_id,
                    event_type=event_type,
                    old_value=old_value,
                    new_value=new_value,
                    document_text_snippet=text_snippet[:500] if text_snippet else None,
                    document_sender=document.sender,
                    document_category=document.category,
                    processed_for_learning=False
                )
                session.add(feedback)
                session.commit()
        except Exception:
            pass

    def learn_from_feedback(self):
        """Verarbeitet unverarbeitete Feedback-Events und aktualisiert Regeln"""
        try:
            with get_db() as session:
                # Unverarbeitete Events laden
                pending_events = session.query(FeedbackEvent).filter(
                    FeedbackEvent.user_id == self.user_id,
                    FeedbackEvent.processed_for_learning == False
                ).order_by(FeedbackEvent.created_at).limit(100).all()

                for event in pending_events:
                    if event.event_type == FeedbackEventType.FOLDER_MOVE:
                        # Ordnerverschiebung: Regel erstellen/verstärken
                        new_folder_id = event.new_value.get('folder_id')
                        if new_folder_id and event.document_sender:
                            self._update_or_create_rule(
                                sender=event.document_sender,
                                target_folder_id=new_folder_id,
                                text_snippet=event.document_text_snippet
                            )

                    elif event.event_type == FeedbackEventType.ENTITY_ASSIGN:
                        # Entity zugewiesen: Keywords aus Text extrahieren
                        entity_id = event.new_value.get('entity_id')
                        if entity_id and event.document_text_snippet:
                            self._learn_entity_keywords(entity_id, event.document_text_snippet)

                    # Event als verarbeitet markieren
                    event.processed_for_learning = True
                    event.processed_at = datetime.now()

                session.commit()
        except Exception:
            pass

    def _update_or_create_rule(self, sender: str, target_folder_id: int, text_snippet: str = None):
        """Erstellt oder aktualisiert eine Klassifikationsregel"""
        with get_db() as session:
            existing = session.query(ClassificationRule).filter(
                ClassificationRule.user_id == self.user_id,
                ClassificationRule.sender_pattern == sender,
                ClassificationRule.target_folder_id == target_folder_id
            ).first()

            # Keywords aus Textausschnitt extrahieren
            keywords = []
            if text_snippet:
                words = re.findall(r'\b[A-Za-zäöüÄÖÜß]{4,}\b', text_snippet)
                keywords = list(set([w.lower() for w in words if len(w) >= 4]))[:10]

            if existing:
                existing.times_applied += 1
                existing.confidence = min(0.99, existing.confidence + 0.05)
                if keywords:
                    existing_kws = existing.subject_keywords or []
                    existing.subject_keywords = list(set(existing_kws + keywords))[:20]
            else:
                rule = ClassificationRule(
                    user_id=self.user_id,
                    sender_pattern=sender,
                    subject_keywords=keywords,
                    target_folder_id=target_folder_id,
                    times_applied=1,
                    confidence=0.5
                )
                session.add(rule)

            session.commit()

    def _learn_entity_keywords(self, entity_id: int, text_snippet: str):
        """Lernt Keywords für eine Entity aus einem Textausschnitt"""
        # Keywords extrahieren die mit der Entity in Verbindung stehen könnten
        words = re.findall(r'\b[A-Za-zäöüÄÖÜß]{4,}\b', text_snippet.lower())
        unique_words = list(set(words))

        # Hier könnte man die häufigsten Words als Aliase zur Entity hinzufügen
        # Für jetzt nur loggen/speichern für spätere Analyse
        pass

    def get_explanation_for_document(self, document_id: int) -> Optional[Dict]:
        """Gibt die Klassifikationserklärung für ein Dokument zurück"""
        try:
            with get_db() as session:
                explanation = session.query(ClassificationExplanation).filter(
                    ClassificationExplanation.document_id == document_id
                ).first()

                if explanation:
                    return {
                        'summary': explanation.summary,
                        'decision_factors': explanation.decision_factors,
                        'final_category': explanation.final_category,
                        'final_confidence': explanation.final_confidence,
                        'alternatives': explanation.alternatives or []
                    }
        except Exception:
            pass

        return None

    def link_entities_to_document(self, document_id: int, entity_ids: List[int], relation_type: str = 'subject'):
        """Verknüpft Entities mit einem Dokument"""
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy import select

        for entity_id in entity_ids:
            try:
                with get_db() as session:
                    document = session.get(Document, document_id)
                    if not document:
                        return

                    entity = session.get(Entity, entity_id)
                    if not entity:
                        continue

                    # Prüfen ob bereits verknüpft (via SQL statt Relationship)
                    existing = session.execute(
                        select(document_entities).where(
                            document_entities.c.document_id == document_id,
                            document_entities.c.entity_id == entity_id
                        )
                    ).first()

                    if not existing:
                        document.entities.append(entity)
                        # Statistik aktualisieren
                        entity.document_count = (entity.document_count or 0) + 1
                        entity.last_document_date = datetime.now()
                        session.commit()
            except IntegrityError:
                # Duplikat-Eintrag ignorieren (bereits zugeordnet)
                pass
            except Exception:
                pass


def get_classifier(user_id: int) -> DocumentClassifier:
    """Factory für DocumentClassifier"""
    return DocumentClassifier(user_id)
