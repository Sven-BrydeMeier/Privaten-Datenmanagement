"""
Selbstlernender Dokumentenklassifikator
"""
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import streamlit as st

from database import get_db, ClassificationRule, Folder, Document
from config.settings import DOCUMENT_CATEGORIES


class DocumentClassifier:
    """Klassifiziert Dokumente und lernt aus Benutzeraktionen"""

    def __init__(self, user_id: int):
        self.user_id = user_id

    def classify(self, text: str, metadata: Dict) -> Tuple[Optional[int], str, float]:
        """
        Klassifiziert ein Dokument basierend auf Text und Metadaten.

        Args:
            text: OCR-Text des Dokuments
            metadata: Extrahierte Metadaten

        Returns:
            Tuple aus (Ordner-ID, Kategorie, Konfidenz)
        """
        # 1. Versuche regelbasierte Klassifikation
        folder_id, confidence = self._apply_rules(text, metadata)

        # 2. Bestimme Kategorie
        category = self._determine_category(text, metadata)

        # 3. Wenn keine Regel greift, verwende heuristische Zuordnung
        if folder_id is None:
            folder_id = self._heuristic_folder(category)
            confidence = 0.3

        return folder_id, category, confidence

    def _apply_rules(self, text: str, metadata: Dict) -> Tuple[Optional[int], float]:
        """Wendet gelernte Regeln an"""
        with get_db() as session:
            rules = session.query(ClassificationRule).filter(
                ClassificationRule.user_id == self.user_id
            ).order_by(ClassificationRule.confidence.desc()).all()

            best_match = None
            best_score = 0

            for rule in rules:
                score = self._match_rule(rule, text, metadata)
                if score > best_score:
                    best_score = score
                    best_match = rule

            if best_match and best_score > 0.5:
                return best_match.target_folder_id, best_score

        return None, 0

    def _match_rule(self, rule: ClassificationRule, text: str, metadata: Dict) -> float:
        """Bewertet wie gut eine Regel auf ein Dokument passt"""
        score = 0
        max_score = 0

        text_lower = text.lower()
        sender = metadata.get('sender', '') or ''

        # Absender-Pattern prüfen
        if rule.sender_pattern:
            max_score += 1
            if rule.sender_pattern.lower() in sender.lower():
                score += 1
            elif rule.sender_pattern.lower() in text_lower[:500]:  # Briefkopf
                score += 0.8

        # Schlüsselwörter prüfen
        if rule.subject_keywords:
            max_score += 1
            keywords = rule.subject_keywords if isinstance(rule.subject_keywords, list) else []
            matches = sum(1 for kw in keywords if kw.lower() in text_lower)
            if keywords:
                score += matches / len(keywords)

        # Kategorie prüfen
        if rule.category:
            max_score += 0.5
            category_hints = metadata.get('category_hints', [])
            if rule.category in category_hints:
                score += 0.5

        return score / max_score if max_score > 0 else 0

    def _determine_category(self, text: str, metadata: Dict) -> str:
        """Bestimmt die Dokumentenkategorie"""
        # Erst aus Metadaten
        hints = metadata.get('category_hints', [])
        if hints:
            return hints[0]

        # Dann heuristisch
        text_lower = text.lower()

        category_patterns = {
            'Rechnung': [r'rechnung', r'invoice', r'zahlungsziel', r'fällig bis'],
            'Mahnung': [r'mahnung', r'zahlungserinnerung', r'überfällig'],
            'Vertrag': [r'vertrag', r'vereinbarung', r'unterzeichnung'],
            'Versicherung': [r'versicherung', r'police', r'versicherungsnummer'],
            'Kontoauszug': [r'kontoauszug', r'buchungen', r'saldo'],
            'Lohnabrechnung': [r'lohnabrechnung', r'gehaltsabrechnung', r'nettobetrag'],
            'Darlehen': [r'darlehen', r'kredit', r'tilgung', r'darlehensnummer'],
            'Steuerbescheid': [r'steuerbescheid', r'einkommenssteuer', r'finanzamt'],
        }

        for category, patterns in category_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return category

        return 'Sonstiges'

    def _heuristic_folder(self, category: str) -> Optional[int]:
        """Findet einen passenden Ordner basierend auf Kategorie"""
        folder_mapping = {
            'Rechnung': 'Finanzen',
            'Mahnung': 'Finanzen',
            'Vertrag': 'Verträge',
            'Versicherung': 'Versicherungen',
            'Kontoauszug': 'Finanzen',
            'Lohnabrechnung': 'Finanzen',
            'Darlehen': 'Darlehen',
            'Rentenbescheid': 'Rentenbescheide',
            'Lebensversicherung': 'Lebensversicherungen',
            'Steuerbescheid': 'Steuern',
        }

        target_folder_name = folder_mapping.get(category)

        if target_folder_name:
            with get_db() as session:
                folder = session.query(Folder).filter(
                    Folder.user_id == self.user_id,
                    Folder.name == target_folder_name
                ).first()
                if folder:
                    return folder.id

        # Fallback: Posteingang
        with get_db() as session:
            inbox = session.query(Folder).filter(
                Folder.user_id == self.user_id,
                Folder.name == 'Posteingang'
            ).first()
            return inbox.id if inbox else None

    def learn_from_move(self, document_id: int, target_folder_id: int):
        """
        Lernt aus einer Benutzeraktion (Dokument verschieben).

        Args:
            document_id: ID des verschobenen Dokuments
            target_folder_id: ID des Zielordners
        """
        with get_db() as session:
            document = session.get(Document, document_id)
            if not document:
                return

            # Merkmale extrahieren
            sender = document.sender
            category = document.category

            # Schlüsselwörter aus Betreff/Text
            keywords = []
            if document.subject:
                # Wichtige Wörter aus Betreff
                words = re.findall(r'\b[A-Za-zäöüÄÖÜß]{4,}\b', document.subject)
                keywords = [w.lower() for w in words[:5]]

            # Existierende Regel suchen oder neue erstellen
            existing_rule = session.query(ClassificationRule).filter(
                ClassificationRule.user_id == self.user_id,
                ClassificationRule.sender_pattern == sender,
                ClassificationRule.target_folder_id == target_folder_id
            ).first()

            if existing_rule:
                # Regel stärken
                existing_rule.times_applied += 1
                existing_rule.confidence = min(0.99, existing_rule.confidence + 0.1)
                # Schlüsselwörter aktualisieren
                if keywords:
                    existing_keywords = existing_rule.subject_keywords or []
                    existing_rule.subject_keywords = list(set(existing_keywords + keywords))
            else:
                # Neue Regel erstellen
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

    def get_folder_suggestions(self, document_id: int) -> List[Dict]:
        """
        Gibt Ordnervorschläge für ein Dokument zurück.

        Args:
            document_id: Dokument-ID

        Returns:
            Liste von Ordnervorschlägen mit Konfidenz
        """
        suggestions = []

        with get_db() as session:
            document = session.get(Document, document_id)
            if not document:
                return suggestions

            # Regeln anwenden
            rules = session.query(ClassificationRule).filter(
                ClassificationRule.user_id == self.user_id
            ).order_by(ClassificationRule.confidence.desc()).limit(10).all()

            metadata = {
                'sender': document.sender,
                'category_hints': [document.category] if document.category else []
            }

            for rule in rules:
                score = self._match_rule(rule, document.ocr_text or '', metadata)
                if score > 0.3:
                    folder = session.get(Folder, rule.target_folder_id)
                    if folder:
                        suggestions.append({
                            'folder_id': folder.id,
                            'folder_name': folder.name,
                            'confidence': score,
                            'reason': f"Ähnlich zu früheren Dokumenten von {rule.sender_pattern}"
                        })

            # Nach Konfidenz sortieren und Duplikate entfernen
            seen_folders = set()
            unique_suggestions = []
            for s in sorted(suggestions, key=lambda x: x['confidence'], reverse=True):
                if s['folder_id'] not in seen_folders:
                    seen_folders.add(s['folder_id'])
                    unique_suggestions.append(s)

        return unique_suggestions[:5]


def get_classifier(user_id: int) -> DocumentClassifier:
    """Factory für DocumentClassifier"""
    return DocumentClassifier(user_id)
