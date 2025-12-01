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

        NEUE METHODE: Da OCR das "T" nicht erkennt, verwenden wir strukturelle Analyse:
        - Trennblätter haben EXTREM wenig Text (< 50 Zeichen)
        - Trennblätter haben sehr wenige Textblöcke (1-2)
        - Trennblätter haben große Schriftgrößen (wenn erkannt)
        """
        text = seite.get_text("text").strip()
        text_clean = re.sub(r'\s+', '', text)

        # Debug-Info
        if self.debug:
            text_preview = text[:200] if len(text) > 200 else text
            text_preview = text_preview.replace('\n', ' ')
            self.debug_info.append(f"  Text-Vorschau: '{text_preview}'")
            self.debug_info.append(f"  Text-Länge: {len(text)} Zeichen")
            self.debug_info.append(f"  Bereinigter Text: '{text_clean}' ({len(text_clean)} Zeichen)")

        # NEUE PRIORITÄT 1: Strukturelle Analyse (funktioniert OHNE OCR-Text!)
        try:
            text_dict = seite.get_text("dict")
            blocks = text_dict.get("blocks", [])
            text_blocks = [b for b in blocks if "lines" in b]

            # Zähle Textblöcke und größte Schriftgröße
            block_count = len(text_blocks)
            max_font_size = 0
            total_chars = 0

            for block in text_blocks:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text_span = span.get("text", "").strip()
                        font_size = span.get("size", 0)

                        if self.debug and text_span:
                            self.debug_info.append(f"    '{text_span}' → Größe: {font_size:.1f}")

                        if font_size > max_font_size:
                            max_font_size = font_size
                        total_chars += len(text_span)

            if self.debug:
                self.debug_info.append(f"  Anzahl Textblöcke: {block_count}")
                self.debug_info.append(f"  Max. Schriftgröße: {max_font_size:.1f}")
                self.debug_info.append(f"  Zeichen in Spans: {total_chars}")

            # KRITERIUM 1: Sehr große Schriftgröße (> 100) = fast immer Trennblatt
            if max_font_size > 100:
                if self.debug:
                    self.debug_info.append(f"  ✂ TRENNBLATT erkannt! (Riesige Schrift: {max_font_size:.1f})")
                return True

            # KRITERIUM 2: Wenig Text + große Schrift + wenige Blöcke
            if block_count <= 3 and max_font_size > 50 and total_chars < 20:
                if self.debug:
                    self.debug_info.append(f"  ✂ TRENNBLATT erkannt! (Wenig Text + große Schrift)")
                return True

            # KRITERIUM 3: Extrem wenig Textinhalt (< 5 Zeichen im bereinigten Text)
            if len(text_clean) > 0 and len(text_clean) <= 5:
                if self.debug:
                    self.debug_info.append(f"  ✂ TRENNBLATT erkannt! (Nur {len(text_clean)} Zeichen)")
                return True

        except Exception as e:
            if self.debug:
                self.debug_info.append(f"  ⚠ Fehler bei struktureller Analyse: {e}")

        # PRIORITÄT 2: Text-basierte Erkennung (falls OCR doch funktioniert)
        # Prüfe auf "T" (case-insensitive)
        if text_clean.upper() in ['T', 'T.', 'T:']:
            if self.debug:
                self.debug_info.append(f"  ✂ TRENNBLATT erkannt! (exakt 'T')")
            return True

        # PRIORITÄT 3: Sehr kurzer Text mit "T" dominant
        if len(text_clean) <= 10 and len(text_clean) > 0:
            t_count = text_clean.upper().count('T')
            if t_count / len(text_clean) >= 0.5:
                if self.debug:
                    self.debug_info.append(f"  ✂ TRENNBLATT erkannt! (kurzer Text, {t_count}/{len(text_clean)} ist T)")
                return True

        # PRIORITÄT 4: Eine Zeile mit nur "T"
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if len(lines) == 1 and lines[0].upper() in ['T', 'T.', 'T:']:
            if self.debug:
                self.debug_info.append(f"  ✂ TRENNBLATT erkannt! (eine Zeile mit T)")
            return True

        if self.debug:
            self.debug_info.append(f"  → Keine Trennblatt-Kriterien erfüllt")

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
