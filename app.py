from flask import Flask, request, jsonify
import logging
import os
import re
import html
import io
import tempfile
import shutil
import gc
import subprocess
from pathlib import Path
from typing import List, Tuple, Generator
from datetime import datetime

from pypdf import PdfReader, PdfWriter
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from openai import AzureOpenAI

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)

# ========== Constants ==========
MAX_SECTION_LENGTH = 1000
SENTENCE_SEARCH_LIMIT = 100
SECTION_OVERLAP = 100

SENTENCE_ENDINGS = [".", "!", "?"]
WORDS_BREAKS = [",", ";", ":", " ", "(", ")", "[", "]", "{", "}", "\t", "\n"]

OFFICE_EXTS = {".docx", ".doc", ".pptx", ".ppt"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}

# ========== Helper Functions ==========

def force_cleanup():
    """Force garbage collection"""
    gc.collect()
    gc.collect()

def log_memory():
    """Log memory usage"""
    try:
        import psutil
        mem = psutil.Process().memory_info().rss / 1024 / 1024
        logging.info(f"💾 Memory: {mem:.2f} MB")
    except:
        pass

def get_blob_service_client():
    """Get Blob Service Client"""
    return BlobServiceClient(
        account_url=f"https://{os.getenv('AZURE_STORAGE_ACCOUNT_NAME')}.blob.core.windows.net",
        credential=os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    )

def parse_blob_url(blob_url: str) -> Tuple[str, str]:
    """Parse blob URL"""
    from urllib.parse import urlparse, unquote
    parsed = urlparse(blob_url)
    path = parsed.path.lstrip("/")
    parts = path.split("/", 1)
    
    if len(parts) != 2:
        raise ValueError("Invalid blob URL")
    
    return parts[0], unquote(parts[1])

