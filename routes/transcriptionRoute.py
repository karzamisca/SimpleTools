# routes/transcriptionRoute.py
from flask import Blueprint
from controllers.transcriptionController import TranscriptionController

# Create blueprint
transcription_bp = Blueprint('transcription', __name__)

# Define routes
transcription_bp.route('/', methods=['GET'])(TranscriptionController.index)
transcription_bp.route('/upload', methods=['POST'])(TranscriptionController.upload)
transcription_bp.route('/status/<job_id>', methods=['GET'])(TranscriptionController.status)
transcription_bp.route('/transcript/<job_id>', methods=['GET'])(TranscriptionController.download_transcript)
transcription_bp.route('/view/<job_id>', methods=['GET'])(TranscriptionController.view_transcript)
transcription_bp.route('/jobs', methods=['GET'])(TranscriptionController.list_jobs)