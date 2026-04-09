# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # App settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Upload settings
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    CHUNKS_FOLDER = os.environ.get('CHUNKS_FOLDER') or 'chunks'
    TRANSCRIPTS_FOLDER = os.environ.get('TRANSCRIPTS_FOLDER') or 'transcripts'
    TEMP_FOLDER = os.environ.get('TEMP_FOLDER') or 'temp_uploads'
    ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'mp3', 'wav', 'm4a'}
    
    # Size limits
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB for direct upload
    MAX_CHUNK_SIZE = int(os.environ.get('MAX_CHUNK_SIZE', 10 * 1024 * 1024))  # 10MB per chunk
    
    # Transcription settings
    CHUNK_LENGTH_MINUTES = int(os.environ.get('CHUNK_LENGTH_MINUTES', 5))
    WHISPER_MODEL = os.environ.get('WHISPER_MODEL', 'medium')
    
    # Session settings
    UPLOAD_SESSION_TIMEOUT = int(os.environ.get('UPLOAD_SESSION_TIMEOUT', 3600))  # 1 hour
    
    @staticmethod
    def init_app():
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(Config.CHUNKS_FOLDER, exist_ok=True)
        os.makedirs(Config.TRANSCRIPTS_FOLDER, exist_ok=True)
        os.makedirs(Config.TEMP_FOLDER, exist_ok=True)