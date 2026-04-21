# routes/scraperZLibraryRoute.py
from flask import Blueprint, render_template, request, jsonify, Response
from controllers.scraperZLibraryController import ScraperController
import json

scraperZLibraryRoute = Blueprint('book', __name__)
controller = ScraperController()


@scraperZLibraryRoute.route('/', methods=['GET'])
def index():
    """Render the search page"""
    return render_template('scraperZLibraryPages/scraperZLibraryMain.html')


@scraperZLibraryRoute.route('/api/search', methods=['POST'])
def search_books():
    """API endpoint to search for books"""
    data = request.get_json()
    query = data.get('query', '').strip()
    max_pages = data.get('max_pages')
    headless = data.get('headless', True)
    
    if not query:
        return jsonify({'success': False, 'error': 'Query is required'}), 400
    
    # Perform search
    results = controller.search_books(query, max_pages, headless)
    
    return jsonify(results)


@scraperZLibraryRoute.route('/api/download/txt', methods=['POST'])
def download_txt():
    """Download results as text file - receives results in request body"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No results provided'}), 400
    
    text_content = controller.format_results_as_text(data)
    
    return Response(
        text_content,
        mimetype='text/plain',
        headers={
            'Content-Disposition': f'attachment;filename=zlib_{data.get("query", "search")}_results.txt'
        }
    )


@scraperZLibraryRoute.route('/api/download/json', methods=['POST'])
def download_json():
    """Download results as JSON file - receives results in request body"""
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