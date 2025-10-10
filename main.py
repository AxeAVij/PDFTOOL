from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse
from reportlab.pdfgen import canvas
from pdfrw import PdfReader, PdfWriter, PageMerge
from reportlab.lib.colors import white
import fitz  # PyMuPDF
import requests
import os
import traceback

app = FastAPI()

# === SETTINGS ===
# Put your Google Drive FILE_ID into the URL below (Any one with link = Viewer)
TEMPLATE_URL = "https://drive.google.com/uc?export=download&id=1Nvuxe1hyXBToMW_b6rOb1AZYdZOnAWZ0"
TEMPLATE_PATH = "/tmp/template.pdf"

# Default text placement on the page (adjust to your template)
# Coordinates are in PDF points with origin at bottom-left.
TEXT_X = 150
TEXT_Y = 500
TEXT_FONT = "Helvetica-Bold"
TEXT_SIZE = 20

# Optional: cover a placeholder area first (white-out) before drawing text.
# Set to None to skip. If you want to cover, set to (x, y, width, height).
COVER_BOX = None  # e.g., (140, 488, 220, 24)


@app.post("/generate-pdf")
async def generate_pdf(request: Request):
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    buyer_name = (data or {}).get("buyer_name") or "Customer"

    # Ensure template is cached in /tmp
    template_path = get_template()

    # Resolve page size from the template's first page
    page_width, page_height = get_template_page_size(template_path)

    # Paths
    overlay_path = f"/tmp/{buyer_name}_overlay.pdf"
    merged_path  = f"/tmp/{buyer_name}.pdf"
    final_path   = f"/tmp/{buyer_name}_flattened.pdf"

    # 1) Build overlay the SAME SIZE as template's first page
    build_overlay_pdf(
        overlay_path=overlay_path,
        text=buyer_name,
        page_width=page_width,
        page_height=page_height,
        x=TEXT_X, y=TEXT_Y,
        font=TEXT_FONT,
        font_size=TEXT_SIZE,
        cover_box=COVER_BOX
    )

    # 2) Merge overlay onto template (overlay only applied to first page)
    merge_overlay_onto_template(template_path, overlay_path, merged_path)

    # 3) Flatten the PDF so it can't be edited
    flatten_pdf(merged_path, final_path)

    # 4) (Optional) clean older PDFs in /tmp
    cleanup_tmp("/tmp", keep=5, ext=".pdf")

    # 5) Return the ACTUAL PDF file stream
    return FileResponse(
        final_path,
        media_type="application/pdf",
        filename=f"{buyer_name}.pdf"
    )


# ---------- Utilities ----------

def get_template():
    """Ensure the template.pdf exists in /tmp; download if missing."""
    if not os.path.exists(TEMPLATE_PATH):
        r = requests.get(TEMPLATE_URL, timeout=60)
        r.raise_for_status()
        with open(TEMPLATE_PATH, "wb") as f:
            f.write(r.content)
    return TEMPLATE_PATH


def get_template_page_size(template_path: str):
    """Read first page size using PyMuPDF (width, height) in points."""
    doc = fitz.open(template_path)
    if doc.page_count == 0:
        doc.close()
        raise HTTPException(status_code=500, detail="Template PDF has no pages")
    rect = doc[0].rect
    w, h = float(rect.width), float(rect.height)
    doc.close()
    return w, h


def build_overlay_pdf(
    overlay_path: str,
    text: str,
    page_width: float,
    page_height: float,
    x: float,
    y: float,
    font: str = "Helvetica-Bold",
    font_size: int = 20,
    cover_box=None
):
    """
    Create a 1-page overlay with identical size to the template's first page.
    Optionally paint a white rectangle (COVER_BOX) over the placeholder area,
    then draw the replacement text at (x, y).
    """
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(overlay_path, pagesize=(page_width, page_height))

    if cover_box:
        cx, cy, cw, ch = cover_box
        c.setFillColor(white)
        c.setStrokeColor(white)
        c.rect(cx, cy, cw, ch, stroke=0, fill=1)  # white-out area

    c.setFont(font, font_size)
    c.drawString(x, y, text)
    c.showPage()
    c.save()


def merge_overlay_onto_template(template_path: str, overlay_path: str, output_path: str):
    """
    Merge 1-page overlay onto the FIRST page of the template.
    Other pages remain untouched.
    """
    template_pdf = PdfReader(template_path)
    overlay_pdf  = PdfReader(overlay_path)

    if not template_pdf.pages:
        raise HTTPException(status_code=500, detail="Template PDF has no pages")

    # If overlay exists, merge onto first page
    if overlay_pdf.pages:
        first_page = template_pdf.pages[0]
        first_overlay = overlay_pdf.pages[0]
        merger = PageMerge(first_page)
        merger.add(first_overlay).render()

    PdfWriter(output_path, trailer=template_pdf).write()


def flatten_pdf(input_file: str, output_file: str):
    """
    Flatten the PDF so text/annotations become static page content.
    """
    doc = fitz.open(input_file)
    for page in doc:
        page.wrap_contents()  # consolidate into static content stream
    doc.save(output_file, deflate=True)
    doc.close()


def cleanup_tmp(folder="/tmp", keep=5, ext=".pdf"):
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
        # Non-fatal; keep going
        print("Cleanup error:\n", traceback.format_exc())
