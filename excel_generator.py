"""
Excel-Generator für RHM Posteingang
Erstellt Excel-Dateien pro Sachbearbeiter und Gesamt-Excel
"""

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from datetime import datetime, timedelta
from io import BytesIO
from typing import Dict, List
from pathlib import Path


class ExcelGenerator:
    SPALTEN = [
        'Eingangsdatum',          # A
        'Internes Aktenzeichen',  # B
        'Externes Aktenzeichen',  # C
        'Mandant',                # D
        'Gegner / Absender',      # E
        'Absendertyp',            # F
        'Sachbearbeiter',         # G
        'Fristdatum',             # H
        'Fristtyp',               # I
        'Fristquelle',            # J
        'Textauszug',             # K
        'PDF-Datei',              # L
        'Status'                  # M
    ]

    def __init__(self):
        self.heute = datetime.now().date()

    def erstelle_excel_dateien(self, alle_daten: List[Dict], temp_path: Path) -> Dict[str, bytes]:
        """
        Erstellt Excel-Dateien pro Sachbearbeiter

        Returns:
            Dict mit Sachbearbeiter → Excel-Bytes
        """
        excel_dateien = {}

        # Gruppiere nach Sachbearbeiter
        sb_gruppen = {}
        for daten in alle_daten:
            sb = daten['sachbearbeiter']
            if sb not in sb_gruppen:
                sb_gruppen[sb] = []
            sb_gruppen[sb].append(daten)

        # Erstelle Excel pro Sachbearbeiter
        for sb, daten_liste in sb_gruppen.items():
            excel_bytes = self._erstelle_einzelne_excel(daten_liste, sb)
            excel_dateien[sb] = excel_bytes

        return excel_dateien

    def erstelle_gesamt_excel(self, alle_daten: List[Dict]) -> bytes:
        """
        Erstellt Gesamt-Excel mit allen Dokumenten
        """
        return self._erstelle_einzelne_excel(alle_daten, "Gesamt")

    def _erstelle_einzelne_excel(self, daten_liste: List[Dict], titel: str) -> bytes:
        """
        Erstellt eine einzelne Excel-Datei
        """
        zeilen = []

        for daten in daten_liste:
            akt_info = daten['aktenzeichen_info']
            analyse = daten['analyse']
            sb = daten['sachbearbeiter']
            dateiname = daten['dateiname']

            # Fristen verarbeiten
            fristen = analyse.get('fristen', [])

            if fristen:
                # Eine Zeile pro Frist
                for frist in fristen:
                    zeile = self._erstelle_zeile(
                        akt_info, analyse, sb, dateiname, frist
                    )
                    zeilen.append(zeile)
            else:
                # Eine Zeile ohne Frist
                zeile = self._erstelle_zeile(
                    akt_info, analyse, sb, dateiname, None
                )
                zeilen.append(zeile)

        # DataFrame erstellen
        df = pd.DataFrame(zeilen, columns=self.SPALTEN)

        # Excel in BytesIO schreiben
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Fristen', index=False)

        buffer.seek(0)
        excel_bytes = buffer.getvalue()

        # Farbliche Markierung hinzufügen
        excel_bytes = self._markiere_fristen(excel_bytes)

        return excel_bytes

    def _erstelle_zeile(self, akt_info: Dict, analyse: Dict, sb: str,
                       dateiname: str, frist: Dict = None) -> List:
        """
        Erstellt eine Zeile für die Excel-Tabelle
        """
        heute_str = self.heute.strftime('%Y-%m-%d')

        zeile = [
            heute_str,  # Eingangsdatum
            akt_info.get('internes_az', ''),  # Internes AZ
            ', '.join(akt_info.get('externe_az', [])),  # Externe AZ
            analyse.get('mandant', ''),  # Mandant
            analyse.get('gegner', ''),  # Gegner / Absender
            analyse.get('absendertyp', 'Sonstige'),  # Absendertyp
            sb,  # Sachbearbeiter
            frist.get('datum', '') if frist else '',  # Fristdatum
            frist.get('typ', '') if frist else '',  # Fristtyp
            frist.get('quelle', '') if frist else '',  # Fristquelle
            analyse.get('textauszug', '')[:200],  # Textauszug (gekürzt)
            dateiname,  # PDF-Datei
            'Neu'  # Status
        ]

        return zeile

    def _markiere_fristen(self, excel_bytes: bytes) -> bytes:
        """
        Markiert Fristen farblich:
        - Rot: ≤ 3 Tage
        - Orange: ≤ 7 Tage
        """
        buffer = BytesIO(excel_bytes)
        wb = load_workbook(buffer)
        ws = wb['Fristen']

        # Farben
        rot = PatternFill(start_color="FF6B6B", end_color="FF6B6B", fill_type="solid")
        orange = PatternFill(start_color="FFA500", end_color="FFA500", fill_type="solid")

        # Spalte H = Fristdatum (Index 8, da 1-basiert)
        fristdatum_col = 8

        for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):  # Ab Zeile 2 (Daten)
            fristdatum_cell = row[fristdatum_col - 1]  # -1 wegen 0-Index
            fristdatum_value = fristdatum_cell.value

            if fristdatum_value:
                try:
                    # Parse Datum
                    if isinstance(fristdatum_value, str):
                        frist_datum = datetime.strptime(fristdatum_value, '%Y-%m-%d').date()
                    elif isinstance(fristdatum_value, datetime):
                        frist_datum = fristdatum_value.date()
                    else:
                        continue

                    # Berechne Differenz
                    diff = (frist_datum - self.heute).days

                    # Markiere
                    if diff <= 3:
                        for cell in row:
                            cell.fill = rot
                    elif diff <= 7:
                        for cell in row:
                            cell.fill = orange

                except:
                    pass

        # Zurück in BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        return output.getvalue()
