# API Usage Guide

## 🚀 เริ่มต้นใช้งาน

### รัน Azure Function (Local)
```bash
func start
```

### Base URL
```
http://localhost:7071/api
```

---

## 📤 Ingestion API

### POST `/api/ingest`

อัปโหลดและประมวลผล document เข้าสู่ Azure Search index

**Request Body:**
```json
{
  "blob_url": "https://scgaidata.blob.core.windows.net/raw/document.pdf",
  "category": "general"
}
```

**Parameters:**
- `blob_url` (required): URL ของไฟล์ใน Azure Blob Storage
- `category` (optional): หมวดหมู่ของเอกสาร (default: "general")

**Response (Success):**
```json
{
  "status": "success",
  "chunks": 5,
  "filename": "document.pdf",
  "pdf_filename": "document.pdf",
  "local_path": "/path/to/processed/document.pdf",
  "blob_url": "https://scgaidata.blob.core.windows.net/processed/document.pdf"
}
```

**Example:**
```bash
curl -X POST http://localhost:7071/api/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "blob_url": "https://scgaidata.blob.core.windows.net/raw/annual-report.pdf",
    "category": "annual-report"
  }'
```

---

## 🗑️ Deletion APIs

### 1. POST `/api/delete_by_id`

ลบ document เดียวโดยใช้ document ID

**Request Body:**
```json
{
  "doc_id": "document-0"
}
```

**Parameters:**
- `doc_id` (required): Document ID ที่ต้องการลบ

**Response (Success):**
```json
{
  "status": "success",
  "deleted": 1,
  "doc_id": "document-0"
}
```

**Response (Not Found):**
```json
{
  "status": "error",
  "message": "Document with ID 'document-0' not found"
}
```

**Example:**
```bash
curl -X POST http://localhost:7071/api/delete_by_id \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "1-_SharePoint_Teams_Site-0"
  }'
```

---

### 2. POST `/api/delete_by_source`

ลบ documents ทั้งหมดที่มาจากไฟล์ต้นฉบับเดียวกัน

**Request Body:**
```json
{
  "source_file": "document.pdf"
}
```

**Parameters:**
- `source_file` (required): ชื่อไฟล์ต้นฉบับ (รวมนามสกุล)

**Response (Success):**
```json
{
  "status": "success",
  "deleted": 15,
  "source_file": "document.pdf"
}
```

**Example:**
```bash
curl -X POST http://localhost:7071/api/delete_by_source \
  -H "Content-Type: application/json" \
  -d '{
    "source_file": "1-ประกาศปิด SharePoint_Teams Site.pdf"
  }'
```

**Use Cases:**
- ลบเอกสารเก่าก่อนอัปโหลดเวอร์ชันใหม่
- ลบเอกสารที่ไม่ต้องการออกจาก index
- Cleanup documents จากไฟล์เดียวทั้งหมด

---

### 3. POST `/api/delete_all` ⚠️

ลบ documents **ทั้งหมด** ใน index (ใช้ด้วยความระมัดระวัง!)

**Request Body:**
```json
{
  "confirm": true
}
```

**Parameters:**
- `confirm` (required): ต้องส่ง `true` เพื่อยืนยันการลบทั้งหมด

**Response (Success):**
```json
{
  "status": "success",
  "deleted": 150,
  "message": "All documents deleted"
}
```

**Response (Missing Confirmation):**
```json
{
  "error": "Must set 'confirm': true to delete all documents"
}
```

**Example:**
```bash
curl -X POST http://localhost:7071/api/delete_all \
  -H "Content-Type: application/json" \
  -d '{
    "confirm": true
  }'
```

**⚠️ คำเตือน:**
- คำสั่งนี้จะลบ **ทั้งหมด** ใน index
- ไม่สามารถ undo ได้
- ใช้เฉพาะเมื่อต้องการ reset index ทั้งหมด
- แนะนำให้ทำ backup ก่อน (ถ้าจำเป็น)

---

