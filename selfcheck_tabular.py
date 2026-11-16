#!/usr/bin/env python3
"""
Self-check for the native Excel / CSV ingestion path in function_app.py.

Runs offline: Azure OpenAI, AI Search, Blob and Form Recognizer are replaced by
fakes, and convert_to_pdf / ocr_pdf are booby-trapped to prove they are never
called. Covers the acceptance tests of the Excel + CSV spec:

  Excel: 3 visible + 1 hidden sheet, two-level merged header, ~50 data rows,
         an embedded image with text → image chunk with URL + OCR text
  CSV:   Thai cp874, ';' delimiter, ~200 rows
  plus edge cases (header-only, empty, ragged, BOM, TSV, dates / numbers).

Usage:
    python selfcheck_tabular.py                       # synthetic files only
    python selfcheck_tabular.py path/to/workbook.xlsx # also dump chunks of a real file
    python selfcheck_tabular.py --live-ocr ...        # real Form Recognizer (needs .env)
"""
import io
import json
import logging
import os
import re
import sys
import tempfile
import types
from datetime import date, datetime

import azure.functions as func
import openpyxl
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import function_app as fa  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")

LIVE_OCR = "--live-ocr" in sys.argv
EXTRA_FILES = [a for a in sys.argv[1:] if not a.startswith("--")]
OCR_TEXT = "INVOICE No. INV-2026-0042 Total 12,500.00 THB"
CALLS = {"index": [], "uploads": [], "ocr": 0}
FAILURES = []


