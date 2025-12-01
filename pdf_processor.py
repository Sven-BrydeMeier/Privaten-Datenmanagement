"""
PDF-Verarbeitungsmodul für RHM Posteingang
Verarbeitet OCR-PDFs, erkennt Trennblätter und segmentiert Dokumente
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict
import re


class PDFProcessor:
    def __init__(self, pdf_path: Path):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)

    def ist_trennblatt(self, seite: fitz.Page) -> bool:
        """
        Prüft, ob eine Seite ein Trennblatt ist.
        Trennblatt = Seite enthält im Wesentlichen nur ein "T"
        """
        text = seite.get_text("text").strip()

        # Bereinige Text von Whitespace
        text_clean = re.sub(r'\s+', '', text)

        # Trennblatt: nur "T" oder sehr kurz mit "T"
        if text_clean in ['T', 't']:
            return True

        # Auch erlauben: wenig Text, aber "T" dominant
        if len(text_clean) <= 5 and 'T' in text_clean.upper():
            return True

        # Prüfe, ob Text fast nur aus "T" und Whitespace besteht
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if len(lines) == 1 and lines[0].upper() in ['T', 'T.']:
            return True

        return False

    def ist_leerseite(self, seite: fitz.Page) -> bool:
        """
        Prüft, ob eine Seite eine Leerseite ist.
        Leerseite = keine sinnvollen Inhalte (nur Whitespace/Artefakte)
        """
        text = seite.get_text("text").strip()

        # Keine oder minimal Text
        if len(text) < 10:
            return True

        # Prüfe, ob nur Whitespace/Sonderzeichen
        text_alphanumeric = re.sub(r'[^a-zA-Z0-9]', '', text)
        if len(text_alphanumeric) < 5:
            return True

        return False

    def extrahiere_text(self, seite: fitz.Page) -> str:
        """Extrahiert OCR-Text von einer Seite"""
        return seite.get_text("text")

    def verarbeite_pdf(self) -> List[Dict]:
        """
        Hauptfunktion: Verarbeitet das PDF und erstellt Einzeldokumente

        Returns:
            Liste von Dokumenten, jedes mit:
            - pages: Liste der Seitennummern
            - text: Volltext des Dokuments
            - pdf_bytes: PDF-Bytes des Einzeldokuments
        """
        dokumente = []
        aktuelle_seiten = []
        gesamt_text = []

        for seiten_nr in range(len(self.doc)):
            seite = self.doc[seiten_nr]

            # Prüfe auf Leerseite (überspringen)
            if self.ist_leerseite(seite):
                continue

            # Prüfe auf Trennblatt
            if self.ist_trennblatt(seite):
                # Wenn aktuelle Seiten vorhanden, speichere als Dokument
                if aktuelle_seiten:
                    dokument = self._erstelle_dokument(aktuelle_seiten, gesamt_text)
                    dokumente.append(dokument)
                    aktuelle_seiten = []
                    gesamt_text = []
            else:
                # Normale Seite: zu aktuellem Dokument hinzufügen
                aktuelle_seiten.append(seiten_nr)
                text = self.extrahiere_text(seite)
                gesamt_text.append(text)

        # Letztes Dokument speichern (falls vorhanden)
        if aktuelle_seiten:
            dokument = self._erstelle_dokument(aktuelle_seiten, gesamt_text)
            dokumente.append(dokument)

        return dokumente

    def _erstelle_dokument(self, seiten_nummern: List[int], text_liste: List[str]) -> Dict:
        """
        Erstellt ein Einzeldokument aus den gegebenen Seiten
        """
        # Volltext zusammenfügen
        volltext = "\n\n".join(text_liste)

        # Einzelnes PDF erstellen
        doc_neu = fitz.open()
        for seiten_nr in seiten_nummern:
            doc_neu.insert_pdf(self.doc, from_page=seiten_nr, to_page=seiten_nr)

        # PDF als Bytes
        pdf_bytes = doc_neu.tobytes()
        doc_neu.close()

        return {
            'pages': seiten_nummern,
            'text': volltext,
            'pdf_bytes': pdf_bytes,
            'page_count': len(seiten_nummern)
        }

    def __del__(self):
        """Schließt das PDF-Dokument"""
        if hasattr(self, 'doc'):
            self.doc.close()
