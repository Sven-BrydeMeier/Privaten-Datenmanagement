"""
Bildvorverarbeitung für Dokumente und Bons
Automatische Randerkennung, Perspektivkorrektur und OCR-Optimierung
"""
import io
import numpy as np
from typing import Tuple, Optional, List
from PIL import Image, ImageEnhance, ImageFilter
import streamlit as st


class ImageProcessor:
    """Service für Bildvorverarbeitung und Dokumentenerkennung"""

    def __init__(self):
        self._cv2_available = None

    @property
    def cv2_available(self) -> bool:
        """Prüft ob OpenCV verfügbar ist"""
        if self._cv2_available is None:
            try:
                import cv2
                self._cv2_available = True
            except ImportError:
                self._cv2_available = False
        return self._cv2_available

    def preprocess_for_ocr(self, image: Image.Image) -> Image.Image:
        """
        Bereitet ein Bild für OCR vor.

        - Konvertiert zu Graustufen
        - Erhöht Kontrast
        - Binarisierung (Schwarz/Weiß)
        - Rauschunterdrückung

        Args:
            image: Eingabebild

        Returns:
            Vorverarbeitetes Bild
        """
        # In Graustufen konvertieren
        if image.mode != 'L':
            gray = image.convert('L')
        else:
            gray = image.copy()

        # Kontrast erhöhen
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(2.0)

        # Schärfen
        gray = gray.filter(ImageFilter.SHARPEN)

        # Wenn OpenCV verfügbar, erweiterte Verarbeitung
        if self.cv2_available:
            gray = self._opencv_enhance(gray)

        return gray

    def _opencv_enhance(self, image: Image.Image) -> Image.Image:
        """Erweiterte Bildverbesserung mit OpenCV"""
        import cv2

        # PIL zu OpenCV
        img_array = np.array(image)

        # Adaptive Threshold für bessere Binarisierung
        binary = cv2.adaptiveThreshold(
            img_array,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,
            2
        )

        # Rauschunterdrückung
        denoised = cv2.fastNlMeansDenoising(binary, None, 10, 7, 21)

        return Image.fromarray(denoised)

    def detect_document_edges(self, image: Image.Image) -> Optional[Image.Image]:
        """
        Erkennt Dokumentenränder und schneidet das Dokument aus.

        Funktioniert mit:
        - Kassenbons
        - Rechnungen
        - Allgemeinen Dokumenten auf kontrastierendem Hintergrund

        Args:
            image: Eingabebild (Foto eines Dokuments)

        Returns:
            Ausgeschnittenes und perspektivkorrigiertes Dokument oder None
        """
        if not self.cv2_available:
            return self._detect_edges_simple(image)

        import cv2

        # PIL zu OpenCV
        img_array = np.array(image)

        # Zu BGR konvertieren falls nötig
        if len(img_array.shape) == 2:
            img_color = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
        elif img_array.shape[2] == 4:
            img_color = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
        else:
            img_color = img_array.copy()

        original = img_color.copy()
        height, width = img_color.shape[:2]

        # Graustufen
        gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)

        # Gaussian Blur für Rauschunterdrückung
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Kantenerkennung mit Canny
        edges = cv2.Canny(blurred, 50, 150)

        # Kanten verstärken
        kernel = np.ones((3, 3), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=2)
        edges = cv2.erode(edges, kernel, iterations=1)

        # Konturen finden
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Nach Fläche sortieren
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        document_contour = None

        for contour in contours[:10]:  # Top 10 Konturen prüfen
            # Kontur approximieren
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

            # Suche nach Viereck (4 Ecken)
            if len(approx) == 4:
                area = cv2.contourArea(approx)
                # Mindestgröße: 10% des Bildes
                if area > (width * height * 0.1):
                    document_contour = approx
                    break

        if document_contour is None:
            # Fallback: Versuche rechteckige Bounding Box
            largest_contour = contours[0]
            area = cv2.contourArea(largest_contour)

            if area > (width * height * 0.1):
                rect = cv2.minAreaRect(largest_contour)
                document_contour = cv2.boxPoints(rect)
                document_contour = np.int0(document_contour)
            else:
                return None

        # Perspektivkorrektur
        warped = self._four_point_transform(original, document_contour.reshape(4, 2))

        # Zurück zu PIL
        if len(warped.shape) == 3:
            warped_rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
        else:
            warped_rgb = warped

        return Image.fromarray(warped_rgb)

    def _detect_edges_simple(self, image: Image.Image) -> Optional[Image.Image]:
        """Einfache Randerkennung ohne OpenCV"""
        # Konvertiere zu Graustufen
        gray = image.convert('L')

        # Finde die Bounding Box des nicht-weißen Bereichs
        pixels = np.array(gray)

        # Threshold anwenden
        binary = pixels < 240  # Alles was nicht fast weiß ist

        if not binary.any():
            return image

        # Zeilen und Spalten mit Inhalt finden
        rows = np.any(binary, axis=1)
        cols = np.any(binary, axis=0)

        if not rows.any() or not cols.any():
            return image

        # Bounding Box
        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]

        # Etwas Rand hinzufügen
        padding = 10
        rmin = max(0, rmin - padding)
        rmax = min(pixels.shape[0], rmax + padding)
        cmin = max(0, cmin - padding)
        cmax = min(pixels.shape[1], cmax + padding)

        # Ausschneiden
        return image.crop((cmin, rmin, cmax, rmax))

    def _four_point_transform(self, image: np.ndarray, pts: np.ndarray) -> np.ndarray:
        """
        Perspektivkorrektur auf Basis von 4 Punkten.

        Args:
            image: OpenCV Bild
            pts: 4 Eckpunkte

        Returns:
            Korrigiertes Bild
        """
        import cv2

        # Punkte ordnen: oben-links, oben-rechts, unten-rechts, unten-links
        rect = self._order_points(pts)
        (tl, tr, br, bl) = rect

        # Berechne neue Dimensionen
        widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        maxWidth = max(int(widthA), int(widthB))

        heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        maxHeight = max(int(heightA), int(heightB))

        # Zielpunkte
        dst = np.array([
            [0, 0],
            [maxWidth - 1, 0],
            [maxWidth - 1, maxHeight - 1],
            [0, maxHeight - 1]
        ], dtype="float32")

        # Perspektivtransformation
        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))

        return warped

    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """Ordnet 4 Punkte: oben-links, oben-rechts, unten-rechts, unten-links"""
        rect = np.zeros((4, 2), dtype="float32")

        # Summe der Koordinaten
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]  # Oben-links hat kleinste Summe
        rect[2] = pts[np.argmax(s)]  # Unten-rechts hat größte Summe

        # Differenz der Koordinaten
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]  # Oben-rechts hat kleinste Differenz
        rect[3] = pts[np.argmax(diff)]  # Unten-links hat größte Differenz

        return rect

    def detect_receipt(self, image: Image.Image) -> Tuple[Optional[Image.Image], dict]:
        """
        Spezialisierte Erkennung für Kassenbons.

        Bons sind typischerweise lang und schmal.

        Args:
            image: Eingabebild

        Returns:
            Tuple aus (ausgeschnittener Bon, Metadaten)
        """
        metadata = {
            'original_size': image.size,
            'detected': False,
            'cropped_size': None,
            'aspect_ratio': None
        }

        # Dokument erkennen
        cropped = self.detect_document_edges(image)

        if cropped is None:
            # Fallback: Einfaches Cropping
            cropped = self._detect_edges_simple(image)

        if cropped:
            metadata['detected'] = True
            metadata['cropped_size'] = cropped.size

            # Aspect Ratio prüfen (Bons sind typischerweise sehr lang)
            w, h = cropped.size
            metadata['aspect_ratio'] = h / w if w > 0 else 0

            # Wenn Bon auf der Seite liegt (breiter als hoch), drehen
            if w > h * 1.5:  # Deutlich breiter als hoch
                cropped = cropped.rotate(90, expand=True)
                metadata['rotated'] = True

        return cropped, metadata

    def auto_rotate(self, image: Image.Image) -> Image.Image:
        """
        Automatische Rotation basierend auf Textausrichtung.

        Args:
            image: Eingabebild

        Returns:
            Korrekt ausgerichtetes Bild
        """
        if not self.cv2_available:
            return image

        import cv2

        img_array = np.array(image.convert('L'))

        # Threshold
        _, binary = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Zeilen projizieren
        coords = np.column_stack(np.where(binary > 0))

        if len(coords) < 100:
            return image

        # Minimum bounding rectangle
        angle = cv2.minAreaRect(coords)[-1]

        # Winkel korrigieren
        if angle < -45:
            angle = 90 + angle
        elif angle > 45:
            angle = angle - 90

        # Nur kleine Korrekturen
        if abs(angle) < 10:
            (h, w) = img_array.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                np.array(image),
                M,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )
            return Image.fromarray(rotated)

        return image

    def enhance_for_receipt(self, image: Image.Image) -> Image.Image:
        """
        Spezielle Verbesserung für Kassenbons.

        Bons haben oft:
        - Niedrigen Kontrast
        - Thermopapier (verblasst)
        - Kleine Schrift

        Args:
            image: Eingabebild

        Returns:
            Verbessertes Bild
        """
        # Graustufen
        if image.mode != 'L':
            gray = image.convert('L')
        else:
            gray = image

        # Starke Kontrasterhöhung
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(2.5)

        # Helligkeit leicht erhöhen (für verblasste Bons)
        brightness = ImageEnhance.Brightness(enhanced)
        enhanced = brightness.enhance(1.1)

        # Schärfen
        enhanced = enhanced.filter(ImageFilter.SHARPEN)
        enhanced = enhanced.filter(ImageFilter.SHARPEN)  # Zweimal für stärkeren Effekt

        # OpenCV-basierte Verbesserung wenn verfügbar
        if self.cv2_available:
            enhanced = self._enhance_receipt_opencv(enhanced)

        return enhanced

    def _enhance_receipt_opencv(self, image: Image.Image) -> Image.Image:
        """OpenCV-basierte Bon-Verbesserung"""
        import cv2

        img_array = np.array(image)

        # CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(img_array)

        # Morphologische Operationen für saubere Zeichen
        kernel = np.ones((1, 1), np.uint8)
        enhanced = cv2.morphologyEx(enhanced, cv2.MORPH_CLOSE, kernel)

        # Adaptive Binarisierung
        binary = cv2.adaptiveThreshold(
            enhanced,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            15,
            4
        )

        return Image.fromarray(binary)


def get_image_processor() -> ImageProcessor:
    """Singleton für den ImageProcessor"""
    if 'image_processor' not in st.session_state:
        st.session_state.image_processor = ImageProcessor()
    return st.session_state.image_processor
