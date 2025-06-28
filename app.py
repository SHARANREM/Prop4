from flask import Flask, request, jsonify, send_file
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

merge_jobs = {}  
MAX_JOBS = 3

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
    .file-block { border: 1px solid #ccc; padding: 15px; margin-bottom: 10px; border-radius: 5px; position: relative; }
    .file-controls { margin-top: 10px; display: flex; justify-content: space-between; }
    .submit-btn, .file-btn { background: #4CAF50; color: white; padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin-top: 10px; }
    .remove-btn { background-color: red; margin-left: 5px; }
    input[type="text"], select { width: 100%; padding: 8px; margin-top: 5px; }
  </style>
</head>
<body>
  <div class="container">
    <h2>Merge PDFs and Images with Custom Options</h2>
    <div id="serverStatus" style="text-align:center; margin-bottom:15px; font-weight:bold; color: #666;"></div>
    <input type="file" id="fileInput" accept="application/pdf,image/*" multiple />
    <button class="file-btn" onclick="addFile()">Add File(s)</button>
    <form id="uploadForm" method="POST" enctype="multipart/form-data">
      <div id="fileOptionsContainer"></div>
      <button type="submit" class="submit-btn">Merge Files</button>
    </form>
    <div id="statusMessage" style="white-space: pre-line; text-align:center; margin-top:20px; font-weight:bold;"></div>
    <div id="downloadLink" style="text-align:center; margin-top:10px;"></div>
  </div>

<script>
let filesData = [];

function addFile() {
  const fileInput = document.getElementById('fileInput');
  const selectedFiles = Array.from(fileInput.files);
  if (selectedFiles.length === 0) return alert("Please select file(s)");
  for (const file of selectedFiles) {
    filesData.push({ file, id: Date.now() + Math.random() });
  }
  fileInput.value = '';
  renderFiles();
}

function moveUp(index) {
  if (index > 0) {
    [filesData[index - 1], filesData[index]] = [filesData[index], filesData[index - 1]];
    renderFiles();
  }
}

function moveDown(index) {
  if (index < filesData.length - 1) {
    [filesData[index + 1], filesData[index]] = [filesData[index], filesData[index + 1]];
    renderFiles();
  }
}

function removeFile(index) {
  filesData.splice(index, 1);
  renderFiles();
}

function renderFiles() {
  const container = document.getElementById('fileOptionsContainer');
  container.innerHTML = '';
  filesData.forEach((item, index) => {
    const file = item.file;
    const isImage = file.type.startsWith('image/');
    const isPDF = file.type === 'application/pdf';
    const block = document.createElement('div');
    block.className = 'file-block';
    block.innerHTML = `<h4>${file.name}</h4>
      ${isImage ? `<label>Orientation</label><select name="orientation_${index}">
          <option value="portrait">Portrait</option>
          <option value="landscape">Landscape</option>
        </select>` : ''}
      ${isPDF ? `<label>Pages to Include (e.g. 1-3,5)</label>
        <input type="text" name="pages_${index}" placeholder="Leave empty for all" />` : ''}
      <div class="file-controls">
        <div>
          <button type="button" class="file-btn" onclick="moveUp(${index})">⬆️</button>
          <button type="button" class="file-btn" onclick="moveDown(${index})">⬇️</button>
          <button type="button" class="file-btn remove-btn" onclick="removeFile(${index})">🗑️</button>
        </div>
      </div>`;
    container.appendChild(block);
  });
}

document.getElementById('uploadForm').addEventListener('submit', async function (e) {
  e.preventDefault();
  if (filesData.length === 0) return alert("No files selected!");
  const formData = new FormData();
  filesData.forEach((item, index) => {
    formData.append("files", item.file);
    const orientation = document.querySelector(`select[name="orientation_${index}"]`);
    const pages = document.querySelector(`input[name="pages_${index}"]`);
    if (orientation) formData.append(`orientation_${index}`, orientation.value);
    if (pages) formData.append(`pages_${index}`, pages.value);
  });
  document.getElementById('statusMessage').innerText = 'Merging files... ⏳';
  document.getElementById('downloadLink').innerHTML = '';
  try {
  const response = await fetch('/start-merge', { method: 'POST', body: formData });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server Error: ${text.slice(0, 100)}...`);
  }

  const result = await response.json();
  const jobId = result.job_id;
  if (!jobId) throw new Error("No job ID received");
  pollJobStatus(jobId);
} catch (err) {
  document.getElementById('statusMessage').innerText = '❌ Error: ' + err.message;
}

});

let lastLogLength = 0;
async function pollJobStatus(jobId) {
  const statusUrl = `/status/${jobId}`;
  const downloadUrl = `/download/${jobId}`;
  const interval = setInterval(async () => {
    try {
      const res = await fetch(statusUrl);
      const json = await res.json();
      if (json.status === 'done') {
        clearInterval(interval);
        document.getElementById('statusMessage').innerText = json.log.join('\\n') + '\\n✅ Merge complete!';
        document.getElementById('downloadLink').innerHTML = `<a href="${downloadUrl}" class="submit-btn">Download PDF</a>`;
      } else if (json.status === 'error') {
        clearInterval(interval);
        document.getElementById('statusMessage').innerText = '❌ Error: ' + (json.message || 'Merge failed.');
      } else {
        if (json.log && json.log.length > lastLogLength) {
          document.getElementById('statusMessage').innerText = json.log.join('\\n');
          lastLogLength = json.log.length;
        }
      }
    } catch (err) {
      clearInterval(interval);
      document.getElementById('statusMessage').innerText = '❌ Status check failed.';
    }
  }, 2000);
}

async function updateServerLoad() {
  try {
    const res = await fetch('/server-load');
    const data = await res.json();
    document.getElementById('serverStatus').innerText = `🖥️ Server Load: ${data.active_jobs} / ${data.max_jobs}`;
  } catch (e) {
    document.getElementById('serverStatus').innerText = '⚠️ Server status unavailable';
  }
}
updateServerLoad();
setInterval(updateServerLoad, 5000);
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
    image = Image.open(image_file).convert("RGB")  # ✅ FIXED
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

    # Save the image temporarily to draw it
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
            merge_jobs[job_id]["log"].append(f"Merging: {filename}")
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
                    img_reader = PdfReader(image_buffer)
                    for page in img_reader.pages:
                        writer.add_page(page)
            temp_files.append(path)
        output_path = os.path.join(MERGED_FOLDER, f'merged_{uuid.uuid4().hex}.pdf')
        with open(output_path, "wb") as f:
            writer.write(f)
        merge_jobs[job_id]["status"] = "done"
        merge_jobs[job_id]["result_path"] = output_path
    except Exception as e:
        merge_jobs[job_id]["status"] = "error"
        merge_jobs[job_id]["message"] = str(e)
        merge_jobs[job_id]["log"].append(f"❌ Error: {str(e)}")
    finally:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

@app.route('/start-merge', methods=['POST'])
def start_merge():
    active_jobs = sum(1 for job in merge_jobs.values() if job["status"] == "processing")
    if active_jobs >= MAX_JOBS:
        return jsonify({"error": "Server busy, please try another server"}), 503
    job_id = str(uuid.uuid4())
    merge_jobs[job_id] = {"status": "processing", "log": []}
    try:
        saved_files = []
        form_data = request.form.to_dict()
        for idx, file in enumerate(request.files.getlist('files')):
            ext = os.path.splitext(file.filename)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            saved_files.append({
                'path': file_path,
                'filename': file.filename,
                'orientation': form_data.get(f'orientation_{idx}', 'portrait'),
                'pages_str': form_data.get(f'pages_{idx}', ''),
                'password': form_data.get(f'password_{idx}', ''),
            })
        Thread(target=do_merge_background, args=(job_id, saved_files)).start()
        return jsonify({"job_id": job_id})
    except Exception as e:
        merge_jobs[job_id] = {"status": "error", "message": str(e), "log": []}
        return jsonify({"error": str(e)}), 500

@app.route('/status/<job_id>')
def check_status(job_id):
    job = merge_jobs.get(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404
    return jsonify({
        "status": job.get("status"),
        "log": job.get("log", []),
        "message": job.get("message", "")
    })

@app.route('/download/<job_id>')
def download_result(job_id):
    job = merge_jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "Result not available"}), 404
    return send_file(job["result_path"], as_attachment=True)

@app.route('/server-load')
def server_load():
    active_jobs = sum(1 for job in merge_jobs.values() if job["status"] == "processing")
    return jsonify({"active_jobs": active_jobs, "max_jobs": MAX_JOBS})

if __name__ == '__main__':
    app.run(debug=True)
