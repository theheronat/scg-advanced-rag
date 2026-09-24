import azure.functions as func
import logging
import os
import json
import io
import subprocess
import gc
import tempfile
import shutil
import csv
import codecs
import hashlib
import html as html_lib
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image
from datetime import datetime, timezone, date, time as dtime, timedelta

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from urllib.parse import urlparse, unquote
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from pypdf import PdfReader
import platform

MAX_SECTION_LENGTH = 2000  # เพิ่มเป็น 2x สำหรับ chunks ใหญ่ขึ้น (ยังอยู่ในขอบเขต embedding model)
SECTION_OVERLAP = 200      # เพิ่มตามสัดส่วน
SENTENCE_SEARCH_LIMIT = 150

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# ---------- Helpers ----------

OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}
IMAGE_EXTS = {".jpg", ".jpeg", ".jpe", ".png"}

# Native tabular path (see "Tabular (Excel / CSV) Processing" section below)
EXCEL_EXTS = {".xlsx", ".xls", ".xlsm"}
CSV_EXTS = {".csv", ".tsv"}
EXCEL_TABLE_FORMAT = os.getenv("EXCEL_TABLE_FORMAT", "markdown").lower()                # markdown | html
EXCEL_SAVE_PROCESSED_FORMAT = os.getenv("EXCEL_SAVE_PROCESSED_FORMAT", "md").lower()    # md | html | none
EXCEL_IMAGE_MODE = os.getenv("EXCEL_IMAGE_MODE", "ocr_ref").lower()                     # ocr_ref | ref_only | none
EXCEL_IMAGE_MIN_PX = int(os.getenv("EXCEL_IMAGE_MIN_PX", "40"))
EXCEL_IMAGE_MIN_BYTES = 1024
EXCEL_ROW_OVERLAP = int(os.getenv("EXCEL_ROW_OVERLAP", "1"))
EXCEL_MAX_HEADER_ROWS = 3
TABULAR_INDEX_BATCH_SIZE = 100


def get_blob_service_client():
    """Get BlobServiceClient"""
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")

    if not account_name or not account_key:
        raise RuntimeError("Storage credentials not found in environment variables")

    return BlobServiceClient(
        account_url=f"https://{account_name}.blob.core.windows.net",
        credential=account_key
    )


def upload_to_blob(file_path, container_name, blob_name):
    """
    Upload file to Azure Blob Storage
    """
    try:
        blob_service = get_blob_service_client()
        
        # สร้าง container ถ้ายังไม่มี
        try:
            container_client = blob_service.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
                logging.info(f"Created container: {container_name}")
        except Exception as e:
            logging.warning(f"Container check/create warning: {e}")
        
        # Upload file
        blob_client = blob_service.get_blob_client(
            container=container_name,
            blob=blob_name
        )

        with open(file_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
        
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        blob_url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}"
        
        logging.info(f"✓ Uploaded to blob: {blob_url}")
        return blob_url
    
    except Exception as e:
        logging.error(f"Failed to upload to blob: {repr(e)}")
        return None


def save_to_local_processed(file_path, filename):
    """
    Save processed file to local directory
    """
    try:
        # สร้าง directory structure
        base_dir = os.path.join(os.getcwd(), "processed")
        today = datetime.now().strftime("%Y-%m-%d")
        local_dir = os.path.join(base_dir, today)
        
        os.makedirs(local_dir, exist_ok=True)
        
        # Copy file
        dest_path = os.path.join(local_dir, filename)
        shutil.copy2(file_path, dest_path)
        
        logging.info(f"✓ Saved to local: {dest_path}")
        return dest_path
    
    except Exception as e:
        logging.error(f"Failed to save locally: {repr(e)}")
        return None


def convert_to_pdf(input_file, output_file):
    """
    Convert files to PDF
    Supported:
    - Office: docx, xlsx, pptx (LibreOffice)
    - Images: jpg, jpeg, jpe, png (Pillow)
    """
    ext = os.path.splitext(input_file)[1].lower()

    try:
        if ext in OFFICE_EXTS:
            return _convert_office_to_pdf(input_file, output_file)

        elif ext in IMAGE_EXTS:
            return _convert_image_to_pdf(input_file, output_file)

        else:
            raise ValueError(f"Unsupported file type: {ext}")

    except Exception as e:
        gc.collect()
        update_data_preparation_log(
            f"[Convert to PDF] - Failed: {repr(e)}", True
        )
        return False
    

def _convert_office_to_pdf(input_file, output_file):
    try:
        env = os.environ.copy()
        temp_profile = tempfile.mkdtemp(prefix="libreoffice_")
        env["HOME"] = temp_profile

        output_dir = os.path.dirname(output_file)
        if not output_dir:
            output_dir = tempfile.gettempdir()
        os.makedirs(output_dir, exist_ok=True)

        # หา LibreOffice
        possible_paths = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/usr/local/bin/libreoffice",
            "/usr/local/bin/soffice",
        ]
        
        libreoffice_cmd = None
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                libreoffice_cmd = path
                logging.info(f"Found LibreOffice at: {path}")
                break
        
        if not libreoffice_cmd:
            for cmd in ["soffice", "libreoffice"]:
                found = shutil.which(cmd)
                if found:
                    libreoffice_cmd = found
                    logging.info(f"Found LibreOffice in PATH: {found}")
                    break
        
        if not libreoffice_cmd:
            raise FileNotFoundError(
                "LibreOffice not found. Install with: brew install --cask libreoffice"
            )

        logging.info(f"Converting: {input_file}")

        # Run conversion
        process = subprocess.run(
            [
                libreoffice_cmd,
                "--headless",
                "--norestore",
                "--nofirststartwizard",
                "--nologo",
                "--convert-to", "pdf",
                "--outdir", output_dir,
                input_file,
            ],
            check=True,
            timeout=160,
            env=env,
            capture_output=True,
            text=True
        )
        
        logging.info(f"LibreOffice output: {process.stdout}")

        # หาไฟล์ PDF
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        expected_output = os.path.join(output_dir, base_name + ".pdf")
        
        if not os.path.exists(expected_output):
            raise RuntimeError(f"PDF not created at: {expected_output}")
        
        # ย้ายไฟล์
        if expected_output != output_file:
            shutil.move(expected_output, output_file)
        
        # Clean up
        shutil.rmtree(temp_profile, ignore_errors=True)

        logging.info(f"[OK] Office → PDF: {output_file}")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"LibreOffice failed: {e.stderr}")
        update_data_preparation_log(
            f"[Convert to PDF] - LibreOffice failed: {e.stderr}", True
        )
        return False
    except subprocess.TimeoutExpired:
        gc.collect()
        update_data_preparation_log(
            "[Convert to PDF] - Office conversion timed out.", True
        )
        return False
    except Exception as e:
        logging.exception("Office conversion error")
        update_data_preparation_log(
            f"[Convert to PDF] - Office conversion error: {repr(e)}", True
        )
        return False
    

def _convert_image_to_pdf(input_file, output_file):
    try:
        with Image.open(input_file) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            img.save(output_file, "PDF", resolution=300.0)

        logging.info(f"[OK] Image → PDF: {input_file}")
        return True

    except Exception as e:
        raise RuntimeError(f"Image conversion failed: {e}")


def download_blob_from_url(blob_url: str):
    blob_service = get_blob_service_client()
    container, blob = parse_blob_url(blob_url)

    blob_client = blob_service.get_blob_client(
        container=container,
        blob=blob
    )

    data = blob_client.download_blob().readall()
    return data, os.path.basename(blob)


def parse_blob_url(blob_url: str):
    """Parse Azure Blob URL into (container_name, blob_name)"""
    parsed = urlparse(blob_url)
    path = parsed.path.lstrip("/")
    parts = path.split("/", 1)
    
    if len(parts) != 2:
        raise ValueError("Invalid blob URL format")

    container_name = parts[0]
    blob_name = unquote(parts[1])

    return container_name, blob_name


def compress_pdf_for_ocr(input_path, output_path, max_size_mb=10):
    """Compress PDF if larger than max_size_mb"""
    try:
        file_size = os.path.getsize(input_path) / (1024 * 1024)  # MB
        
        if file_size <= max_size_mb:
            return input_path
        
        logging.info(f"PDF is {file_size:.2f}MB, compressing...")
        
        # ใช้ Ghostscript compress (ต้องติดตั้ง: brew install ghostscript)
        subprocess.run([
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={output_path}",
            input_path
        ], check=True, timeout=60)
        
        new_size = os.path.getsize(output_path) / (1024 * 1024)
        logging.info(f"Compressed: {file_size:.2f}MB -> {new_size:.2f}MB")
        
        return output_path
    except:
        logging.warning("PDF compression failed, using original")
        return input_path


def get_form_recognizer_client():
    """Form Recognizer client shared by ocr_pdf and ocr_image_bytes"""
    return DocumentAnalysisClient(
        endpoint=os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT"),
        credential=AzureKeyCredential(os.getenv("AZURE_FORM_RECOGNIZER_KEY"))
    )