def download_blob(blob_url: str, local_path: str) -> bool:
    """Download file from blob"""
    try:
        blob_service = get_blob_service_client()
        container, blob_name = parse_blob_url(blob_url)
        
        blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
        
        os.makedirs(Path(local_path).parent, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(blob_client.download_blob().readall())
        
        logging.info(f"✓ Downloaded: {blob_name}")
        return True
    except Exception as e:
        logging.error(f"Download failed: {e}")
        return False

def upload_blob_pages(filename: str, temp_dir: str) -> bool:
    """Upload PDF pages as separate blobs"""
    try:
        blob_service = get_blob_service_client()
        container_name = os.getenv("AZURE_BLOB_CONTAINER", "processed")
        blob_container = blob_service.get_container_client(container_name)
        
        if not blob_container.exists():
            blob_container.create_container()
        
        # Split PDF and upload each page
        reader = PdfReader(filename)
        pages = reader.pages
        
        for i in range(len(pages)):
            blob_name = blob_name_from_file_page(filename, i+1)
            logging.info(f"  Uploading page {i+1} -> {blob_name}")
            
            f = io.BytesIO()
            writer = PdfWriter()
            writer.add_page(pages[i])
            writer.write(f)
            f.seek(0)
            
            blob_container.upload_blob(blob_name, f, overwrite=True)
            
            # Cleanup
            del f, writer
            force_cleanup()
        
        del reader, pages
        force_cleanup()
        
        return True
    except Exception as e:
        logging.error(f"Blob upload failed: {e}")
        return False

def blob_name_from_file_page(filename: str, page: int = 0) -> str:
    """Generate blob name from filename and page"""
    basename = os.path.basename(filename)
    if Path(filename).suffix.lower() == ".pdf":
        return Path(basename).stem + f"-{page}.pdf"
    return basename

def convert_to_pdf(input_file: str, output_file: str) -> bool:
    """Convert Office files to PDF using LibreOffice"""
    try:
        env = os.environ.copy()
        temp_profile = tempfile.mkdtemp(prefix="libreoffice_")
        
        try:
            env["HOME"] = temp_profile
            
            output_dir = Path(output_file).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            import platform
            if platform.system() == "Darwin":
                libreoffice_cmd = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
            else:
                libreoffice_cmd = "libreoffice"
            
            if not Path(libreoffice_cmd).exists():
                libreoffice_cmd = shutil.which("libreoffice") or shutil.which("soffice")
                if not libreoffice_cmd:
                    raise FileNotFoundError("LibreOffice not found")
            
            subprocess.run(
                [
                    libreoffice_cmd,
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(output_dir),
                    input_file,
                ],
                check=True,
                timeout=160,
                env=env,
                capture_output=True
            )
            
            expected = output_dir / (Path(input_file).stem + ".pdf")
            if expected.exists() and expected != Path(output_file):
                shutil.move(str(expected), output_file)
            
            return Path(output_file).exists()
            
        finally:
            shutil.rmtree(temp_profile, ignore_errors=True)
        
    except Exception as e:
        logging.error(f"Conversion failed: {e}")
        return False

def table_to_html(table) -> str:
    """Convert Form Recognizer table to HTML"""
    table_html = "<table>"
    rows = [
        sorted([cell for cell in table.cells if cell.row_index == i], 
               key=lambda cell: cell.column_index) 
        for i in range(table.row_count)
    ]
    for row_cells in rows:
        table_html += "<tr>"
        for cell in row_cells:
            tag = "th" if (cell.kind == "columnHeader" or cell.kind == "rowHeader") else "td"
            cell_spans = ""
            if cell.column_span > 1:
                cell_spans += f" colSpan={cell.column_span}"
            if cell.row_span > 1:
                cell_spans += f" rowSpan={cell.row_span}"
            table_html += f"<{tag}{cell_spans}>{html.escape(cell.content)}</{tag}>"
        table_html += "</tr>"
    table_html += "</table>"
    return table_html

def get_document_text(filename: str, use_local_parser: bool = False) -> List[Tuple[int, int, str]]:
    """Extract text from PDF using Form Recognizer or local parser"""
    offset = 0
    page_map = []
    
    if use_local_parser:
        logging.info("Using local PDF parser")
        reader = PdfReader(filename)
        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            page_map.append((page_num, offset, page_text))
            offset += len(page_text)
        del reader
    else:
        logging.info("Using Azure Form Recognizer")
        client = DocumentAnalysisClient(
            endpoint=os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT"),
            credential=AzureKeyCredential(os.getenv("AZURE_FORM_RECOGNIZER_KEY"))
        )
        
        with open(filename, "rb") as f:
            poller = client.begin_analyze_document("prebuilt-layout", document=f)
        
        form_recognizer_results = poller.result()
        
        for page_num, page in enumerate(form_recognizer_results.pages):
            tables_on_page = [
                table for table in form_recognizer_results.tables 
                if table.bounding_regions[0].page_number == page_num + 1
            ]
            
            # Mark table positions
            page_offset = page.spans[0].offset
            page_length = page.spans[0].length
            table_chars = [-1] * page_length
            
            for table_id, table in enumerate(tables_on_page):
                for span in table.spans:
                    for i in range(span.length):
                        idx = span.offset - page_offset + i
                        if 0 <= idx < page_length:
                            table_chars[idx] = table_id
            
            # Build page text
            page_text = ""
            added_tables = set()
            for idx, table_id in enumerate(table_chars):
                if table_id == -1:
                    page_text += form_recognizer_results.content[page_offset + idx]
                elif table_id not in added_tables:
                    page_text += table_to_html(tables_on_page[table_id])
                    added_tables.add(table_id)
            
            page_text += " "
            page_map.append((page_num, offset, page_text))
            offset += len(page_text)
        
        del form_recognizer_results, poller, client
    
    force_cleanup()
    return page_map

def split_text(page_map: List[Tuple[int, int, str]]) -> Generator[Tuple[str, int], None, None]:
    """Split text into sections with smart boundary detection"""
    
    def find_page(offset):
        for i in range(len(page_map) - 1):
            if page_map[i][1] <= offset < page_map[i + 1][1]:
                return i
        return len(page_map) - 1
    
    all_text = "".join(p[2] for p in page_map)
    length = len(all_text)
    start = 0
    
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
        
        # Find word boundary at start
        last_word = -1
        while start > 0 and start > end - MAX_SECTION_LENGTH - 2 * SENTENCE_SEARCH_LIMIT and all_text[start] not in SENTENCE_ENDINGS:
            if all_text[start] in WORDS_BREAKS:
                last_word = start
            start -= 1
        
        if all_text[start] not in SENTENCE_ENDINGS and last_word > 0:
            start = last_word
        
        if start > 0:
            start += 1
        
        section_text = all_text[start:end]
        yield (section_text, find_page(start))
        
        # Handle unclosed tables
        last_table_start = section_text.rfind("<table")
        if (last_table_start > 2 * SENTENCE_SEARCH_LIMIT and 
            last_table_start > section_text.rfind("</table")):
            start = min(end - SECTION_OVERLAP, start + last_table_start)
        else:
            start = end - SECTION_OVERLAP
    
    if start + SECTION_OVERLAP < end:
        yield (all_text[start:end], find_page(start))

def build_contextual_prompt(document: str, chunk: str) -> str:
    """Build contextual prompt for enrichment"""
    return f"""
    <document> 
    {document} 
    </document> 
    Here is the chunk we want to situate within the whole document 
    <chunk> 
    {chunk}
    </chunk> 
    1. Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk.
    2. Return the document's language.
    3. Please keep every context and word from each chunk; just add whole-document context into this chunk.
    4. Answer only with the succinct context and nothing else.
    5. Must contain section, context, title, year.

    Example:
    This Chunk is part of 'xxx' section, the context is about 'xxx' and title of this document is 'xxx', in year 'xxx, here is the chunk 'xxx' (include topic of that paragraph that chunk included)
    """

def contextualize_chunk(full_document: str, chunk: str) -> str:
    """Add context to chunk using OpenAI"""
    client = None
    try:
        client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_URL"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("OPENAI_API_VERSION")
        )
        
        # Limit document context to first 4000 chars
        doc_context = full_document[:4000]
        prompt = build_contextual_prompt(doc_context, chunk[:800])
        
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_MODEL"),
            messages=[{"role": "system", "content": prompt}],
            temperature=0.3,
            max_tokens=300
        )
        
        context = response.choices[0].message.content
        
        # Cleanup
        del response
        
        return context
        
    except Exception as e:
        logging.error(f"Contextualization failed: {e}")
        return ""
    finally:
        del client
        force_cleanup()

