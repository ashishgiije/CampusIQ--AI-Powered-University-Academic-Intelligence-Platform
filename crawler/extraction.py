"""Page-preserving native extraction and bounded OCR, adapted from v0.6."""
from io import BytesIO
import os
import re

from bs4 import BeautifulSoup

MAX_PAGES = 250
MAX_OCR_PAGES = 24
MAX_PAGE_TEXT = 60000

def html_content(markup):
    soup = BeautifulSoup(markup, "html.parser")
    for node in soup.select("script,style,header,footer,nav,noscript"):
        node.decompose()
    content = soup.select_one("main,article,[role='main']") or soup
    for row in content.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"], recursive=False)]
        if cells and not row.find("table"):
            row.replace_with(" | ".join(cells) + "\n")
    return content.get_text("\n", strip=True)[:MAX_PAGE_TEXT]

def extract_html(markup):
    body = html_content(markup)
    return ([{"number": 1, "text": body, "ocr": False}], [], len(body.strip()) >= 45)

def native_page(page, fallback, index):
    text = ""
    try:
        text = page.get_text(sort=True) or ""
        if len(text.strip()) >= 45:
            if re.search(r"seat|subject|course code|examination", text[:1000], re.I) and page.get_drawings():
                tables = page.find_tables().tables
                rows = []
                for table in tables[:20]:
                    for row in table.extract()[:600]:
                        rows.append(" | ".join(" ".join((cell or "").split()) for cell in row))
                if rows:
                    text += "\n\n" + "\n".join(rows)
            return text
    except (ValueError, RuntimeError):
        if len(text.strip()) >= 45:
            return text
    try:
        alternate = fallback.pages[index].extract_text() or ""
        return max((text, alternate), key=len)
    except Exception:
        return text

def ocr_page(page, language):
    from PIL import Image
    import pytesseract
    if binary := os.getenv("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = binary
    longest = max(page.rect.width, page.rect.height, 1)
    image = page.get_pixmap(dpi=int(min(210, 2800 * 72 / longest)), alpha=False)
    with Image.open(BytesIO(image.tobytes("png"))) as pixels:
        return pytesseract.image_to_string(pixels, lang=language, timeout=18)

def extract_pdf(data, ocr_mode="auto"):
    import pymupdf
    from pypdf import PdfReader
    if not data.startswith(b"%PDF-"):
        raise ValueError("PDF header mismatch")
    pages, warnings = [], []
    try:
        fallback = PdfReader(BytesIO(data))
    except Exception:
        fallback = None
    budget = MAX_OCR_PAGES
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass or not 0 < len(document) <= MAX_PAGES:
            raise ValueError("PDF is encrypted, empty or exceeds the page limit")
        for index, page in enumerate(document):
            native = native_page(page, fallback, index)
            output = native
            ocr = False
            insufficient = len(re.sub(r"\s", "", native)) < 45
            if ocr_mode == "force" or (ocr_mode == "auto" and insufficient):
                if budget:
                    budget -= 1
                    try:
                        recognized = ocr_page(page, os.getenv("OCR_LANG", "eng"))
                        if len(recognized.strip()) > len(output.strip()):
                            output, ocr = recognized, True
                    except Exception as error:
                        warnings.append(f"Page {index + 1}: OCR failed ({type(error).__name__}).")
                else:
                    warnings.append(f"Page {index + 1}: OCR page limit reached.")
            if ocr:
                warnings.append(f"Page {index + 1}: OCR text and numeric values require visual verification.")
            if len(re.sub(r"\s", "", output)) < 12:
                warnings.append(f"Page {index + 1}: sparse or unreadable text.")
            if len(output) > MAX_PAGE_TEXT:
                warnings.append(f"Page {index + 1}: extracted text exceeded the page limit.")
            pages.append({"number": index + 1, "text": output[:MAX_PAGE_TEXT], "ocr": ocr})
    readable = sum(len(p["text"].strip()) >= 45 for p in pages) >= max(1, (len(pages) + 1) // 2)
    return pages, warnings, readable