def ocr_table_to_html(table):
    """Convert a Form Recognizer table to the <table> HTML used across the index"""
    html_table = "<table>\n"
    for cell in table.cells:
        if cell.row_index == 0 and cell.column_index == 0:
            html_table += "  <tr>\n"
        elif cell.column_index == 0 and cell.row_index > 0:
            html_table += "  </tr>\n  <tr>\n"

        cell_tag = "th" if cell.kind == "columnHeader" else "td"
        html_table += f"    <{cell_tag}>{cell.content}</{cell_tag}>\n"

    html_table += "  </tr>\n</table>"
    return html_table


def ocr_pdf(pdf_path):
    """OCR PDF with compression and table extraction"""
    # Compress ถ้าจำเป็น
    temp_pdf = None
    if os.path.getsize(pdf_path) > 10 * 1024 * 1024:  # > 10MB
        temp_pdf = pdf_path + ".compressed.pdf"
        pdf_path = compress_pdf_for_ocr(pdf_path, temp_pdf)

    try:
        client = get_form_recognizer_client()

        with open(pdf_path, "rb") as f:
            poller = client.begin_analyze_document(
                "prebuilt-layout",
                document=f
            )

        logging.info("⏳ Waiting for OCR to complete...")
        result = poller.result()

        # Build a map of tables by page and bounding region
        tables_by_page = {}
        if result.tables:
            logging.info(f"📊 Found {len(result.tables)} tables")
            for table in result.tables:
                page_num = table.bounding_regions[0].page_number if table.bounding_regions else 1
                if page_num not in tables_by_page:
                    tables_by_page[page_num] = []

                # Convert table to HTML format
                tables_by_page[page_num].append(ocr_table_to_html(table))

        # Extract text and insert tables at appropriate positions
        pages = []
        offset = 0
        for page in result.pages:
            # Get text from lines
            text = " ".join(line.content for line in page.lines)

            # Insert tables for this page
            if page.page_number in tables_by_page:
                for table_html in tables_by_page[page.page_number]:
                    text += "\n\n" + table_html + "\n\n"

            pages.append((page.page_number, offset, text))
            offset += len(text)

        logging.info(f"✓ OCR completed: {len(pages)} pages, {len(result.tables or [])} tables extracted")
        return pages

    finally:
        # ลบไฟล์ compressed
        if temp_pdf and os.path.exists(temp_pdf):
            os.remove(temp_pdf)


def split_text(page_map):
    """Split text into sections while tracking page numbers"""
    def find_page(offset):
        for i in range(len(page_map) - 1):
            if page_map[i][1] <= offset < page_map[i + 1][1]:
                return i
        return len(page_map) - 1

    all_text = "".join(p[2] for p in page_map)
    start = 0
    length = len(all_text)

    SENTENCE_ENDINGS = [".", "!", "?"]
    WORDS_BREAKS = [",", ";", ":", " ", "(", ")", "[", "]", "{", "}", "\t", "\n"]

    while start + SECTION_OVERLAP < length:
        last_word = -1
        end = start + MAX_SECTION_LENGTH

        if end > length:
            end = length
        else:
            # Find sentence ending
            while end < length and (end - start - MAX_SECTION_LENGTH) < SENTENCE_SEARCH_LIMIT and all_text[end] not in SENTENCE_ENDINGS:
                if all_text[end] in WORDS_BREAKS:
                    last_word = end
                end += 1

            if end < length and all_text[end] not in SENTENCE_ENDINGS and last_word > 0:
                end = last_word

        if end < length:
            end += 1

        section_text = all_text[start:end]
        page_num = find_page(start)

        yield (section_text, page_num)

        # Handle unclosed tables
        last_table_start = section_text.rfind("<table")
        if (last_table_start > 2 * SENTENCE_SEARCH_LIMIT and
            last_table_start > section_text.rfind("</table")):
            start = min(end - SECTION_OVERLAP, start + last_table_start)
        else:
            start = end - SECTION_OVERLAP

    if start + SECTION_OVERLAP < end:
        yield (all_text[start:end], find_page(start))


def build_contextual_prompt(document, chunk):
    return f"""
<document>
{document}
</document>

<chunk>
{chunk}
</chunk>

Give a short context situating this chunk within the document.
Must contain section, context, title, year.
Return only the contextualized text.
"""


def contextualize(document, chunk):
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_URL"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION")
    )

    short_doc = document[:2000]
    prompt = build_contextual_prompt(short_doc, chunk[:500])

    response = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_MODEL"),
        messages=[{"role": "system", "content": prompt}],
        temperature=0.3,
        max_tokens=200
    )
    return response.choices[0].message.content


def embed(text):
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_URL"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION")
    )

    emb = client.embeddings.create(
        model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL"),
        input=text
    )
    return emb.data[0].embedding


def index_docs(docs):
    search = SearchClient(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        index_name=os.getenv("AZURE_SEARCH_INDEX"),
        credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
    )
    search.upload_documents(docs)

def contextualize_batch(document, chunks, batch_size=5):
    """Contextualize multiple chunks in parallel"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_URL"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION")
    )
    
    short_doc = document[:2000]
    results = {}
    
    def process_chunk(index, chunk):
        try:
            prompt = build_contextual_prompt(short_doc, chunk[:500])
            response = client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_MODEL"),
                messages=[{"role": "system", "content": prompt}],
                temperature=0.3,
                max_tokens=200
            )
            return index, response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error contextualizing chunk {index}: {e}")
            return index, chunk[:100]  # fallback
    
    # Process in parallel (max 5 concurrent)
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = {
            executor.submit(process_chunk, i, chunk): i 
            for i, chunk in enumerate(chunks)
        }
        
        for future in as_completed(futures):
            idx, context = future.result()
            results[idx] = context
    
    return [results[i] for i in sorted(results.keys())]


def embed_batch(texts, batch_size=16):
    """Embed multiple texts in one API call"""
    client = AzureOpenAI(
        azure_endpoint=os.getenv("AZURE_OPENAI_URL"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION")
    )
    
    all_embeddings = []
    
    # Azure OpenAI รองรับ batch embedding
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        logging.info(f"Embedding batch {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}")
        
        response = client.embeddings.create(
            model=os.getenv("AZURE_OPENAI_EMBEDDING_MODEL"),
            input=batch
        )
        
        embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(embeddings)
    
    return all_embeddings


def sanitize_document_id(doc_id: str) -> str:
    """
    Sanitize document ID to be Azure Search compliant.
    Azure Search only allows: letters, digits, underscore (_), dash (-), equal sign (=)

    Options:
    1. URL-safe Base64 encode (preserves all characters)
    2. Replace invalid characters (simpler but may lose info)

    Using option 2 for readability
    """
    import re
    # Replace invalid characters with underscore
    # Keep only: a-z, A-Z, 0-9, _, -, =
    sanitized = re.sub(r'[^a-zA-Z0-9_\-=]', '_', doc_id)

    # Remove consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)

    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')

    return sanitized


def update_data_preparation_log(message: str, is_error: bool = False):
    if is_error:
        logging.error(message)
    else:
        logging.info(message)


def validate_pdf(path):
    if not os.path.exists(path):
        raise RuntimeError("PDF not found")

    size = os.path.getsize(path)
    if size < 1024:
        raise RuntimeError("PDF is empty or corrupted")

    with open(path, "rb") as f:
        header = f.read(4)
        if header != b"%PDF":
            raise RuntimeError("Not a valid PDF file")


# ---------- Tabular (Excel / CSV) Processing ----------
"""
Native ingestion path for spreadsheets. `.xlsx/.xlsm/.xls` and `.csv/.tsv` files
skip LibreOffice → PDF → OCR → split_text() entirely:

    file → read cells → detect layout (titles / tables / headers / notes / images)
         → Markdown (or HTML) tables → row-aware chunks → contextualize_batch
         → embed_batch → index_docs

Excel reading
  * openpyxl, opened ONCE in normal mode (read_only=False, data_only=True).
    Read-only mode exposes neither ws.merged_cells, cell styles nor ws._images, and
    all three are needed. Formulas resolve to their cached values. Only cells that
    exist in the sheet XML are scanned (ws._cells), so sheets formatted down to row
    1,048,576 do not blow up the loop.
  * `.xls` (legacy) is read with xlrd (formatting_info=True for merges + bold).
    Embedded images are not available for .xls and are skipped with a log line.
  * Hidden / veryHidden sheets are skipped. Merged cells resolve to the top-left
    anchor value (unmerge_value). Dates → ISO `YYYY-MM-DD`, whole floats lose
    their `.0`, `None` → "".
  * Layout detection per sheet (real workbooks are not "row 1 = header"):
      - band row  = one merged/lone value outside a table → sheet title, table
                    title, image caption or free-text note
      - table     = contiguous non-band rows; blank rows / bands split tables
      - header    = leading all-bold rows (max 3). Without style info: first row,
                    extended downward while a merged cell groups distinct
                    sub-columns below it (two-level headers → "Group / Sub")
      - key-value = grids with bold labels + plain values in alternating columns
                    are rendered as a 2-column Field | Value table
      - columns that are empty, or only ever the right half of a horizontal
        merge, are dropped
    Band rows that are not used as a table title or image caption are indexed as
    one "notes" chunk per sheet, so no text is lost.