def create_sections(
    filename: str, 
    page_map: List[Tuple[int, int, str]], 
    category: str,
    add_context: bool = True
) -> Generator[dict, None, None]:
    """Create sections from page map with optional contextual enrichment"""
    
    # Get full document text for context
    full_document = "".join(p[2] for p in page_map) if add_context else ""
    
    for i, (section, pagenum) in enumerate(split_text(page_map)):
        
        # Add contextual information
        if add_context and full_document:
            logging.info(f"  Adding context to section {i+1}")
            context = contextualize_chunk(full_document, section)
            
            if context:
                # Prepend context to section
                enriched_content = f"{context}\n\n{section}"
            else:
                enriched_content = section
        else:
            enriched_content = section
        
        yield {
            "id": re.sub("[^0-9a-zA-Z_-]", "_", f"{filename}-{i}"),
            "content": enriched_content,
            "category": category,
            "page": blob_name_from_file_page(filename, pagenum + 1),
            "source_file": filename,
            "created": datetime.utcnow().isoformat() + 'Z'
        }
        
        # Cleanup after each section
        del enriched_content
        if i % 5 == 0:
            force_cleanup()

def index_sections(filename: str, sections: List[dict]) -> bool:
    """Index sections to Azure AI Search"""
    search_client = None
    try:
        logging.info(f"Indexing sections from '{filename}'")
        
        search_client = SearchClient(
            endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
            index_name=os.getenv("AZURE_SEARCH_INDEX"),
            credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
        )
        
        batch_size = 100
        batch = []
        
        for i, section in enumerate(sections):
            batch.append(section)
            
            if len(batch) >= batch_size:
                results = search_client.upload_documents(documents=batch)
                succeeded = sum([1 for r in results if r.succeeded])
                logging.info(f"  Indexed {len(batch)} sections, {succeeded} succeeded")
                
                del batch, results
                batch = []
                force_cleanup()
        
        # Index remaining
        if batch:
            results = search_client.upload_documents(documents=batch)
            succeeded = sum([1 for r in results if r.succeeded])
            logging.info(f"  Indexed {len(batch)} sections, {succeeded} succeeded")
        
        return True
        
    except Exception as e:
        logging.error(f"Indexing failed: {e}")
        raise
    finally:
        del search_client
        force_cleanup()

def convert_to_pdf_if_needed(file_path: str, temp_dir: str) -> str:
    """Convert Office files to PDF if needed"""
    ext = Path(file_path).suffix.lower()
    
    if ext == '.pdf':
        return file_path
    
    if ext in OFFICE_EXTS:
        logging.info(f"🔄 Converting {ext} to PDF...")
        pdf_path = str(Path(temp_dir) / (Path(file_path).stem + ".pdf"))
        
        if convert_to_pdf(file_path, pdf_path):
            logging.info(f"✓ Converted to: {pdf_path}")
            return pdf_path
        else:
            raise Exception("PDF conversion failed")
    
    raise Exception(f"Unsupported file type: {ext}")

