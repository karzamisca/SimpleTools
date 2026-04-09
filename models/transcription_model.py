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
    _model = None
    
    def __init__(self, filename, filepath, language='en'):
        self.id = str(uuid.uuid4())
        self.filename = filename
        self.filepath = filepath
        self.language = language
        self.status = 'queued'
        self.progress = 0
        self.current_chunk = None
        self.transcript_path = None
        self.transcript_text = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        
        # Store in class dictionary
        TranscriptionJob._jobs[self.id] = self
    
    @classmethod
    def get_model(cls):
        """Lazy load Whisper model"""
        if cls._model is None:
            print(f"Loading Whisper model: {Config.WHISPER_MODEL}...")
            cls._model = whisper.load_model(Config.WHISPER_MODEL)
            print("Model loaded!")
        return cls._model
    
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
            'created_at': self.created_at,
            'error': self.error
        }
    
    def process(self):
        """Process the transcription in background thread"""
        try:
            self.status = 'processing'
            self.progress = 0
            
            model = self.get_model()
            
            # Convert to audio and split into chunks
            audio = AudioSegment.from_file(self.filepath)
            chunk_length_ms = Config.CHUNK_LENGTH_MINUTES * 60 * 1000
            
            chunks = []
            job_chunks_folder = os.path.join(Config.CHUNKS_FOLDER, self.id)
            os.makedirs(job_chunks_folder, exist_ok=True)
            
            total_chunks = (len(audio) + chunk_length_ms - 1) // chunk_length_ms
            
            # Create chunks
            for i, start in enumerate(range(0, len(audio), chunk_length_ms)):
                end = min(start + chunk_length_ms, len(audio))
                chunk = audio[start:end]
                chunk_name = os.path.join(job_chunks_folder, f"chunk_{i}.mp3")
                chunk.export(chunk_name, format="mp3")
                chunks.append(chunk_name)
                self.progress = int((i + 1) / total_chunks * 30)
                print(f"Created chunk {i+1}/{total_chunks}")
            
            # Transcribe chunks
            final_text = ""
            language_param = None if self.language == 'auto' else self.language
            
            for idx, chunk_file in enumerate(chunks):
                self.current_chunk = f"{idx+1}/{len(chunks)}"
                result = model.transcribe(chunk_file, language=language_param)
                final_text += result["text"] + "\n"
                self.progress = 30 + int((idx + 1) / len(chunks) * 70)
            
            # Save transcription
            self.transcript_path = os.path.join(Config.TRANSCRIPTS_FOLDER, f"{self.id}.txt")
            with open(self.transcript_path, "w", encoding="utf-8") as f:
                f.write(final_text)
            
            self.transcript_text = final_text[:500] + "..." if len(final_text) > 500 else final_text
            
            # Clean up chunks
            for chunk_file in chunks:
                os.remove(chunk_file)
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