## 🔍 การตรวจสอบ Index

### ดูจำนวน Documents ใน Index

```bash
# ใช้ Azure Search REST API
curl -X GET "https://bmg-cognitivesearch.search.windows.net/indexes/scg-rag/docs/$count?api-version=2023-11-01" \
  -H "api-key: YOUR_SEARCH_KEY"
```

### ค้นหา Documents

```bash
# Search ทั้งหมด
curl -X POST "https://bmg-cognitivesearch.search.windows.net/indexes/scg-rag/docs/search?api-version=2023-11-01" \
  -H "api-key: YOUR_SEARCH_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "search": "*",
    "top": 10
  }'
```

---

## 📊 Flow การใช้งานทั่วไป

### 1. อัปโหลดเอกสารใหม่
```bash
# 1.1 อัปโหลดไฟล์ไปยัง Azure Blob (raw container)
# 1.2 เรียก ingest API
POST /api/ingest
```

### 2. อัปเดตเอกสาร
```bash
# 2.1 ลบเอกสารเก่า
POST /api/delete_by_source

# 2.2 อัปโหลดเวอร์ชันใหม่
POST /api/ingest
```

### 3. ลบเอกสารที่ไม่ต้องการ
```bash
# ลบแค่ document เดียว
POST /api/delete_by_id

# หรือลบทั้งไฟล์
POST /api/delete_by_source
```

### 4. Reset Index (ทั้งหมด)
```bash
POST /api/delete_all {"confirm": true}
```

---

## 🛠️ การทดสอบ

### ใช้ Python Script
```bash
# ทดสอบ delete routes
python test_delete_routes.py

# ทดสอบการเปลี่ยนแปลงทั้งหมด
python test_changes.py
```

### ใช้ curl
ดูตัวอย่างใน sections ด้านบน

### ใช้ Postman
1. Import requests จากตัวอย่างด้านบน
2. ตั้งค่า base URL: `http://localhost:7071/api`
3. ทดสอบแต่ละ endpoint

---

## ⚙️ Environment Variables

ตรวจสอบให้แน่ใจว่าตัวแปรเหล่านี้ถูกตั้งค่าใน `local.settings.json`:

```json
{
  "AZURE_SEARCH_ENDPOINT": "https://your-search.search.windows.net",
  "AZURE_SEARCH_INDEX": "scg-rag",
  "AZURE_SEARCH_KEY": "your-key",
  "AZURE_OPENAI_URL": "https://your-openai.cognitiveservices.azure.com/",
  "AZURE_OPENAI_API_KEY": "your-key",
  "AZURE_OPENAI_MODEL": "gpt-4o-mini",
  "AZURE_OPENAI_EMBEDDING_MODEL": "text-embedding-3-large-762847",
  "AZURE_STORAGE_ACCOUNT_NAME": "your-storage",
  "AZURE_STORAGE_ACCOUNT_KEY": "your-key"
}
```

---

## 🐛 Troubleshooting

### Error: Missing credentials
- ตรวจสอบ `local.settings.json`
- รีสตาร์ท function: `func start`

### Error: DeploymentNotFound
- ตรวจสอบ deployment name ใน Azure OpenAI
- อัปเดต `AZURE_OPENAI_EMBEDDING_MODEL`

### Error: InvalidDocumentKey
- แก้ไขแล้ว! ใช้ `sanitize_document_id()` function
- รองรับภาษาไทยและอักขระพิเศษ

### Error: Connection refused
- ตรวจสอบว่า function กำลังรันอยู่
- ตรวจสอบ port (default: 7071)

---

## 📚 เอกสารเพิ่มเติม

- [CHANGES.md](CHANGES.md) - บันทึกการเปลี่ยนแปลงทั้งหมด
- [README.md](README.md) - คำแนะนำการติดตั้งและใช้งาน
- [Azure Search REST API](https://learn.microsoft.com/en-us/rest/api/searchservice/)
- [Azure Functions Python](https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference-python)
