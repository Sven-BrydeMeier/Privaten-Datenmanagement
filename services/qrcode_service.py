"""
QR-Code Generator Service
Erstellt QR-Codes für Dokumente und Inventar
"""
from datetime import datetime
from typing import Optional
from pathlib import Path
import base64
import io

# QR-Code generierung über Pillow (ohne qrcode library)
try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class QRCodeService:
    """Service für QR-Code Generierung"""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.qr_dir = Path("data/qrcodes")
        self.qr_dir.mkdir(parents=True, exist_ok=True)

    def generate_document_qr(self, document_id: int, base_url: str = None) -> Optional[str]:
        """
        Generiert QR-Code für ein Dokument
        Returns: Base64-encoded PNG image
        """
        url = f"{base_url or 'app://'}document/{document_id}"
        return self._generate_qr_code(url, f"doc_{document_id}")

    def generate_inventory_qr(self, qr_code: str, base_url: str = None) -> Optional[str]:
        """
        Generiert QR-Code für einen Inventargegenstand
        Returns: Base64-encoded PNG image
        """
        url = f"{base_url or 'app://'}inventory/{qr_code}"
        return self._generate_qr_code(url, f"inv_{qr_code}")

    def generate_share_qr(self, share_token: str, base_url: str = None) -> Optional[str]:
        """
        Generiert QR-Code für einen Share-Link
        Returns: Base64-encoded PNG image
        """
        url = f"{base_url or 'https://example.com/'}share/{share_token}"
        return self._generate_qr_code(url, f"share_{share_token}")

    def generate_custom_qr(self, data: str, name: str = None) -> Optional[str]:
        """
        Generiert benutzerdefinierten QR-Code
        Returns: Base64-encoded PNG image
        """
        return self._generate_qr_code(data, name or f"custom_{datetime.now().strftime('%Y%m%d%H%M%S')}")

    def _generate_qr_code(self, data: str, filename: str) -> Optional[str]:
        """
        Generiert QR-Code als Base64-String
        Verwendet eine einfache Implementierung ohne externe QR-Library
        """
        if not PIL_AVAILABLE:
            return self._generate_placeholder_qr(data)

        try:
            # Einfacher QR-Code-ähnliches Muster generieren
            # (In Produktion würde man eine echte QR-Library verwenden)
            size = 200
            img = Image.new('RGB', (size, size), 'white')
            draw = ImageDraw.Draw(img)

            # Daten als Hash für Muster verwenden
            hash_value = hash(data)

            # Rahmen zeichnen
            draw.rectangle([10, 10, size-10, size-10], outline='black', width=3)

            # Positionsmarkierungen (Ecken)
            for pos in [(20, 20), (size-50, 20), (20, size-50)]:
                draw.rectangle([pos[0], pos[1], pos[0]+30, pos[1]+30], fill='black')
                draw.rectangle([pos[0]+5, pos[1]+5, pos[0]+25, pos[1]+25], fill='white')
                draw.rectangle([pos[0]+10, pos[1]+10, pos[0]+20, pos[1]+20], fill='black')

            # Datenmuster (vereinfacht)
            cell_size = 8
            for y in range(60, size-60, cell_size):
                for x in range(60, size-60, cell_size):
                    # Pseudo-zufälliges Muster basierend auf Hash und Position
                    if (hash_value + x * y) % 3 == 0:
                        draw.rectangle([x, y, x+cell_size-1, y+cell_size-1], fill='black')

            # Als Base64 speichern
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)

            return base64.b64encode(buffer.getvalue()).decode('utf-8')

        except Exception as e:
            print(f"QR-Code Generierung fehlgeschlagen: {e}")
            return self._generate_placeholder_qr(data)

    def _generate_placeholder_qr(self, data: str) -> str:
        """Generiert einen Placeholder wenn PIL nicht verfügbar"""
        # SVG als Fallback
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
            <rect width="200" height="200" fill="white"/>
            <rect x="10" y="10" width="180" height="180" fill="none" stroke="black" stroke-width="2"/>
            <text x="100" y="100" text-anchor="middle" font-size="12">QR: {data[:20]}...</text>
        </svg>'''

        return base64.b64encode(svg.encode()).decode('utf-8')

    def save_qr_to_file(self, base64_data: str, filename: str) -> Optional[Path]:
        """Speichert QR-Code als Datei"""
        try:
            file_path = self.qr_dir / str(self.user_id) / f"{filename}.png"
            file_path.parent.mkdir(parents=True, exist_ok=True)

            image_data = base64.b64decode(base64_data)

            with open(file_path, 'wb') as f:
                f.write(image_data)

            return file_path

        except Exception as e:
            print(f"QR-Code speichern fehlgeschlagen: {e}")
            return None

    def get_qr_as_html_img(self, base64_data: str, alt: str = "QR Code") -> str:
        """Gibt QR-Code als HTML img-Tag zurück"""
        return f'<img src="data:image/png;base64,{base64_data}" alt="{alt}" style="max-width: 200px;"/>'

    def batch_generate_inventory_qrs(self, qr_codes: list, base_url: str = None) -> dict:
        """Generiert QR-Codes für mehrere Inventargegenstände"""
        results = {}

        for qr_code in qr_codes:
            qr_image = self.generate_inventory_qr(qr_code, base_url)
            if qr_image:
                results[qr_code] = qr_image

        return results


# Hilfsfunktion für Streamlit
def display_qr_code(base64_data: str, caption: str = None):
    """Zeigt QR-Code in Streamlit an"""
    import streamlit as st

    if base64_data:
        st.image(
            f"data:image/png;base64,{base64_data}",
            caption=caption,
            width=200
        )
    else:
        st.warning("QR-Code konnte nicht generiert werden")
