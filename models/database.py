import os
import json
import uuid
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any

class DatabaseManager:
    """Handles all database operations for the StoryWeaver AI application."""
    
    def __init__(self, db_path: str = 'storyweaver.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self) -> None:
        """Initialize the database with required tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Projects table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settings TEXT DEFAULT '{}',
                status TEXT DEFAULT 'active'
            )
        ''')
        
        # Content table for storing story scenes, images, audio
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS content (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                type TEXT NOT NULL,
                content_text TEXT,
                image_path TEXT,
                audio_path TEXT,
                order_index INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
            )
        ''')
        
        # Templates table for LaTeX templates
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                latex_template TEXT NOT NULL,
                description TEXT,
                is_default BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User sessions table (for future multi-user support)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id TEXT PRIMARY KEY,
                session_data TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        
        self.insert_default_templates()
    
    def insert_default_templates(self) -> None:
        """Insert default LaTeX templates."""
        templates = [
            {
                'id': 'children_storybook',
                'name': 'Children\'s Storybook',
                'type': 'story',
                'description': 'Colorful and engaging template for children\'s stories',
                'template': '''\\documentclass[a4paper,12pt]{book}
\\usepackage[utf8]{inputenc}
\\usepackage{graphicx}
\\usepackage[margin=1in]{geometry}
\\usepackage{fancyhdr}
\\usepackage{titlesec}
\\usepackage{xcolor}
\\usepackage{tcolorbox}

\\definecolor{storyblue}{RGB}{102,126,234}
\\definecolor{storypurple}{RGB}{118,75,162}

\\title{{\\Huge\\textcolor{storyblue}{{{title}}}}}
\\author{{\\Large\\textcolor{storypurple}{{{author}}}}}
\\date{{\\textcolor{gray}{{{date}}}}}

\\pagestyle{fancy}
\\fancyhf{{}}
\\fancyhead[C]{{\\textcolor{storyblue}{{{title}}}}}
\\fancyfoot[C]{{\\thepage}}

\\begin{{document}}
\\maketitle
\\newpage
\\tableofcontents
\\newpage

{content}

\\end{{document}}'''
            },
            {
                'id': 'comic_book',
                'name': 'Comic Book Style',
                'type': 'comic',
                'description': 'Dynamic layout perfect for comic-style stories',
                'template': '''\\documentclass[a4paper]{article}
\\usepackage[utf8]{inputenc}
\\usepackage{graphicx}
\\usepackage[margin=0.75in]{geometry}
\\usepackage{multicol}
\\usepackage{xcolor}
\\usepackage{tikz}
\\usepackage{tcolorbox}

\\definecolor{comicred}{RGB}{220,20,60}
\\definecolor{comicblue}{RGB}{30,144,255}

\\title{{\\Huge\\textbf{{\\textcolor{comicred}{{{title}}}}}}}
\\date{{\\textcolor{comicblue}{{{date}}}}}

\\begin{{document}}
\\maketitle
\\thispagestyle{{empty}}
\\newpage

{content}

\\end{{document}}'''
            },
            {
                'id': 'educational_book',
                'name': 'Educational Book',
                'type': 'educational',
                'description': 'Clean and professional template for educational content',
                'template': '''\\documentclass[a4paper,11pt]{report}
\\usepackage[utf8]{inputenc}
\\usepackage{graphicx}
\\usepackage[margin=1.2in]{geometry}
\\usepackage{fancyhdr}
\\usepackage{titlesec}
\\usepackage{hyperref}
\\usepackage{tcolorbox}

\\title{{\\LARGE\\textbf{{{title}}}}}
\\author{{{author}}}
\\date{{{date}}}

\\pagestyle{fancy}
\\fancyhf{{}}
\\fancyhead[L]{{\\leftmark}}
\\fancyhead[R]{{{title}}}
\\fancyfoot[C]{{\\thepage}}

\\begin{{document}}
\\maketitle
\\tableofcontents
\\newpage

{content}

\\end{{document}}'''
            }
        ]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for template in templates:
            cursor.execute('''
                INSERT OR REPLACE INTO templates (id, name, type, latex_template, description, is_default)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                template['id'], 
                template['name'], 
                template['type'], 
                template['template'], 
                template['description'], 
                True
            ))
        
        conn.commit()
        conn.close()
    
    def create_project(self, name: str, project_type: str, settings: Optional[Dict] = None) -> str:
        """Create a new project and return its ID."""
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
    
    def get_projects(self, project_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all projects, optionally filtered by type."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if project_type:
            cursor.execute('''
                SELECT * FROM projects 
                WHERE type = ? AND status = 'active' 
                ORDER BY updated_at DESC
            ''', (project_type,))
        else:
            cursor.execute('''
                SELECT * FROM projects 
                WHERE status = 'active' 
                ORDER BY updated_at DESC
            ''')
        
        projects = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': p[0],
                'name': p[1],
                'type': p[2],
                'created_at': p[3],
                'updated_at': p[4],
                'settings': json.loads(p[5]) if p[5] else {},
                'status': p[6]
            }
            for p in projects
        ]
    
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific project by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        project = cursor.fetchone()
        conn.close()
        
        if project:
            return {
                'id': project[0],
                'name': project[1],
                'type': project[2],
                'created_at': project[3],
                'updated_at': project[4],
                'settings': json.loads(project[5]) if project[5] else {},
                'status': project[6]
            }
        return None
    
    def update_project(self, project_id: str, **kwargs) -> bool:
        """Update project fields."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Build dynamic update query
        fields = []
        values = []
        
        for key, value in kwargs.items():
            if key in ['name', 'type', 'status']:
                fields.append(f'{key} = ?')
                values.append(value)
            elif key == 'settings':
                fields.append('settings = ?')
                values.append(json.dumps(value))
        
        if fields:
            fields.append('updated_at = CURRENT_TIMESTAMP')
            query = f"UPDATE projects SET {', '.join(fields)} WHERE id = ?"
            values.append(project_id)
            
            cursor.execute(query, values)
            conn.commit()
        
        conn.close()
        return True
    
    def delete_project(self, project_id: str) -> bool:
        """Soft delete a project by setting status to 'deleted'."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE projects 
            SET status = 'deleted', updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (project_id,))
        
        conn.commit()
        conn.close()
        return True
    
    def add_content(self, project_id: str, content_type: str, 
                   text: Optional[str] = None, 
                   image_path: Optional[str] = None, 
                   audio_path: Optional[str] = None, 
                   order_index: int = 0,
                   metadata: Optional[Dict] = None) -> str:
        """Add content to a project."""
        content_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO content (id, project_id, type, content_text, image_path, audio_path, order_index, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            content_id, project_id, content_type, text, 
            image_path, audio_path, order_index, 
            json.dumps(metadata or {})
        ))
        
        conn.commit()
        conn.close()
        
        return content_id
    
    def get_project_content(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all content for a project."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM content 
            WHERE project_id = ? 
            ORDER BY order_index, created_at
        ''', (project_id,))
        
        content = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': c[0],
                'project_id': c[1],
                'type': c[2],
                'content_text': c[3],
                'image_path': c[4],
                'audio_path': c[5],
                'order_index': c[6],
                'metadata': json.loads(c[7]) if c[7] else {},
                'created_at': c[8]
            }
            for c in content
        ]
    
    def update_content(self, content_id: str, **kwargs) -> bool:
        """Update content fields."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        fields = []
        values = []
        
        for key, value in kwargs.items():
            if key in ['content_text', 'image_path', 'audio_path', 'order_index']:
                fields.append(f'{key} = ?')
                values.append(value)
            elif key == 'metadata':
                fields.append('metadata = ?')
                values.append(json.dumps(value))
        
        if fields:
            query = f"UPDATE content SET {', '.join(fields)} WHERE id = ?"
            values.append(content_id)
            
            cursor.execute(query, values)
            conn.commit()
        
        conn.close()
        return True
    
    def delete_content(self, content_id: str) -> bool:
        """Delete content by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM content WHERE id = ?', (content_id,))
        conn.commit()
        conn.close()
        return True
    
    def get_templates(self, template_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get available templates."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if template_type:
            cursor.execute('''
                SELECT id, name, type, description, is_default, created_at 
                FROM templates WHERE type = ? 
                ORDER BY is_default DESC, name
            ''', (template_type,))
        else:
            cursor.execute('''
                SELECT id, name, type, description, is_default, created_at 
                FROM templates 
                ORDER BY type, is_default DESC, name
            ''')
        
        templates = cursor.fetchall()
        conn.close()
        
        return [
            {
                'id': t[0],
                'name': t[1],
                'type': t[2],
                'description': t[3],
                'is_default': bool(t[4]),
                'created_at': t[5]
            }
            for t in templates
        ]
    
    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific template by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM templates WHERE id = ?', (template_id,))
        template = cursor.fetchone()
        conn.close()
        
        if template:
            return {
                'id': template[0],
                'name': template[1],
                'type': template[2],
                'latex_template': template[3],
                'description': template[4],
                'is_default': bool(template[5]),
                'created_at': template[6]
            }
        return None
    
    def cleanup_old_sessions(self, days: int = 30) -> None:
        """Clean up old user sessions."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM user_sessions 
            WHERE datetime(last_accessed) < datetime('now', '-' || ? || ' days')
        ''', (days,))
        
        conn.commit()
        conn.close()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Count projects by type
        cursor.execute('''
            SELECT type, COUNT(*) as count 
            FROM projects 
            WHERE status = 'active' 
            GROUP BY type
        ''')
        projects_by_type = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Count total content items
        cursor.execute('SELECT COUNT(*) FROM content')
        total_content = cursor.fetchone()[0]
        
        # Count content by type
        cursor.execute('''
            SELECT type, COUNT(*) as count 
            FROM content 
            GROUP BY type
        ''')
        content_by_type = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            'projects_by_type': projects_by_type,
            'total_content': total_content,
            'content_by_type': content_by_type,
            'total_projects': sum(projects_by_type.values())
        }