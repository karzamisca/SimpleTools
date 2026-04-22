# models/scraperZLibraryModel.py
import re
import time
import io
import zipfile
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from playwright.sync_api import sync_playwright, Page, BrowserContext
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


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
    MAX_WORKERS = 10  # Fixed number of concurrent download threads
    
    # Account credentials - UPDATE THESE
    LOGIN_EMAIL = os.environ.get("ZLIBRARY_EMAIL")
    LOGIN_PASSWORD = os.environ.get("ZLIBRARY_PASSWORD")
    
    def __init__(self):
        self.books: List[Book] = []
        self.statistics: Dict = {}
        self._is_logged_in = False
        self._download_lock = threading.Lock()
        self._download_progress = {'completed': 0, 'total': 0, 'failed': 0}
    
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
                
                full_text = download_btn.text_content().strip()
                size_match = re.search(r'(\d+\.?\d*\s*(MB|KB|GB|B))', full_text, re.IGNORECASE)
                if size_match:
                    file_size = size_match.group(1)
                    print(f"    File size: {file_size}")
                
                extension_span = download_btn.query_selector('.book-property__extension')
                if extension_span:
                    extension = extension_span.text_content().strip()
                    print(f"    File extension: {extension}")
            else:
                print("    ⚠ Download button not found on book page")
            
        except Exception as e:
            print(f"    Error extracting download info: {e}")
        
        return download_url, file_size
    
    def _download_single_book(self, book_data: Dict, idx: int, total: int, headless: bool = True) -> Optional[Dict]:
        """Download a single book using its own browser instance"""
        thread_id = threading.current_thread().name
        print(f"\n[{idx}/{total}] [{thread_id}] Starting: {book_data['title'][:50]}...")
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    accept_downloads=True
                )
                
                # Login for this browser instance
                page = self._login(context)
                
                book_link = book_data.get('link')
                if not book_link or book_link == 'N/A':
                    print(f"[{idx}/{total}] ⚠ No link available, skipping")
                    browser.close()
                    return None
                
                try:
                    print(f"[{idx}/{total}] Navigating to book page...")
                    page.goto(book_link, timeout=30000)
                    page.wait_for_load_state("networkidle")
                    time.sleep(1)
                    
                    # Extract download info
                    download_url, file_size = self._extract_download_info(page)
                    
                    # Download file
                    file_content = self._download_file_from_page(page)
                    
                    if file_content and len(file_content) > 0:
                        safe_title = re.sub(r'[^\w\s-]', '', book_data['title'][:50])
                        safe_title = re.sub(r'[-\s]+', '_', safe_title)
                        if not safe_title:
                            safe_title = f"book_{idx}"
                        
                        extension = book_data.get('file', 'txt').split(',')[0].strip().lower()
                        if extension == 'N/A' or not extension:
                            extension = 'txt'
                        
                        filename = f"{safe_title}.{extension}"
                        
                        result = {
                            'filename': filename,
                            'content': file_content,
                            'size': len(file_content),
                            'download_url': download_url,
                            'file_size': file_size
                        }
                        
                        with self._download_lock:
                            self._download_progress['completed'] += 1
                            completed = self._download_progress['completed']
                            print(f"[{idx}/{total}] ✅ Success: {filename} ({len(file_content)} bytes) - Progress: {completed}/{total}")
                        
                        browser.close()
                        return result
                    else:
                        with self._download_lock:
                            self._download_progress['failed'] += 1
                        print(f"[{idx}/{total}] ❌ No file content received")
                        browser.close()
                        return None
                
                except Exception as e:
                    with self._download_lock:
                        self._download_progress['failed'] += 1
                    print(f"[{idx}/{total}] ❌ Error: {e}")
                    browser.close()
                    return None
                
        except Exception as e:
            with self._download_lock:
                self._download_progress['failed'] += 1
            print(f"[{idx}/{total}] ❌ Browser error: {e}")
            return None
    
    def _download_file_from_page(self, page: Page) -> Optional[bytes]:
        """Download a single file from the current book page and return its content"""
        try:
            download_btn = page.query_selector('a.addDownloadedBook')
            if not download_btn:
                download_btn = page.query_selector('a[class*="addDownloadedBook"]')
            if not download_btn:
                download_btn = page.query_selector('a.btn-default')
            if not download_btn:
                download_btn = page.query_selector('a[href*="/dl/"]')
            
            if download_btn:
                href = download_btn.get_attribute('href')
                if href:
                    full_url = f"{self.BASE_URL}{href}" if not href.startswith('http') else href
                    
                    try:
                        with page.expect_download(timeout=30000) as download_info:
                            page.goto(full_url, timeout=30000)
                        
                        download = download_info.value
                        time.sleep(2)
                        file_content = download.read_bytes()
                        return file_content
                        
                    except Exception:
                        try:
                            with page.expect_download(timeout=30000) as download_info:
                                download_btn.click()
                            
                            download = download_info.value
                            time.sleep(2)
                            file_content = download.read_bytes()
                            return file_content
                            
                        except Exception:
                            try:
                                download = download_info.value
                                temp_path = download.path()
                                if temp_path and os.path.exists(temp_path):
                                    time.sleep(1)
                                    with open(temp_path, 'rb') as f:
                                        file_content = f.read()
                                    return file_content
                            except Exception:
                                pass
                
                return None
            else:
                return None
            
        except Exception as e:
            print(f"    Download error: {e}")
            return None
    
    def extract_books_from_table(self, page: Page) -> List[Book]:
        """Extract book information from the current page's table"""
        books = []
        book_rows = page.query_selector_all('table.table_book tbody tr')
        
        for row in book_rows:
            try:
                authors = row.query_selector_all('.authors a')
                author_list = [author.text_content().strip() for author in authors]
                
                title_element = row.query_selector('td:nth-child(2) > a')
                if title_element:
                    title = ' '.join(title_element.text_content().strip().split())
                    link = title_element.get_attribute('href')
                    if link and not link.startswith('http'):
                        link = f"{self.BASE_URL}{link}"
                else:
                    title = 'N/A'
                    link = 'N/A'
                
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
    
    def get_total_books_count(self, page: Page) -> int:
        """Get total number of books found"""
        try:
            content = page.content()
            match = re.search(r'booksTotal:\s*(\d+)', content)
            if match:
                return int(match.group(1))
            
            result_count = page.query_selector('.totalCount, .search-result-count')
            if result_count:
                text = result_count.text_content()
                numbers = re.findall(r'\d+', text)
                if numbers:
                    return int(numbers[0])
            
            return 0
        except:
            return 0
    
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
    
    def search_books(self, query: str, page_num: int = 1, max_pages: Optional[int] = None, headless: bool = True) -> Tuple[List[Book], int, int]:
        """Search Z-Library for books matching query
        
        Returns:
            Tuple of (books_list, total_pages_available, total_books_count)
        """
        all_books = []
        encoded_query = query.replace(' ', '%20')
        total_pages_available = 1
        total_books_count = 0
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            page = self._login(context)
            
            try:
                page_url = f"{self.BASE_URL}/s/{encoded_query}?view=table"
                if page_num > 1:
                    page_url += f"&page={page_num}"
                
                print(f"Accessing: {page_url}")
                page.goto(page_url, timeout=60000)
                page.wait_for_load_state("networkidle")
                time.sleep(2)
                
                total_pages_available = self.get_total_pages(page)
                total_books_count = self.get_total_books_count(page)
                print(f"Total pages available: {total_pages_available}")
                print(f"Total books found: {total_books_count}")
                
                try:
                    page.wait_for_selector('table.table_book tbody tr', timeout=10000)
                except:
                    print(f"No table found on page {page_num}")
                    return [], total_pages_available, total_books_count
                
                books = self.extract_books_from_table(page)
                print(f"Found {len(books)} books on page {page_num}")
                all_books.extend(books)
                
            except Exception as e:
                print(f"Error occurred: {e}")
                import traceback
                traceback.print_exc()
            finally:
                browser.close()
        
        self.books = all_books
        self.statistics = self.calculate_statistics(all_books)
        print(f"\nBooks found on page {page_num}: {len(all_books)}")
        return all_books, total_pages_available, total_books_count
    
    def download_books(self, books: List[Dict], max_books: Optional[int] = None, headless: bool = True) -> bytes:
        """Download actual book files concurrently and zip them together"""
        books_to_download = books[:max_books] if max_books else books
        total_books = len(books_to_download)
        
        # Reset progress counters
        self._download_progress = {'completed': 0, 'total': total_books, 'failed': 0}
        
        print(f"\n{'='*60}")
        print(f"📚 Starting MULTI-THREADED DOWNLOAD")
        print(f"📚 Total books: {total_books}")
        print(f"📚 Concurrent workers: {self.MAX_WORKERS}")
        print(f"{'='*60}")
        
        downloaded_files = []
        
        # Use ThreadPoolExecutor for concurrent downloads
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            # Submit all download tasks
            future_to_book = {
                executor.submit(
                    self._download_single_book, 
                    book_data, 
                    idx, 
                    total_books, 
                    headless
                ): (book_data, idx)
                for idx, book_data in enumerate(books_to_download, 1)
            }
            
            # Process completed tasks as they finish
            for future in as_completed(future_to_book):
                book_data, idx = future_to_book[future]
                try:
                    result = future.result()
                    if result:
                        downloaded_files.append(result)
                except Exception as e:
                    print(f"[{idx}/{total_books}] ❌ Thread error: {e}")
                    with self._download_lock:
                        self._download_progress['failed'] += 1
        
        print(f"\n{'='*60}")
        print(f"📊 Download Summary:")
        print(f"  ✅ Successfully downloaded: {len(downloaded_files)} books")
        print(f"  ❌ Failed downloads: {self._download_progress['failed']} books")
        print(f"{'='*60}")
        
        # Create ZIP archive
        print(f"\n📦 Creating ZIP archive...")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_info in downloaded_files:
                zip_file.writestr(file_info['filename'], file_info['content'])
                print(f"  Added: {file_info['filename']} ({file_info['size']} bytes)")
        
        zip_buffer.seek(0)
        total_size = zip_buffer.getbuffer().nbytes
        print(f"\n✅ ZIP created: {total_size:,} bytes ({total_size/1024/1024:.2f} MB)")
        
        return zip_buffer.getvalue()