from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from reportlab.pdfgen import canvas
from pdfrw import PdfReader, PdfWriter, PageMerge
import fitz  # PyMuPDF
import requests
import os
import zipfile

app = FastAPI()

TEMPLATE_URL = "https://drive.google.com/uc?export=download&id=1Nvuxe1hyXBToMW_b6rOb1AZYdZOnAWZ0"
TEMPLATE_PATH = "/tmp/template.pdf"

# Return ZIP if file exceeds this many bytes (set to None to always return PDF)
MAX_INLINE_BYTES = 8 * 1024 * 1024   # ~8 MB (tune for your Zap)

TEXT_X = 150
TEXT_Y = 500
TEXT_FONT = "Helvetica-Bold"
TEXT_SIZE = 20
COVER_BOX = None  # e.g., (140, 488, 220, 24)

@app.post("/generate-pdf")
async def generate_pdf(request: Request):
    data = await request.json()
    buyer_name = (data or {}).get("buyer_name") or "Customer"

    template_path = get_template()
    pw, ph = get_template_page_size(template_path)

    overlay_path  = f"/tmp/{buyer_name}_overlay.pdf"
    merged_path   = f"/tmp/{buyer_name}.pdf"
    flattened_pdf = f"/tmp/{buyer_name}_flattened.pdf"
    zipped_file   = f"/tmp/{buyer_name}.zip"

    # 1) Build overlay same size as template
    build_overlay_pdf(
        overlay_path, buyer_name, pw, ph,
        TEXT_X, TEXT_Y, TEXT_FONT, TEXT_SIZE, COVER_BOX
    )

    # 2) Merge overlay onto template (first page)
    merge_overlay_onto_template(template_path, overlay_path, merged_path)

    # 3) Flatten + try to compress aggressively
    flatten_and_compress_pdf(merged_path, flattened_pdf)

    # 4) If large, zip it
    file_to_send = flattened_pdf
    filename     = f"{buyer_name}.pdf"
    if MAX_INLINE_BYTES is not None:
        try:
            size = os.path.getsize(flattened_pdf)
            if size > MAX_INLINE_BYTES:
                with zipfile.ZipFile(zipped_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.write(flattened_pdf, arcname=f"{buyer_name}.pdf")
                file_to_send = zipped_file
                filename     = f"{buyer_name}.zip"
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="Failed to generate output file")

    # 5) Tidy up old artifacts (optional)
    cleanup_tmp("/tmp", keep=6, ext=".pdf")
    cleanup_tmp("/tmp", keep=6, ext=".zip")

    # 6) Return the actual file (PDF or ZIP)
    media_type = "application/zip" if file_to_send.endswith(".zip") else "application/pdf"
    return FileResponse(file_to_send, media_type=media_type, filename=filename)


# ---------- Utilities ----------

def get_template():
    if not os.path.exists(TEMPLATE_PATH):
        r = requests.get(TEMPLATE_URL, timeout=60)
        r.raise_for_status()
        with open(TEMPLATE_PATH, "wb") as f:
            f.write(r.content)
    return TEMPLATE_PATH

def get_template_page_size(template_path: str):
    doc = fitz.open(template_path)
    if doc.page_count == 0:
        doc.close()
        raise HTTPException(status_code=500, detail="Template PDF has no pages")
    rect = doc[0].rect
    w, h = float(rect.width), float(rect.height)
    doc.close()
    return w, h

def build_overlay_pdf(overlay_path, text, pw, ph, x, y, font, font_size, cover_box):
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import white
    c = canvas.Canvas(overlay_path, pagesize=(pw, ph))
    if cover_box:
        cx, cy, cw, ch = cover_box
        c.setFillColor(white)
        c.setStrokeColor(white)
        c.rect(cx, cy, cw, ch, stroke=0, fill=1)
    c.setFont(font, font_size)
    c.drawString(x, y, text)
    c.showPage()
    c.save()

def merge_overlay_onto_template(template_path: str, overlay_path: str, output_path: str):
    template_pdf = PdfReader(template_path)
    overlay_pdf  = PdfReader(overlay_path)
    if not template_pdf.pages:
        raise HTTPException(status_code=500, detail="Template PDF has no pages")
    if overlay_pdf.pages:
        merger = PageMerge(template_pdf.pages[0])
        merger.add(overlay_pdf.pages[0]).render()
    PdfWriter(output_path, trailer=template_pdf).write()

def flatten_and_compress_pdf(input_file: str, output_file: str):
    # Flatten and apply aggressive cleanup / compression
    doc = fitz.open(input_file)
    for page in doc:
        page.wrap_contents()
    # Save with cleanup flags; this can shrink quite a bit
    doc.save(
        output_file,
        deflate=True,          # compress streams
        clean=True,            # rebuild xref, remove unused objects
        garbage=4,             # maximum garbage collection
        linear=True            # web-optimized
    )
    doc.close()

def cleanup_tmp(folder="/tmp", keep=6, ext=".pdf"):
    try:
        files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.endswith(ext)
        ]
        files.sort(key=lambda p: os.path.getmtime(p))
        while len(files) > keep:
            os.remove(files.pop(0))
    except Exception:
        pass
