# สรุปการเปลี่ยนแปลง

## วันที่: 2026-02-05

### ✅ การปรับปรุงหลัก

#### 1. **ปรับโครงสร้าง Document ให้ตรงกับ Azure Search Index**
   - เปลี่ยนจาก `contentVector` เป็น `content_vector`
   - เปลี่ยนจาก `sourcefile` เป็น `source_file`
   - เพิ่มฟิลด์ใหม่: `section`, `block_type`, `created`, `group`
   - โครงสร้างเอกสารใหม่:
     ```python
     {
         "id": "document-0",
         "content": "contextualized text",
         "content_vector": [3072-dim array],
         "section": "section_0",
         "block_type": "paragraph",  # ตรวจจับอัตโนมัติ: "table", "heading", หรือ "paragraph"
         "source_file": "document.pdf",
         "page": "1",  # หมายเลขหน้า
         "category": "general",
         "created": "2026-02-05T00:00:00Z",
         "group": ["general"]
     }
     ```

#### 2. **ปรับปรุงการติดตามหน้าเพจ (Page Tracking)**
   - ฟังก์ชัน `split_text()` ตอนนี้ return `(text, page_number)` tuple
   - แต่ละ section จะมี reference ถึงหน้าที่เกี่ยวข้อง
   - รูปแบบ page reference: `{base_filename}-{page_num}.pdf`
   - ตัวอย่าง: `annual-report-1.pdf`, `annual-report-2.pdf`

#### 3. **ใช้ text-embedding-3-large สำหรับ Embedding**
   - Dimension: 3072 floats
   - ตัวแปร environment: `AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-3-large`
   - รองรับ batch embedding (16 texts ต่อ batch)

#### 4. **แก้ไข Datetime Warning**
   - เปลี่ยนจาก `datetime.utcnow()`
   - เป็น `datetime.now(timezone.utc)`
   - รูปแบบ output: `2026-02-05T00:00:00Z`

#### 5. **แก้ไขชื่อตัวแปร Environment**
   - `OPENAI_EMBEDDING_MODEL` → `AZURE_OPENAI_EMBEDDING_MODEL`
   - `OPENAI_API_VERSION` → `AZURE_OPENAI_API_VERSION`

### 📋 ตัวแปร Environment ที่จำเป็น

```bash
# Azure Storage
AZURE_STORAGE_ACCOUNT_NAME=your-account
AZURE_STORAGE_ACCOUNT_KEY=your-key
AZURE_STORAGE_CONTAINER=raw

# Azure Form Recognizer
AZURE_FORM_RECOGNIZER_ENDPOINT=https://your-endpoint.cognitiveservices.azure.com
AZURE_FORM_RECOGNIZER_KEY=your-key

# Azure Search
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_INDEX=scg-rag
AZURE_SEARCH_KEY=your-key

# Azure OpenAI
AZURE_OPENAI_URL=https://your-openai.cognitiveservices.azure.com/
AZURE_OPENAI_MODEL=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2025-01-01-preview
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-3-large
```

### 🧪 การทดสอบ

รันสคริปต์ทดสอบ:
```bash
source .venv/bin/activate
python test_changes.py
```

ผลลัพธ์ที่คาดหวัง:
- ✓ ตัวแปร environment ทั้งหมดถูกตั้งค่าถูกต้อง
- ✓ Embedding model เป็น text-embedding-3-large
- ✓ Datetime format ถูกต้อง (UTC with 'Z' suffix)
- ✓ โครงสร้าง document ตรงตาม Azure index schema

### 📝 วิธีใช้งาน

1. **อัปโหลดไฟล์และประมวลผล:**
   ```bash
   curl -X POST http://localhost:5050/api/ingest \
     -H "Content-Type: application/json" \
     -d '{
       "blob_url": "https://storage.blob.core.windows.net/raw/document.pdf",
       "category": "annual-report"
     }'
   ```

2. **ผลลัพธ์:**
   - ✅ ไฟล์เดียวจะถูกแยกเป็นหลาย sections
   - ✅ แต่ละ section จะระบุหน้าที่เกี่ยวข้อง
   - ✅ เก็บ embedding vectors ด้วย text-embedding-3-large
   - ✅ Index ทั้งหมดบน Azure Cognitive Search

### 🔍 การตรวจสอบใน Azure Portal

หลังจาก index สำเร็จ คุณสามารถตรวจสอบใน Azure Portal:

1. เข้า Azure Cognitive Search → Index: `scg-rag`
2. ตรวจสอบฟิลด์:
   - `id`: Unique identifier
   - `content`: Contextualized text
   - `content_vector`: 3072-dim embedding
   - `section`: Section identifier
   - `page`: Page reference (e.g., "document-1.pdf")
   - `source_file`: Original filename
   - `category`: Document category
   - `group`: StringCollection field

### 🔧 การแก้ไขเพิ่มเติม (2026-02-05)

