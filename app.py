import os
import json
import uuid
import sqlite3
from datetime import datetime
from io import BytesIO
import base64
import subprocess
import threading
import time
from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.utils import secure_filename
from PIL import Image
import requests

# AI Service imports (you'll need to install these)
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['GENERATED_FOLDER'] = 'static/generated'
app.config['EXPORTS_FOLDER'] = 'static/exports'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create necessary directories
for folder in [app.config['UPLOAD_FOLDER'], app.config['GENERATED_FOLDER'], app.config['EXPORTS_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

class DatabaseManager:
    def __init__(self, db_path='storyweaver.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settings TEXT DEFAULT '{}'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS content (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                type TEXT NOT NULL,
                content_text TEXT,
                image_path TEXT,
                audio_path TEXT,
                order_index INTEGER DEFAULT 0,
                FOREIGN KEY (project_id) REFERENCES projects (id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                latex_template TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
        
        # Insert default templates
        self.insert_default_templates()
    
    def insert_default_templates(self):
        templates = [
            {
                'id': 'storybook_template',
                'name': 'Children Storybook',
                'type': 'story',
                'template': r'''\documentclass[a4paper,12pt]{book}
\usepackage[utf8]{inputenc}
\usepackage{graphicx}
\usepackage{geometry}
\usepackage{fancyhdr}
\usepackage{titlesec}
\geometry{margin=1in}

\title{{{title}}}
\author{{{author}}}
\date{{{date}}}

\begin{document}
\maketitle
\tableofcontents

{content}

\end{document}'''
            },
            {
                'id': 'educational_template',
                'name': 'Educational Book',
                'type': 'educational',
                'template': r'''\documentclass[a4paper,12pt]{report}
\usepackage[utf8]{inputenc}
\usepackage{graphicx}
\usepackage{geometry}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{fancyhdr}
\usepackage{titlesec}
\geometry{margin=1in}

\title{{{title}}}
\author{{{author}}}
\date{{{date}}}

\begin{document}
\maketitle
\tableofcontents

{content}

\end{document}'''
            },
            {
                'id': 'comic_template',
                'name': 'Comic Book',
                'type': 'comic',
                'template': r'''\documentclass[a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage{graphicx}
\usepackage[margin=0.5in]{geometry}
\usepackage{multicol}

\title{{{title}}}
\date{{{date}}}

\begin{document}
\maketitle

{content}

\end{document}'''
            }
        ]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for template in templates:
            cursor.execute('''
                INSERT OR REPLACE INTO templates (id, name, type, latex_template)
                VALUES (?, ?, ?, ?)
            ''', (template['id'], template['name'], template['type'], template['template']))
        
        conn.commit()
        conn.close()
    
    def create_project(self, name, project_type, settings=None):
        project_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO projects (id, name, type, settings)
            VALUES (?, ?, ?, ?)
        ''', (project_id, name, project_type, json.dumps(settings or {})))
        
        conn.commit()
        conn.close()
        
        return project_id
    
    def get_projects(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM projects ORDER BY updated_at DESC')
        projects = cursor.fetchall()
        
        conn.close()
        return projects
    
    def add_content(self, project_id, content_type, text=None, image_path=None, audio_path=None, order_index=0):
        content_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO content (id, project_id, type, content_text, image_path, audio_path, order_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (content_id, project_id, content_type, text, image_path, audio_path, order_index))
        
        conn.commit()
        conn.close()
        
        return content_id
    
    def get_project_content(self, project_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM content WHERE project_id = ? ORDER BY order_index
        ''', (project_id,))
        content = cursor.fetchall()
        
        conn.close()
        return content

from models.ai_service import AIService

class PDFGenerator:
    def __init__(self, db_manager):
        self.db_manager = db_manager
    
    def generate_latex_code(self, project_id, template_type="storybook"):
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()
        
        # Get project info
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        project = cursor.fetchone()
        
        # Get template
        cursor.execute('SELECT latex_template FROM templates WHERE type = ?', (template_type,))
        template = cursor.fetchone()
        
        # Get content
        cursor.execute('SELECT * FROM content WHERE project_id = ? ORDER BY order_index', (project_id,))
        content_items = cursor.fetchall()
        
        conn.close()
        
        if not template:
            return None, "Template not found"
        
        latex_template = template[0]
        
        # Build content sections
        content_sections = []
        for item in content_items:
            if item[3]:  # content_text exists
                # Sanitize text for LaTeX
                sanitized_text = item[3].replace('&', '\\&').replace('%', '\\%').replace('$', '\\$')
                sanitized_title = sanitized_text[:50].replace('{', '').replace('}', '')
                content_sections.append(f"\\section*{{{sanitized_title}...}}")
                content_sections.append(sanitized_text)
                
            if item[4]:  # image_path exists
                abs_image_path = os.path.abspath(item[4])
                content_sections.append(f"\\begin{{figure}}[h!]")
                content_sections.append(f"\\centering")
                content_sections.append(f"\\includegraphics[width=0.8\\textwidth]{{{abs_image_path}}}")
                content_sections.append(f"\\end{{figure}}")
        
        # Fill template
        latex_code = latex_template.format(
            title=project[1] if project else "Generated Story",
            author="StoryWeaver AI",
            date=datetime.now().strftime("%Y-%m-%d"),
            content="\n\n".join(content_sections)
        )
        
        return latex_code, None
    
    def compile_pdf(self, latex_code, output_filename):
        try:
            # Create temporary tex file
            tex_file = f"{output_filename}.tex"
            pdf_file = f"{output_filename}.pdf"
            
            with open(tex_file, 'w', encoding='utf-8') as f:
                f.write(latex_code)
            
            # Compile with pdflatex
            result = subprocess.run([
                'pdflatex', 
                '-output-directory', 
                os.path.dirname(output_filename),
                tex_file
            ], capture_output=True, text=True)
            
            if result.returncode == 0 and os.path.exists(pdf_file):
                # Clean up auxiliary files
                for ext in ['.aux', '.log', '.tex']:
                    aux_file = f"{output_filename}{ext}"
                    if os.path.exists(aux_file):
                        os.remove(aux_file)
                
                return pdf_file, None
            else:
                return None, result.stderr
        
        except Exception as e:
            return None, str(e)

# Initialize services
db_manager = DatabaseManager()
ai_service = AIService()
pdf_generator = PDFGenerator(db_manager)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/projects', methods=['GET', 'POST'])
def handle_projects():
    if request.method == 'GET':
        projects = db_manager.get_projects()
        return jsonify([{
            'id': p[0],
            'name': p[1],
            'type': p[2],
            'created_at': p[3],
            'updated_at': p[4],
            'settings': json.loads(p[5]) if p[5] else {}
        } for p in projects])
    
    elif request.method == 'POST':
        data = request.get_json()
        project_id = db_manager.create_project(
            data['name'],
            data['type'],
            data.get('settings', {})
        )
        return jsonify({'project_id': project_id})

@app.route('/api/create-book', methods=['POST'])
def create_book():
    data = request.get_json()
    
    book_type = data.get('type', 'story')
    
    # Determine number of scenes based on book type
    if book_type == 'story':
        num_scenes = 10
    elif book_type == 'educational':
        num_scenes = 15
    elif book_type == 'comic':
        num_scenes = 20
    else:
        num_scenes = 10 # Default
        
    story_data, error = ai_service.generate_story_structure(
        data['character_name'],
        data['character_friend'],
        data['setting'],
        data['moral'],
        num_scenes
    )
    
    if error:
        return jsonify({'error': error}), 500
    
    # Create project
    project_id = db_manager.create_project(
        data['title'],
        book_type,
        data
    )
    
    # Generate images for each scene
    for i, scene in enumerate(story_data['scenes']):
        # Add text content
        db_manager.add_content(
            project_id,
            'text',
            text=scene['text'],
            order_index=i * 2
        )
        
        # Generate and save image
        image_data, error = ai_service.generate_image(
            scene['image_prompt'],
            data.get('art_style', 'watercolor')
        )
        
        if image_data:
            # Save image
            image_filename = f"{project_id}_scene_{i}.png"
            image_path = os.path.join(app.config['GENERATED_FOLDER'], image_filename)
            
            with open(image_path, 'wb') as f:
                f.write(base64.b64decode(image_data))
            
            db_manager.add_content(
                project_id,
                'image',
                image_path=image_path,
                order_index=i * 2 + 1
            )
            scene['image_url'] = f"/{image_path}" # Add image URL to the scene
        else:
            scene['image_url'] = None
        
        # Generate audio
        if data.get('generate_audio', True):
            audio_data, error = ai_service.generate_audio_narration(scene['text'])
            if audio_data:
                audio_filename = f"{project_id}_scene_{i}.mp3"
                audio_path = os.path.join(app.config['GENERATED_FOLDER'], audio_filename)
                
                with open(audio_path, 'wb') as f:
                    f.write(audio_data)
                
                # In a real app, you'd save the audio_path to the database here
    
    return jsonify({
        'project_id': project_id,
        'story': story_data
    })

@app.route('/api/modify-image', methods=['POST'])
def modify_image():
    data = request.get_json()
    
    modified_image, error = ai_service.modify_image(
        data['image_data'],
        data['modification_prompt']
    )
    
    if error:
        return jsonify({'error': error}), 500
    
    # Encode the image data to base64
    encoded_image = base64.b64encode(modified_image).decode('utf-8')

    return jsonify({'image_data': encoded_image})

@app.route('/api/generate-image', methods=['POST'])
def generate_image():
    data = request.get_json()
    
    image_data, error = ai_service.generate_image(
        data['prompt'],
        data.get('style', 'watercolor')
    )
    
    if error:
        return jsonify({'error': error}), 500

    # Create a project for the generated image
    project_id = db_manager.create_project(
        name=f"Generated Image: {data['prompt'][:30]}...",
        project_type='ecommerce',
        settings=data
    )

    # Save the image to the generated folder
    image_filename = f"{project_id}_generated.png"
    image_path = os.path.join(app.config['GENERATED_FOLDER'], image_filename)

    try:
        with open(image_path, 'wb') as f:
            f.write(image_data)
    except Exception as e:
        return jsonify({'error': f'Failed to save image: {str(e)}'}), 500

    # Add content to the database
    db_manager.add_content(
        project_id=project_id,
        content_type='image',
        image_path=image_path
    )
    
    # Encode the image data to base64
    encoded_image = base64.b64encode(image_data).decode('utf-8')

    return jsonify({'image_data': encoded_image})

@app.route('/api/combine-images', methods=['POST'])
def combine_images():
    data = request.get_json()
    
    combined_image, error = ai_service.combine_images(
        data['image1_data'],
        data['image2_data'],
        data['combination_prompt']
    )
    
    if error:
        return jsonify({'error': error}), 500
    
    return jsonify({'image_data': combined_image})

@app.route('/api/generate-pdf/<project_id>')
def generate_pdf(project_id):
    # Get project to determine the template type
    conn = sqlite3.connect(db_manager.db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT type FROM projects WHERE id = ?', (project_id,))
    project = cursor.fetchone()
    conn.close()

    if not project:
        return jsonify({'error': 'Project not found'}), 404

    template_type = project[0]
    
    latex_code, error = pdf_generator.generate_latex_code(project_id, template_type)
    
    if error:
        return jsonify({'error': error}), 500
    
    output_filename = os.path.join(
        app.config['EXPORTS_FOLDER'],
        f"project_{project_id}"
    )
    
    pdf_path, error = pdf_generator.compile_pdf(latex_code, output_filename)
    
    if error:
        return jsonify({'error': f'PDF Compilation Failed: {error}'}), 500
    
    return send_file(pdf_path, as_attachment=True)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Convert to base64 for frontend
        with open(filepath, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode()
        
        return jsonify({
            'filename': filename,
            'filepath': filepath,
            'image_data': image_data
        })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
