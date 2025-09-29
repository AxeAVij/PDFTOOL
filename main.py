from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from pdfrw import PdfReader, PdfWriter, PageMerge
import fitz  # PyMuPDF
import os, requests

app = FastAPI()

# === Settings ===
TEMPLATE_URL = "https://drive.google.com/uc?export=download&id=1Nvuxe1hyXBToMW_b6rOb1AZYdZOnAWZ0"
TEMPLATE_PATH = "/tmp/template.pdf"


@app.post("/generate-pdf")
async def generate_pdf(request: Request):
    data = await request.json()
    buyer_name = data.get("buyer_name", "Customer")

    # Ensure template is available
    template_path = get_template()

    # File paths
    overlay_file = f"/tmp/{buyer_name}_overlay.pdf"
    base_output = f"/tmp/{buyer_name}.pdf"
    flattened_file = f"/tmp/{buyer_name}_flattened.pdf"

    # === Step 1: create overlay with buyer_name ===
    c = canvas.Canvas(overlay_file, pagesize=letter)
    c.setFont("Helvetica-Bold", 20)
    # Adjust (x, y) coordinates to match where {name} should appear
    c.drawString(150, 500, buyer_name)
    c.save()

    # === Step 2: merge overlay onto template ===
    template = PdfReader(template_path)
    overlay = PdfReader(overlay_file)
    for page, ol in zip(template.pages, overlay.pages):
        merger = PageMerge(page)
        merger.add(ol).render()
    PdfWriter(base_output, trailer=template).write()

    # === Step 3: flatten PDF ===
    flatten_pdf(base_output, flattened_file)

    # === Step 4: cleanup old files ===
    cleanup_tmp("/tmp", keep=3, ext=".pdf")

    # === Step 5: return the actual PDF ===
    return FileResponse(
        flattened_file,
        media_type="application/pdf",
        filename=f"{buyer_name}.pdf"
    )


# === Utilities ===
def get_template():
    """Ensure template.pdf is available in /tmp/"""
    if not os.path.exists(TEMPLATE_PATH):
        print("Downloading template PDF...")
        r = requests.get(TEMPLATE_URL)
        r.raise_for_status()
        with open(TEMPLATE_PATH, "wb") as f:
            f.write(r.content)
    return TEMPLATE_PATH


def flatten_pdf(input_file, output_file):
    """Flatten all contents of a PDF"""
    doc = fitz.open(input_file)
    for page in doc:
        page.wrap_contents()
    doc.save(output_file, deflate=True)


def cleanup_tmp(folder="/tmp", keep=3, ext=".pdf"):
    """Keep only the newest N PDFs in /tmp/"""
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(ext)]
    files.sort(key=lambda x: os.path.getmtime(x))
    while len(files) > keep:
        os.remove(files.pop(0))
