# โครงสร้าง Azure Search Index

## 📊 ฟิลด์ทั้งหมดใน Index `scg-rag`

### 1. **id** (String, Key)
- Document ID ที่ไม่ซ้ำกัน
- ถูก sanitize เพื่อให้เป็นไปตาม Azure Search rules
- รูปแบบ: `{sanitized_filename}-{section_number}`
- ตัวอย่าง: `"1-_SharePoint_Teams_Site-0"`

### 2. **content** (String, Retrievable, Searchable, Filterable)
- เนื้อหาที่ผ่าน contextualization แล้ว
- รวม context จาก GPT-4o-mini + เนื้อหาต้นฉบับ
- ความยาวสูงสุด: 1000 characters ต่อ section

### 3. **content_vector** (SingleCollection, Dimension: 3072)
- Vector embedding จาก `text-embedding-3-large`
- ใช้สำหรับ semantic search
- Dimension: 3072 floats

### 4. **section** (String, Retrievable, Filterable)
- ระบุ section ของ document
- รูปแบบ: `"section_{i}"` (i = 0, 1, 2, ...)
- ตัวอย่าง: `"section_0"`, `"section_1"`

### 5. **block_type** (String, Retrievable, Filterable)
- ประเภทของ block (ตรวจจับอัตโนมัติจากเนื้อหา)
- ค่าที่เป็นไปได้:
  - `"table"`: เนื้อหาที่มี HTML table tags
  - `"heading"`: เนื้อหาที่ขึ้นต้นด้วย `#` หรือสั้นกว่า 100 ตัวอักษร
  - `"paragraph"`: เนื้อหาทั่วไป
- สามารถขยายเป็น `"image"` ได้ในอนาคต

### 6. **source_file** (String, Retrievable, Searchable, Filterable, Sortable)
- ชื่อไฟล์ต้นฉบับ (PDF filename)
- **เป็น `.pdf` เสมอ** (แม้ว่าต้นทางจะเป็น .docx, .pptx)
- รองรับภาษาไทยและอักขระพิเศษ
- ตัวอย่าง: `"1-ประกาศปิด SharePoint_Teams Site.pdf"`

### 7. **page** (String, Retrievable, Filterable, Sortable)
- **หมายเลขหน้าที่มีเนื้อหาอยู่**
- เป็นตัวเลข (1-indexed)
- ตัวอย่าง: `"1"`, `"2"`, `"15"`
- ใช้สำหรับอ้างอิงว่าเนื้อหาอยู่หน้าไหนของเอกสาร

### 8. **category** (String, Retrievable, Searchable, Filterable, Facetable)
- หมวดหมู่ของเอกสาร
- กำหนดตอน ingest
- ตัวอย่าง: `"general"`, `"annual-report"`, `"announcement"`

### 9. **created** (DateTimeOffset, Retrievable, Filterable, Sortable)
- Timestamp ที่สร้าง document
- รูปแบบ: ISO 8601 with 'Z' suffix
- ตัวอย่าง: `"2026-02-05T00:00:00Z"`

### 10. **group** (StringCollection, Retrievable, Filterable)
- กลุ่มที่ document นี้อยู่
- สามารถมีหลายค่า
- ปัจจุบันเก็บ category
- ตัวอย่าง: `["general"]`, `["annual-report", "financial"]`

---

## 📝 ตัวอย่าง Document จริง

```json
{
  "id": "1-_SharePoint_Teams_Site-0",
  "content": "This chunk is part of the \"content\" section of the document titled \"ประกาศปิด SharePoint/Teams Site,\" which is a notification regarding the closure...",
  "content_vector": [0.025002, -0.060580, ...],  // 3072 dimensions
  "section": "section_0",
  "block_type": "paragraph",  // ตรวจจับอัตโนมัติ: "table", "heading", หรือ "paragraph"
  "source_file": "1-ประกาศปิด SharePoint_Teams Site.pdf",
  "page": "1",
  "category": "announcement",
  "created": "2026-02-05T01:50:00Z",
  "group": ["announcement"]
}
```

---

## 🔍 ตัวอย่าง Query

### 1. ค้นหาทั้งหมดจากไฟล์เดียว
```json
{
  "search": "*",
  "filter": "source_file eq '1-ประกาศปิด SharePoint_Teams Site.pdf'"
}
```

### 2. ค้นหาเฉพาะหน้า 1
```json
{
  "search": "*",
  "filter": "page eq '1'"
}
```

### 3. ค้นหาตาม category
```json
{
  "search": "*",
  "filter": "category eq 'announcement'"
}
```

### 4. ค้นหาเฉพาะ block type
```json
{
  "search": "*",
  "filter": "block_type eq 'table'"
}
```

### 5. Semantic Search
```json
{
  "search": "SharePoint site closure policy",
  "vectors": [{
    "value": [0.025002, -0.060580, ...],  // query vector
    "fields": "content_vector",
    "k": 10
  }]
}
```

---

## 🎯 Use Cases

### 1. หาเอกสารที่เกี่ยวข้อง
```python
# ค้นหาด้วย semantic search + filter ตาม category
results = search_client.search(
    search_text="SharePoint closure",
    filter="category eq 'announcement'",
    top=10
)
```

### 2. หาหน้าที่มีข้อมูล
```python
# ค้นหาและแสดงหน้าที่เกี่ยวข้อง
results = search_client.search(
    search_text="policy",
    select=["source_file", "page", "content"]
)
for result in results:
    print(f"Found in: {result['source_file']}, Page: {result['page']}")
```

### 3. ลบเอกสารเก่า
```python
# ลบทั้งหมดจาก source_file
search_client.search(
    search_text="",
    filter="source_file eq 'old-document.pdf'"
)
```

### 4. ค้นหาเฉพาะตาราง
```python
# ค้นหาเฉพาะ blocks ที่เป็นตาราง
results = search_client.search(
    search_text="financial data",
    filter="block_type eq 'table'",
    top=10
)
for result in results:
    print(f"Table found in: {result['source_file']}, Page: {result['page']}")
```

---

## ⚙️ การปรับแต่ง Index

### เพิ่ม Scoring Profile
สามารถเพิ่ม scoring profile เพื่อ boost ผลลัพธ์ตาม:
- `created` (documents ใหม่กว่า)
- `category` (priority categories)

### เพิ่ม Suggester
สร้าง suggester สำหรับ autocomplete:
- `source_file`
- `category`

### เพิ่ม Analyzer
- Thai language analyzer สำหรับ `content`
- Keyword analyzer สำหรับ `source_file`

---

## 📈 Monitoring

### ตรวจสอบจำนวน Documents
```bash
curl -X GET "https://bmg-cognitivesearch.search.windows.net/indexes/scg-rag/docs/$count?api-version=2023-11-01" \
  -H "api-key: YOUR_KEY"
```

### ตรวจสอบ Storage Size
```bash
curl -X GET "https://bmg-cognitivesearch.search.windows.net/indexes/scg-rag/stats?api-version=2023-11-01" \
  -H "api-key: YOUR_KEY"
```

---

## 🚀 Performance Tips

1. **Batch Upload**: อัปโหลด documents ที่ละ 100-1000 รายการ
2. **Selective Fields**: ใช้ `select` เพื่อ retrieve เฉพาะฟิลด์ที่ต้องการ
3. **Filter First**: ใช้ `filter` ก่อน `search` เพื่อลดขอบเขต
4. **Cache Results**: Cache ผลลัพธ์ query ที่ใช้บ่อย
5. **Monitor Quota**: ตรวจสอบ storage และ document count อยู่เสมอ
