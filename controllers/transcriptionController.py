# controllers/transcriptionController.py
import os
import json
import shutil
import traceback
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import request, jsonify, send_file, render_template
from models.transcriptionModel import TranscriptionJob
from config import Config

# Store upload sessions with expiration
upload_sessions = {}

def cleanup_expired_sessions():
    """Remove expired upload sessions"""
    current_time = datetime.now()
    expired = []
    for upload_id, session in upload_sessions.items():
        if current_time - session['created_at'] > timedelta(hours=1):
            # Clean up temp files
            if os.path.exists(session['temp_dir']):
                shutil.rmtree(session['temp_dir'])
            expired.append(upload_id)
    
    for upload_id in expired:
        del upload_sessions[upload_id]

class TranscriptionController:
    """Controller for handling transcription requests"""
    
    @staticmethod
    def index():
        """Render the main page"""
        return render_template('transcriptionPages/transcriptionMain.html')
    
    @staticmethod
    def upload():
        """Handle regular file upload (for small files)"""
        try:
            if 'file' not in request.files:
                return jsonify({'error': 'No file part'}), 400
            
            file = request.files['file']
            language = request.form.get('language', 'en')
            
            if file.filename == '':
                return jsonify({'error': 'No selected file'}), 400
            
            if not TranscriptionJob.allowed_file(file.filename):
                return jsonify({'error': f'File type not allowed. Allowed: {Config.ALLOWED_EXTENSIONS}'}), 400
            
            # Check file size
            file.seek(0, 2)
            file_size = file.tell()
            file.seek(0)
            
            if file_size > Config.MAX_CONTENT_LENGTH:
                return jsonify({
                    'error': f'File too large. Maximum size: {Config.MAX_CONTENT_LENGTH / (1024*1024):.0f}MB. Use chunked upload for large files.'
                }), 400
            
            # Save uploaded file
            filename = secure_filename(file.filename)
            job = TranscriptionJob(filename, None, language)
            filepath = os.path.join(Config.UPLOAD_FOLDER, f"{job.id}_{filename}")
            
            os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
            file.save(filepath)
            job.filepath = filepath
            
            # Start processing
            job.start_processing()
            
            return jsonify({
                'job_id': job.id,
                'status': 'queued',
                'filename': filename,
                'upload_method': 'direct'
            })
            
        except Exception as e:
            print(f"Upload error: {str(e)}")
            print(traceback.format_exc())
            return jsonify({'error': f'Upload failed: {str(e)}'}), 500
    
    @staticmethod
    def upload_chunk():
        """Handle chunked file upload"""
        try:
            # Clean up old sessions periodically
            cleanup_expired_sessions()
            
            # Validate required fields
            if 'chunk' not in request.files:
                return jsonify({'error': 'No chunk file provided'}), 400
            
            chunk_file = request.files['chunk']
            upload_id = request.form.get('uploadId')
            chunk_index = request.form.get('chunkIndex')
            total_chunks = request.form.get('totalChunks')
            filename = request.form.get('filename')
            language = request.form.get('language', 'en')
            
            # Validate all required fields
            if not all([upload_id, chunk_index is not None, total_chunks, filename]):
                return jsonify({'error': 'Missing required fields'}), 400
            
            chunk_index = int(chunk_index)
            total_chunks = int(total_chunks)
            filename = secure_filename(filename)
            
            # Validate chunk index
            if chunk_index < 0 or chunk_index >= total_chunks:
                return jsonify({'error': f'Invalid chunk index: {chunk_index}'}), 400
            
            # Create temp directory for this upload
            temp_dir = os.path.join(Config.UPLOAD_FOLDER, f"temp_{upload_id}")
            os.makedirs(temp_dir, exist_ok=True)
            
            # Save chunk
            chunk_path = os.path.join(temp_dir, f"chunk_{chunk_index:06d}.part")
            chunk_file.save(chunk_path)
            
            # Update or create session
            if upload_id not in upload_sessions:
                upload_sessions[upload_id] = {
                    'filename': filename,
                    'language': language,
                    'total_chunks': total_chunks,
                    'chunks_received': set(),
                    'temp_dir': temp_dir,
                    'created_at': datetime.now(),
                    'last_chunk_at': datetime.now(),
                    'file_size': 0
                }
            
            session = upload_sessions[upload_id]
            session['chunks_received'].add(chunk_index)
            session['last_chunk_at'] = datetime.now()
            
            # Calculate total received size
            chunk_size = os.path.getsize(chunk_path)
            session['file_size'] += chunk_size
            
            # Check if all chunks received
            received_count = len(session['chunks_received'])
            is_complete = received_count == total_chunks
            
            # Log progress
            print(f"Chunk upload: {upload_id[:8]}... - Chunk {chunk_index+1}/{total_chunks} ({received_count}/{total_chunks} received)")
            
            response_data = {
                'status': 'chunk_received',
                'upload_id': upload_id,
                'chunk_index': chunk_index,
                'received': received_count,
                'total': total_chunks,
                'progress': (received_count / total_chunks) * 100,
                'is_complete': is_complete
            }
            
            # If all chunks received, automatically finalize
            if is_complete:
                print(f"All chunks received for {upload_id[:8]}... Finalizing...")
                finalize_result = TranscriptionController._finalize_upload_internal(
                    upload_id, session
                )
                response_data.update(finalize_result)
            
            return jsonify(response_data)
            
        except Exception as e:
            print(f"Chunk upload error: {str(e)}")
            print(traceback.format_exc())
            return jsonify({'error': f'Chunk upload failed: {str(e)}'}), 500
    
    @staticmethod
    def finalize_upload():
        """Manually finalize chunked upload"""
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'error': 'No data provided'}), 400
            
            upload_id = data.get('uploadId')
            language = data.get('language', 'en')
            
            if not upload_id:
                return jsonify({'error': 'No upload ID provided'}), 400
            
            if upload_id not in upload_sessions:
                return jsonify({'error': 'Upload session not found or expired'}), 404
            
            session = upload_sessions[upload_id]
            
            # Override language if provided
            if language:
                session['language'] = language
            
            result = TranscriptionController._finalize_upload_internal(upload_id, session)
            return jsonify(result)
            
        except Exception as e:
            print(f"Finalize upload error: {str(e)}")
            print(traceback.format_exc())
            return jsonify({'error': f'Finalize failed: {str(e)}'}), 500
    
    @staticmethod
    def _finalize_upload_internal(upload_id, session):
        """Internal method to combine chunks and create job"""
        try:
            # Verify all chunks are present
            if len(session['chunks_received']) != session['total_chunks']:
                missing = set(range(session['total_chunks'])) - session['chunks_received']
                return {
                    'status': 'incomplete',
                    'error': f'Missing chunks: {sorted(missing)}',
                    'received': len(session['chunks_received']),
                    'total': session['total_chunks']
                }
            
            print(f"Combining {session['total_chunks']} chunks for {upload_id[:8]}...")
            
            # Create job
            filename = secure_filename(session['filename'])
            language = session['language']
            job = TranscriptionJob(filename, None, language)
            final_path = os.path.join(Config.UPLOAD_FOLDER, f"{job.id}_{filename}")
            
            # Combine all chunks in order
            total_bytes = 0
            with open(final_path, 'wb') as outfile:
                for i in range(session['total_chunks']):
                    chunk_path = os.path.join(session['temp_dir'], f"chunk_{i:06d}.part")
                    
                    if not os.path.exists(chunk_path):
                        raise Exception(f"Chunk file missing: {i}")
                    
                    with open(chunk_path, 'rb') as infile:
                        chunk_data = infile.read()
                        outfile.write(chunk_data)
                        total_bytes += len(chunk_data)
            
            print(f"Combined file size: {total_bytes / (1024*1024):.2f} MB")
            
            # Verify file was created
            if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
                raise Exception("Failed to create combined file")
            
            # Clean up temp directory
            try:
                shutil.rmtree(session['temp_dir'])
                print(f"Cleaned up temp directory: {session['temp_dir']}")
            except Exception as e:
                print(f"Warning: Could not cleanup temp dir: {e}")
            
            # Remove session
            del upload_sessions[upload_id]
            
            # Start transcription
            job.filepath = final_path
            job.start_processing()
            
            return {
                'status': 'completed',
                'job_id': job.id,
                'filename': filename,
                'file_size': total_bytes,
                'upload_method': 'chunked',
                'chunks_processed': session['total_chunks']
            }
            
        except Exception as e:
            print(f"Internal finalize error: {str(e)}")
            print(traceback.format_exc())
            
            # Don't delete session on error so user can retry
            return {
                'status': 'error',
                'error': str(e),
                'upload_id': upload_id
            }
    
    @staticmethod
    def upload_status(upload_id):
        """Check status of chunked upload"""
        try:
            if upload_id not in upload_sessions:
                return jsonify({'error': 'Upload session not found'}), 404
            
            session = upload_sessions[upload_id]
            
            return jsonify({
                'upload_id': upload_id,
                'filename': session['filename'],
                'total_chunks': session['total_chunks'],
                'received': len(session['chunks_received']),
                'progress': (len(session['chunks_received']) / session['total_chunks']) * 100,
                'file_size': session['file_size'],
                'created_at': session['created_at'].isoformat(),
                'last_chunk_at': session['last_chunk_at'].isoformat(),
                'chunks_missing': sorted(set(range(session['total_chunks'])) - session['chunks_received'])
            })
            
        except Exception as e:
            print(f"Upload status error: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    @staticmethod
    def cancel_upload(upload_id):
        """Cancel and cleanup chunked upload"""
        try:
            if upload_id not in upload_sessions:
                return jsonify({'error': 'Upload session not found'}), 404
            
            session = upload_sessions[upload_id]
            
            # Clean up temp directory
            if os.path.exists(session['temp_dir']):
                shutil.rmtree(session['temp_dir'])
            
            # Remove session
            del upload_sessions[upload_id]
            
            return jsonify({
                'status': 'cancelled',
                'upload_id': upload_id
            })
            
        except Exception as e:
            print(f"Cancel upload error: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
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
    
    @staticmethod
    def list_uploads():
        """List all active upload sessions (admin only)"""
        try:
            uploads = []
            for upload_id, session in upload_sessions.items():
                uploads.append({
                    'upload_id': upload_id,
                    'filename': session['filename'],
                    'progress': (len(session['chunks_received']) / session['total_chunks']) * 100,
                    'created_at': session['created_at'].isoformat(),
                    'last_activity': session['last_chunk_at'].isoformat()
                })
            
            return jsonify({
                'active_uploads': len(uploads),
                'uploads': uploads
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @staticmethod
    def cleanup_temp_files():
        """Manually cleanup all temp files (admin only)"""
        try:
            cleaned = 0
            temp_pattern = os.path.join(Config.UPLOAD_FOLDER, "temp_*")
            import glob
            
            for temp_dir in glob.glob(temp_pattern):
                try:
                    shutil.rmtree(temp_dir)
                    cleaned += 1
                except Exception as e:
                    print(f"Error cleaning {temp_dir}: {e}")
            
            upload_sessions.clear()
            
            return jsonify({
                'status': 'cleaned',
                'directories_removed': cleaned
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500