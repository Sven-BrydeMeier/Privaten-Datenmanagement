"""
PDF-Verarbeitungsmodul für RHM Posteingang
Verarbeitet OCR-PDFs, erkennt Trennblätter und segmentiert Dokumente
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Tuple
import re


class PDFProcessor:
    def __init__(self, pdf_path: Path, debug: bool = False):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.debug = debug
        self.debug_info = []  # Speichert Debug-Informationen

    def ist_trennblatt(self, seite: fitz.Page, seiten_nr: int) -> bool:
        """
        Prüft, ob eine Seite ein Trennblatt ist.
        Trennblatt = Seite enthält im Wesentlichen nur ein "T" (oft mit großer Schrift)
        """
        text = seite.get_text("text").strip()

        # Debug-Info - zeige ersten Teil des Textes
        if self.debug:
            text_preview = text[:200] if len(text) > 200 else text
            text_preview = text_preview.replace('\n', ' ')
            self.debug_info.append(f"  Text-Vorschau: '{text_preview}'")
            self.debug_info.append(f"  Text-Länge: {len(text)} Zeichen")

        # Bereinige Text von Whitespace
        text_clean = re.sub(r'\s+', '', text)
        if self.debug:
            self.debug_info.append(f"  Bereinigter Text: '{text_clean}'")

        # Trennblatt: nur "T" oder sehr kurz mit "T"
        if text_clean.upper() in ['T', 'T.', 'T:']:
            if self.debug:
                self.debug_info.append(f"  → TRENNBLATT erkannt (exakt 'T')")
            return True

        # Prüfe auf große Schriftgröße (für T mit Schriftgröße 500)
        try:
            text_dict = seite.get_text("dict")
            for block in text_dict.get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line.get("spans", []):
                            text_span = span.get("text", "").strip().upper()
                            font_size = span.get("size", 0)

                            # Debug: Zeige Schriftgrößen
                            if self.debug and text_span:
                                self.debug_info.append(f"    Text: '{text_span}' | Schriftgröße: {font_size:.1f}")

                            # Großes T (Schriftgröße > 100) ist eindeutig ein Trennblatt
                            if text_span in ['T', 'T.', 'T:'] and font_size > 100:
                                if self.debug:
                                    self.debug_info.append(f"  → TRENNBLATT erkannt (großes T, Schriftgröße: {font_size:.1f})")
                                return True

                            # Auch wenn nur "T" auf der Seite und Schrift > 50
                            if 'T' in text_span and font_size > 50 and len(text_clean) <= 5:
                                if self.debug:
                                    self.debug_info.append(f"  → TRENNBLATT erkannt (T mit Schriftgröße: {font_size:.1f})")
                                return True
        except Exception as e:
            if self.debug:
                self.debug_info.append(f"  Warnung: Schriftgröße konnte nicht gelesen werden: {e}")

        # Fallback: Auch erlauben - wenig Text, aber "T" dominant
        if len(text_clean) <= 10 and 'T' in text_clean.upper():
            # Prüfe, ob mindestens 50% des Textes "T" ist
            t_count = text_clean.upper().count('T')
            if t_count / len(text_clean) >= 0.5:
                if self.debug:
                    self.debug_info.append(f"  → TRENNBLATT erkannt (kurz mit T)")
                return True

        # Prüfe, ob Text fast nur aus "T" und Whitespace besteht
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if len(lines) == 1 and lines[0].upper() in ['T', 'T.', 'T:']:
            if self.debug:
                self.debug_info.append(f"  → TRENNBLATT erkannt (eine Zeile)")
            return True

        return False

    def ist_leerseite(self, seite: fitz.Page, seiten_nr: int) -> bool:
        """
        Prüft, ob eine Seite eine Leerseite ist.
        Leerseite = keine sinnvollen Inhalte (nur Whitespace/Artefakte)
        """
        text = seite.get_text("text").strip()

        # Sehr strenge Kriterien - nur wirklich leere Seiten
        if len(text) == 0:
            if self.debug:
                self.debug_info.append(f"  → LEERSEITE (kein Text)")
            return True

        # Nur Whitespace/Sonderzeichen - aber strenger
        text_alphanumeric = re.sub(r'[^a-zA-Z0-9]', '', text)
        if len(text_alphanumeric) == 0 and len(text) < 20:
            if self.debug:
                self.debug_info.append(f"  → LEERSEITE (nur Whitespace)")
            return True

        return False

    def extrahiere_text(self, seite: fitz.Page) -> str:
        """Extrahiert OCR-Text von einer Seite"""
        return seite.get_text("text")

    def verarbeite_pdf(self) -> Tuple[List[Dict], List[str]]:
        """
        Hauptfunktion: Verarbeitet das PDF und erstellt Einzeldokumente

        Returns:
            Tuple von (Dokumente, Debug-Info):
            - Dokumente: Liste von Dokumenten, jedes mit:
                - pages: Liste der Seitennummern
                - text: Volltext des Dokuments
                - pdf_bytes: PDF-Bytes des Einzeldokuments
            - Debug-Info: Liste von Debug-Meldungen
        """
        dokumente = []
        aktuelle_seiten = []
        gesamt_text = []
        trennblatt_count = 0
        leerseiten_count = 0

        if self.debug:
            self.debug_info.append(f"=== PDF-Verarbeitung gestartet ===")
            self.debug_info.append(f"Gesamt-Seiten: {len(self.doc)}")

        for seiten_nr in range(len(self.doc)):
            seite = self.doc[seiten_nr]

            if self.debug:
                self.debug_info.append(f"\n--- Verarbeite Seite {seiten_nr + 1} ---")

            # Prüfe auf Leerseite (überspringen)
            if self.ist_leerseite(seite, seiten_nr):
                leerseiten_count += 1
                if self.debug:
                    self.debug_info.append(f"  ⊘ Seite {seiten_nr + 1} übersprungen (Leerseite)")
                continue

            # Prüfe auf Trennblatt
            if self.ist_trennblatt(seite, seiten_nr):
                trennblatt_count += 1
                if self.debug:
                    self.debug_info.append(f"  ✂ Seite {seiten_nr + 1} ist TRENNBLATT #{trennblatt_count}")
                    self.debug_info.append(f"    Aktuelle Seiten im Buffer: {len(aktuelle_seiten)}")

                # Wenn aktuelle Seiten vorhanden, speichere als Dokument
                if aktuelle_seiten:
                    dokument = self._erstelle_dokument(aktuelle_seiten, gesamt_text)
                    dokumente.append(dokument)
                    if self.debug:
                        self.debug_info.append(f"  ✓ Dokument #{len(dokumente)} erstellt (Seiten: {aktuelle_seiten[0]+1}-{aktuelle_seiten[-1]+1})")
                    aktuelle_seiten = []
                    gesamt_text = []
                else:
                    if self.debug:
                        self.debug_info.append(f"    ⚠ Kein Dokument erstellt (keine Seiten im Buffer)")

                if self.debug:
                    self.debug_info.append(f"    → Fahre fort mit nächster Seite...")
            else:
                # Normale Seite: zu aktuellem Dokument hinzufügen
                if self.debug:
                    self.debug_info.append(f"  📄 Seite {seiten_nr + 1} ist normale Dokumentseite")
                aktuelle_seiten.append(seiten_nr)
                text = self.extrahiere_text(seite)
                gesamt_text.append(text)
                if self.debug:
                    self.debug_info.append(f"    → Seiten im Buffer: {len(aktuelle_seiten)}")

        # Letztes Dokument speichern (falls vorhanden)
        if aktuelle_seiten:
            dokument = self._erstelle_dokument(aktuelle_seiten, gesamt_text)
            dokumente.append(dokument)
            if self.debug:
                self.debug_info.append(f"  ✓ Dokument #{len(dokumente)} erstellt (Seiten: {aktuelle_seiten[0]+1}-{aktuelle_seiten[-1]+1})")

        if self.debug:
            self.debug_info.append(f"=== Verarbeitung abgeschlossen ===")
            self.debug_info.append(f"Erkannte Dokumente: {len(dokumente)}")
            self.debug_info.append(f"Trennblätter: {trennblatt_count}")
            self.debug_info.append(f"Leerseiten: {leerseiten_count}")

        return dokumente, self.debug_info

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
