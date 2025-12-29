# WICHTIG: Whoosh-Warnungen unterdrücken bevor irgendwelche Services importiert werden
# Whoosh verwendet alte Regex-Syntax ohne Raw-Strings, was Python 3.13 warnt
import warnings
warnings.filterwarnings('ignore', category=SyntaxWarning, module=r'whoosh\..*')
warnings.filterwarnings('ignore', category=SyntaxWarning, module=r'whoosh')
warnings.filterwarnings('ignore', category=DeprecationWarning, module=r'whoosh\..*')
warnings.filterwarnings('ignore', category=DeprecationWarning, module=r'whoosh')

from .encryption import EncryptionService
from .ocr import OCRService
from .ai_service import AIService
from .document_classifier import DocumentClassifier
from .search_service import SearchService
from .image_processor import ImageProcessor

__all__ = [
    'EncryptionService',
    'OCRService',
    'AIService',
    'DocumentClassifier',
    'SearchService',
    'ImageProcessor'
]
