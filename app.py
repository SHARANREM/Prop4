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
    return """
    <!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Advanced PDF Merger</title>
  <style>
    body { font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; }
    .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
    h2 { text-align: center; color: #333; }
    .file-block { border: 1px solid #ccc; padding: 15px; margin-bottom: 15px; border-radius: 5px; }
    .file-block label { display: block; margin-top: 10px; font-weight: bold; }
    .submit-btn { background: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; display: block; margin: 0 auto; }
    input[type="text"], select { width: 100%; padding: 8px; margin-top: 5px; }
  </style>
</head>
<body>
  <div class="container">
    <h2>Merge PDFs and Images with Custom Options</h2>
    <form id="uploadForm" method="POST" enctype="multipart/form-data">
  <input type="file" name="files" id="files" multiple required accept="application/pdf,image/*" onchange="generateFileOptions()" />
  <div id="fileOptionsContainer"></div>
  <button type="submit" class="submit-btn">Merge Files</button>
</form>

<div id="statusMessage" style="text-align:center; margin-top:20px; font-weight:bold;"></div>
<div id="downloadLink" style="text-align:center; margin-top:10px;"></div>

  </div>

  <script>
  function generateFileOptions() {
    const files = document.getElementById('files').files;
    const container = document.getElementById('fileOptionsContainer');
    container.innerHTML = '';

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const isImage = file.type.startsWith('image/');
      const isPDF = file.type === 'application/pdf';

      const fileBlock = document.createElement('div');
      fileBlock.className = 'file-block';
      fileBlock.innerHTML = `<h4>${file.name}</h4>`;

      if (isImage) {
        fileBlock.innerHTML += `
          <label for="orientation_${i}">Orientation</label>
          <select name="orientation_${i}" id="orientation_${i}">
            <option value="portrait">Portrait</option>
            <option value="landscape">Landscape</option>
          </select>
        `;
      }

      if (isPDF) {
        fileBlock.innerHTML += `
          <label for="pages_${i}">Pages to Include (e.g. 1-3,5)</label>
          <input type="text" name="pages_${i}" id="pages_${i}" placeholder="Leave empty for all" />
        `;
      }

      container.appendChild(fileBlock);
    }
  }

  document.getElementById('uploadForm').addEventListener('submit', async function (e) {
  e.preventDefault();

  const form = e.target;
  const formData = new FormData(form); // ✅ already includes <input type="file" name="files" multiple>

  document.getElementById('statusMessage').innerText = 'Merging files... ⏳';
  document.getElementById('downloadLink').innerHTML = '';

  try {
    const response = await fetch('/start-merge', {
      method: 'POST',
      body: formData
    });

    const result = await response.json();
    const jobId = result.job_id;
    if (!jobId) throw new Error("No job ID received");

    pollJobStatus(jobId);
  } catch (err) {
    document.getElementById('statusMessage').innerText = '❌ Error: ' + err.message;
  }
});


  async function pollJobStatus(jobId) {
    const statusUrl = `/status/${jobId}`;
    const downloadUrl = `/download/${jobId}`;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(statusUrl);
        const json = await res.json();

        if (json.status === 'done') {
          clearInterval(interval);
          document.getElementById('statusMessage').innerText = '✅ Merge complete!';
          document.getElementById('downloadLink').innerHTML = `<a href="${downloadUrl}" class="submit-btn">Download PDF</a>`;
        } else if (json.status === 'error') {
          clearInterval(interval);
          document.getElementById('statusMessage').innerText = '❌ Error: ' + (json.message || 'Merge failed.');
        }
      } catch (err) {
        clearInterval(interval);
        document.getElementById('statusMessage').innerText = '❌ Status check failed.';
      }
    }, 5000); // Check every 5 seconds
  }
</script>
</body>
</html>
"""

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

def do_merge_background(job_id, saved_files):
    writer = PdfWriter()
    temp_files = []

    try:
        for file_info in saved_files:
            path = file_info['path']
            filename = file_info['filename']
            orientation = file_info['orientation']
            pages_str = file_info['pages_str']
            password = file_info['password']

            if filename.endswith('.pdf'):
                reader = PdfReader(path)
                if reader.is_encrypted:
                    reader.decrypt(password or '')
                selected_pages = parse_ranges(pages_str)
                for i, page in enumerate(reader.pages):
                    if not selected_pages or i in selected_pages:
                        writer.add_page(page)

            elif filename.endswith(('.jpg', '.jpeg', '.png')):
                with open(path, 'rb') as img_file:
                    img = BytesIO(img_file.read())
                    img.seek(0)
                    image_buffer = convert_image_to_pdf(img, orientation)
                    image_buffer.seek(0)
                    img_reader = PdfReader(image_buffer)
                    for page in img_reader.pages:
                        writer.add_page(page)

            temp_files.append(path)

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
    saved_files = []

    for idx, file in enumerate(request.files.getlist('files')):
        filename = file.filename.lower()
        save_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{filename}")
        file.save(save_path)
        saved_files.append({
            "path": save_path,
            "filename": filename,
            "orientation": request.form.get(f'orientation_{idx}', 'portrait'),
            "pages_str": request.form.get(f'pages_{idx}', ''),
            "password": request.form.get(f'password_{idx}', '')
        })

    merge_jobs[job_id] = {"status": "processing"}
    Thread(target=do_merge_background, args=(job_id, saved_files)).start()
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
