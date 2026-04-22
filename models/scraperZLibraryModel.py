# models/scraperZLibraryModel.py
import os
import re
import time
import io
import zipfile
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from playwright.sync_api import sync_playwright, Page, BrowserContext
from dotenv import load_dotenv

load_dotenv()


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
    download_url: str = 'N/A'
    file_size: str = 'N/A'
    
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
            'link': self.link,
            'download_url': self.download_url,
            'file_size': self.file_size
        }


class ZLibraryScraperModel:
    """Model handling Z-Library scraping operations"""
    
    BASE_URL = "https://z-library.sk"
    
    # Account credentials - UPDATE THESE
    LOGIN_EMAIL = os.environ.get("ZLIBRARY_EMAIL")
    LOGIN_PASSWORD = os.environ.get("ZLIBRARY_PASSWORD")
    
    def __init__(self):
        self.books: List[Book] = []
        self.statistics: Dict = {}
        self._is_logged_in = False
    
    def _login(self, context: BrowserContext) -> Page:
        """Login to Z-Library account"""
        page = context.new_page()
        
        try:
            print("🔐 Attempting to login...")
            
            # Go to login page
            page.goto(f"{self.BASE_URL}/login", timeout=30000)
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            
            # Check if already logged in (skip login if already authenticated)
            current_url = page.url
            if "/login" not in current_url:
                print("✅ Already logged in! (Not on login page)")
                self._is_logged_in = True
                return page
            
            # Find the login form
            login_form = page.query_selector('#loginForm')
            if not login_form:
                print("⚠ Login form not found")
                return page
            
            # Fill email field
            email_input = page.query_selector('input[name="email"]')
            if email_input:
                email_input.fill(self.LOGIN_EMAIL)
                print(f"  ✓ Filled email: {self.LOGIN_EMAIL}")
            else:
                print("  ✗ Email input not found")
                return page
            
            # Fill password field
            password_input = page.query_selector('input[name="password"]')
            if password_input:
                password_input.fill(self.LOGIN_PASSWORD)
                print("  ✓ Filled password")
            else:
                print("  ✗ Password input not found")
                return page
            
            # Click submit button
            submit_btn = page.query_selector('button[type="submit"][name="submit"]')
            if not submit_btn:
                submit_btn = page.query_selector('#loginForm button[type="submit"]')
            if not submit_btn:
                submit_btn = page.query_selector('button.btn-info')
            
            if submit_btn:
                print("  ✓ Found submit button, clicking...")
                submit_btn.click()
                
                # Wait for navigation
                page.wait_for_load_state("networkidle")
                time.sleep(3)
                
                # Check if login was successful - URL changed from /login
                current_url = page.url
                print(f"  Current URL after login: {current_url}")
                
                # SUCCESS: URL no longer contains /login
                if "/login" not in current_url:
                    self._is_logged_in = True
                    print("✅ Login successful! (URL changed from login page)")
                    return page
                
                # Also check for user menu as backup indicator
                user_menu = page.query_selector('.user-menu, .dropdown-toggle, [data-user], .user-profile')
                if user_menu:
                    self._is_logged_in = True
                    print("✅ Login successful! (User menu found)")
                    return page
                
                # Check for error message on login page
                error_msg = page.query_selector('.form-error, .validation-error')
                if error_msg:
                    error_text = error_msg.text_content().strip()
                    print(f"  ✗ Login error: {error_text}")
                else:
                    print("  ⚠ Login may have failed - still on login page without error")
            
            self._is_logged_in = False
            return page
            
        except Exception as e:
            print(f"⚠ Login error: {e}")
            import traceback
            traceback.print_exc()
            self._is_logged_in = False
            return page
    
    def _extract_download_info(self, page: Page) -> Tuple[str, str]:
        """Extract download URL and file size from book page"""
        download_url = 'N/A'
        file_size = 'N/A'
        
        try:
            # Look for download button - class="btn btn-default addDownloadedBook"
            download_btn = page.query_selector('a.addDownloadedBook')
            if not download_btn:
                download_btn = page.query_selector('a[class*="addDownloadedBook"]')
            if not download_btn:
                download_btn = page.query_selector('a.btn-default')
            
            if download_btn:
                href = download_btn.get_attribute('href')
                if href:
                    download_url = f"{self.BASE_URL}{href}" if not href.startswith('http') else href
                    print(f"    Found download URL: {download_url}")
                
                # Extract file size from the button text
                full_text = download_btn.text_content().strip()
                # Pattern: "epub, 2.98 MB" or similar
                size_match = re.search(r'(\d+\.?\d*\s*(MB|KB|GB|B))', full_text, re.IGNORECASE)
                if size_match:
                    file_size = size_match.group(1)
                    print(f"    File size: {file_size}")
                
                # Also extract file extension if available
                extension_span = download_btn.query_selector('.book-property__extension')
                if extension_span:
                    extension = extension_span.text_content().strip()
                    print(f"    File extension: {extension}")
            else:
                print("    ⚠ Download button not found on book page")
            
        except Exception as e:
            print(f"    Error extracting download info: {e}")
        
        return download_url, file_size
    
    def _download_file(self, page: Page) -> Optional[bytes]:
        """Download a single file from the current book page and return its content"""
        try:
            print("    Looking for download button...")
            
            # Find the download button on the book page
            download_btn = page.query_selector('a.addDownloadedBook')
            if not download_btn:
                download_btn = page.query_selector('a[class*="addDownloadedBook"]')
            if not download_btn:
                download_btn = page.query_selector('a.btn-default')
            if not download_btn:
                download_btn = page.query_selector('a[href*="/dl/"]')
            
            if download_btn:
                print("    ✓ Found download button, clicking...")
                
                # Set up download handler before clicking
                with page.expect_download(timeout=60000) as download_info:
                    download_btn.click()
                
                download = download_info.value
                suggested_filename = download.suggested_filename
                print(f"    Download started: {suggested_filename}")
                
                # CRITICAL: Save the file to a temporary location first, then read it
                # This ensures the download completes fully
                temp_path = download.path()
                if temp_path:
                    print(f"    Download saved to: {temp_path}")
                    # Wait a moment for download to complete
                    time.sleep(1)
                    with open(temp_path, 'rb') as f:
                        file_content = f.read()
                    print(f"    ✓ Read {len(file_content)} bytes from temp file")
                    return file_content
                else:
                    # Fallback: try reading directly from download object
                    file_content = download.read_bytes()
                    print(f"    ✓ Downloaded {len(file_content)} bytes directly")
                    return file_content
            else:
                print("    ✗ Download button not found on page")
                return None
            
        except Exception as e:
            print(f"    Error downloading file: {e}")
            import traceback
            traceback.print_exc()
            return None
    
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
        
        for book in books:
            lang = book.language
            stats['languages'][lang] = stats['languages'].get(lang, 0) + 1
        
        for book in books:
            year = book.year
            if year != 'N/A' and year.isdigit():
                stats['years'][year] = stats['years'].get(year, 0) + 1
        
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
                print(f"Accessing: {first_page_url}")
                page.goto(first_page_url, timeout=60000)
                page.wait_for_load_state("networkidle")
                time.sleep(2)
                
                # Determine total pages
                total_pages = self.get_total_pages(page)
                if max_pages:
                    total_pages = min(total_pages, max_pages)
                
                print(f"\nTotal pages to scrape: {total_pages}")
                
                # Extract books from all pages
                for current_page in range(1, total_pages + 1):
                    if current_page > 1:
                        page_url = f"{self.BASE_URL}/s/{encoded_query}?view=table&page={current_page}"
                        print(f"\nAccessing page {current_page}: {page_url}")
                        page.goto(page_url, timeout=60000)
                        page.wait_for_load_state("networkidle")
                        time.sleep(1)
                    
                    try:
                        page.wait_for_selector('table.table_book tbody tr', timeout=10000)
                    except:
                        print(f"No table found on page {current_page}")
                        continue
                    
                    books = self.extract_books_from_table(page)
                    print(f"Found {len(books)} books on page {current_page}")
                    all_books.extend(books)
                
            except Exception as e:
                print(f"Error occurred: {e}")
                import traceback
                traceback.print_exc()
            finally:
                browser.close()
        
        self.books = all_books
        self.statistics = self.calculate_statistics(all_books)
        print(f"\nTotal books found: {len(all_books)}")
        return all_books
    
    def download_books(self, books: List[Dict], max_books: Optional[int] = None, headless: bool = True) -> bytes:
        """
        Download actual book files and zip them together
        
        Args:
            books: List of book dictionaries with 'link' field
            max_books: Maximum number of books to download (None for all)
            headless: Run browser in headless mode
        
        Returns:
            Bytes of zip file containing all downloaded books
        """
        downloaded_files = []
        
        # Limit number of books if specified
        books_to_download = books[:max_books] if max_books else books
        
        print(f"\n📚 Starting download of {len(books_to_download)} books...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                accept_downloads=True  # Important: Enable downloads
            )
            
            # Login first
            page = self._login(context)
            
            try:
                for idx, book_data in enumerate(books_to_download, 1):
                    print(f"\n[{idx}/{len(books_to_download)}] Processing: {book_data['title'][:50]}...")
                    
                    book_link = book_data.get('link')
                    if not book_link or book_link == 'N/A':
                        print(f"  ⚠ No link available, skipping")
                        continue
                    
                    try:
                        # Go to book page
                        print(f"  Navigating to: {book_link}")
                        page.goto(book_link, timeout=30000)
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)
                        
                        # Extract download info (optional, for logging)
                        download_url, file_size = self._extract_download_info(page)
                        
                        # Create safe filename
                        safe_title = re.sub(r'[^\w\s-]', '', book_data['title'][:50])
                        safe_title = re.sub(r'[-\s]+', '_', safe_title)
                        if not safe_title:
                            safe_title = f"book_{idx}"
                        
                        extension = book_data.get('file', 'txt').split(',')[0].strip().lower()
                        if extension == 'N/A' or not extension:
                            extension = 'txt'
                        
                        filename = f"{safe_title}.{extension}"
                        
                        # Download the file directly from the book page
                        file_content = self._download_file(page)
                        
                        if file_content:
                            downloaded_files.append({
                                'filename': filename,
                                'content': file_content,
                                'size': len(file_content)
                            })
                            print(f"  ✅ Successfully downloaded: {filename} ({len(file_content)} bytes)")
                        else:
                            print(f"  ❌ Failed to download file content")
                    
                    except Exception as e:
                        print(f"  ❌ Error processing book: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                    
                    # Small delay between downloads to avoid rate limiting
                    time.sleep(2)
                
            except Exception as e:
                print(f"Error during download process: {e}")
                import traceback
                traceback.print_exc()
            finally:
                browser.close()
        
        # Create zip file in memory
        print(f"\n📦 Creating ZIP archive with {len(downloaded_files)} files...")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_info in downloaded_files:
                zip_file.writestr(file_info['filename'], file_info['content'])
                print(f"  Added: {file_info['filename']} ({file_info['size']} bytes)")
        
        zip_buffer.seek(0)
        
        total_size = zip_buffer.getbuffer().nbytes
        print(f"\n✅ Created ZIP archive: {total_size} bytes")
        
        return zip_buffer.getvalue()