"""
PDF-Verarbeitungsmodul für RHM Posteingang
Verarbeitet OCR-PDFs, erkennt Trennblätter und segmentiert Dokumente
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Tuple
import re


class PDFProcessor:
    def __init__(self, pdf_path: Path, debug: bool = False, trennmodus: str = "Text 'Trennseite'", excel_path: Path = None):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.debug = debug
        self.excel_path = excel_path
        self.debug_info = []  # Speichert Debug-Informationen

    def ist_trennblatt(self, seite: fitz.Page, seiten_nr: int) -> bool:
        """
        Prüft, ob eine Seite ein Trennblatt ist.
        Sucht nach dem Wort "Trennseite" im Text (case-insensitive).
        """
        text = seite.get_text("text").strip()

        if self.debug:
            self.debug_info.append(f"  Text-Vorschau: '{text[:100]}...'")

        # Suche nach dem Wort "Trennseite" (case-insensitive)
        if "trennseite" in text.lower():
            if self.debug:
                self.debug_info.append(f"  ✂ TRENNBLATT erkannt! (Text 'Trennseite' gefunden)")
            return True

        return False

    def ist_leerseite(self, seite: fitz.Page, seiten_nr: int) -> bool:
        """
        Prüft, ob eine Seite eine Leerseite ist.
        Leerseite = KOMPLETT leer, keine Inhalte
        WICHTIG: Weiße Blätter ohne T sind keine Trennblätter!
        """
        text = seite.get_text("text").strip()

        # NUR komplett leere Seiten (0 Zeichen)
        if len(text) == 0:
            if self.debug:
                self.debug_info.append(f"  → LEERSEITE (0 Zeichen)")
            return True

        # SEHR strenge Kriterien: Nur wenn absolut kein alphanumerisches Zeichen
        text_alphanumeric = re.sub(r'[^a-zA-Z0-9]', '', text)
        if len(text_alphanumeric) == 0 and len(text) <= 3:
            if self.debug:
                self.debug_info.append(f"  → LEERSEITE (nur 1-3 Sonderzeichen)")
            return True

        # Alle anderen Seiten sind KEINE Leerseiten
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
            try:
                seite = self.doc[seiten_nr]

                if self.debug:
                    self.debug_info.append(f"\n--- Verarbeite Seite {seiten_nr + 1} von {len(self.doc)} ---")

                # Prüfe auf Leerseite (überspringen)
                ist_leer = self.ist_leerseite(seite, seiten_nr)
                if ist_leer:
                    leerseiten_count += 1
                    if self.debug:
                        self.debug_info.append(f"  ⊘ Seite {seiten_nr + 1} übersprungen (Leerseite)")
                    continue

                # Prüfe auf Trennblatt
                ist_trenner = self.ist_trennblatt(seite, seiten_nr)
                if ist_trenner:
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

            except Exception as e:
                if self.debug:
                    self.debug_info.append(f"  ❌ FEHLER bei Seite {seiten_nr + 1}: {str(e)}")
                    import traceback
                    self.debug_info.append(f"     {traceback.format_exc()}")
                # Fahre trotzdem fort
                continue

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
