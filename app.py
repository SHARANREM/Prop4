from flask import Flask, request, jsonify, send_file, render_template_string
import os
import uuid
from pypdf import PdfReader, PdfWriter
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
MERGED_FOLDER = 'merged'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(MERGED_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template_string("""
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
    <form id="uploadForm" method="POST" action="/merge" enctype="multipart/form-data">
      <input type="file" name="files" id="files" multiple required accept="application/pdf,image/*" onchange="generateFileOptions()" />
      <div id="fileOptionsContainer"></div>
      <button type="submit" class="submit-btn">Merge Files</button>
    </form>
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
  </script>
</body>
</html>
    """)

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

    # Resize image to fit within page
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

@app.route('/merge', methods=['POST'])
def merge():
    files = request.files.getlist('files')
    writer = PdfWriter()
    temp_files = []

    try:
        for idx, file in enumerate(files):
            filename = file.filename.lower()
            orientation = request.form.get(f'orientation_{idx}', 'portrait')
            pages_str = request.form.get(f'pages_{idx}', '')

            if filename.endswith('.pdf'):
                saved_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{filename}")
                file.save(saved_path)
                temp_files.append(saved_path)

                reader = PdfReader(saved_path)
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

        return send_file(output_path, as_attachment=True)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)

if __name__ == '__main__':
    app.run(debug=True)