CSV / TSV reading
  * Encoding: utf-8-sig / utf-8 are validated over the whole file first; then
    cp874 is accepted when it yields mostly Thai characters; then
    charset-normalizer's guess; then tis-620, latin-1. (Sniffers alone tend to
    label short cp874 samples as cp1252 → mojibake, hence the Thai check first.)
  * Delimiter: csv.Sniffer over `, ; \\t |` (.tsv → tab, fallback comma).
  * Parsed with the stdlib csv module; values stay strings ("1000" stays "1000").
    First non-empty row is the header; ragged rows are padded, extra columns are
    kept under "Column N" headers; blank rows are skipped.

Chunking (shared by Excel and CSV): chunk_excel_sheet() never splits a row,
repeats the context line + header in every chunk, carries EXCEL_ROW_OVERLAP rows
into the next chunk and emits over-long single rows as their own chunk.

Index mapping — NO schema change:
  * section   : "{sheet_name}#chunk_{i}" / "{sheet_name}#image_{n}" /
                "{sheet_name}#notes" (Excel), "{csv_basename}#chunk_{i}" (CSV).
                The sheet name lives in `section` because the index has no
                sheet field and adding one would need a schema migration.
  * page      : 1-based workbook sheet position (Excel), "1" (CSV)
  * block_type: "table" | "image" | "paragraph" (sheet notes)
  * source_file: the original filename (.xlsx/.csv kept, not renamed to .pdf)
  * id        : sanitize_document_id(f"{base}-{sheet}-{i}"). Names containing
                non-ASCII (e.g. Thai) get a short sha1 suffix first, because
                sanitize_document_id turns every Thai character into "_" and
                all Thai sheet names would otherwise collide.

Embedded images (Excel only): extracted from ws._images, falling back to the
xlsx zip (xl/media via drawing rels) when openpyxl exposes none for a sheet.
Tiny images (< EXCEL_IMAGE_MIN_PX or < EXCEL_IMAGE_MIN_BYTES) are skipped. Each
image is uploaded to `processed/images/{base}/{sheet}/{n}.{ext}`, OCR'd with the
same Form Recognizer client/model as ocr_pdf (prebuilt-layout) and indexed as a
block_type="image" chunk. The blob URL is written inside `content` (no index
field fits it). Nearby title/caption bands are attached to the image chunk.
Charts are not rasterized; they are counted and logged.

Environment flags
  EXCEL_TABLE_FORMAT          markdown (default) | html     chunk table syntax
  EXCEL_SAVE_PROCESSED_FORMAT md (default) | html | none    processed copy in
                              local processed/ + blob `processed` (Excel + CSV)
  EXCEL_IMAGE_MODE            ocr_ref (default: upload + OCR + reference)
                              | ref_only (upload + reference, no OCR) | none
  EXCEL_IMAGE_MIN_PX          40 (default) minimum image width/height
  EXCEL_ROW_OVERLAP           1 (default) data rows repeated between chunks
