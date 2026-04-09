# routes/transcriptionRoute.py
from flask import Blueprint
from controllers.transcriptionController import TranscriptionController

# Create blueprint
transcription_bp = Blueprint('transcription', __name__)

# Main routes
transcription_bp.route('/', methods=['GET'])(TranscriptionController.index)
transcription_bp.route('/upload', methods=['POST'])(TranscriptionController.upload)

# Chunked upload routes
transcription_bp.route('/upload-chunk', methods=['POST'])(TranscriptionController.upload_chunk)
transcription_bp.route('/finalize-upload', methods=['POST'])(TranscriptionController.finalize_upload)
transcription_bp.route('/upload-status/<upload_id>', methods=['GET'])(TranscriptionController.upload_status)
transcription_bp.route('/cancel-upload/<upload_id>', methods=['POST'])(TranscriptionController.cancel_upload)

# Job management routes
transcription_bp.route('/status/<job_id>', methods=['GET'])(TranscriptionController.status)
transcription_bp.route('/transcript/<job_id>', methods=['GET'])(TranscriptionController.download_transcript)
transcription_bp.route('/view/<job_id>', methods=['GET'])(TranscriptionController.view_transcript)
transcription_bp.route('/jobs', methods=['GET'])(TranscriptionController.list_jobs)

# Admin routes
transcription_bp.route('/admin/uploads', methods=['GET'])(TranscriptionController.list_uploads)
transcription_bp.route('/admin/cleanup', methods=['POST'])(TranscriptionController.cleanup_temp_files)