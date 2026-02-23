import azure.functions as func
import logging
import os
import json
import io
import subprocess
import gc
import tempfile
import shutil
from PIL import Image
from datetime import datetime, timezone

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


def ocr_pdf(pdf_path):
    """OCR PDF with compression and table extraction"""
    # Compress ถ้าจำเป็น
    temp_pdf = None
    if os.path.getsize(pdf_path) > 10 * 1024 * 1024:  # > 10MB
        temp_pdf = pdf_path + ".compressed.pdf"
        pdf_path = compress_pdf_for_ocr(pdf_path, temp_pdf)

    try:
        client = DocumentAnalysisClient(
            endpoint=os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT"),
            credential=AzureKeyCredential(os.getenv("AZURE_FORM_RECOGNIZER_KEY"))
        )

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
                html_table = "<table>\n"
                for cell in table.cells:
                    if cell.row_index == 0 and cell.column_index == 0:
                        html_table += "  <tr>\n"
                    elif cell.column_index == 0 and cell.row_index > 0:
                        html_table += "  </tr>\n  <tr>\n"

                    cell_tag = "th" if cell.kind == "columnHeader" else "td"
                    html_table += f"    <{cell_tag}>{cell.content}</{cell_tag}>\n"

                html_table += "  </tr>\n</table>"
                tables_by_page[page_num].append(html_table)

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