"""

OCR_IMAGE_FORMATS = {"png", "jpeg", "bmp", "tiff"}

_XML_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def _id_token(text, fallback="x"):
    """ID-safe token; non-ASCII names get a hash suffix so they stay unique."""
    token = sanitize_document_id(text)
    if any(ord(ch) > 127 for ch in text):
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        token = f"{token}-{digest}" if token else digest
    return token or fallback


def _has_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _format_cell_value(value, number_format=None):
    """Render a cell value as text: ISO dates, no trailing .0, None → ''."""
    if value is None:
        return ""
    is_percent = bool(number_format) and str(number_format).endswith("%")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.strftime("%Y-%m-%d")
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dtime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, float):
        if is_percent:
            return f"{value * 100:g}%"
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return f"{value * 100}%" if is_percent else str(value)
    return str(value).replace("\r\n", "\n").strip()


def build_merged_lookup(ranges, bounds):
    """
    Map every (row, col) inside a merged range to (anchor_row, anchor_col, range_id).
    ranges: iterable of (min_row, min_col, max_row, max_col), 1-based.
    Clamped to the used bounds so a sheet-wide merge does not explode memory.
    """
    min_row, min_col, max_row, max_col = bounds
    lookup = {}
    for range_id, (r1, c1, r2, c2) in enumerate(ranges):
        for r in range(max(r1, min_row), min(r2, max_row) + 1):
            for c in range(max(c1, min_col), min(c2, max_col) + 1):
                lookup[(r, c)] = (r1, c1, range_id)
    return lookup


def _anchor_cell(ws, row, col, merged_lookup):
    anchor = merged_lookup.get((row, col))
    key = (anchor[0], anchor[1]) if anchor else (row, col)
    cells = getattr(ws, "_cells", None)
    if cells is not None:
        return cells.get(key)  # does not create empty cells
    return ws.cell(*key)


def unmerge_value(ws, row, col, merged_lookup):
    """Value of (row, col); cells inside a merged range resolve to the top-left anchor value."""
    cell = _anchor_cell(ws, row, col, merged_lookup)
    return cell.value if cell is not None else None


def _grid_from_cells(read_cell, bounds, merged_lookup):
    """
    Build the neutral sheet grid used by the layout detector.
    read_cell(r, c) → (value, number_format, bold) of the (anchor) cell, or None.
    Returns a list with one entry per sheet row in bounds: None for blank rows,
    else {"row", "values", "mids" (merge id per col), "bold"}.
    """
    min_row, min_col, max_row, max_col = bounds
    grid = []
    for r in range(min_row, max_row + 1):
        values, mids, bold = [], [], []
        for c in range(min_col, max_col + 1):
            anchor = merged_lookup.get((r, c))
            info = read_cell(anchor[0], anchor[1]) if anchor else read_cell(r, c)
            value, number_format, is_bold = info if info else (None, None, False)
            values.append(_format_cell_value(value, number_format))
            mids.append(anchor[2] if anchor else None)
            bold.append(bool(is_bold))
        grid.append({"row": r, "values": values, "mids": mids, "bold": bold} if any(values) else None)
    return grid


def _openpyxl_sheet_grid(ws):
    cells = getattr(ws, "_cells", None)
    if cells is not None:
        coords = [k for k, cell in cells.items() if _has_value(cell.value)]
    else:
        coords = [(c.row, c.column) for row in ws.iter_rows() for c in row if _has_value(c.value)]
    if not coords:
        return []
    bounds = (min(r for r, _ in coords), min(c for _, c in coords),
              max(r for r, _ in coords), max(c for _, c in coords))
    ranges = [(m.min_row, m.min_col, m.max_row, m.max_col) for m in ws.merged_cells.ranges]
    merged_lookup = build_merged_lookup(ranges, bounds)

    def read_cell(r, c):
        cell = _anchor_cell(ws, r, c, {})
        if cell is None:
            return None
        return cell.value, cell.number_format, bool(cell.font is not None and cell.font.b)

    logging.info(f"    Used range R{bounds[0]}C{bounds[1]}:R{bounds[2]}C{bounds[3]}, merged ranges: {len(ranges)}")
    return _grid_from_cells(read_cell, bounds, merged_lookup)


def _xls_sheet_grid(book, sh):
    import xlrd

    empty_types = (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)
    coords = [(r + 1, c + 1) for r in range(sh.nrows) for c in range(sh.ncols)
              if sh.cell_type(r, c) not in empty_types and _has_value(sh.cell_value(r, c))]
    if not coords:
        return []
    bounds = (min(r for r, _ in coords), min(c for _, c in coords),
              max(r for r, _ in coords), max(c for _, c in coords))
    # xlrd merged_cells: (rlo, rhi, clo, chi), 0-based, half-open
    ranges = [(rlo + 1, clo + 1, rhi, chi) for rlo, rhi, clo, chi in getattr(sh, "merged_cells", [])]
    merged_lookup = build_merged_lookup(ranges, bounds)
    has_formatting = bool(getattr(book, "xf_list", None))

    def read_cell(r, c):
        r0, c0 = r - 1, c - 1
        if r0 >= sh.nrows or c0 >= sh.ncols:
            return None
        cell = sh.cell(r0, c0)
        if cell.ctype in empty_types:
            value = None
        elif cell.ctype == xlrd.XL_CELL_DATE:
            value = xlrd.xldate_as_datetime(cell.value, book.datemode)
        elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
            value = bool(cell.value)
        elif cell.ctype == xlrd.XL_CELL_ERROR:
            value = xlrd.error_text_from_code.get(cell.value, "#ERR")
        else:
            value = cell.value
        number_format, is_bold = None, False
        if has_formatting:
            xf = book.xf_list[cell.xf_index]
            is_bold = bool(book.font_list[xf.font_index].bold)
            fmt = book.format_map.get(xf.format_key)
            number_format = fmt.format_str if fmt else None
        return value, number_format, is_bold

    return _grid_from_cells(read_cell, bounds, merged_lookup)


# ----- Layout detection -----

def _row_groups(row):
    """Distinct non-empty value groups in a row (a merged range counts once)."""
    groups = []
    for j, v in enumerate(row["values"]):
        if v:
            g = row["mids"][j] if row["mids"][j] is not None else ("cell", j)
            if g not in groups:
                groups.append(g)
    return groups


def _row_text(row):
    seen, parts = set(), []
    for j, v in enumerate(row["values"]):
        g = row["mids"][j] if row["mids"][j] is not None else ("cell", j)
        if v and g not in seen:
            seen.add(g)
            parts.append(v)
    return " ".join(parts)


def _all_bold(row):
    flags = [b for v, b in zip(row["values"], row["bold"]) if v]
    return bool(flags) and all(flags)


def _is_band(row, prev_kind, width):
    """A lone value (merged or single cell) that is not part of a running table."""
    if width <= 1 or prev_kind == "table":
        return False
    return len(_row_groups(row)) == 1


def _groups_subcolumns(upper, lower, cols):
    """True when a horizontal merge in `upper` spans distinct values in `lower` (two-level header)."""
    spans = {}
    for j in cols:
        mid = upper["mids"][j]
        if mid is not None and upper["values"][j]:
            spans.setdefault(mid, []).append(j)
    for span in spans.values():
        if len(span) < 2:
            continue
        below = [lower["values"][j] for j in span if lower["values"][j]]
        below_groups = {lower["mids"][j] if lower["mids"][j] is not None else ("cell", j)
                        for j in span if lower["values"][j]}
        if len(below) >= 2 and len(below_groups) >= 2:
            return True
    return False


def flatten_header(header_rows):
    """Join stacked header rows per column ("Group / Sub"); blanks → "Column N"."""
    width = max((len(r) for r in header_rows), default=0)
    header = []
    for j in range(width):
        labels = []
        for hr in header_rows:
            label = str(hr[j]).strip() if j < len(hr) else ""
            if label and (not labels or labels[-1] != label):
                labels.append(label)
        header.append(" / ".join(labels) if labels else f"Column {j + 1}")
    return header


def _build_table(rows, title):
    """Turn contiguous grid rows into {"title", "kind", "header_rows", "rows"}."""
    width = len(rows[0]["values"])
    cols = [j for j in range(width) if any(r["values"][j] for r in rows)]
    kept = []
    for j in cols:
        if kept:
            prev = kept[-1]
            if all((r["mids"][j] is not None and r["mids"][j] == r["mids"][prev]) or not r["values"][j]
                   for r in rows):
                continue  # right half of a horizontal merge in every row → duplicate column
        kept.append(j)

    def pick(r):
        return [r["values"][j] for j in kept]

    has_style = any(any(r["bold"][j] for j in kept) for r in rows)
    bold_rows = [_all_bold({"values": pick(r), "bold": [r["bold"][j] for j in kept]}) for r in rows]

    # Key-value grid: bold labels / plain values alternating, no all-bold header row
    if has_style and not any(bold_rows) and len(kept) >= 2 and len(kept) % 2 == 0:
        is_kv = all(
            all(r["bold"][j] == (pos % 2 == 0) for pos, j in enumerate(kept) if r["values"][j])
            for r in rows
        )
        if is_kv:
            pairs = []
            for r in rows:
                vals = pick(r)
                for k in range(0, len(vals), 2):
                    if vals[k] or vals[k + 1]:
                        pairs.append([vals[k], vals[k + 1]])
            return {"title": title, "kind": "kv", "header_rows": [["Field", "Value"]], "rows": pairs}

    n_header = 0
    if has_style:
        while n_header < len(rows) and n_header < EXCEL_MAX_HEADER_ROWS and bold_rows[n_header]:
            n_header += 1
        if n_header == len(rows) and len(rows) > 1:
            n_header = 1  # everything bold → style says nothing about the header
    if n_header == 0:
        n_header = 1
        while (n_header < len(rows) - 1 and n_header < EXCEL_MAX_HEADER_ROWS
               and _groups_subcolumns(rows[n_header - 1], rows[n_header], kept)):
            n_header += 1

    return {
        "title": title,
        "kind": "table",
        "header_rows": [pick(r) for r in rows[:n_header]],
        "rows": [pick(r) for r in rows[n_header:]],
    }


def _parse_sheet_layout(sheet_name, sheet_index, grid, images):
    """Split a sheet grid into title, tables, notes and captioned images."""
    width = len(next((r for r in grid if r), {"values": []})["values"])
    items = []  # [kind, payload]: "blank" | "band" (row) | "table" (list of rows)
    prev_kind = None
    for row in grid:
        if row is None:
            items.append(["blank", None])
            prev_kind = "blank"
        elif _is_band(row, prev_kind, width):
            items.append(["band", row])
            prev_kind = "band"
        elif prev_kind == "table":
            items[-1][1].append(row)
        else:
            # A blank-row gap inside one table: continue it when the previous table
            # has a bold header and this block does not start with one.
            back = len(items) - 1
            while back >= 0 and items[back][0] == "blank":
                back -= 1
            prev = items[back] if back >= 0 else None
            if (prev and prev[0] == "table" and back < len(items) - 1
                    and _all_bold(prev[1][0]) and not _all_bold(row)
                    and {j for j, v in enumerate(row["values"]) if v}
                    <= {j for r in prev[1] for j, v in enumerate(r["values"]) if v}):
                del items[back + 1:]
                items[-1][1].append(row)
            else:
                items.append(["table", [row]])
            prev_kind = "table"

    # A lone value that ended up as a one-row "table" (e.g. one-column sheets) is text
    for item in items:
        if item[0] == "table" and len(item[1]) == 1 and len(_row_groups(item[1][0])) == 1:
            item[0], item[1] = "band", item[1][0]

    consumed = set()
    sheet_title, title_row = None, None
    first = next((it for it in items if it[0] != "blank"), None)
    if first and first[0] == "band":
        sheet_title = _row_text(first[1])
        title_row = first[1]["row"]

    tables = []
    for i, (kind, payload) in enumerate(items):
        if kind != "table":
            continue
        title = None
        if (i > 0 and items[i - 1][0] == "band" and items[i - 1][1]["row"] not in consumed
                and items[i - 1][1]["row"] != title_row):
            title = _row_text(items[i - 1][1])
            consumed.add(items[i - 1][1]["row"])
        tables.append(_build_table(payload, title))

    bands = [p for k, p in items if k == "band"]
    for img in images:
        top = img.get("from_row")
        if top is None:
            continue
        bottom = img.get("to_row") or top
        near = [b for b in bands if b["row"] not in consumed and top - 2 <= b["row"] <= bottom + 2]
        img["captions"] = [_row_text(b) for b in near]
        consumed.update(b["row"] for b in near)

    # The sheet title stays available as table context / caption, but is not a note
    notes = [_row_text(b) for b in bands if b["row"] not in consumed and b["row"] != title_row]
    return {
        "name": sheet_name,
        "index": sheet_index,
        "title": sheet_title,
        "tables": tables,
        "notes": notes,
        "images": images,
    }


# ----- Excel images -----

def _anchor_rows(anchor):
    """(from_row, to_row), 1-based, from an openpyxl drawing anchor."""
    start = getattr(anchor, "_from", None)
    end = getattr(anchor, "to", None)
    from_row = start.row + 1 if start is not None else None
    to_row = end.row + 1 if end is not None else from_row
    return from_row, to_row


def _zip_part_path(base_part, target):
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _zip_rels(zf, part):
    rels_path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if rels_path not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(rels_path))
    return {rel.get("Id"): (rel.get("Type", ""), _zip_part_path(part, rel.get("Target", "")))
            for rel in root.findall("rel:Relationship", _XML_NS)}


def _zip_images_by_sheet(path):
    """
    Fallback image extraction straight from the xlsx zip: workbook.xml → sheet
    rels → drawing → drawing rels → xl/media/*. Returns {sheet_name: [image, ...]}.
    """
    result = {}
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if not any(n.startswith("xl/media/") for n in names):
            return result
        wb_rels = _zip_rels(zf, "xl/workbook.xml")
        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        for sheet in wb_root.findall("main:sheets/main:sheet", _XML_NS):
            sheet_name = sheet.get("name")
            rid = sheet.get(f"{{{_XML_NS['r']}}}id")
            sheet_part = wb_rels.get(rid, (None, None))[1]
            if not sheet_part or sheet_part not in names:
                continue
            for rel_type, drawing_part in _zip_rels(zf, sheet_part).values():
                if not rel_type.endswith("/drawing") or drawing_part not in names:
                    continue
                drawing_rels = _zip_rels(zf, drawing_part)
                d_root = ET.fromstring(zf.read(drawing_part))
                for anchor in list(d_root):
                    blip = anchor.find(".//a:blip", _XML_NS)
                    if blip is None:
                        continue
                    media = drawing_rels.get(blip.get(f"{{{_XML_NS['r']}}}embed"), (None, None))[1]
                    if not media or media not in names:
                        continue
                    start = anchor.find("xdr:from/xdr:row", _XML_NS)
                    end = anchor.find("xdr:to/xdr:row", _XML_NS)
                    from_row = int(start.text) + 1 if start is not None else None
                    to_row = int(end.text) + 1 if end is not None else from_row
                    result.setdefault(sheet_name, []).append({
                        "data": zf.read(media),
                        "ext": posixpath.splitext(media)[1].lstrip(".").lower(),
                        "from_row": from_row,
                        "to_row": to_row,
                    })
    return result


def extract_sheet_images(ws, zip_fallback=None):
    """
    Embedded images of one worksheet: [{"index", "data", "ext", "from_row", "to_row"}].
    Uses openpyxl's ws._images; when that is empty, uses the zip fallback list
    (images openpyxl could not load, e.g. EMF/WMF) for the same sheet.
    """
    images = []
    for img in getattr(ws, "_images", []):
        try:
            data = img._data()
            from_row, to_row = _anchor_rows(img.anchor)
            images.append({"data": data, "ext": (img.format or "png").lower(),
                           "from_row": from_row, "to_row": to_row})
        except Exception as e:
            logging.warning(f"  ⚠️  Image extraction failed on sheet {ws.title}: {repr(e)}")
    if not images and zip_fallback:
        logging.info(f"  🖼️ Using zip fallback for {len(zip_fallback)} image(s) on sheet {ws.title}")
        images = [dict(img) for img in zip_fallback]
    for i, img in enumerate(images, 1):
        img["index"] = i
    return images


def _prepare_image_for_ocr(data, ext):
    """Returns (data, ext, width, height) ready for OCR/upload, or (None, reason)."""
    if len(data) < EXCEL_IMAGE_MIN_BYTES:
        return None, f"too small ({len(data)} bytes)"
    try:
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            fmt = (im.format or ext or "").lower()
            if width < EXCEL_IMAGE_MIN_PX or height < EXCEL_IMAGE_MIN_PX:
                return None, f"too small ({width}x{height}px)"
            if fmt in ("jpg", "mpo"):
                fmt = "jpeg"
            if fmt not in OCR_IMAGE_FORMATS:
                buf = io.BytesIO()
                im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(buf, "PNG")
                data, fmt = buf.getvalue(), "png"
    except Exception as e:
        return None, f"unsupported image format '{ext}': {repr(e)}"
    return (data, "jpg" if fmt == "jpeg" else fmt, width, height), None


def ocr_image_bytes(image_bytes):
    """OCR one image with the same Form Recognizer client/model as ocr_pdf."""
    client = get_form_recognizer_client()
    poller = client.begin_analyze_document("prebuilt-layout", document=image_bytes)
    result = poller.result()
    text = "\n".join(line.content for page in result.pages for line in page.lines)
    tables = [ocr_table_to_html(t) for t in (result.tables or [])]
    if tables:
        text += "\n\n" + "\n\n".join(tables)
    return text.strip()


def build_image_doc(sheet_name, sheet_index, img, image_url, ocr_text, base_token, sheet_token):
    """Index units (usually one) for an embedded image: sheet context + blob URL + OCR text."""
    head = [f"# Sheet: {sheet_name} — Embedded image {img['index']}"]
    head += [f"Caption: {c}" for c in img.get("captions", [])]
    head.append(f"(image_url: {image_url or 'unavailable'})")
    head_text = "\n".join(head)

    if EXCEL_IMAGE_MODE == "ref_only":
        bodies = [""]
    else:
        # Long OCR text (e.g. a screenshot of a big table) is split on line boundaries
        bodies, current = [], ""
        room = max(MAX_SECTION_LENGTH - len(head_text) - 10, 200)
        for line in (ocr_text or "(no text detected)").split("\n"):
            if current and len(current) + len(line) + 1 > room:
                bodies.append(current)
                current = ""
            current = f"{current}\n{line}" if current else line
        bodies.append(current)

    units = []
    for part, body in enumerate(bodies):
        suffix = "" if part == 0 else f"_part{part + 1}"
        units.append({
            "text": head_text + (f"\nOCR:\n{body}" if body else ""),
            "section": f"{sheet_name}#image_{img['index']}{suffix}",
            "block_type": "image",
            "page": str(sheet_index),
            "id_key": f"{base_token}-{sheet_token}-img-{img['index']}{suffix.replace('_', '-')}",
        })
    return units


# ----- Serialization + chunking (shared by Excel and CSV) -----

def _flat_cell(value):
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _md_line(cells):
    return "| " + " | ".join(_flat_cell(c).replace("|", "\\|") for c in cells) + " |"


def _html_line(cells, tag):
    return "  <tr>\n" + "".join(f"    <{tag}>{html_lib.escape(_flat_cell(c))}</{tag}>\n" for c in cells) + "  </tr>"


def _table_renderer(header_rows, table_format):
    """(head, row_fn, tail) so chunking and full serialization render identically."""
    header = flatten_header(header_rows)
    width = len(header)

    def fit(row):
        row = list(row[:width])
        return row + [""] * (width - len(row))

    if table_format == "html":
        return "<table>\n" + _html_line(header, "th"), (lambda r: _html_line(fit(r), "td")), "</table>"
    head = _md_line(header) + "\n" + _md_line(["---"] * width)
    return head, (lambda r: _md_line(fit(r))), ""


def _join_table(context_line, head, row_lines, tail):
    return "\n".join(p for p in [context_line, head, *row_lines, tail] if p)


def build_table_context_line(scope, name, columns, titles=()):
    """'# Sheet: {name} — {titles} — Columns: a, b, …' so every chunk is self-describing."""
    cols = ", ".join(columns[:12]) + (", …" if len(columns) > 12 else "")
    parts = [f"# {scope}: {name}"] + [t for t in titles if t] + [f"Columns: {cols}"]
    return " — ".join(parts)


def serialize_sheet_markdown(context_line, header_rows, data_rows):
    head, row_fn, tail = _table_renderer(header_rows, "markdown")
    return _join_table(context_line, head, [row_fn(r) for r in data_rows], tail)


def serialize_sheet_html(context_line, header_rows, data_rows):
    head, row_fn, tail = _table_renderer(header_rows, "html")
    return _join_table(context_line, head, [row_fn(r) for r in data_rows], tail)


def chunk_excel_sheet(context_line, header_rows, data_rows, table_format=None):
    """
    Row-aware chunking for one table: never splits a row, repeats the context
    line + header in every chunk, carries EXCEL_ROW_OVERLAP rows forward, and
    emits a single row longer than MAX_SECTION_LENGTH as its own chunk.
    Returns a list of chunk texts.
    """
    head, row_fn, tail = _table_renderer(header_rows, table_format or EXCEL_TABLE_FORMAT)
    base_len = len(_join_table(context_line, head, [], tail))
    chunks, current, current_len = [], [], base_len

    for row in data_rows:
        line = row_fn(row)
        line_len = len(line) + 1
        if current and current_len + line_len > MAX_SECTION_LENGTH:
            chunks.append(_join_table(context_line, head, current, tail))
            current = current[-EXCEL_ROW_OVERLAP:] if EXCEL_ROW_OVERLAP > 0 else []
            while current and base_len + sum(len(l) + 1 for l in current) + line_len > MAX_SECTION_LENGTH:
                current.pop(0)
            current_len = base_len + sum(len(l) + 1 for l in current)
        current.append(line)
        current_len += line_len
        if len(current) == 1 and current_len > MAX_SECTION_LENGTH:
            logging.warning(f"  ⚠️  Row longer than MAX_SECTION_LENGTH ({current_len} chars), emitted as its own chunk")
            chunks.append(_join_table(context_line, head, current, tail))
            current, current_len = [], base_len

    if current or not chunks:
        # header-only tables still produce one chunk
        chunks.append(_join_table(context_line, head, current, tail))
    return chunks


def _chunk_text_lines(context_line, lines):
    """Pack free-text lines (sheet notes) into chunks without splitting a line."""
    chunks, current = [], []
    for line in lines:
        if current and len(context_line) + sum(len(l) + 1 for l in current) + len(line) + 1 > MAX_SECTION_LENGTH:
            chunks.append("\n".join([context_line] + current))
            current = []
        current.append(line)
    if current:
        chunks.append("\n".join([context_line] + current))
    return chunks


# ----- Shared doc building / artifact -----

def _build_tabular_docs(units, full_doc, category, source_file):
    """contextualize_batch → embed_batch → index-schema docs (same fields as ingest)."""
    texts = [u["text"] for u in units]
    logging.info("🤖 Contextualizing all chunks...")
    contexts = contextualize_batch(full_doc, texts, batch_size=5)
    logging.info("📊 Embedding all chunks...")
    final_texts = [contexts[i] + "\n\n" + texts[i] for i in range(len(texts))]
    vectors = embed_batch(final_texts, batch_size=16)

    docs, seen = [], set()
    for i, unit in enumerate(units):
        doc_id = sanitize_document_id(unit["id_key"])
        if doc_id in seen:
            logging.warning(f"  ⚠️  Duplicate document id {doc_id}, adding suffix")
            doc_id = sanitize_document_id(f"{unit['id_key']}-{i}")
        seen.add(doc_id)
        docs.append({
            "id": doc_id,
            "content": final_texts[i],
            "content_vector": vectors[i],
            "section": unit["section"],
            "block_type": unit["block_type"],
            "source_file": source_file,  # keep the real extension (.xlsx / .csv)
            "page": unit["page"],
            "category": category,
            "created": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "group": [category]
        })
    del contexts, final_texts, vectors, texts
    gc.collect()
    return docs


def _bounded_full_doc(parts, limit=2000):
    """Concatenate parts until the contextualize cap is reached (avoids giant strings)."""
    out, size = [], 0
    for part in parts:
        out.append(part)
        size += len(part) + 2
        if size >= limit:
            break
    return "\n\n".join(out)[:limit]


def _save_tabular_artifact(title, sections, base_filename, temp_dir, artifact_info):
    """
    Write a human-readable .md/.html rendering (EXCEL_SAVE_PROCESSED_FORMAT) to
    local processed/ and the `processed` blob container.
    sections: [(heading, [block, ...])], block = ("text", str) |
              ("table", caption, header_rows, rows) | ("image", caption, url, ocr_text)
    """
    fmt = EXCEL_SAVE_PROCESSED_FORMAT
    if fmt not in ("md", "html"):
        logging.info("💾 Processed artifact disabled (EXCEL_SAVE_PROCESSED_FORMAT=none)")
        return
    filename = f"{base_filename}.{fmt}"
    path = os.path.join(temp_dir, filename)
    esc = html_lib.escape
    logging.info(f"💾 Saving processed copy as {fmt.upper()}...")

    with open(path, "w", encoding="utf-8") as f:
        if fmt == "html":
            f.write(f'<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>{esc(title)}</title></head><body>\n')
            f.write(f"<h1>{esc(title)}</h1>\n")
        else:
            f.write(f"# {title}\n\n")
        for heading, blocks in sections:
            f.write(f"<h2>{esc(heading)}</h2>\n" if fmt == "html" else f"## {heading}\n\n")
            for block in blocks:
                kind = block[0]
                if kind == "text":
                    f.write(f"<p>{esc(block[1])}</p>\n" if fmt == "html" else f"{block[1]}\n\n")
                elif kind == "table":
                    _, caption, header_rows, rows = block
                    if caption:
                        f.write(f"<h3>{esc(caption)}</h3>\n" if fmt == "html" else f"### {caption}\n\n")
                    head, row_fn, tail = _table_renderer(header_rows, "html" if fmt == "html" else "markdown")
                    f.write(head + "\n")
                    for row in rows:
                        f.write(row_fn(row) + "\n")
                    f.write((tail + "\n" if tail else "") + "\n")
                elif kind == "image":
                    _, caption, url, ocr_text = block
                    if fmt == "html":
                        f.write(f"<h3>{esc(caption)}</h3>\n")
                        if url:
                            f.write(f'<p><a href="{esc(url)}"><img src="{esc(url)}" style="max-width:100%"></a></p>\n')
                        if ocr_text:
                            f.write(f"<pre>{esc(ocr_text)}</pre>\n")
                    else:
                        f.write(f"### {caption}\n\n")
                        if url:
                            f.write(f"![{caption}]({url})\n\n")
                        if ocr_text:
                            f.write(f"OCR:\n\n```\n{ocr_text}\n```\n\n")
        if fmt == "html":
            f.write("</body></html>\n")

    artifact_info["filename"] = filename
    artifact_info["local_path"] = save_to_local_processed(path, filename)
    artifact_info["blob_url"] = upload_to_blob(path, "processed", filename)


# ----- Excel -----

def read_excel_sheets(file_path, include_images=True):
    """
    Read every visible worksheet into a layout-parsed sheet dict:
    {"name", "index" (1-based workbook position), "title", "tables", "notes", "images"}.
    """
    ext = os.path.splitext(file_path)[1].lower()
    sheets, visible = [], 0

    if ext == ".xls":
        import xlrd
        try:
            book = xlrd.open_workbook(file_path, formatting_info=True)
        except Exception as e:
            logging.warning(f"  ⚠️  .xls formatting info unavailable ({repr(e)}), reading values only")
            book = xlrd.open_workbook(file_path)
        if include_images:
            logging.info("  🖼️ Embedded images are not extracted from legacy .xls files")
        for index, sh in enumerate(book.sheets(), 1):
            if sh.visibility != 0:
                logging.info(f"  📋 Skipping hidden sheet: {sh.name}")
                continue
            visible += 1
            logging.info(f"  📗 Reading sheet: {sh.name}")
            sheets.append(_parse_sheet_layout(sh.name, index, _xls_sheet_grid(book, sh), []))
    else:
        import openpyxl
        # Normal (non read-only) mode: needed for merged_cells, fonts and ws._images
        wb = openpyxl.load_workbook(file_path, read_only=False, data_only=True)
        zip_images = None
        try:
            with zipfile.ZipFile(file_path) as zf:
                charts = [n for n in zf.namelist() if n.startswith("xl/charts/chart")]
            if charts:
                logging.info(f"  📉 {len(charts)} chart(s) in workbook — charts are not rasterized, skipped")
        except zipfile.BadZipFile:
            pass

        for index, ws in enumerate(wb.worksheets, 1):
            if ws.sheet_state != "visible":
                logging.info(f"  📋 Skipping {ws.sheet_state} sheet: {ws.title}")
                continue
            visible += 1
            logging.info(f"  📗 Reading sheet: {ws.title}")
            grid = _openpyxl_sheet_grid(ws)

            images = []
            if include_images:
                fallback = None
                if not getattr(ws, "_images", None):
                    if zip_images is None:
                        try:
                            zip_images = _zip_images_by_sheet(file_path)
                        except Exception as e:
                            logging.warning(f"  ⚠️  Zip image fallback failed: {repr(e)}")
                            zip_images = {}
                    fallback = zip_images.get(ws.title)
                images = extract_sheet_images(ws, fallback)

            sheets.append(_parse_sheet_layout(ws.title, index, grid, images))
        wb.close()

    if visible == 0:
        raise RuntimeError("No visible sheets")

    for s in sheets:
        logging.info(f"    {s['name']}: {len(s['tables'])} table(s), "
                     f"{sum(len(t['rows']) for t in s['tables'])} data row(s), "
                     f"{len(s['notes'])} note line(s), {len(s['images'])} image(s)")
        for t in s["tables"]:
            if not t["rows"]:
                logging.info(f"    ℹ️  Table '{t['title'] or '-'}' on {s['name']} has only a header, indexing it as one chunk")
    return sheets


def process_excel(input_path, category, original_filename, temp_dir=None, artifact_info=None):
    """
    Native Excel ingestion (no PDF / OCR of the sheet itself). Returns index docs:
    table chunks, one notes chunk per sheet with free text, and one chunk per
    embedded image. See the section docstring for metadata mapping and flags.
    """
    temp_dir = temp_dir or os.path.dirname(input_path)
    artifact_info = artifact_info if artifact_info is not None else {}
    try:
        logging.info(f"📗 Reading Excel {original_filename} ...")
        sheets = read_excel_sheets(input_path, include_images=EXCEL_IMAGE_MODE != "none")

        base_filename = os.path.splitext(original_filename)[0]
        base_token = _id_token(base_filename, "workbook")
        units, outline, sections = [], [f"Workbook: {original_filename}"], []
        ocr_cache = {}
        image_count = 0

        for sheet in sheets:
            name, index = sheet["name"], sheet["index"]
            sheet_token = _id_token(name, f"sheet{index}")
            page = str(index)
            blocks = []
            outline.append(f"- Sheet {index} '{name}'" + (f": {sheet['title']}" if sheet["title"] else ""))

            # Free text (title, subtitle, notes) → one paragraph chunk
            notes = ([sheet["title"]] if sheet["title"] else []) + sheet["notes"]
            if notes:
                blocks.append(("text", "\n".join(notes)))
            if sheet["notes"]:
                for k, text in enumerate(_chunk_text_lines(f"# Sheet: {name} — Notes", notes)):
                    units.append({"text": text, "section": f"{name}#notes" + (f"_{k + 1}" if k else ""),
                                  "block_type": "paragraph", "page": page,
                                  "id_key": f"{base_token}-{sheet_token}-notes-{k}"})

            chunk_i = 0
            for table in sheet["tables"]:
                columns = flatten_header(table["header_rows"])
                outline.append(f"  • {table['title'] or 'table'}: {', '.join(columns[:8])}")
                context_line = build_table_context_line("Sheet", name, columns, (sheet["title"], table["title"]))
                for text in chunk_excel_sheet(context_line, table["header_rows"], table["rows"]):
                    units.append({"text": text, "section": f"{name}#chunk_{chunk_i}",
                                  "block_type": "table", "page": page,
                                  "id_key": f"{base_token}-{sheet_token}-{chunk_i}"})
                    chunk_i += 1
                blocks.append(("table", table["title"], table["header_rows"], table["rows"]))

            ocr_done = 0
            for img in sheet["images"]:
                prepared, reason = _prepare_image_for_ocr(img["data"], img["ext"])
                if prepared is None:
                    logging.info(f"  🖼️ Skipping image {img['index']} on {name}: {reason}")
                    continue
                data, ext, width, height = prepared
                img_path = os.path.join(temp_dir, f"img_{index}_{img['index']}.{ext}")
                with open(img_path, "wb") as f:
                    f.write(data)
                image_url = upload_to_blob(img_path, "processed", f"images/{base_filename}/{name}/{img['index']}.{ext}")
                if not image_url:
                    logging.warning(f"  ⚠️  Upload failed for image {img['index']} on {name}, indexing without URL")

                ocr_text = ""
                if EXCEL_IMAGE_MODE == "ocr_ref":
                    digest = hashlib.sha1(data).hexdigest()
                    if digest not in ocr_cache:
                        try:
                            logging.info(f"  🔍 OCR image {img['index']} on {name} ({width}x{height}px)")
                            ocr_cache[digest] = ocr_image_bytes(data)
                        except Exception as e:
                            logging.warning(f"  ⚠️  OCR failed for image {img['index']} on {name}: {repr(e)}")
                            ocr_cache[digest] = None
                    if ocr_cache[digest] is not None:
                        ocr_done += 1
                    ocr_text = ocr_cache[digest] or ""

                units.extend(build_image_doc(name, index, img, image_url, ocr_text, base_token, sheet_token))
                caption = f"Embedded image {img['index']}" + (f" — {img['captions'][0]}" if img.get("captions") else "")
                blocks.append(("image", caption, image_url, ocr_text))
                image_count += 1
                img["data"] = None  # free memory early
            if sheet["images"]:
                logging.info(f"🖼️ Extracted {len(sheet['images'])} image(s) from sheet {name}, OCR'd {ocr_done}")

            sections.append((f"Sheet: {name}", blocks))

        if not units:
            raise RuntimeError("No content extracted from workbook")
        logging.info(f"✂️  Created {len(units)} chunks ({image_count} image chunk source(s))")

        full_doc = _bounded_full_doc(["\n".join(outline)] + [u["text"] for u in units])
        docs = _build_tabular_docs(units, full_doc, category, original_filename)
        _save_tabular_artifact(original_filename, sections, base_filename, temp_dir, artifact_info)

        logging.info(f"✅ Excel processing complete: {len(docs)} documents created")
        return docs

    except Exception as e:
        logging.exception("❌ Excel processing failed")
        update_data_preparation_log(f"[Excel Processing] - Failed: {repr(e)}", True)
        raise RuntimeError(f"Excel processing failed: {e}") from e
    finally:
        gc.collect()


# ----- CSV -----

def _decodes_cleanly(path, encoding):
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                decoder.decode(block)
        decoder.decode(b"", final=True)
        return True
    except (UnicodeDecodeError, LookupError):
        return False


def detect_csv_encoding(path):
    """utf-8-sig/utf-8 → cp874 (if mostly Thai) → charset-normalizer → tis-620 → latin-1."""
    with open(path, "rb") as f:
        sample = f.read(1 << 20)

    if _decodes_cleanly(path, "utf-8"):
        return "utf-8-sig" if sample.startswith(codecs.BOM_UTF8) else "utf-8"

    if _decodes_cleanly(path, "cp874"):
        text = sample.decode("cp874", errors="ignore")
        non_ascii = [ch for ch in text if ord(ch) > 127]
        thai = sum(1 for ch in non_ascii if "฀" <= ch <= "๿")
        if non_ascii and thai / len(non_ascii) >= 0.5:
            return "cp874"

    try:
        from charset_normalizer import from_bytes
        best = from_bytes(sample).best()
        if best and best.encoding and _decodes_cleanly(path, best.encoding):
            return best.encoding
    except ImportError:
        pass

    for encoding in ("tis-620", "latin-1"):
        if _decodes_cleanly(path, encoding):
            return encoding
    return "latin-1"


def read_csv_rows(path):
    """
    Parse a CSV/TSV with detected encoding + delimiter.
    Returns (header_rows, data_rows) in the same shape as Excel tables.
    """
    name = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    encoding = detect_csv_encoding(path)

    with open(path, encoding=encoding, newline="") as f:
        sample = f.read(64 * 1024)
    if ext == ".tsv":
        delimiter = "\t"
    else:
        sniff_text = sample[:sample.rfind("\n")] if "\n" in sample else sample
        try:
            delimiter = csv.Sniffer().sniff(sniff_text, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","

    csv.field_size_limit(16 * 1024 * 1024)
    header, rows, ragged = None, [], 0
    with open(path, encoding=encoding, newline="") as f:
        for record in csv.reader(f, delimiter=delimiter):
            cells = [c.strip() for c in record]
            if not any(cells):
                continue
            if header is None:
                header = cells
                continue
            if len(cells) != len(header):
                ragged += 1
            rows.append(cells)

    if header is None:
        raise RuntimeError("Empty CSV")

    width = max([len(header)] + [len(r) for r in rows])
    header = header + [""] * (width - len(header))
    # drop unnamed columns that are empty everywhere (e.g. trailing delimiters)
    keep = [j for j in range(width) if header[j] or any(j < len(r) and r[j] for r in rows)]
    if len(keep) < width:
        header = [header[j] for j in keep]
        rows = [[r[j] if j < len(r) else "" for j in keep] for r in rows]
    header = [h or f"Column {j + 1}" for j, h in enumerate(header)]
    if ragged:
        logging.warning(f"  ⚠️  CSV {name}: {ragged} row(s) with a column count different from the header "
                        f"({len(header)} columns kept; short rows padded)")

    logging.info(f"📄 CSV {name}: {len(rows)} rows, enc={encoding}, delim={delimiter!r}")
    return [header], rows


def process_csv(path, category, original_filename, temp_dir=None, artifact_info=None):
    """Native CSV/TSV ingestion: one logical sheet named after the file, same chunker as Excel."""
    temp_dir = temp_dir or os.path.dirname(path)
    artifact_info = artifact_info if artifact_info is not None else {}
    try:
        logging.info(f"📄 Reading CSV {original_filename} ...")
        header_rows, rows = read_csv_rows(path)
        if not rows:
            logging.info("  ℹ️  CSV has only a header row, indexing it as one chunk")

        csv_basename = os.path.splitext(original_filename)[0]
        base_token = _id_token(csv_basename, "csv")
        context_line = build_table_context_line("File", original_filename, flatten_header(header_rows))
        units = [{"text": text, "section": f"{csv_basename}#chunk_{i}", "block_type": "table",
                  "page": "1", "id_key": f"{base_token}-{i}"}
                 for i, text in enumerate(chunk_excel_sheet(context_line, header_rows, rows))]
        logging.info(f"✂️  Created {len(units)} chunks")

        docs = _build_tabular_docs(units, _bounded_full_doc(u["text"] for u in units), category, original_filename)
        _save_tabular_artifact(original_filename, [(f"File: {original_filename}", [("table", None, header_rows, rows)])],
                               csv_basename, temp_dir, artifact_info)

        logging.info(f"✅ CSV processing complete: {len(docs)} documents created")
        return docs

    except Exception as e:
        logging.exception("❌ CSV processing failed")
        update_data_preparation_log(f"[CSV Processing] - Failed: {repr(e)}", True)
        raise RuntimeError(f"CSV processing failed: {e}") from e
    finally:
        gc.collect()


def _ingest_tabular(input_path, ext, category, original_filename, temp_dir):
    """Excel/CSV branch of ingest: same response shape, no PDF conversion or OCR."""
    artifact_info = {}
    if ext in EXCEL_EXTS:
        file_type = "excel"
        docs = process_excel(input_path, category, original_filename, temp_dir, artifact_info)
    else:
        file_type = "csv"
        docs = process_csv(input_path, category, original_filename, temp_dir, artifact_info)

    if not docs:
        raise RuntimeError("No documents created for indexing")

    # Batched: an index upload is capped at 1000 docs / 16MB and big sheets can exceed that
    logging.info(f"📊 Indexing {len(docs)} documents...")
    for i in range(0, len(docs), TABULAR_INDEX_BATCH_SIZE):
        index_docs(docs[i:i + TABULAR_INDEX_BATCH_SIZE])

    block_types = {}
    for d in docs:
        block_types[d["block_type"]] = block_types.get(d["block_type"], 0) + 1
    logging.info("✅ Completed successfully")

    return func.HttpResponse(
        json.dumps({
            "status": "success",
            "chunks": len(docs),
            "filename": original_filename,
            "pdf_filename": None,  # tabular files are not converted to PDF
            "local_path": artifact_info.get("local_path"),
            "blob_url": artifact_info.get("blob_url"),
            "processed_filename": artifact_info.get("filename"),
            "file_type": file_type,
            "block_types": block_types
        }),
        status_code=200,
        mimetype="application/json"
    )


# ---------- Azure Function ----------
@app.route(route="ingest", auth_level=func.AuthLevel.ANONYMOUS)  # เปลี่ยนจาก FUNCTION
def ingest(req: func.HttpRequest) -> func.HttpResponse:
# @app.route(route="ingest")
# def ingest(req: func.HttpRequest) -> func.HttpResponse:
    temp_dir = None
    
    try:
        body = req.get_json()
        blob_url = body["blob_url"]
        category = body.get("category", "general")

        temp_dir = tempfile.mkdtemp(prefix="ingest_")
        logging.info(f"📁 Created temp directory: {temp_dir}")
        
        # Download and convert (existing code)
        file_bytes, filename = download_blob_from_url(blob_url)
        original_filename = filename
        logging.info(f"⬇️  Downloaded: {filename} ({len(file_bytes)} bytes)")
        
        input_path = os.path.join(temp_dir, filename)
        with open(input_path, "wb") as f:
            f.write(file_bytes)
        
        del file_bytes
        gc.collect()

        ext = os.path.splitext(filename)[1].lower()

        # Excel / CSV: native tabular path, skips PDF conversion + OCR + split_text
        if ext in EXCEL_EXTS or ext in CSV_EXTS:
            return _ingest_tabular(input_path, ext, category, original_filename, temp_dir)

        pdf_filename = os.path.splitext(filename)[0] + ".pdf"
        
        if ext == ".pdf":
            pdf_path = input_path
            pdf_filename = filename
        else:
            pdf_path = os.path.join(temp_dir, pdf_filename)
            logging.info(f"🔄 Converting {ext} to PDF...")
            success = convert_to_pdf(input_path, pdf_path)
            if not success:
                raise RuntimeError("File conversion to PDF failed")
            logging.info(f"✓ Conversion successful")

        validate_pdf(pdf_path)
        
        # Save processed
        local_saved_path = save_to_local_processed(pdf_path, pdf_filename)
        blob_pdf_url = upload_to_blob(pdf_path, "processed", pdf_filename)

        # OCR
        logging.info("🔍 Starting OCR...")
        pages = ocr_pdf(pdf_path)
        
        if not pages:
            raise RuntimeError("No text extracted from PDF")

        # Create chunks with page tracking
        logging.info("✂️  Creating chunks...")
        full_doc = "".join(p[2] for p in pages)
        sections_with_pages = list(split_text(pages))  # Returns [(text, page_num), ...]
        logging.info(f"Created {len(sections_with_pages)} sections")

        # Extract texts and page numbers
        chunks = [section[0] for section in sections_with_pages]
        page_numbers = [section[1] for section in sections_with_pages]

        del pages
        gc.collect()

        # ===== ใช้ BATCH PROCESSING =====
        logging.info("🤖 Contextualizing all chunks...")
        contexts = contextualize_batch(full_doc, chunks, batch_size=5)

        logging.info("📊 Embedding all chunks...")
        final_texts = [contexts[i] + "\n\n" + chunks[i] for i in range(len(chunks))]
        vectors = embed_batch(final_texts, batch_size=16)

        # Build documents matching Azure index structure
        docs = []
        base_filename = os.path.splitext(pdf_filename)[0]

        for i in range(len(chunks)):
            # Page reference is just the page number (1-indexed)
            page_ref = str(page_numbers[i] + 1)

            # Sanitize document ID for Azure Search
            doc_id = sanitize_document_id(f"{base_filename}-{i}")

            # Determine block type based on content
            content_text = chunks[i]
            if "<table" in content_text.lower() and "</table>" in content_text.lower():
                block_type = "table"
            elif content_text.startswith("#") or len(content_text) < 100:
                # Short text might be heading
                block_type = "heading"
            else:
                block_type = "paragraph"

            docs.append({
                "id": doc_id,
                "content": final_texts[i],
                "content_vector": vectors[i],
                "section": f"section_{i}",
                "block_type": block_type,  # Dynamic based on content type
                "source_file": pdf_filename,  # Use PDF filename, not original
                "page": page_ref,  # Just the page number
                "category": category,
                "created": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                "group": [category]  # StringCollection field
            })

        del contexts, final_texts, vectors, chunks, sections_with_pages, page_numbers
        gc.collect()

        if not docs:
            raise RuntimeError("No documents created for indexing")

        # Index documents
        logging.info(f"📊 Indexing {len(docs)} documents...")
        index_docs(docs)

        logging.info("✅ Completed successfully")

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "chunks": len(docs),
                "filename": original_filename,
                "pdf_filename": pdf_filename,
                "local_path": local_saved_path,
                "blob_url": blob_pdf_url
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("❌ Error occurred")
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "message": str(e)
            }),
            status_code=500,
            mimetype="application/json"
        )
    
    finally:
        if temp_dir and os.path.exists(temp_dir):
            logging.info(f"🧹 Cleaning up temp: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)
        gc.collect()


# ---------- Delete Routes ----------
@app.route(route="delete_by_id", auth_level=func.AuthLevel.ANONYMOUS)
def delete_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Delete document by ID"""
    try:
        body = req.get_json()
        doc_id = body.get("doc_id")

        if not doc_id:
            return func.HttpResponse(
                json.dumps({"error": "doc_id is required"}),
                status_code=400,
                mimetype="application/json"
            )

        logging.info(f"🗑️  Deleting document with ID: {doc_id}")

        search_client = SearchClient(
            endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
            index_name=os.getenv("AZURE_SEARCH_INDEX"),
            credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
        )

        # Delete by document ID
        result = search_client.delete_documents(documents=[{"id": doc_id}])

        if result and len(result) > 0:
            logging.info(f"✓ Deleted document: {doc_id}")
            return func.HttpResponse(
                json.dumps({
                    "status": "success",
                    "deleted": 1,
                    "doc_id": doc_id
                }),
                status_code=200,
                mimetype="application/json"
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "message": f"Document with ID '{doc_id}' not found"
                }),
                status_code=404,
                mimetype="application/json"
            )

    except Exception as e:
        logging.exception("❌ Delete by ID failed")
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "message": str(e)
            }),
            status_code=500,
            mimetype="application/json"
        )
    finally:
        gc.collect()


@app.route(route="delete_by_source", auth_level=func.AuthLevel.ANONYMOUS)
def delete_by_source(req: func.HttpRequest) -> func.HttpResponse:
    """Delete all documents from a source file"""
    try:
        body = req.get_json()
        source_file = body.get("source_file")

        if not source_file:
            return func.HttpResponse(
                json.dumps({"error": "source_file is required"}),
                status_code=400,
                mimetype="application/json"
            )

        logging.info(f"🗑️  Deleting all documents from source: {source_file}")

        search_client = SearchClient(
            endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
            index_name=os.getenv("AZURE_SEARCH_INDEX"),
            credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
        )

        deleted_total = 0

        # Delete in batches
        while True:
            # Search for documents with this source_file
            filter_expr = f"source_file eq '{source_file}'"
            results = search_client.search(
                "",
                filter=filter_expr,
                top=1000,
                include_total_count=True
            )

            count = results.get_count()
            if count == 0:
                break

            # Delete batch
            docs_to_delete = [{"id": d["id"]} for d in results]
            result = search_client.delete_documents(documents=docs_to_delete)
            deleted_total += len(result)

            logging.info(f"  Deleted {len(result)} documents")

            # Small delay to let index update
            import time
            time.sleep(1)

        logging.info(f"✓ Deleted {deleted_total} documents from {source_file}")

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "deleted": deleted_total,
                "source_file": source_file
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("❌ Delete by source failed")
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "message": str(e)
            }),
            status_code=500,
            mimetype="application/json"
        )
    finally:
        gc.collect()


@app.route(route="delete_all", auth_level=func.AuthLevel.ANONYMOUS)
def delete_all(req: func.HttpRequest) -> func.HttpResponse:
    """Delete ALL documents from the index (use with caution!)"""
    try:
        body = req.get_json()
        confirm = body.get("confirm", False)

        if not confirm:
            return func.HttpResponse(
                json.dumps({
                    "error": "Must set 'confirm': true to delete all documents"
                }),
                status_code=400,
                mimetype="application/json"
            )

        logging.warning("⚠️  DELETING ALL DOCUMENTS FROM INDEX!")

        search_client = SearchClient(
            endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
            index_name=os.getenv("AZURE_SEARCH_INDEX"),
            credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
        )

        deleted_total = 0

        # Delete in batches
        while True:
            # Get all documents
            results = search_client.search("*", top=1000, include_total_count=True)

            count = results.get_count()
            if count == 0:
                break

            # Delete batch
            docs_to_delete = [{"id": d["id"]} for d in results]
            result = search_client.delete_documents(documents=docs_to_delete)
            deleted_total += len(result)

            logging.info(f"  Deleted {len(result)} documents")

            # Small delay to let index update
            import time
            time.sleep(1)

        logging.info(f"✓ Deleted ALL {deleted_total} documents from index")

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "deleted": deleted_total,
                "message": "All documents deleted"
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("❌ Delete all failed")
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "message": str(e)
            }),
            status_code=500,
            mimetype="application/json"
        )
    finally:
        gc.collect()