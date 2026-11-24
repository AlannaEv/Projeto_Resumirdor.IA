from pypdf import PdfReader
from pathlib import Path

caminho = Path(__file__).parent / "documento_pdf.pdf"

arquivo = PdfReader(caminho)

def extrair_texto():
    texto = ""

    for pagina in arquivo.pages:
        texto += pagina.extract_text() or ""

    return texto