#### 6. **แก้ไข Document ID Sanitization**
   - Azure Search ไม่รองรับ document ID ที่มีอักขระพิเศษ, ช่องว่าง, หรือภาษาไทย
   - เพิ่มฟังก์ชัน `sanitize_document_id()` ที่ [function_app.py:524-541](function_app.py#L524-L541)
   - แปลงอักขระที่ไม่ถูกต้องเป็น underscore (_)
   - Azure Search อนุญาตเฉพาะ: `letters, digits, _, -, =`
   - ตัวอย่าง:
     - `"1-ประกาศปิด SharePoint_Teams Site-0"` → `"1-_SharePoint_Teams_Site-0"`
     - `"document with spaces.pdf-0"` → `"document_with_spaces_pdf-0"`

#### 7. **แก้ไข Embedding Model Deployment Name**
   - ตั้งค่า `AZURE_OPENAI_EMBEDDING_MODEL=text-embedding-3-large-762847`
   - ใช้ deployment name ที่แท้จริงใน Azure OpenAI (ไม่ใช่ชื่อ model)
   - อัปเดตทั้งใน [.env:15](.env#L15) และ [local.settings.json:21](local.settings.json#L21)

#### 8. **เพิ่ม Delete Routes**
   - เพิ่ม 3 routes สำหรับการลบ documents ใน [function_app.py:630-836](function_app.py#L630-L836)
   - **DELETE by ID**: `/api/delete_by_id` - ลบ document เดียวด้วย document ID
   - **DELETE by Source**: `/api/delete_by_source` - ลบทั้งหมดจาก source file เดียวกัน
   - **DELETE All**: `/api/delete_all` - ลบทั้งหมดใน index (ต้องมี confirm=true)
   - รองรับ batch deletion (1000 docs/batch)
   - มี retry logic และ error handling

#### 9. **แก้ไขฟิลด์ใน Index**
   - แก้ไข `source_file`: ใช้ `pdf_filename` แทน `original_filename` (เป็น `.pdf` เสมอ)
   - แก้ไข `page`: เก็บเฉพาะหมายเลขหน้า (1-indexed) แทนชื่อไฟล์
   - ตัวอย่างก่อนแก้:
     - `source_file`: `"1-ประกาศปิด SharePoint_Teams Site.docx"` ❌
     - `page`: `"1-ประกาศปิด SharePoint_Teams Site-1.pdf"` ❌
   - ตัวอย่างหลังแก้:
     - `source_file`: `"1-ประกาศปิด SharePoint_Teams Site.pdf"` ✓
     - `page`: `"1"` ✓ (แค่หมายเลขหน้า)

#### 10. **เพิ่มการตรวจจับ Block Type แบบ Dynamic**
   - เปลี่ยนจากการใช้ `block_type = "text"` แบบคงที่
   - เพิ่มตรรกะการตรวจจับประเภทเนื้อหาอัตโนมัติ ที่ [function_app.py:584-596](function_app.py#L584-L596)
   - ประเภทที่รองรับ:
     - `"table"`: เนื้อหาที่มี HTML table tags (`<table>...</table>`)
     - `"heading"`: เนื้อหาที่ขึ้นต้นด้วย `#` หรือสั้นกว่า 100 ตัวอักษร
     - `"paragraph"`: เนื้อหาทั่วไป (default)
   - ตัวอย่างการตรวจจับ:
     ```python
     if "<table" in content_text.lower() and "</table>" in content_text.lower():
         block_type = "table"
     elif content_text.startswith("#") or len(content_text) < 100:
         block_type = "heading"
     else:
         block_type = "paragraph"
     ```

### 🚀 Next Steps

1. Deploy ไปยัง Azure Function
2. ทดสอบกับไฟล์จริง (รองรับภาษาไทยและช่องว่างในชื่อไฟล์แล้ว)
3. Monitor performance และ embedding quality
4. ปรับ batch size ตามความเหมาะสม

### 🗑️ API Endpoints

#### Ingestion
- `POST /api/ingest` - อัปโหลดและประมวลผล document

#### Deletion
- `POST /api/delete_by_id` - ลบ document โดย ID
  ```json
  {"doc_id": "document-0"}
  ```
- `POST /api/delete_by_source` - ลบทั้งหมดจาก source file
  ```json
  {"source_file": "document.pdf"}
  ```
- `POST /api/delete_all` - ลบทั้งหมด (ระวัง!)
  ```json
  {"confirm": true}
  ```

### 🐛 การแก้ไข Errors ที่พบ

1. **Missing credentials error**
   - แก้: เปลี่ยน `LEGAL_AZURE_OPENAI_API_KEY` → `AZURE_OPENAI_API_KEY` ใน local.settings.json

2. **DeploymentNotFound error**
   - แก้: ใช้ deployment name ที่แท้จริง `text-embedding-3-large-762847`

3. **InvalidDocumentKey error**
   - แก้: เพิ่ม `sanitize_document_id()` function เพื่อทำความสะอาด document ID
