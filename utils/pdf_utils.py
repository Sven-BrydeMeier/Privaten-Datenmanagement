"""
PDF-Verarbeitungsutilities
"""
import io
from typing import List, Tuple, Optional
from pathlib import Path
from PIL import Image
import streamlit as st


class PDFProcessor:
    """Verarbeitet PDF-Dateien und trennt mehrseitige Dokumente"""

    def __init__(self):
        self._pdf2image_available = None

    @property
    def pdf2image_available(self) -> bool:
        """Prüft ob pdf2image verfügbar ist"""
        if self._pdf2image_available is None:
            try:
                from pdf2image import convert_from_bytes
                self._pdf2image_available = True
            except ImportError:
                self._pdf2image_available = False
        return self._pdf2image_available

    def get_page_count(self, pdf_bytes: bytes) -> int:
        """Gibt die Seitenanzahl eines PDFs zurück"""
        from PyPDF2 import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages)

    def split_pdf(self, pdf_bytes: bytes, page_ranges: List[Tuple[int, int]]) -> List[bytes]:
        """
        Teilt ein PDF in mehrere PDFs basierend auf Seitenbereichen.

        Args:
            pdf_bytes: Original-PDF
            page_ranges: Liste von (start, end) Tuples (0-basiert, exklusiv)

        Returns:
            Liste von PDF-Bytes
        """
        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        result = []

        for start, end in page_ranges:
            writer = PdfWriter()
            for page_num in range(start, min(end, len(reader.pages))):
                writer.add_page(reader.pages[page_num])

            output = io.BytesIO()
            writer.write(output)
            result.append(output.getvalue())

        return result

    def extract_page(self, pdf_bytes: bytes, page_num: int) -> bytes:
        """Extrahiert eine einzelne Seite als neues PDF"""
        return self.split_pdf(pdf_bytes, [(page_num, page_num + 1)])[0]

    def detect_document_boundaries(self, pdf_bytes: bytes) -> List[int]:
        """
        Erkennt Dokumentgrenzen in einem mehrseitigen PDF.

        Methoden:
        1. Trennseiten (weiße Seiten mit "Trennseite")
        2. Layoutwechsel (große Unterschiede im Layout)

        Args:
            pdf_bytes: PDF-Bytes

        Returns:
            Liste von Seitennummern, die neue Dokumente beginnen (immer mit 0)
        """
        from services.ocr import get_ocr_service

        ocr = get_ocr_service()
        boundaries = [0]  # Erstes Dokument beginnt bei Seite 0

        if not self.pdf2image_available:
            return boundaries

        try:
            from pdf2image import convert_from_bytes

            images = convert_from_bytes(pdf_bytes, dpi=150)

            for i, image in enumerate(images):
                if i == 0:
                    continue

                # Prüfe auf Trennseite
                if ocr.detect_separator_page(image):
                    # Nächste Seite (nach Trennseite) ist neuer Dokumentanfang
                    if i + 1 < len(images):
                        boundaries.append(i + 1)

                # Prüfe auf starken Layoutwechsel
                elif i > 0 and self._detect_layout_change(images[i-1], image):
                    boundaries.append(i)

        except Exception as e:
            error_msg = str(e)
            if "poppler" in error_msg.lower():
                st.warning("⚠️ Dokumenttrennung nicht verfügbar: Poppler ist nicht installiert. "
                          "Für automatische Dokumenttrennung installieren Sie bitte 'poppler-utils' "
                          "(Linux: apt install poppler-utils, Mac: brew install poppler)")
            else:
                st.warning(f"Dokumenttrennung fehlgeschlagen: {e}")

        return sorted(set(boundaries))

    def _detect_layout_change(self, prev_image: Image.Image, curr_image: Image.Image) -> bool:
        """
        Erkennt signifikante Layoutänderungen zwischen zwei Seiten.

        Eine einfache Heuristik basierend auf Bildunterschieden.
        """
        # Bilder auf gleiche Größe bringen
        size = (200, 280)  # Thumbnail-Größe
        prev_thumb = prev_image.convert('L').resize(size)
        curr_thumb = curr_image.convert('L').resize(size)

        # Pixel vergleichen
        prev_pixels = list(prev_thumb.getdata())
        curr_pixels = list(curr_thumb.getdata())

        # Unterschied berechnen
        diff = sum(abs(p - c) for p, c in zip(prev_pixels, curr_pixels))
        max_diff = 255 * len(prev_pixels)

        # Wenn mehr als 40% Unterschied, wahrscheinlich neues Dokument
        return (diff / max_diff) > 0.4

    def merge_pdfs(self, pdf_list: List[bytes]) -> bytes:
        """Fügt mehrere PDFs zu einem zusammen"""
        from PyPDF2 import PdfReader, PdfWriter

        writer = PdfWriter()

        for pdf_bytes in pdf_list:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def pdf_to_images(self, pdf_bytes: bytes, dpi: int = 200) -> List[Image.Image]:
        """Konvertiert PDF-Seiten zu Bildern"""
        if not self.pdf2image_available:
            return []

        from pdf2image import convert_from_bytes
        return convert_from_bytes(pdf_bytes, dpi=dpi)

    def rotate_page(self, pdf_bytes: bytes, page_num: int, degrees: int) -> bytes:
        """Rotiert eine Seite im PDF"""
        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(io.BytesIO(pdf_bytes))
        writer = PdfWriter()

        for i, page in enumerate(reader.pages):
            if i == page_num:
                page.rotate(degrees)
            writer.add_page(page)

        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()


def get_pdf_processor() -> PDFProcessor:
    """Singleton für PDFProcessor"""
    if 'pdf_processor' not in st.session_state:
        st.session_state.pdf_processor = PDFProcessor()
    return st.session_state.pdf_processor
