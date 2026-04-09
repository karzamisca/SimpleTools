# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # App settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Upload settings
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    CHUNKS_FOLDER = os.environ.get('CHUNKS_FOLDER') or 'chunks'
    TRANSCRIPTS_FOLDER = os.environ.get('TRANSCRIPTS_FOLDER') or 'transcripts'
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'mp3', 'wav', 'm4a'}
    
    # No MAX_CONTENT_LENGTH limit for chunked uploads
    MAX_CONTENT_LENGTH = None
    
    # Transcription settings
    CHUNK_LENGTH_MINUTES = int(os.environ.get('CHUNK_LENGTH_MINUTES', 3))  # Changed to 3 minutes
    WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'medium')
    
    # Debug mode
    DEBUG = os.environ.get('FLASK_ENV') == 'development'
    
    @staticmethod
    def init_app():
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(Config.CHUNKS_FOLDER, exist_ok=True)
        os.makedirs(Config.TRANSCRIPTS_FOLDER, exist_ok=True)