import os
import subprocess
import tempfile
import shutil
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from pathlib import Path

class PDFGenerator:
    """Handles PDF generation from LaTeX code and content."""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.latex_compiler = os.getenv('LATEX_COMPILER', 'pdflatex')
        self.output_dir = os.getenv('LATEX_OUTPUT_DIR', 'static/exports')
        self.temp_dir = tempfile.gettempdir()
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
    
    def check_latex_installation(self) -> bool:
        """Check if LaTeX is properly installed."""
        try:
            result = subprocess.run([self.latex_compiler, '--version'], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def generate_latex_from_project(self, 
                                   project_id: str, 
                                   template_id: str = 'children_storybook',
                                   custom_settings: Optional[Dict] = None) -> Tuple[Optional[str], Optional[str]]:
        """Generate LaTeX code from a project's content."""
        
        # Get project information
        project = self.db_manager.get_project(project_id)
        if not project:
            return None, "Project not found"
        
        # Get template
        template = self.db_manager.get_template(template_id)
        if not template:
            return None, "Template not found"
        
        # Get project content
        content_items = self.db_manager.get_project_content(project_id)
        
        # Build LaTeX content sections
        latex_sections = self._build_content_sections(content_items, custom_settings)
        
        # Prepare template variables
        template_vars = {
            'title': project['name'],
            'author': custom_settings.get('author', 'StoryWeaver AI'),
            'date': datetime.now().strftime("%B %d, %Y"),
            'content': '\n\n'.join(latex_sections)
        }
        
        # Fill template
        try:
            latex_code = template['latex_template'].format(**template_vars)
            return latex_code, None
        except KeyError as e:
            return None, f"Template variable missing: {e}"
        except Exception as e:
            return None, f"Template processing error: {str(e)}"
    
    def _build_content_sections(self, 
                               content_items: List[Dict],
                               settings: Optional[Dict] = None) -> List[str]:
        """Build LaTeX sections from content items."""
        
        sections = []
        current_scene = 1
        
        # Group content by scene/chapter
        grouped_content = self._group_content_by_scene(content_items)
        
        for scene_content in grouped_content:
            scene_sections = []
            
            # Add scene/chapter title
            if scene_content.get('title'):
                if settings and settings.get('book_type') == 'comic':
                    scene_sections.append(f"\\section*{{{scene_content['title']}}}")
                else:
                    scene_sections.append(f"\\chapter{{{scene_content['title']}}}")
            
            # Add text content
            for item in scene_content.get('text_items', []):
                if item['content_text']:
                    # Clean and format text for LaTeX
                    clean_text = self._clean_text_for_latex(item['content_text'])
                    scene_sections.append(clean_text)
            
            # Add images
            for item in scene_content.get('image_items', []):
                if item['image_path'] and os.path.exists(item['image_path']):
                    image_section = self._create_image_section(item, settings)
                    scene_sections.append(image_section)
            
            # Add scene break
            scene_sections.append("\\vspace{1em}")
            
            if scene_sections:
                sections.extend(scene_sections)
            
            current_scene += 1
        
        return sections
    
    def _group_content_by_scene(self, content_items: List[Dict]) -> List[Dict]:
        """Group content items by scene/order."""
        
        scenes = {}
        
        for item in content_items:
            scene_index = item['order_index'] // 10  # Group by tens
            
            if scene_index not in scenes:
                scenes[scene_index] = {
                    'title': f"Scene {scene_index + 1}",
                    'text_items': [],
                    'image_items': [],
                    'audio_items': []
                }
            
            if item['type'] == 'text':
                scenes[scene_index]['text_items'].append(item)
            elif item['type'] == 'image':
                scenes[scene_index]['image_items'].append(item)
            elif item['type'] == 'audio':
                scenes[scene_index]['audio_items'].append(item)
        
        # Convert to sorted list
        return [scenes[key] for key in sorted(scenes.keys())]
    
    def _clean_text_for_latex(self, text: str) -> str:
        """Clean text for LaTeX compilation."""
        
        # Escape special LaTeX characters
        latex_special_chars = {
            '&': '\\&',
            '%': '\\%',
            '$': '\\$',
            '#': '\\#',
            '^': '\\textasciicircum{}',
            '_': '\\_',
            '{': '\\{',
            '}': '\\}',
            '~': '\\textasciitilde{}',
            '\\': '\\textbackslash{}'
        }
        
        clean_text = text
        for char, replacement in latex_special_chars.items():
            clean_text = clean_text.replace(char, replacement)
        
        # Handle quotes
        clean_text = clean_text.replace('"', "''")
        clean_text = clean_text.replace('"', '``')
        clean_text = clean_text.replace('"', "''")
        
        # Add paragraph breaks
        paragraphs = clean_text.split('\n\n')
        return '\n\n'.join(f"\\noindent {para.strip()}" for para in paragraphs if para.strip())
    
    def _create_image_section(self, image_item: Dict, settings: Optional[Dict] = None) -> str:
        """Create LaTeX code for an image."""
        
        image_path = image_item['image_path']
        
        # Convert to relative path if needed
        if image_path.startswith('/'):
            image_path = image_path.lstrip('/')
        
        # Default image settings
        width = settings.get('image_width', '0.8') if settings else '0.8'
        centering = settings.get('center_images', True) if settings else True
        
        image_latex = [
            "\\begin{figure}[h!]",
        ]
        
        if centering:
            image_latex.append("\\centering")
        
        image_latex.extend([
            f"\\includegraphics[width={width}\\textwidth]{{{image_path}}}",
        ])
        
        # Add caption if available in metadata
        metadata = image_item.get('metadata', {})
        if metadata and metadata.get('caption'):
            caption = self._clean_text_for_latex(metadata['caption'])
            image_latex.append(f"\\caption{{{caption}}}")
        
        image_latex.extend([
            "\\end{figure}",
            "\\vspace{0.5em}"
        ])
        
        return '\n'.join(image_latex)
    
    def compile_pdf(self, 
                   latex_code: str, 
                   output_filename: str,
                   compile_twice: bool = True) -> Tuple[Optional[str], Optional[str]]:
        """Compile LaTeX code to PDF."""
        
        if not self.check_latex_installation():
            return None, "LaTeX is not installed or not accessible"
        
        # Create temporary directory for compilation
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Write LaTeX code to file
                tex_file = os.path.join(temp_dir, 'document.tex')
                with open(tex_file, 'w', encoding='utf-8') as f:
                    f.write(latex_code)
                
                # First compilation
                result1 = subprocess.run([
                    self.latex_compiler,
                    '-output-directory', temp_dir,
                    '-interaction=nonstopmode',
                    tex_file
                ], capture_output=True, text=True, timeout=60)
                
                # Second compilation if requested (for TOC, references, etc.)
                if compile_twice and result1.returncode == 0:
                    result2 = subprocess.run([
                        self.latex_compiler,
                        '-output-directory', temp_dir,
                        '-interaction=nonstopmode',
                        tex_file
                    ], capture_output=True, text=True, timeout=60)
                    final_result = result2
                else:
                    final_result = result1
                
                pdf_file = os.path.join(temp_dir, 'document.pdf')
                
                if final_result.returncode == 0 and os.path.exists(pdf_file):
                    # Copy PDF to output directory
                    output_path = os.path.join(self.output_dir, f"{output_filename}.pdf")
                    shutil.copy2(pdf_file, output_path)
                    return output_path, None
                else:
                    # Return compilation errors
                    error_log = final_result.stderr or final_result.stdout
                    return None, f"LaTeX compilation failed:\n{error_log}"
            
            except subprocess.TimeoutExpired:
                return None, "LaTeX compilation timeout"
            except Exception as e:
                return None, f"PDF generation error: {str(e)}"
    
    def generate_cover_page(self, 
                           title: str,
                           author: str = "StoryWeaver AI",
                           cover_image: Optional[str] = None,
                           style: str = "modern") -> str:
        """Generate LaTeX code for a cover page."""
        
        cover_styles = {
            "modern": self._modern_cover_template,
            "classic": self._classic_cover_template,
            "children": self._children_cover_template
        }
        
        template_func = cover_styles.get(style, cover_styles["modern"])
        return template_func(title, author, cover_image)
    
    def _modern_cover_template(self, title: str, author: str, cover_image: Optional[str]) -> str:
        """Modern cover page template."""
        
        cover_latex = [
            "\\begin{titlepage}",
            "\\centering",
            "\\vspace*{2cm}",
        ]
        
        if cover_image and os.path.exists(cover_image):
            cover_latex.extend([
                f"\\includegraphics[width=0.6\\textwidth]{{{cover_image}}}",
                "\\vspace{2cm}",
            ])
        
        cover_latex.extend([
            "{\\Huge\\bfseries " + self._clean_text_for_latex(title) + "\\par}",
            "\\vspace{1.5cm}",
            "{\\Large\\itshape " + self._clean_text_for_latex(author) + "\\par}",
            "\\vfill",
            "{\\large \\today\\par}",
            "\\end{titlepage}",
            "\\newpage"
        ])
        
        return '\n'.join(cover_latex)
    
    def _classic_cover_template(self, title: str, author: str, cover_image: Optional[str]) -> str:
        """Classic cover page template."""
        
        cover_latex = [
            "\\begin{titlepage}",
            "\\centering",
            "\\vspace*{3cm}",
            "\\rule{\\linewidth}{0.5mm} \\\\[0.4cm]",
            "{\\huge\\bfseries " + self._clean_text_for_latex(title) + "\\par}",
            "\\rule{\\linewidth}{0.5mm} \\\\[1.5cm]",
        ]
        
        if cover_image and os.path.exists(cover_image):
            cover_latex.extend([
                f"\\includegraphics[width=0.5\\textwidth]{{{cover_image}}}",
                "\\vspace{1cm}",
            ])
        
        cover_latex.extend([
            "{\\Large\\itshape " + self._clean_text_for_latex(author) + "\\par}",
            "\\vfill",
            "{\\large \\today\\par}",
            "\\end{titlepage}",
            "\\newpage"
        ])
        
        return '\n'.join(cover_latex)
    
    def _children_cover_template(self, title: str, author: str, cover_image: Optional[str]) -> str:
        """Children's book cover page template."""
        
        cover_latex = [
            "\\begin{titlepage}",
            "\\centering",
            "\\vspace*{1cm}",
        ]
        
        if cover_image and os.path.exists(cover_image):
            cover_latex.extend([
                f"\\includegraphics[width=0.8\\textwidth]{{{cover_image}}}",
                "\\vspace{1cm}",
            ])
        
        cover_latex.extend([
            "{\\Huge\\colorbox{yellow}{\\textcolor{blue}{\\textbf{" + self._clean_text_for_latex(title) + "}}}\\par}",
            "\\vspace{2cm}",
            "{\\LARGE\\textcolor{purple}{\\textbf{" + self._clean_text_for_latex(author) + "}}\\par}",
            "\\vfill",
            "\\end{titlepage}",
            "\\newpage"
        ])
        
        return '\n'.join(cover_latex)
    
    def create_audiobook_companion(self, 
                                  project_id: str, 
                                  output_filename: str) -> Tuple[Optional[str], Optional[str]]:
        """Create an audiobook companion PDF with QR codes or audio instructions."""
        
        project = self.db_manager.get_project(project_id)
        if not project:
            return None, "Project not found"
        
        content_items = self.db_manager.get_project_content(project_id)
        audio_items = [item for item in content_items if item['type'] == 'audio']
        
        if not audio_items:
            return None, "No audio content found in project"
        
        # Generate LaTeX for audiobook companion
        latex_code = self._generate_audiobook_latex(project, audio_items)
        
        # Compile to PDF
        return self.compile_pdf(latex_code, f"{output_filename}_audiobook")
    
    def _generate_audiobook_latex(self, project: Dict, audio_items: List[Dict]) -> str:
        """Generate LaTeX code for audiobook companion."""
        
        latex_sections = [
            "\\documentclass[a5paper,12pt]{article}",
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage{graphicx}",
            "\\usepackage[margin=1in]{geometry}",
            "\\usepackage{hyperref}",
            "\\usepackage{xcolor}",
            "",
            f"\\title{{Audio Companion: {self._clean_text_for_latex(project['name'])}}}",
            "\\author{StoryWeaver AI}",
            "\\date{\\today}",
            "",
            "\\begin{document}",
            "\\maketitle",
            "\\newpage",
            "",
            "\\section*{How to Use This Audiobook}",
            "This companion guide contains instructions for accessing the audio narration of your story.",
            "\\vspace{1em}",
            "",
            "\\section*{Audio Tracks}",
        ]
        
        for i, audio_item in enumerate(audio_items, 1):
            audio_filename = os.path.basename(audio_item['audio_path']) if audio_item['audio_path'] else f"track_{i}.mp3"
            latex_sections.extend([
                f"\\subsection*{{Track {i}}}",
                f"\\textbf{{File:}} {audio_filename}\\\\",
                f"\\textbf{{Duration:}} Approximately {self._estimate_audio_duration(audio_item)} minutes\\\\",
                "\\vspace{1em}",
            ])
        
        latex_sections.extend([
            "",
            "\\end{document}"
        ])
        
        return '\n'.join(latex_sections)
    
    def _estimate_audio_duration(self, audio_item: Dict) -> float:
        """Estimate audio duration based on text length."""
        if audio_item.get('content_text'):
            # Rough estimate: 150 words per minute reading speed
            word_count = len(audio_item['content_text'].split())
            return round(word_count / 150, 1)
        return 1.0  # Default to 1 minute if no text available