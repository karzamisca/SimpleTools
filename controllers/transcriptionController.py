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
    def upload_chunk():
        """Handle chunk upload"""
        if 'chunk' not in request.files:
            return jsonify({'error': 'No chunk part'}), 400
        
        chunk_file = request.files['chunk']
        job_id = request.form.get('job_id')
        chunk_index = int(request.form.get('chunk_index', 0))
        total_chunks = int(request.form.get('total_chunks', 1))
        filename = request.form.get('filename')
        language = request.form.get('language', 'en')
        model = request.form.get('model', 'medium')
        
        if not job_id:
            # First chunk - create new job
            job = TranscriptionJob(filename, None, language, model)
            job_id = job.id
            job.total_chunks = total_chunks
        else:
            job = TranscriptionJob.get_job(job_id)
            if not job:
                return jsonify({'error': 'Job not found'}), 404
        
        # Save chunk
        job_chunks_folder = os.path.join(Config.CHUNKS_FOLDER, job_id)
        os.makedirs(job_chunks_folder, exist_ok=True)
        
        chunk_path = os.path.join(job_chunks_folder, f"chunk_{chunk_index}.mp3")
        chunk_file.save(chunk_path)
        
        # Update job progress
        job.received_chunks = job.received_chunks + 1 if hasattr(job, 'received_chunks') else 1
        
        # If all chunks received, start processing
        if job.received_chunks == total_chunks:
            job.start_processing()
        
        return jsonify({
            'job_id': job_id,
            'chunk_index': chunk_index,
            'received': job.received_chunks,
            'total': total_chunks,
            'status': 'processing' if job.received_chunks == total_chunks else 'uploading'
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