# ========== API Routes ==========

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }), 200

@app.route('/api/ingest', methods=['POST'])
def ingest():
    """Main ingestion endpoint"""
    temp_dir = None
    
    try:
        log_memory()
        
        # Parse request
        data = request.get_json()
        blob_url = data.get("blob_url")
        category = data.get("category", "general")
        skip_blobs = data.get("skip_blobs", False)
        add_context = data.get("add_context", True)
        use_local_parser = data.get("use_local_parser", False)
        
        if not blob_url:
            return jsonify({"error": "blob_url is required"}), 400
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="ingest_")
        logging.info(f"📁 Temp: {temp_dir}")
        
        # Download
        filename = Path(blob_url).name
        local_path = Path(temp_dir) / filename
        
        if not download_blob(blob_url, str(local_path)):
            raise Exception("Download failed")
        
        force_cleanup()
        log_memory()
        
        # Convert to PDF if needed
        logging.info(f"📄 Processing: {filename}")
        pdf_path = convert_to_pdf_if_needed(str(local_path), temp_dir)
        
        force_cleanup()
        log_memory()
        
        # Upload PDF pages to blob (optional)
        if not skip_blobs:
            logging.info("📤 Uploading PDF pages to blob...")
            upload_blob_pages(pdf_path, temp_dir)
        
        # Extract text
        logging.info("🔍 Extracting text...")
        page_map = get_document_text(pdf_path, use_local_parser)
        
        if not page_map:
            raise Exception("No text extracted")
        
        force_cleanup()
        log_memory()
        
        # Create sections with context
        logging.info(f"✂️ Creating sections (context={add_context})...")
        sections = list(create_sections(
            os.path.basename(filename),
            page_map,
            category,
            add_context=add_context
        ))
        
        del page_map
        force_cleanup()
        log_memory()
        
        # Index sections
        logging.info(f"📊 Indexing {len(sections)} sections...")
        index_sections(os.path.basename(filename), sections)
        
        del sections
        force_cleanup()
        log_memory()
        
        logging.info("✅ Completed")
        
        return jsonify({
            "status": "success",
            "filename": filename,
            "category": category,
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logging.exception("❌ Error")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    
    finally:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        force_cleanup()

@app.route('/api/delete', methods=['POST'])
def delete_documents():
    """Delete documents from index"""
    try:
        data = request.get_json()
        filename = data.get("filename")
        
        if not filename:
            return jsonify({"error": "filename is required"}), 400
        
        logging.info(f"🗑️ Removing sections from '{filename}'")
        
        search_client = SearchClient(
            endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
            index_name=os.getenv("AZURE_SEARCH_INDEX"),
            credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
        )
        
        deleted_total = 0
        while True:
            filter_expr = f"sourcefile eq '{filename}'"
            results = search_client.search("", filter=filter_expr, top=1000, include_total_count=True)
            
            if results.get_count() == 0:
                break
            
            docs_to_delete = [{"id": d["id"]} for d in results]
            result = search_client.delete_documents(documents=docs_to_delete)
            deleted_total += len(result)
            
            logging.info(f"  Removed {len(result)} sections")
            
            # Wait for index to update
            time.sleep(2)
        
        del search_client
        force_cleanup()
        
        return jsonify({
            "status": "success",
            "deleted": deleted_total
        }), 200
        
    except Exception as e:
        logging.exception("Delete failed")
        return jsonify({"error": str(e)}), 500

# ========== Main ==========

if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    
    # Validate env vars
    required = [
        "AZURE_STORAGE_ACCOUNT_NAME",
        "AZURE_STORAGE_ACCOUNT_KEY",
        "AZURE_FORM_RECOGNIZER_ENDPOINT",
        "AZURE_FORM_RECOGNIZER_KEY",
        "AZURE_OPENAI_URL",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_MODEL",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_INDEX",
        "AZURE_SEARCH_KEY",
    ]
    
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        logging.error(f"❌ Missing: {missing}")
        exit(1)
    
    logging.info("🚀 Starting server...")
    
    port = int(os.getenv('PORT', 5000))
    
    # Use gunicorn in production
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        use_reloader=False,
        threaded=False
    )