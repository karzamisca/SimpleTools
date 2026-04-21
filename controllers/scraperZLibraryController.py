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
        max_pages = data.get('max_pages')
        headless = data.get('headless', True)
        
        if not query:
            return jsonify({'success': False, 'error': 'Query is required'}), 400
        
        if len(query) < 2:
            return jsonify({'success': False, 'error': 'Search query must be at least 2 characters long'}), 400
        
        try:
            books = cls._model.search_books(query, max_pages, headless)
            
            result = {
                'success': True,
                'query': query,
                'books': [book.to_dict() for book in books],
                'statistics': cls._model.statistics,
                'total_count': len(books)
            }
            return jsonify(result)
            
        except Exception as e:
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
    def _format_results_as_text(cls, results: Dict) -> str:
        """Format results as plain text for download"""
        if not results.get('success'):
            return f"Error: {results.get('error', 'Unknown error')}"
        
        lines = []
        lines.append("=" * 80)
        lines.append("Z-Library Search Results")
        lines.append("=" * 80)
        lines.append(f"Search Query: {results['query']}")
        lines.append(f"Total Books Found: {results['total_count']}")
        lines.append("=" * 80)
        lines.append("")
        
        for idx, book_data in enumerate(results['books'], 1):
            lines.append(f"Book #{idx}")
            lines.append("-" * 60)
            lines.append(f"Title: {book_data['title']}")
            lines.append(f"Author(s): {', '.join(book_data['authors']) if book_data['authors'] else 'N/A'}")
            lines.append(f"Publisher: {book_data['publisher']}")
            lines.append(f"Year: {book_data['year']}")
            lines.append(f"Pages: {book_data['pages']}")
            lines.append(f"Language: {book_data['language']}")
            lines.append(f"File: {book_data['file']}")
            lines.append(f"Link: {book_data['link']}")
            lines.append("=" * 80)
            lines.append("")
        
        if results.get('statistics'):
            stats = results['statistics']
            lines.append("")
            lines.append("=" * 80)
            lines.append("SUMMARY STATISTICS")
            lines.append("=" * 80)
            
            if stats.get('languages'):
                lines.append("\nLanguages Distribution:")
                for lang, count in sorted(stats['languages'].items(), key=lambda x: x[1], reverse=True):
                    percentage = (count / results['total_count']) * 100
                    lines.append(f"  {lang}: {count} books ({percentage:.1f}%)")
            
            if stats.get('formats'):
                lines.append("\nFile Formats Distribution:")
                for fmt, count in sorted(stats['formats'].items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"  {fmt}: {count} books")
        
        return "\n".join(lines)