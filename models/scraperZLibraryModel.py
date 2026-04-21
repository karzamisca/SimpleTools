# models/scraperZLibraryModel.py
import re
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Page


@dataclass
class Book:
    """Book data model"""
    title: str
    authors: List[str] = field(default_factory=list)
    publisher: str = 'N/A'
    year: str = 'N/A'
    pages: str = 'N/A'
    language: str = 'N/A'
    file: str = 'N/A'
    link: str = 'N/A'
    
    def to_dict(self) -> dict:
        """Convert book to dictionary"""
        return {
            'title': self.title,
            'authors': self.authors,
            'publisher': self.publisher,
            'year': self.year,
            'pages': self.pages,
            'language': self.language,
            'file': self.file,
            'link': self.link
        }


class ZLibraryScraperModel:
    """Model handling Z-Library scraping operations"""
    
    BASE_URL = "https://z-library.sk"
    
    def __init__(self):
        self.books: List[Book] = []
        self.statistics: Dict = {}
    
    def extract_books_from_table(self, page: Page) -> List[Book]:
        """Extract book information from the current page's table"""
        books = []
        book_rows = page.query_selector_all('table.table_book tbody tr')
        
        for row in book_rows:
            try:
                # Extract author(s)
                authors = row.query_selector_all('.authors a')
                author_list = [author.text_content().strip() for author in authors]
                
                # Extract title and link
                title_element = row.query_selector('td:nth-child(2) > a')
                if title_element:
                    title = ' '.join(title_element.text_content().strip().split())
                    link = title_element.get_attribute('href')
                    if link and not link.startswith('http'):
                        link = f"{self.BASE_URL}{link}"
                else:
                    title = 'N/A'
                    link = 'N/A'
                
                # Extract other fields
                publisher_element = row.query_selector('td:nth-child(3) a')
                publisher = publisher_element.text_content().strip() if publisher_element else 'N/A'
                
                year_element = row.query_selector('td:nth-child(4)')
                year = year_element.text_content().strip() if year_element else 'N/A'
                
                pages_element = row.query_selector('td:nth-child(5)')
                pages = pages_element.text_content().strip() if pages_element else 'N/A'
                
                language_element = row.query_selector('td:nth-child(6)')
                language = language_element.text_content().strip() if language_element else 'N/A'
                
                file_element = row.query_selector('td:nth-child(7) .book-property__extension')
                file_info = file_element.text_content().strip() if file_element else 'N/A'
                
                book = Book(
                    title=title,
                    authors=author_list,
                    publisher=publisher,
                    year=year,
                    pages=pages,
                    language=language,
                    file=file_info,
                    link=link
                )
                books.append(book)
                
            except Exception as e:
                print(f"Error extracting book: {e}")
                continue
        
        return books
    
    def get_total_pages(self, page: Page) -> int:
        """Get total number of pages from pagination"""
        try:
            content = page.content()
            match = re.search(r'pagesTotal:\s*(\d+)', content)
            if match:
                return int(match.group(1))
            
            page_links = page.query_selector_all('.paginator a, .paginator span')
            page_numbers = []
            for link in page_links:
                text = link.text_content().strip()
                if text.isdigit():
                    page_numbers.append(int(text))
            if page_numbers:
                return max(page_numbers)
            
            return 1
        except:
            return 1
    
    def calculate_statistics(self, books: List[Book]) -> Dict:
        """Calculate statistics from books data"""
        if not books:
            return {}
        
        stats = {
            'total_books': len(books),
            'languages': {},
            'years': {},
            'formats': {}
        }
        
        # Language distribution
        for book in books:
            lang = book.language
            stats['languages'][lang] = stats['languages'].get(lang, 0) + 1
        
        # Year distribution
        for book in books:
            year = book.year
            if year != 'N/A' and year.isdigit():
                stats['years'][year] = stats['years'].get(year, 0) + 1
        
        # Format distribution
        for book in books:
            if book.file != 'N/A':
                format_match = re.match(r'([a-zA-Z0-9]+)', book.file)
                if format_match:
                    fmt = format_match.group(1).upper()
                    stats['formats'][fmt] = stats['formats'].get(fmt, 0) + 1
        
        return stats
    
    def search_books(self, query: str, max_pages: Optional[int] = None, headless: bool = True) -> List[Book]:
        """Search Z-Library for books matching query"""
        all_books = []
        encoded_query = query.replace(' ', '%20')
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            try:
                # Get first page
                first_page_url = f"{self.BASE_URL}/s/{encoded_query}?view=table"
                page.goto(first_page_url, timeout=60000)
                page.wait_for_load_state("networkidle")
                time.sleep(2)
                
                # Determine total pages
                total_pages = self.get_total_pages(page)
                if max_pages:
                    total_pages = min(total_pages, max_pages)
                
                # Extract books from all pages
                for current_page in range(1, total_pages + 1):
                    if current_page > 1:
                        page_url = f"{self.BASE_URL}/s/{encoded_query}?view=table&page={current_page}"
                        page.goto(page_url, timeout=60000)
                        page.wait_for_load_state("networkidle")
                        time.sleep(1)
                    
                    try:
                        page.wait_for_selector('table.table_book tbody tr', timeout=10000)
                    except:
                        continue
                    
                    books = self.extract_books_from_table(page)
                    all_books.extend(books)
                
            except Exception as e:
                print(f"Error occurred: {e}")
                import traceback
                traceback.print_exc()
            finally:
                browser.close()
        
        self.books = all_books
        self.statistics = self.calculate_statistics(all_books)
        return all_books