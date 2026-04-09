# controllers/transcriptionController.py
import os
from werkzeug.utils import secure_filename
from flask import request, jsonify, send_file, render_template
from models.transcriptionModel import TranscriptionJob
from config import Config

class TranscriptionController:
    """Controller for handling transcription requests"""
    
    @staticmethod
    def index():
        """Render the main page"""
        return render_template('transcriptionPages/transcriptionMain.html')
    
    @staticmethod
    def upload():
        """Handle file upload and start transcription job"""
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        language = request.form.get('language', 'en')
        model = request.form.get('model', 'medium')  # Added model selection with 'medium' as default
        
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if not TranscriptionJob.allowed_file(file.filename):
            return jsonify({'error': 'File type not allowed'}), 400
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        job = TranscriptionJob(filename, None, language, model)  # Pass model parameter
        filepath = os.path.join(Config.UPLOAD_FOLDER, f"{job.id}_{filename}")
        file.save(filepath)
        job.filepath = filepath
        
        # Start processing
        job.start_processing()
        
        return jsonify({
            'job_id': job.id, 
            'status': 'queued',
            'model': model  # Include model in response
        })
    
    @staticmethod
    def status(job_id):
        """Get job status"""
        job = TranscriptionJob.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        return jsonify(job.to_dict())
    
    @staticmethod
    def download_transcript(job_id):
        """Download transcript file"""
        job = TranscriptionJob.get_job(job_id)
        if not job:
            return jsonify({'error': 'Job not found'}), 404
        
        if job.status != 'completed':
            return jsonify({'error': 'Transcription not ready'}), 400
        
        return send_file(
            job.transcript_path,
            as_attachment=True,
            download_name=f"transcript_{job.filename}.txt"
        )
    
    @staticmethod
    def view_transcript(job_id):
        """View transcript in browser"""
        job = TranscriptionJob.get_job(job_id)
        if not job:
            return "Job not found", 404
        
        if job.status != 'completed':
            return "Transcription not ready yet", 400
        
        content = job.get_transcript_content()
        if not content:
            return "Transcript not found", 404
        
        return render_template('transcriptionPages/transcriptionReview.html', 
                             view='transcriptionPages',
                             content=content,
                             filename=job.filename,
                             job_id=job_id)
    
    @staticmethod
    def list_jobs():
        """List all jobs"""
        jobs = TranscriptionJob.get_all_jobs()
        return jsonify([job.to_dict() for job in jobs])