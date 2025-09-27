from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os

app = FastAPI()

@app.post("/generate-pdf")
async def generate_pdf(request: Request):
    data = await request.json()
    buyer_name = data.get("buyer_name", "Customer")

    # TODO: your PDF editing logic here
    # For now, just simulate a PDF file
    output_file = f"/tmp/{buyer_name}.pdf"
    with open(output_file, "w") as f:
        f.write(f"Hello {buyer_name}, this is your personalized PDF.")

    # Cleanup old files
    cleanup_tmp("/tmp", keep=3, ext=".pdf")

    return JSONResponse({
        "status": "ok",
        "pdf_path": output_file,
        "buyer_name": buyer_name
    })


def cleanup_tmp(folder="/tmp", keep=3, ext=".pdf"):
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(ext)]
    files.sort(key=lambda x: os.path.getmtime(x))
    while len(files) > keep:
        os.remove(files.pop(0))