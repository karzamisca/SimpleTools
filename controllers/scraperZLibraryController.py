# controllers/scraperZLibraryController.py
from typing import Dict, List, Optional
from models.scraperZLibraryModel import ZLibraryScraperModel, Book


class ScraperController:
    """Controller handling business logic for book scraping"""
    
    def __init__(self):
        self.model = ZLibraryScraperModel()
    
    def search_books(self, query: str, max_pages: Optional[int] = None, headless: bool = True) -> Dict:
        """
        Search for books and return results with statistics
        
        Args:
            query: Search query string
            max_pages: Maximum number of pages to scrape (None for all)
            headless: Run browser in headless mode
        
        Returns:
            Dictionary containing books and statistics
        """
        if not query or len(query.strip()) < 2:
            return {
                'success': False,
                'error': 'Search query must be at least 2 characters long',
                'books': [],
                'statistics': {}
            }
        
        try:
            books = self.model.search_books(query, max_pages, headless)
            
            return {
                'success': True,
                'query': query,
                'books': [book.to_dict() for book in books],
                'statistics': self.model.statistics,
                'total_count': len(books)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'books': [],
                'statistics': {}
            }
    
    def format_results_as_text(self, results: Dict) -> str:
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
        
        # Add statistics
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