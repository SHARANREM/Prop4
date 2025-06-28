from flask import Flask, request, jsonify, send_file, render_template_string
import os, uuid
from threading import Thread
from pypdf import PdfReader, PdfWriter
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'uploads'
MERGED_FOLDER = 'merged'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(MERGED_FOLDER, exist_ok=True)

merge_jobs = {}  # job_id -> {status, result_path or error}

@app.route('/')
def index():
    return "<h2>PDF Merge Background App</h2>"

def parse_ranges(pages_str):
    if not pages_str:
        return None
    result = set()
    for part in pages_str.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            result.update(range(start - 1, end))
        else:
            result.add(int(part) - 1)
    return sorted(result)

def convert_image_to_pdf(image_file, orientation):
    image = Image.open(image_file.stream).convert("RGB")
    width, height = A4
    if orientation == "landscape":
        width, height = height, width
    ratio = min(width / image.width, height / image.height)
    new_size = (int(image.width * ratio), int(image.height * ratio))
    image = image.resize(new_size)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))
    x = (width - new_size[0]) / 2
    y = (height - new_size[1]) / 2
    temp_img_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}.jpg")
    image.save(temp_img_path)
    c.drawImage(temp_img_path, x, y, width=new_size[0], height=new_size[1])
    c.showPage()
    c.save()
    os.remove(temp_img_path)
    buffer.seek(0)
    return buffer

def do_merge_background(job_id, file_objs, form_data):
    writer = PdfWriter()
    temp_files = []

    try:
        for idx, file in enumerate(file_objs):
            filename = file.filename.lower()
            orientation = form_data.get(f'orientation_{idx}', 'portrait')
            pages_str = form_data.get(f'pages_{idx}', '')
            password = form_data.get(f'password_{idx}', '')

            if filename.endswith('.pdf'):
                saved_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{filename}")
                file.save(saved_path)
                temp_files.append(saved_path)
                reader = PdfReader(saved_path)
                if reader.is_encrypted:
                    reader.decrypt(password or '')
                selected_pages = parse_ranges(pages_str)
                for i, page in enumerate(reader.pages):
                    if not selected_pages or i in selected_pages:
                        writer.add_page(page)
            elif filename.endswith(('.jpg', '.jpeg', '.png')):
                img_pdf = convert_image_to_pdf(file, orientation)
                img_reader = PdfReader(img_pdf)
                for page in img_reader.pages:
                    writer.add_page(page)

        output_path = os.path.join(MERGED_FOLDER, f'merged_{uuid.uuid4().hex}.pdf')
        with open(output_path, "wb") as f:
            writer.write(f)
        merge_jobs[job_id] = {"status": "done", "result_path": output_path}

    except Exception as e:
        merge_jobs[job_id] = {"status": "error", "message": str(e)}

    finally:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

@app.route('/start-merge', methods=['POST'])
def start_merge():
    job_id = str(uuid.uuid4())
    files = request.files.getlist('files')
    form_data = request.form.to_dict()
    merge_jobs[job_id] = {"status": "processing"}
    Thread(target=do_merge_background, args=(job_id, files, form_data)).start()
    return jsonify({"job_id": job_id})

@app.route('/status/<job_id>')
def check_status(job_id):
    job = merge_jobs.get(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404
    return jsonify(job)

@app.route('/download/<job_id>')
def download_result(job_id):
    job = merge_jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "Result not available"}), 404
    return send_file(job["result_path"], as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
