# controllers/scraperZLibraryController.py
from typing import Dict
from flask import render_template, request, jsonify, Response
from models.scraperZLibraryModel import ZLibraryScraperModel
import json


class ScraperController:
    """Controller handling all business logic for book scraping"""
    
    _model = ZLibraryScraperModel()
    
    @classmethod
    def index(cls):
        """Render the search page"""
        return render_template('scraperZLibraryPages/scraperZLibraryMain.html')
    
    @classmethod
    def search_books(cls):
        """API endpoint to search for books"""
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'Invalid request data'}), 400
        
        query = data.get('query', '').strip()
        page = data.get('page', 1)
        headless = data.get('headless', True)
        
        if not query:
            return jsonify({'success': False, 'error': 'Query is required'}), 400
        
        if len(query) < 2:
            return jsonify({'success': False, 'error': 'Search query must be at least 2 characters long'}), 400
        
        try:
            books, total_pages, total_books = cls._model.search_books(query, page, None, headless)
            statistics = cls._model.statistics
            
            result = {
                'success': True,
                'query': query,
                'books': [book.to_dict() for book in books],
                'statistics': statistics,
                'total_count': len(books),
                'current_page': page,
                'total_pages': total_pages,
                'total_books_count': total_books
            }
            return jsonify(result)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': str(e),
                'books': [],
                'statistics': {}
            }), 500
    
    @classmethod
    def download_txt(cls):
        """Download results as text file"""
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No results provided'}), 400
        
        text_content = cls._format_results_as_text(data)
        
        return Response(
            text_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': f'attachment;filename=zlib_{data.get("query", "search")}_results.txt'
            }
        )
    
    @classmethod
    def download_json(cls):
        """Download results as JSON file"""
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No results provided'}), 400
        
        return Response(
            json.dumps(data, indent=2, ensure_ascii=False),
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment;filename=zlib_{data.get("query", "search")}_results.json'
            }
        )
    
    @classmethod
    def download_books_zip(cls):
        """Download actual book files as a zip archive using multi-threading"""
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        books = data.get('books', [])
        max_books = data.get('max_books')
        headless = data.get('headless', True)
        
        if not books:
            return jsonify({'error': 'No books provided'}), 400
        
        try:
            print(f"\n📚 Controller: Starting multi-threaded download of {len(books)} books...")
            
            zip_content = cls._model.download_books(books, max_books, headless)
            
            query = data.get('query', 'download')
            safe_query = query.replace(' ', '_')[:50]
            
            return Response(
                zip_content,
                mimetype='application/zip',
                headers={
                    'Content-Disposition': f'attachment;filename=zlib_books_{safe_query}.zip',
                    'Content-Type': 'application/zip'
                }
            )
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"❌ Controller error: {e}")
            return jsonify({'error': str(e)}), 500
    
    @classmethod
    def _format_results_as_text(cls, results: Dict) -> str:
        """Format results as plain text for download"""
        if not results.get('success'):
            return f"Error: {results.get('error', 'Unknown error')}"
        
        lines = []
        lines.append("=" * 80)
        lines.append("Z-Library Search Results")
        lines.append("=" * 80)
        lines.append(f"Search Query: {results['query']}")
        lines.append(f"Total Books Found: {results.get('total_books_count', results['total_count'])}")
        lines.append(f"Books in this export: {results['total_count']}")
        lines.append(f"Date: {cls._get_current_time()}")
        lines.append("=" * 80)
        lines.append("")
        
        for idx, book_data in enumerate(results['books'], 1):
            lines.append(f"Book #{idx}")
            lines.append("-" * 60)
            lines.append(f"Title: {book_data['title']}")
            
            authors = book_data.get('authors', [])
            authors_str = ', '.join(authors) if authors else 'N/A'
            lines.append(f"Author(s): {authors_str}")
            
            lines.append(f"Publisher: {book_data.get('publisher', 'N/A')}")
            lines.append(f"Year: {book_data.get('year', 'N/A')}")
            lines.append(f"Pages: {book_data.get('pages', 'N/A')}")
            lines.append(f"Language: {book_data.get('language', 'N/A')}")
            lines.append(f"File: {book_data.get('file', 'N/A')}")
            lines.append(f"Link: {book_data.get('link', 'N/A')}")
            
            if book_data.get('download_url') and book_data['download_url'] != 'N/A':
                lines.append(f"Download URL: {book_data['download_url']}")
            
            if book_data.get('file_size') and book_data['file_size'] != 'N/A':
                lines.append(f"File Size: {book_data['file_size']}")
            
            lines.append("=" * 80)
            lines.append("")
        
        if results.get('statistics'):
            stats = results['statistics']
            lines.append("")
            lines.append("=" * 80)
            lines.append("SUMMARY STATISTICS")
            lines.append("=" * 80)
            lines.append(f"Total Books in export: {stats.get('total_books', 0)}")
            
            if stats.get('languages'):
                lines.append("\nLanguages Distribution:")
                for lang, count in sorted(stats['languages'].items(), key=lambda x: x[1], reverse=True):
                    percentage = (count / results['total_count']) * 100 if results['total_count'] > 0 else 0
                    lines.append(f"  {lang}: {count} books ({percentage:.1f}%)")
            
            if stats.get('formats'):
                lines.append("\nFile Formats Distribution:")
                for fmt, count in sorted(stats['formats'].items(), key=lambda x: x[1], reverse=True):
                    percentage = (count / results['total_count']) * 100 if results['total_count'] > 0 else 0
                    lines.append(f"  {fmt}: {count} books ({percentage:.1f}%)")
        
        return "\n".join(lines)
    
    @staticmethod
    def _get_current_time() -> str:
        """Get current formatted time"""
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')