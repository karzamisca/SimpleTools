# models/transcriptionModel.py
import os
import uuid
import whisper
import threading
from datetime import datetime
from pydub import AudioSegment
from config import Config

class TranscriptionJob:
    """Model for transcription job data and operations"""
    
    # Class variable to store all jobs
    _jobs = {}
    _models = {}
    
    def __init__(self, filename, filepath, language='en', model='medium'):
        self.id = str(uuid.uuid4())
        self.filename = filename
        self.filepath = filepath
        self.language = language
        self.model = model
        self.status = 'uploading'  # New initial status
        self.progress = 0
        self.current_chunk = None
        self.transcript_path = None
        self.transcript_text = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.total_chunks = 0
        self.received_chunks = 0
        
        # Store in class dictionary
        TranscriptionJob._jobs[self.id] = self
    
    @classmethod
    def get_model(cls, model_name='medium'):
        """Lazy load Whisper model with caching per model type"""
        if model_name not in cls._models:
            print(f"Loading Whisper model: {model_name}...")
            device = "cpu"
            cls._models[model_name] = whisper.load_model(model_name)
            print(f"Model {model_name} loaded!")
        return cls._models[model_name]
    
    @classmethod
    def get_job(cls, job_id):
        """Get a specific job by ID"""
        return cls._jobs.get(job_id)
    
    @classmethod
    def get_all_jobs(cls):
        """Get all jobs"""
        return list(cls._jobs.values())
    
    @classmethod
    def allowed_file(cls, filename):
        """Check if file extension is allowed"""
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS
    
    def to_dict(self):
        """Convert job to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'filename': self.filename,
            'status': self.status,
            'progress': self.progress,
            'current_chunk': self.current_chunk,
            'language': self.language,
            'model': self.model,
            'created_at': self.created_at,
            'error': self.error,
            'received_chunks': self.received_chunks,
            'total_chunks': self.total_chunks
        }
    
    def process(self):
        """Process the transcription in background thread"""
        try:
            self.status = 'processing'
            self.progress = 0
            
            # Load the specific model for this job
            model = self.get_model(self.model)
            
            # Get all chunks from the chunks folder
            job_chunks_folder = os.path.join(Config.CHUNKS_FOLDER, self.id)
            chunks = []
            
            # Sort chunks by index
            for i in range(self.total_chunks):
                chunk_file = os.path.join(job_chunks_folder, f"chunk_{i}.mp3")
                if os.path.exists(chunk_file):
                    chunks.append(chunk_file)
            
            # Transcribe chunks
            final_text = ""
            language_param = None if self.language == 'auto' else self.language
            
            for idx, chunk_file in enumerate(chunks):
                self.current_chunk = f"{idx+1}/{len(chunks)}"
                result = model.transcribe(chunk_file, language=language_param)
                final_text += result["text"] + "\n"
                self.progress = int((idx + 1) / len(chunks) * 100)
            
            # Save transcription
            self.transcript_path = os.path.join(Config.TRANSCRIPTS_FOLDER, f"{self.id}.txt")
            with open(self.transcript_path, "w", encoding="utf-8") as f:
                f.write(final_text)
            
            self.transcript_text = final_text[:500] + "..." if len(final_text) > 500 else final_text
            
            # Clean up chunks
            for chunk_file in chunks:
                os.remove(chunk_file)
            if os.path.exists(job_chunks_folder):
                os.rmdir(job_chunks_folder)
            
            self.status = 'completed'
            self.progress = 100
            
        except Exception as e:
            self.status = 'error'
            self.error = str(e)
            print(f"Error in job {self.id}: {str(e)}")
    
    def start_processing(self):
        """Start background processing thread"""
        thread = threading.Thread(target=self.process)
        thread.daemon = True
        thread.start()
        return self.id
    
    def get_transcript_content(self):
        """Read transcript content from file"""
        if self.transcript_path and os.path.exists(self.transcript_path):
            with open(self.transcript_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None