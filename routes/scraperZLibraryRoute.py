# routes/scraperZLibraryRoute.py
from flask import Blueprint
from controllers.scraperZLibraryController import ScraperController

# Create blueprint
scraperZLibraryRoute = Blueprint('scraperZLibrary', __name__)

# Define routes
scraperZLibraryRoute.route('/', methods=['GET'])(ScraperController.index)
scraperZLibraryRoute.route('/api/search', methods=['POST'])(ScraperController.search_books)
scraperZLibraryRoute.route('/api/download/txt', methods=['POST'])(ScraperController.download_txt)
scraperZLibraryRoute.route('/api/download/json', methods=['POST'])(ScraperController.download_json)
scraperZLibraryRoute.route('/api/download/books', methods=['POST'])(ScraperController.download_books_zip)  # New route
scraperZLibraryRoute.add_url_rule(
    '/api/download/stream',
    view_func=ScraperController.download_books_stream,
    methods=['POST'],
)
scraperZLibraryRoute.add_url_rule(
    '/api/download/file/<token>',
    view_func=ScraperController.fetch_stored_file,
    methods=['GET'],
)