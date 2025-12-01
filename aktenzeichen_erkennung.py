"""
Aktenzeichen-Erkennungsmodul für RHM Posteingang
Implementiert alle Regeln aus dem Masterprompt
"""

import re
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime


class AktenzeichenErkenner:
    # Kanzlei-Kürzel (MQ vor M, da MQ spezifischer)
    KUERZEL = ['MQ', 'SQ', 'TS', 'CV', 'FÜ', 'FU', 'M']
    KUERZEL_NORMALISIERT = {
        'MQ': 'M',  # MQ = M (RAin Marquardsen)
        'FU': 'FÜ',  # FU = FÜ
        'FÜ': 'FÜ',
        'SQ': 'SQ',
        'TS': 'TS',
        'CV': 'CV',
        'M': 'M'
    }

    # Schlagwörter für "Ihr Zeichen" etc.
    ZEICHEN_KEYWORDS = [
        'ihr zeichen', 'unser zeichen', 'ihr az', 'ihr az.',
        'ihr aktenzeichen', 'dortiges aktenzeichen', 'verwendungszweck'
    ]

    # Externe Aktenzeichen-Schlagwörter
    EXTERNE_KEYWORDS = [
        'aktenzeichen beim', 'az.', 'schadennummer', 'schaden-nr',
        'versicherungsnummer', 'kundennummer'
    ]

    def __init__(self, excel_path: Path):
        """Lädt das Aktenregister"""
        self.akten_register = self._lade_aktenregister(excel_path)

    def _lade_aktenregister(self, excel_path: Path) -> pd.DataFrame:
        """Lädt aktenregister.xlsx, Blatt 'akten'"""
        df = pd.read_excel(excel_path, sheet_name='akten', header=1)

        # Spalten bereinigen
        df['Akte'] = df['Akte'].astype(str).str.strip()
        df['SB'] = df['SB'].astype(str).str.strip().str.upper()

        # FU zu FÜ normalisieren
        df['SB'] = df['SB'].replace('FU', 'FÜ')

        return df

    def erkenne_aktenzeichen(self, text: str) -> Dict:
        """
        Hauptfunktion: Erkennt internes und externe Aktenzeichen im Text

        Returns:
            Dict mit:
            - internes_az: Internes Kanzlei-Aktenzeichen (z.B. "151/25M")
            - stamm: Nur der Stamm (z.B. "151/25")
            - kuerzel: Sachbearbeiter-Kürzel (z.B. "M")
            - externe_az: Liste externer Aktenzeichen
            - quelle: Woher das interne AZ stammt (zeichen_feld, vollmuster, register, etc.)
        """
        result = {
            'internes_az': None,
            'stamm': None,
            'kuerzel': None,
            'externe_az': [],
            'quelle': None
        }

        # Priorität 1: "Ihr Zeichen / Unser Zeichen" etc.
        zeichen_az = self._suche_in_zeichen_feldern(text)
        if zeichen_az:
            result.update(zeichen_az)
            result['quelle'] = 'zeichen_feld'
            return result

        # Priorität 2: Vollmuster im Text
        vollmuster = self._suche_vollmuster(text)
        if vollmuster:
            result.update(vollmuster)
            result['quelle'] = 'vollmuster'
            return result

        # Priorität 3: Stämme mit Registertreffer
        register_az = self._suche_stamm_mit_register(text)
        if register_az:
            result.update(register_az)
            result['quelle'] = 'register'
            return result

        # Externe Aktenzeichen sammeln (immer)
        result['externe_az'] = self._suche_externe_aktenzeichen(text)

        return result

    def _suche_in_zeichen_feldern(self, text: str) -> Optional[Dict]:
        """
        Sucht nach Aktenzeichen in "Ihr Zeichen / Unser Zeichen" etc. Zeilen
        Höchste Priorität!
        """
        lines = text.split('\n')

        for i, line in enumerate(lines):
            line_lower = line.lower()

            # Prüfe, ob Zeile ein Zeichen-Keyword enthält
            if any(kw in line_lower for kw in self.ZEICHEN_KEYWORDS):
                # Suche in dieser und der nächsten Zeile (wegen Umbruch)
                such_text = line
                if i + 1 < len(lines):
                    such_text += " " + lines[i + 1]

                # Suche nach Stamm
                stamm_match = re.search(r'\b(\d{1,5}/\d{2})', such_text)
                if stamm_match:
                    stamm = stamm_match.group(1)

                    # Hole Text nach dem Stamm (Suffix)
                    start_pos = stamm_match.end()
                    suffix = such_text[start_pos:start_pos + 20]  # max 20 Zeichen

                    # Suche Kürzel im Suffix (direkt nach Stamm, ohne Leerzeichen)
                    kuerzel = self._finde_kuerzel_im_text(suffix, position_sensitive=True)

                    if kuerzel:
                        # Kürzel gefunden!
                        kuerzel_norm = self.KUERZEL_NORMALISIERT.get(kuerzel, kuerzel)
                        return {
                            'internes_az': f"{stamm}{kuerzel_norm}",
                            'stamm': stamm,
                            'kuerzel': kuerzel_norm
                        }
                    else:
                        # Kein Kürzel im Suffix → Register prüfen
                        register_info = self._pruefe_register(stamm)
                        if register_info:
                            return register_info

        return None

    def _suche_vollmuster(self, text: str) -> Optional[Dict]:
        """
        Sucht nach Vollmustern: \d{1,5}/\d{2}(SQ|M|MQ|TS|FÜ|CV)...
        """
        # Pattern: Stamm + Kürzel
        pattern = r'\b(\d{1,5}/\d{2})(MQ|SQ|TS|CV|FÜ|FU|M)\b'

        matches = re.findall(pattern, text, re.IGNORECASE)

        if matches:
            # Nehme ersten Match
            stamm, kuerzel = matches[0]
            kuerzel = kuerzel.upper()
            kuerzel_norm = self.KUERZEL_NORMALISIERT.get(kuerzel, kuerzel)

            return {
                'internes_az': f"{stamm}{kuerzel_norm}",
                'stamm': stamm,
                'kuerzel': kuerzel_norm
            }

        return None

    def _suche_stamm_mit_register(self, text: str) -> Optional[Dict]:
        """
        Sucht nach Stämmen und prüft gegen Aktenregister
        """
        stamm_matches = re.findall(r'\b(\d{1,5}/\d{2})\b', text)

        for stamm in stamm_matches:
            register_info = self._pruefe_register(stamm)
            if register_info:
                return register_info

        return None

    def _pruefe_register(self, stamm: str) -> Optional[Dict]:
        """
        Prüft, ob ein Stamm im Aktenregister existiert
        Returns internes AZ = Akte + SB aus Register
        """
        treffer = self.akten_register[self.akten_register['Akte'] == stamm]

        if not treffer.empty:
            row = treffer.iloc[0]
            sb = row['SB']
            sb_norm = self.KUERZEL_NORMALISIERT.get(sb, sb)

            return {
                'internes_az': f"{stamm}{sb_norm}",
                'stamm': stamm,
                'kuerzel': sb_norm,
                'register_data': row.to_dict()
            }

        return None

    def _finde_kuerzel_im_text(self, text: str, position_sensitive: bool = False) -> Optional[str]:
        """
        Findet Kürzel im Text
        position_sensitive: Wenn True, muss Kürzel am Anfang sein (für Suffix)
        """
        text_upper = text.upper()

        if position_sensitive:
            # Kürzel muss am Anfang sein (mit max 1-2 Zeichen Abstand)
            for kuerzel in self.KUERZEL:
                if text_upper[:5].find(kuerzel) in [0, 1, 2]:
                    return kuerzel
        else:
            # Irgendwo im Text
            for kuerzel in self.KUERZEL:
                if kuerzel in text_upper:
                    return kuerzel

        return None

    def _suche_externe_aktenzeichen(self, text: str) -> List[str]:
        """
        Sucht nach externen Aktenzeichen (Gerichte, Versicherungen, etc.)
        """
        externe = []
        lines = text.split('\n')

        for line in lines:
            line_lower = line.lower()

            # Prüfe auf externe Keywords
            if any(kw in line_lower for kw in self.EXTERNE_KEYWORDS):
                # Extrahiere alles, was wie ein AZ aussieht
                # Typische Muster: 123 C 456/78, 12 O 345/24, Schaden-Nr. 123456789
                patterns = [
                    r'\b\d+\s+[A-Z]+\s+\d+/\d+\b',  # Gerichts-AZ
                    r'\b[A-Z]{2,}\d{6,}\b',  # Versicherungsnummern
                    r'\b\d{6,}\b'  # Schadensnummern
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, line)
                    externe.extend(matches)

        return list(set(externe))  # Duplikate entfernen

    def ermittle_sachbearbeiter(self, akt_info: Dict, analyse: Dict) -> str:
        """
        Ermittelt den Sachbearbeiter basierend auf Aktenzeichen und Analyse

        Priorität:
        1. Kürzel aus internem AZ
        2. Register-Daten
        3. Heuristik (nicht implementiert)
        4. "nicht-zugeordnet"
        """
        # 1. Kürzel aus internem AZ
        if akt_info.get('kuerzel'):
            return akt_info['kuerzel']

        # 2. Register-Daten
        if 'register_data' in akt_info:
            sb = akt_info['register_data'].get('SB')
            if sb:
                return self.KUERZEL_NORMALISIERT.get(sb, sb)

        # 3. Fallback
        return 'nicht-zugeordnet'

    def generiere_dateiname(self, internes_az: Optional[str], mandant: Optional[str],
                           gegner: Optional[str], datum: Optional[str],
                           stichworte: List[str]) -> str:
        """
        Generiert Dateinamen nach Schema:
        [Aktenzeichen]_[Mandant]_[Gegner]_[Datum]_[Stichworte].pdf
        """
        teile = []

        # 1. Aktenzeichen
        if internes_az:
            teile.append(self._bereinige_text(internes_az))
        else:
            teile.append("ohne-az")

        # 2. Mandant
        if mandant:
            teile.append(self._bereinige_text(mandant)[:30])

        # 3. Gegner
        if gegner:
            teile.append(self._bereinige_text(gegner)[:30])

        # 4. Datum
        if datum:
            teile.append(self._bereinige_text(datum))

        # 5. Stichworte (max 3)
        if stichworte:
            stichworte_str = "_".join([self._bereinige_text(s) for s in stichworte[:3]])
            teile.append(stichworte_str[:40])

        dateiname = "_".join(teile) + ".pdf"
        return dateiname

    def _bereinige_text(self, text: str) -> str:
        """
        Bereinigt Text für Dateinamen:
        - Umlaute ersetzen
        - Sonderzeichen entfernen
        - Leerzeichen durch Unterstrich
        """
        if not text:
            return ""

        # Umlaute
        replacements = {
            'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
            'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue'
        }
        for alt, neu in replacements.items():
            text = text.replace(alt, neu)

        # Nur alphanumerisch, Unterstrich, Bindestrich
        text = re.sub(r'[^a-zA-Z0-9_\-]', '_', text)

        # Mehrfache Unterstriche vermeiden
        text = re.sub(r'_+', '_', text)

        return text.strip('_')

    def hole_register_info(self, stamm: str) -> Optional[Dict]:
        """
        Holt zusätzliche Informationen aus dem Register
        (Mandant, Gegner, Kurzbez, etc.)
        """
        treffer = self.akten_register[self.akten_register['Akte'] == stamm]

        if not treffer.empty:
            row = treffer.iloc[0]
            info = {
                'art': row.get('Art'),
                'kurzbez': row.get('Kurzbez.'),
                'gegner': row.get('Gegner'),
                'sb': row.get('SB')
            }

            # Parse Kurzbez nach "Mandant ./. Gegner"
            kurzbez = info.get('kurzbez', '')
            if isinstance(kurzbez, str) and './' in kurzbez:
                teile = kurzbez.split('./')
                if len(teile) >= 2:
                    info['mandant'] = teile[0].strip()
                    info['gegner_aus_kurzbez'] = teile[1].strip()

            return info

        return None