def check(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILURES.append(msg)


# ---------- fakes ----------

def _forbidden(name):
    def _raise(*a, **k):
        raise AssertionError(f"{name} must not be called for Excel/CSV")
    return _raise


class _FakePoller:
    def result(self):
        CALLS["ocr"] += 1
        line = types.SimpleNamespace(content=OCR_TEXT)
        return types.SimpleNamespace(pages=[types.SimpleNamespace(lines=[line])], tables=[])


def install_fakes(temp_root):
    fa.contextualize_batch = lambda doc, chunks, batch_size=5: [f"[ctx {i}]" for i in range(len(chunks))]
    fa.embed_batch = lambda texts, batch_size=16: [[0.1, 0.2, 0.3] for _ in texts]
    fa.index_docs = lambda docs: CALLS["index"].append(list(docs))
    fa.convert_to_pdf = _forbidden("convert_to_pdf")
    fa.ocr_pdf = _forbidden("ocr_pdf")
    fa.split_text = _forbidden("split_text")

    def fake_upload(path, container, blob):
        CALLS["uploads"].append((container, blob))
        return f"https://example.blob.core.windows.net/{container}/{blob}"
    fa.upload_to_blob = fake_upload
    fa.save_to_local_processed = lambda path, filename: path

    if not LIVE_OCR:
        fa.get_form_recognizer_client = lambda: types.SimpleNamespace(
            begin_analyze_document=lambda model, document: _FakePoller())


# ---------- fixtures ----------

def text_image_png():
    img = Image.new("RGB", (640, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 630, 190], outline="black", width=3)
    draw.text((30, 40), "INVOICE No. INV-2026-0042", fill="black")
    draw.text((30, 100), "Total 12,500.00 THB", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf


def build_workbook(path):
    wb = openpyxl.Workbook()

    # Sheet 1: title band + two-level merged header (no bold → merge heuristic)
    ws1 = wb.active
    ws1.title = "Budget"
    ws1["A1"] = "Budget 2026 by department"
    ws1.merge_cells("A1:E1")
    ws1["A3"] = "Department"
    ws1.merge_cells("A3:A4")
    ws1["B3"] = "Q1"
    ws1.merge_cells("B3:C3")
    ws1["D3"] = "Q2"
    ws1.merge_cells("D3:E3")
    for col, label in zip("BCDE", ["Plan", "Actual", "Plan", "Actual"]):
        ws1[f"{col}4"] = label
    for i, dept in enumerate(["Finance", "HR", "IT", "Sales"]):
        ws1.append([dept, 1000.0 * (i + 1), 950.5 + i, 1200, 1180.0])

    # Sheet 2: ~50 data rows, bold header, dates + numbers, long text (forces multiple chunks)
    ws2 = wb.create_sheet("Journal")
    ws2.append(["Date", "Account", "Description", "Debit", "Credit"])
    for c in ws2[1]:
        c.font = Font(bold=True)
    for i in range(1, 51):
        ws2.append([date(2026, 1, (i % 28) + 1), f"{1000 + i}",
                    f"Row {i:02d} — payment for services rendered to vendor number {i} in January",
                    float(i * 100), None])
    ws2["A52"] = datetime(2026, 2, 1, 0, 0)

    # Sheet 3: embedded image with text
    ws3 = wb.create_sheet("Scans")
    ws3["A1"] = "Scanned invoice"
    ws3.add_image(XLImage(text_image_png()), "A3")

    # Hidden sheet must be ignored
    ws4 = wb.create_sheet("Secret")
    ws4["A1"] = "HIDDEN-CONTENT"
    ws4.sheet_state = "hidden"

    wb.save(path)


def build_thai_csv(path, rows=200):
    lines = ["รหัสบัญชี;ชื่อบัญชี;หมวดหมู่;ยอดคงเหลือ"]
    cats = ["สินทรัพย์", "หนี้สิน", "รายได้", "ค่าใช้จ่าย"]
    for i in range(rows):
        lines.append(f"{1000 + i};บัญชีทดสอบลำดับที่ {i} สำหรับลูกหนี้การค้าและเจ้าหนี้การค้า;{cats[i % 4]};{i * 1000}")
    with open(path, "w", encoding="cp874", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")


def http_request(blob_name):
    return func.HttpRequest(method="POST", url="/api/ingest", headers={}, params={},
                            body=json.dumps({"blob_url": f"https://acct.blob.core.windows.net/raw/{blob_name}",
                                             "category": "accounting"}).encode())


def ingest_file(path):
    with open(path, "rb") as f:
        data = f.read()
    fa.download_blob_from_url = lambda url: (data, os.path.basename(path))
    CALLS["index"].clear()
    resp = fa.ingest(http_request(os.path.basename(path)))
    body = json.loads(resp.get_body())
    docs = [d for batch in CALLS["index"] for d in batch]
    return resp.status_code, body, docs


# ---------- checks ----------

def table_rows(content):
    return [l for l in content.splitlines() if l.startswith("| ") and not l.startswith("| ---")]


def check_chunks_repeat_header(docs, header_line):
    table_docs = [d for d in docs if d["block_type"] == "table"]
    check(all(header_line in d["content"] for d in table_docs),
          f"every table chunk repeats the header ({len(table_docs)} chunks)")


def check_excel(tmp):
    print("\n[Excel] synthetic workbook")
    path = os.path.join(tmp, "acceptance_workbook.xlsx")
    build_workbook(path)
    status, body, docs = ingest_file(path)

    check(status == 200 and body.get("status") == "success", f"ingest returns success (got {status}: {body.get('message')})")
    check({"status", "chunks", "filename", "pdf_filename", "local_path", "blob_url"} <= body.keys(),
          "response keeps the existing JSON shape")
    check(body.get("chunks") == len(docs) and body.get("filename") == "acceptance_workbook.xlsx",
          f"chunks/filename in response ({body.get('chunks')} chunks)")

    sheets = {d["section"].split("#")[0] for d in docs}
    check(sheets == {"Budget", "Journal", "Scans"}, f"only the 3 visible sheets indexed ({sorted(sheets)})")
    check(not any("HIDDEN-CONTENT" in d["content"] for d in docs), "hidden sheet content not indexed")
    check(all(d["source_file"] == "acceptance_workbook.xlsx" for d in docs), "source_file keeps .xlsx")
    check(len({d["id"] for d in docs}) == len(docs), "document ids are unique")
    check(all(re.fullmatch(r"[A-Za-z0-9_\-=]+", d["id"]) for d in docs), "document ids are Azure Search safe")

    budget = [d for d in docs if d["section"].startswith("Budget#chunk")]
    check(len(budget) == 1 and "| Department | Q1 / Plan | Q1 / Actual | Q2 / Plan | Q2 / Actual |" in budget[0]["content"],
          "two-level merged header flattened to 'Group / Sub'")
    check(budget and "| Finance | 1000 | 950.5 | 1200 | 1180 |" in budget[0]["content"],
          "numbers rendered without trailing .0")
    check(budget and "Budget 2026 by department" in budget[0]["content"], "sheet title band used as table context")

    journal = [d for d in docs if d["section"].startswith("Journal#chunk")]
    header = "| Date | Account | Description | Debit | Credit |"
    check(len(journal) > 1, f"Journal split into multiple chunks ({len(journal)})")
    check_chunks_repeat_header(journal, header)
    seen_rows = {r for d in journal for r in table_rows(d["content"])}
    expected = [f"| 2026-01-{(i % 28) + 1:02d} | {1000 + i} | Row {i:02d} — payment for services rendered to vendor number {i} in January | {i * 100} |  |"
                for i in range(1, 51)]
    check(all(r in seen_rows for r in expected), "no data row split or lost across chunks (ISO dates, empty cells)")
    check(any("| 2026-02-01 |" in r for r in seen_rows), "datetime at midnight rendered as YYYY-MM-DD")
    check(all(len(d["content"]) - len(f"[ctx {0}]\n\n") <= fa.MAX_SECTION_LENGTH + 10 for d in journal),
          "chunks respect MAX_SECTION_LENGTH")
    check(all(d["page"] == "2" for d in journal), "page = 1-based sheet position")

    images = [d for d in docs if d["block_type"] == "image"]
    check(len(images) == 1 and images[0]["section"] == "Scans#image_1", "image indexed as Scans#image_1")
    if images:
        content = images[0]["content"]
        check("image_url: https://example.blob.core.windows.net/processed/images/acceptance_workbook/Scans/1.png" in content,
              "image chunk contains blob URL")
        check("INVOICE" in content and "INV-2026-0042" in content, "image chunk contains OCR text")
        check("Caption: Scanned invoice" in content, "nearby title band attached as caption")
    check(("processed", "images/acceptance_workbook/Scans/1.png") in CALLS["uploads"], "image uploaded to processed container")
    check(("processed", "acceptance_workbook.md") in CALLS["uploads"], "processed .md artifact uploaded")


def check_csv(tmp):
    print("\n[CSV] Thai cp874 with ';' delimiter, 200 rows")
    path = os.path.join(tmp, "ผังบัญชี_export.csv")
    build_thai_csv(path)
    check(fa.detect_csv_encoding(path) == "cp874", f"encoding detected as cp874 (got {fa.detect_csv_encoding(path)})")
    header_rows, rows = fa.read_csv_rows(path)
    check(header_rows == [["รหัสบัญชี", "ชื่อบัญชี", "หมวดหมู่", "ยอดคงเหลือ"]], "row 1 is the header, no mojibake")
    check(len(rows) == 200 and rows[0][0] == "1000", "200 data rows, values kept as strings")

    status, body, docs = ingest_file(path)
    check(status == 200 and body.get("status") == "success", f"ingest returns success (got {status}: {body.get('message')})")
    check(len(docs) > 1, f"multiple chunks ({len(docs)})")
    check_chunks_repeat_header(docs, "| รหัสบัญชี | ชื่อบัญชี | หมวดหมู่ | ยอดคงเหลือ |")
    check(all(d["content"].split("\n\n", 1)[1].startswith("# File: ผังบัญชี_export.csv — Columns:") for d in docs),
          "chunks start with '# File: … — Columns:' context line")
    check([d["section"] for d in docs] == [f"ผังบัญชี_export#chunk_{i}" for i in range(len(docs))],
          "section = '{basename}#chunk_{i}'")
    seen = {r for d in docs for r in table_rows(d["content"])}
    check(all(f"| {1000 + i} | บัญชีทดสอบลำดับที่ {i} สำหรับลูกหนี้การค้าและเจ้าหนี้การค้า | " in "\n".join(seen)
              for i in range(200)), "no row split or lost")
    check(all(d["page"] == "1" and d["source_file"] == "ผังบัญชี_export.csv" for d in docs), "page=1, source_file keeps .csv")
    check(len({d["id"] for d in docs}) == len(docs), "document ids are unique")


def check_edge_cases(tmp):
    print("\n[Edge cases]")
    p = os.path.join(tmp, "header_only.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("a,b,c\n")
    h, rows = fa.read_csv_rows(p)
    chunks = fa.chunk_excel_sheet("# File: header_only.csv — Columns: a, b, c", h, rows)
    check(len(chunks) == 1 and "| a | b | c |" in chunks[0], "header-only CSV → one chunk")

    p = os.path.join(tmp, "empty.csv")
    open(p, "w").close()
    try:
        fa.read_csv_rows(p)
        check(False, "empty CSV raises")
    except RuntimeError as e:
        check(str(e) == "Empty CSV", "empty CSV raises RuntimeError('Empty CSV')")

    p = os.path.join(tmp, "ragged.csv")
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write("id,name\n1,Alice,extra\n2\n3,Carol\n")
    check(fa.detect_csv_encoding(p) == "utf-8-sig", "UTF-8 BOM detected")
    h, rows = fa.read_csv_rows(p)
    check(h == [["id", "name", "Column 3"]] and rows[1] == ["2"], "ragged rows: extra column kept, header widened")
    md = fa.serialize_sheet_markdown("# File: ragged.csv", h, rows)
    check("| 2 |  |  |" in md and "| 1 | Alice | extra |" in md, "short rows padded in serialization")

    p = os.path.join(tmp, "data.tsv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("x\ty\n1,5\t2\n")
    h, rows = fa.read_csv_rows(p)
    check(h == [["x", "y"]] and rows == [["1,5", "2"]], ".tsv uses tab delimiter")

    p = os.path.join(tmp, "single.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("name\nA\nB\n")
    h, rows = fa.read_csv_rows(p)
    check(h == [["name"]] and len(rows) == 2, "single-column CSV is valid")

    wide = [["x" * 2500]]
    chunks = fa.chunk_excel_sheet("# File: wide.csv", [["col"]], wide + [["small"]])
    check(len(chunks) == 2 and "x" * 2500 in chunks[0], "over-long single row emitted as its own chunk")

    check(fa.serialize_sheet_html("# Sheet: S", [["a<b"]], [["1 & 2"]]).count("<th>a&lt;b</th>") == 1,
          "HTML serialization escapes cells")


def dump_real_file(path, tmp):
    print(f"\n[Real file] {path}")
    status, body, docs = ingest_file(path)
    print(f"  status={status} chunks={body.get('chunks')} block_types={body.get('block_types')}")
    for d in docs:
        first = d["content"].split("\n\n", 1)[-1].splitlines()[0]
        print(f"  - {d['section']:<28} {d['block_type']:<9} page={d['page']:<3} {first[:110]}")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        install_fakes(tmp)
        check_excel(tmp)
        check_csv(tmp)
        check_edge_cases(tmp)
        for f in EXTRA_FILES:
            dump_real_file(f, tmp)

    print("\n" + ("✅ All checks passed" if not FAILURES else f"❌ {len(FAILURES)} check(s) failed"))
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
