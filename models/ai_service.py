import os
import json
import time
import base64
import asyncio
from io import BytesIO
from typing import Optional, Dict, List, Tuple, Any
from PIL import Image
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

from google import genai
from google.genai import types

class RateLimiter:
    """Simple rate limiter for API calls."""
    
    def __init__(self, max_requests: int = 20, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    def can_make_request(self) -> bool:
        """Check if a new request can be made."""
        now = time.time()
        # Remove old requests outside the time window
        self.requests = [req_time for req_time in self.requests if now - req_time < self.time_window]
        
        return len(self.requests) < self.max_requests
    
    def add_request(self) -> None:
        """Record a new request."""
        self.requests.append(time.time())
    
    def time_until_next_request(self) -> float:
        """Get seconds until next request is allowed."""
        if self.can_make_request():
            return 0
        
        oldest_request = min(self.requests)
        return self.time_window - (time.time() - oldest_request)

class AIService:
    """Handles all AI service integrations including Gemini and ElevenLabs."""
    
    def __init__(self):
        self.gemini_client = genai.Client(
            api_key=os.getenv('GEMINI_API_KEY')
        )
        self.elevenlabs_api_key = os.getenv('ELEVENLABS_API_KEY')
        self.elevenlabs_voice_id = os.getenv('ELEVENLABS_VOICE_ID', '21m00Tcm4TlvDq8ikWAM') # Jessica's Voice ID
        self.elevenlabs_client = ElevenLabs(api_key=self.elevenlabs_api_key)
        
        # Rate limiters
        self.image_limiter = RateLimiter(max_requests=20, time_window=60)
        self.text_limiter = RateLimiter(max_requests=50, time_window=60)
        self.audio_limiter = RateLimiter(max_requests=10, time_window=60)
    
    def check_api_keys(self) -> Dict[str, bool]:
        """Check if required API keys are configured."""
        return {
            'gemini': bool(os.getenv('GEMINI_API_KEY')),
            'elevenlabs': bool(os.getenv('ELEVENLABS_API_KEY'))
        }
    
    def generate_story_structure(self, 
                                     character_name: str,
                                     character_friend: str,
                                     setting: str,
                                     moral: str,
                                     num_scenes: int = 3) -> Optional[Dict[str, Any]]:
        """Generate a complete story structure with scenes."""
        
        if not self.text_limiter.can_make_request():
            return None, "Text generation rate limit exceeded"
        
        prompt = f"""
        Create a sophisticated {num_scenes}-scene story with these elements:
        
        Main Character: {character_name}
        Friend/Companion: {character_friend}
        Setting: {setting}
        Theme/Moral: {moral}
        
        Please format your response as a JSON object with this exact structure:
        {{
            "title": "An engaging and powerful story title",
            "summary": "A brief, compelling summary of the story",
            "scenes": [
                {{
                    "scene_number": 1,
                    "title": "Scene title",
                    "text": "The narrative text for this scene, written with engaging and sophisticated language.",
                    "image_prompt": "A highly detailed, vivid, and powerful visual description for an advanced AI image generator. The prompt should specify character appearances, intricate setting details, dramatic mood, a specific art style (e.g., photorealistic, digital painting, cinematic), and camera angle. Aim for a prompt that will produce an 8K resolution masterpiece.",
                    "key_emotions": ["emotion1", "emotion2"],
                    "dialogue": "Any dialogue in this scene"
                }}
            ]
        }}
        
        Guidelines:
        - Use rich, evocative language.
        - Each scene must powerfully advance the story and its theme.
        - Image prompts must be exceptionally detailed and consistent with character descriptions to generate cinematic, high-quality visuals.
        - Include vivid sensory details to create an immersive experience.
        - Ensure the theme is woven naturally and thoughtfully into the narrative.
        """
        
        try:
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Content(parts=[types.Part.from_text(text=prompt)])]
            )
            
            self.text_limiter.add_request()
            
            if response and response.candidates and response.candidates[0].content:
                text = response.candidates[0].content.parts[0].text
                
                # Clean and parse JSON response
                text = text.strip()
                if text.startswith('```json'):
                    text = text[7:]
                if text.endswith('```'):
                    text = text[:-3]
                
                story_data = json.loads(text.strip())
                
                # Validate the structure
                if self._validate_story_structure(story_data):
                    return story_data, None
                else:
                    return None, "Invalid story structure generated"
            return None, "Failed to generate story"

        except Exception as e:
            return None, f"Story generation error: {str(e)}"
    
    def _validate_story_structure(self, story_data: Dict) -> bool:
        """Validate the generated story structure."""
        required_keys = ['title', 'scenes']
        if not all(key in story_data for key in required_keys):
            return False
        
        if not isinstance(story_data['scenes'], list) or not story_data['scenes']:
            return False
        
        for scene in story_data['scenes']:
            required_scene_keys = ['title', 'text', 'image_prompt']
            if not all(key in scene for key in required_scene_keys):
                return False
        
        return True
    
    def generate_image(self, 
                           prompt: str, 
                           style: str = "realistic",
                           character_consistency: Optional[Dict] = None) -> Tuple[Optional[str], Optional[str]]:
        """Generate an image based on text prompt."""
        
        if not self.image_limiter.can_make_request():
            wait_time = self.image_limiter.time_until_next_request()
            return None, f"Image generation rate limit exceeded. Try again in {int(wait_time)} seconds."
        
        # Enhanced prompt with style and consistency
        full_prompt = self._build_image_prompt(prompt, style, character_consistency)
        
        try:
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash-image-preview",
                contents=[full_prompt]
            )
            
            self.image_limiter.add_request()
            
            image_parts = [
                part.inline_data.data
                for part in response.candidates[0].content.parts
                if part.inline_data
            ]
            
            if image_parts:
                return image_parts[0], None
            return None, "Failed to generate image"

        except Exception as e:
            return None, f"Image generation error: {str(e)}"
    
    def _build_image_prompt(self, 
                          base_prompt: str, 
                          style: str,
                          character_consistency: Optional[Dict] = None) -> str:
        """Build an enhanced image generation prompt."""
        
        style_guides = {
            "watercolor": "hyperrealistic watercolor painting, intricate details, vibrant and rich colors, dramatic lighting, masterful brush strokes, professional art",
            "comic": "gritty comic book art style, cinematic panels, detailed line work by a master artist like Jim Lee, dynamic action poses, atmospheric coloring",
            "realistic": "hyperrealistic photograph, 8K resolution, shot on a professional DSLR camera with a prime lens, cinematic lighting, ultra-detailed textures, photorealistic",
            "cartoon": "feature film animation style, 3D render like Pixar or DreamWorks, expressive characters, beautiful lighting and shading, cinematic composition",
            "oil-painting": "masterpiece oil painting in the style of the old masters, rich textures, dramatic chiaroscuro lighting, classical composition, incredible detail",
            "digital-art": "trending on ArtStation, epic digital painting, concept art, highly detailed, by a world-renowned digital artist, volumetric lighting, matte painting"
        }
        
        enhanced_prompt = base_prompt
        
        # Add character consistency if provided
        if character_consistency:
            consistency_details = []
            if 'appearance' in character_consistency:
                consistency_details.append(f"The character must have these features: {character_consistency['appearance']}")
            if 'clothing' in character_consistency:
                consistency_details.append(f"The character must be wearing: {character_consistency['clothing']}")
            
            if consistency_details:
                enhanced_prompt += f". {'. '.join(consistency_details)}"
        
        # Add style guide
        style_guide = style_guides.get(style, style_guides["realistic"])
        enhanced_prompt += f". Art Style: {style_guide}"
        
        # Add quality and technical specifications for powerful, advanced images
        enhanced_prompt += """. 
**Technical Quality**: Masterpiece, 8K resolution, ultra-high definition, photorealistic, hyper-detailed, sharp focus, professional color grading, Unreal Engine 5 render.
**Artistic Elements**: Cinematic lighting, epic composition, dramatic angle, breathtaking, award-winning photography, professional concept art.
**Negative Prompt**: Avoid blurry, low-quality, cartoonish, simple, amateurish, deformed, disfigured, watermark, signature."""
        
        return enhanced_prompt
    
    def modify_image(self, 
                         image_data: str, 
                         modification_prompt: str,
                         preserve_style: bool = True) -> Tuple[Optional[str], Optional[str]]:
        """Modify an existing image based on instructions."""
        
        if not self.image_limiter.can_make_request():
            wait_time = self.image_limiter.time_until_next_request()
            return None, f"Image modification rate limit exceeded. Try again in {int(wait_time)} seconds."
        
        try:
            # Convert base64 to PIL Image
            image = Image.open(BytesIO(base64.b64decode(image_data)))
            
            # Build modification prompt
            full_prompt = modification_prompt
            if preserve_style:
                full_prompt += ". Enhance the image while strictly maintaining the original art style, color palette, and core composition. The modification should be seamless, photorealistic, and of the highest quality, matching the detail and lighting of the source image. The final result should be 8K resolution."
            
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash-image-preview",
                contents=[full_prompt, image]
            )
            
            self.image_limiter.add_request()
            
            image_parts = [
                part.inline_data.data
                for part in response.candidates[0].content.parts
                if part.inline_data
            ]
            
            if image_parts:
                return image_parts[0], None
            return None, "Failed to modify image"

        except Exception as e:
            return None, f"Image modification error: {str(e)}"
    
    def combine_images(self, 
                           image1_data: str, 
                           image2_data: str, 
                           combination_prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """Combine two images based on instructions."""
        
        if not self.image_limiter.can_make_request():
            wait_time = self.image_limiter.time_until_next_request()
            return None, f"Image combination rate limit exceeded. Try again in {int(wait_time)} seconds."
        
        try:
            image1 = Image.open(BytesIO(base64.b64decode(image1_data)))
            image2 = Image.open(BytesIO(base64.b64decode(image2_data)))
            
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash-image-preview",
                contents=[image1, image2, combination_prompt]
            )
            
            self.image_limiter.add_request()
            
            image_parts = [
                part.inline_data.data
                for part in response.candidates[0].content.parts
                if part.inline_data
            ]
            
            if image_parts:
                return image_parts[0], None
            return None, "Failed to combine images"

        except Exception as e:
            return None, f"Image combination error: {str(e)}"
    
    def add_logo_to_image(self, 
                              base_image_data: str, 
                              logo_image_data: str, 
                              placement_instructions: str = "Place the logo appropriately on the clothing/product") -> Tuple[Optional[str], Optional[str]]:
        """Add a logo to an existing image."""
        
        prompt = f"""
        Apply the provided logo to the base image, following these instructions: '{placement_instructions}'.
        **Strict Requirements for a Photorealistic Result**:
        - **Seamless Integration**: The logo must blend perfectly with the surface texture (e.g., fabric weave, material reflections, surface curvature).
        - **Realistic Lighting**: The logo must accurately adopt the lighting, shadows, and highlights of the base image. It should not look 'pasted on'.
        - **Perspective Matching**: The logo must be warped and angled to perfectly match the perspective of the surface it is on.
        - **High Fidelity**: Maintain the logo's original clarity, proportions, and color. The final output must be high-resolution and artifact-free.
        - **Minimal Impact**: The base image must remain completely unchanged except for the addition of the logo.
        """
        
        return self.combine_images(base_image_data, logo_image_data, prompt)
    
    def generate_audio_narration(self, 
                                     text: str, 
                                     voice_settings: Optional[Dict] = None) -> Tuple[Optional[bytes], Optional[str]]:
        """Generate audio narration using ElevenLabs API."""
        
        if not self.audio_limiter.can_make_request():
            wait_time = self.audio_limiter.time_until_next_request()
            return None, f"Audio generation rate limit exceeded. Try again in {int(wait_time)} seconds."
        
        if not self.elevenlabs_api_key:
            return None, "ElevenLabs API key not configured"
        
        try:
            # Default voice settings optimized for storytelling
            default_settings = {
                "stability": 0.6,
                "similarity_boost": 0.8,
                "style": 0.2,
                "use_speaker_boost": True
            }
            
            if voice_settings:
                default_settings.update(voice_settings)

            response = self.elevenlabs_client.text_to_speech.stream(
                voice_id=self.elevenlabs_voice_id,
                output_format="mp3_22050_32",
                text=text,
                model_id="eleven_multilingual_v2",
                voice_settings=VoiceSettings(**default_settings),
            )

            self.audio_limiter.add_request()

            # Stream the audio into a BytesIO object
            audio_stream = BytesIO()
            for chunk in response:
                if chunk:
                    audio_stream.write(chunk)
            
            audio_stream.seek(0)
            return audio_stream.read(), None

        except Exception as e:
            return None, f"Audio generation error: {str(e)}"
    
    def generate_book_content(self, 
                                  title: str, 
                                  book_type: str,
                                  theme: str,
                                  chapter_count: int = 5) -> Tuple[Optional[Dict], Optional[str]]:
        """Generate structured book content."""
        
        if not self.text_limiter.can_make_request():
            return None, "Text generation rate limit exceeded"
        
        prompt = f"""
        Create a sophisticated {book_type} book titled "{title}" with the following specifications:
        
        - Theme: {theme}
        - Number of Chapters: {chapter_count}
        - Book Type: {book_type}
        
        Please format your response as a JSON object with this structure:
        {{
            "title": "{title}",
            "subtitle": "An engaging and thought-provoking subtitle",
            "author": "AI Publishing Pro",
            "theme": "{theme}",
            "book_type": "{book_type}",
            "chapters": [
                {{
                    "chapter_number": 1,
                    "title": "Chapter title",
                    "content": "Well-written chapter content with rich vocabulary and complex ideas.",
                    "image_suggestions": ["A detailed, powerful prompt for an AI image generator to create a cinematic, 8K resolution image for this chapter.", "Another highly descriptive image prompt."],
                    "key_points": ["Insightful Point 1", "Profound Point 2"]
                }}
            ],
            "conclusion": "A powerful conclusion that summarizes the core message."
        }}
        
        Make the content engaging, sophisticated, and insightful.
        """
        
        try:
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Content(parts=[types.Part.from_text(text=prompt)])]
            )
            
            self.text_limiter.add_request()
            
            if response and response.candidates and response.candidates[0].content:
                text = response.candidates[0].content.parts[0].text
                
                # Clean and parse JSON response
                text = text.strip()
                if text.startswith('```json'):
                    text = text[7:]
                if text.endswith('```'):
                    text = text[:-3]
                
                book_data = json.loads(text.strip())
                return book_data, None
            return None, "Failed to generate book content"

        except json.JSONDecodeError as e:
            return None, f"Failed to parse book JSON: {str(e)}"
        except Exception as e:
            return None, f"Book generation error: {str(e)}"
    
    def generate_latex_from_content(self, 
                                        book_data: Dict,
                                        template_type: str = "storybook") -> Tuple[Optional[str], Optional[str]]:
        """Generate LaTeX code from book content."""
        
        if not self.text_limiter.can_make_request():
            return None, "Text generation rate limit exceeded"
        
        prompt = f"""
        Convert the following book data into professionally formatted LaTeX code using a modern, elegant {template_type} style:
        
        Book Data:
        {json.dumps(book_data, indent=2)}
        
        Requirements:
        - Use a professional LaTeX document class (like memoir or KOMA-Script) and relevant packages (graphicx, geometry, etc.).
        - Include flawless formatting for titles, chapters, sections, and body content.
        - Add placeholders like `\\includegraphics[width=\\textwidth]{{placeholder.png}}` for images.
        - Ensure the code is clean, well-commented, and compiles perfectly with pdflatex.
        - Design for visual appeal and professional typography (ligatures, kerning, spacing).
        - Automatically generate a table of contents.
        
        Return only the raw LaTeX code inside a single block, with no explanations or markdown formatting.
        """
        
        try:
            response = self.gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Content(parts=[types.Part.from_text(text=prompt)])]
            )
            
            self.text_limiter.add_request()
            
            if response and response.candidates and response.candidates[0].content:
                latex_code = response.candidates[0].content.parts[0].text.strip()
                
                # Clean up the LaTeX code
                if latex_code.startswith('```latex'):
                    latex_code = latex_code[8:]
                if latex_code.startswith('```'):
                    latex_code = latex_code[3:]
                if latex_code.endswith('```'):
                    latex_code = latex_code[:-3]
                
                return latex_code.strip(), None
            return None, "Failed to generate LaTeX code"

        except Exception as e:
            return None, f"LaTeX generation error: {str(e)}"
    
    async def enhance_image_prompt(self, 
                                 base_prompt: str, 
                                 enhancement_type: str = "quality") -> str:
        """Enhance an image prompt for better results."""
        
        enhancements = {
            "quality": "masterpiece, 8K, ultra high definition, intricate details, professional grade, sharp focus",
            "artistic": "artistically composed, award-winning, stunningly beautiful lighting, aesthetically perfect, emotionally resonant",
            "realistic": "hyperrealistic, photorealistic, Unreal Engine 5 render, lifelike textures, natural lighting, accurate physics",
            "stylized": "highly stylized digital painting, unique and coherent art style, creative masterpiece, vibrant color theory",
            "dramatic": "dramatic cinematic lighting, volumetric light, epic and dynamic composition, high emotional impact, intense atmosphere"
        }
        
        enhancement = enhancements.get(enhancement_type, enhancements["quality"])
        return f"{base_prompt}, {enhancement}."
    
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get current rate limit status for all services."""
        return {
            "image_generation": {
                "can_make_request": self.image_limiter.can_make_request(),
                "requests_made": len(self.image_limiter.requests),
                "max_requests": self.image_limiter.max_requests,
                "time_until_reset": max(0, self.image_limiter.time_until_next_request())
            },
            "text_generation": {
                "can_make_request": self.text_limiter.can_make_request(),
                "requests_made": len(self.text_limiter.requests),
                "max_requests": self.text_limiter.max_requests,
                "time_until_reset": max(0, self.text_limiter.time_until_next_request())
            },
            "audio_generation": {
                "can_make_request": self.audio_limiter.can_make_request(),
                "requests_made": len(self.audio_limiter.requests),
                "max_requests": self.audio_limiter.max_requests,
                "time_until_reset": max(0, self.audio_limiter.time_until_next_request())
            }
        }
    
    def batch_generate_images(self, 
                                  prompts: List[str], 
                                  style: str = "realistic",
                                  max_concurrent: int = 3) -> List[Tuple[Optional[str], Optional[str]]]:
        """Generate multiple images with controlled concurrency."""
        
        # This function uses asyncio which might be complex in a standard Flask setup.
        # It's recommended to run this in a separate thread or with an async-capable server (like Uvicorn).
        async def run_batch():
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def generate_single(prompt):
                async with semaphore:
                    # In an async context, we'd ideally use an async version of the Gemini client.
                    # For simplicity, we run the synchronous function in a thread pool.
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(
                        None, self.generate_image, prompt, style
                    )

            tasks = [generate_single(prompt) for prompt in prompts]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            processed_results = []
            for result in results:
                if isinstance(result, Exception):
                    processed_results.append((None, str(result)))
                else:
                    processed_results.append(result)
            return processed_results

        return asyncio.run(run_batch())
    
    def estimate_generation_time(self, 
                               num_scenes: int, 
                               generate_audio: bool = True,
                               generate_images: bool = True) -> Dict[str, float]:
        """Estimate time for content generation."""
        
        estimates = {
            "story_text": 20,  # seconds
            "per_image": 30,   # seconds per image (higher quality takes longer)
            "per_audio": 15    # seconds per audio clip
        }
        
        total_time = estimates["story_text"]
        
        if generate_images:
            total_time += num_scenes * estimates["per_image"]
        
        if generate_audio:
            total_time += num_scenes * estimates["per_audio"]
        
        return {
            "estimated_seconds": total_time,
            "estimated_minutes": round(total_time / 60, 1),
            "breakdown": {
                "story_generation": estimates["story_text"],
                "image_generation": num_scenes * estimates["per_image"] if generate_images else 0,
                "audio_generation": num_scenes * estimates["per_audio"] if generate_audio else 0
            }
        }