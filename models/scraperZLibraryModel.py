# models/scraperZLibraryModel.py
import re
import time
import os
import pathlib
import tempfile
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from playwright.sync_api import sync_playwright, Page, BrowserContext


PROFILE_DIR = str(pathlib.Path.home() / ".zlibrary_profile")


@dataclass
class Book:
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
    BASE_URL = "https://z-library.sk"
    LOGIN_EMAIL = os.environ.get("ZLIBRARY_EMAIL")
    LOGIN_PASSWORD = os.environ.get("ZLIBRARY_PASSWORD")

    def create_context(self, playwright, headless: bool = True) -> BrowserContext:
        return playwright.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=headless,
            viewport={'width': 1280, 'height': 800},
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            accept_downloads=True,
        )

    @staticmethod
    def _wait_for_idle(page: Page, timeout: int = 15000) -> None:
        """
        Wait for networkidle, but treat a timeout as a soft warning rather than
        a fatal error. Z-Library pages often keep long-polling connections open
        that prevent networkidle from ever firing; domcontentloaded is enough
        for our scraping purposes.
        """
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass  # Best-effort; carry on regardless

    def login(self, context: BrowserContext) -> Tuple[Page, bool]:
        page = context.new_page()
        try:
            print("🔐 Attempting to login...")
            page.goto(f"{self.BASE_URL}/login", timeout=30000)
            self._wait_for_idle(page)
            time.sleep(2)

            if "/login" not in page.url:
                print("✅ Already logged in (persistent session)")
                return page, True

            login_form = page.query_selector('#loginForm')
            if not login_form:
                print("⚠ Login form not found — assuming already authenticated")
                return page, True

            email_input = page.query_selector('input[name="email"]')
            password_input = page.query_selector('input[name="password"]')
            if not email_input or not password_input:
                print("✗ Email or password input not found")
                return page, False

            email_input.fill(self.LOGIN_EMAIL)
            print(f"  ✓ Filled email: {self.LOGIN_EMAIL}")
            password_input.fill(self.LOGIN_PASSWORD)
            print("  ✓ Filled password")

            submit_btn = (
                page.query_selector('button[type="submit"][name="submit"]') or
                page.query_selector('#loginForm button[type="submit"]') or
                page.query_selector('button.btn-info')
            )
            if not submit_btn:
                print("✗ Submit button not found")
                return page, False

            submit_btn.click()
            self._wait_for_idle(page)
            time.sleep(3)

            print(f"  URL after login: {page.url}")
            if "/login" not in page.url:
                print("✅ Login successful")
                return page, True

            error_el = page.query_selector('.form-error, .validation-error')
            error_msg = error_el.text_content().strip() if error_el else "Unknown (still on login page)"
            print(f"  ✗ Login failed: {error_msg}")
            return page, False

        except Exception as e:
            print(f"⚠ Login exception: {e}")
            import traceback; traceback.print_exc()
            return page, False

    def extract_books_from_table(self, page: Page) -> List[Book]:
        books = []
        rows = page.query_selector_all('table.table_book tbody tr')

        for row in rows:
            try:
                authors = [a.text_content().strip()
                           for a in row.query_selector_all('.authors a')]

                title_el = row.query_selector('td:nth-child(2) > a')
                if title_el:
                    title = ' '.join(title_el.text_content().strip().split())
                    link = title_el.get_attribute('href') or 'N/A'
                    if link != 'N/A' and not link.startswith('http'):
                        link = f"{self.BASE_URL}{link}"
                else:
                    title, link = 'N/A', 'N/A'

                def _cell_text(selector):
                    el = row.query_selector(selector)
                    return el.text_content().strip() if el else 'N/A'

                publisher = _cell_text('td:nth-child(3) a')
                year      = _cell_text('td:nth-child(4)')
                pages     = _cell_text('td:nth-child(5)')
                language  = _cell_text('td:nth-child(6)')
                file_info = _cell_text('td:nth-child(7) .book-property__extension')

                books.append(Book(
                    title=title, authors=authors, publisher=publisher,
                    year=year, pages=pages, language=language,
                    file=file_info, link=link,
                ))
            except Exception as e:
                print(f"Error extracting row: {e}")

        return books

    def get_total_pages(self, page: Page) -> int:
        try:
            match = re.search(r'pagesTotal:\s*(\d+)', page.content())
            if match:
                return int(match.group(1))
            nums = [
                int(el.text_content().strip())
                for el in page.query_selector_all('.paginator a, .paginator span')
                if el.text_content().strip().isdigit()
            ]
            return max(nums) if nums else 1
        except Exception:
            return 1

    def get_total_books_count(self, page: Page) -> int:
        try:
            match = re.search(r'booksTotal:\s*(\d+)', page.content())
            if match:
                return int(match.group(1))
            el = page.query_selector('.totalCount, .search-result-count')
            if el:
                nums = re.findall(r'\d+', el.text_content())
                return int(nums[0]) if nums else 0
            return 0
        except Exception:
            return 0

    def extract_download_info(self, page: Page) -> Tuple[str, str]:
        try:
            btn = (
                page.query_selector('a.addDownloadedBook') or
                page.query_selector('a[class*="addDownloadedBook"]') or
                page.query_selector('a[href*="/dl/"]')
            )
            if not btn:
                return 'N/A', 'N/A'

            href = btn.get_attribute('href') or ''
            url = f"{self.BASE_URL}{href}" if href and not href.startswith('http') else href

            text = btn.text_content().strip()
            size_match = re.search(r'(\d+\.?\d*\s*(MB|KB|GB|B))', text, re.IGNORECASE)
            size = size_match.group(1) if size_match else 'N/A'

            ext_el = btn.query_selector('.book-property__extension')
            ext = ext_el.text_content().strip() if ext_el else ''
            if ext:
                print(f"    File extension: {ext}")

            print(f"    Found download URL: {url}  size: {size}")
            return url, size

        except Exception as e:
            print(f"    Error extracting download info: {e}")
            return 'N/A', 'N/A'

    # Network-level error substrings that indicate a transient drop.
    _RETRYABLE_ERRORS = (
        "Timeout",                           # expect_download or goto timed out — server didn't respond
        "ERR_CONNECTION_RESET",
        "ERR_CONNECTION_CLOSED",
        "ERR_TUNNEL_CONNECTION_FAILED",
        "ERR_EMPTY_RESPONSE",
        "net::ERR_",
        "Target page, context or browser has been closed",
        "Connection refused",
    )
    # Cloudflare error codes that mean "server temporarily unavailable, retry".
    _RETRYABLE_CF_CODES = (b"522", b"523", b"524", b"525", b"526", b"530")

    _MAX_RETRIES = 3
    _RETRY_BACKOFF = (10, 20, 40)   # seconds to wait before attempt 2, 3, 4 — longer for CF timeouts

    @staticmethod
    def _is_cloudflare_error_page(data: bytes) -> Optional[str]:
        """
        Return a human-readable reason string if `data` is a Cloudflare error
        HTML page (e.g. 522 Connection timed out), otherwise return None.

        Cloudflare error pages always contain the string 'cloudflare' and one
        of the known 5xx error codes inside a <title> or .code-label element.
        We check the first 2 KB only — the full page can be ~10 KB but the
        telltale markers are always near the top.
        """
        head = data[:2048].lower()
        if b"cloudflare" not in head:
            return None
        for code in ZLibraryScraperModel._RETRYABLE_CF_CODES:
            if code in head:
                return f"Cloudflare error {code.decode()} (server-side timeout)"
        # Generic Cloudflare error page without a known code
        if b"cf-error-details" in head or b"cf-wrapper" in head:
            return "Cloudflare error page (unknown code)"
        return None

    def download_file(self, page: Page, context: BrowserContext, download_url: str) -> Optional[bytes]:
        """
        Download a file given its direct dl URL.
        Returns raw bytes on success, None on failure.

        Two classes of retryable failure are handled:

        1. Network-level exceptions (ERR_CONNECTION_RESET, tunnel failures, …)
           — caught in the outer except block via _RETRYABLE_ERRORS substrings.

        2. Cloudflare 5xx HTML pages returned as the file body (error 522, 523…)
           — the download "succeeds" from Playwright's perspective but the bytes
           are an HTML error page, not the real file. Detected by
           _is_cloudflare_error_page() after save_as completes.

        WHY the inner try/except around goto():
          Playwright raises "Page.goto: Download is starting" as an EXCEPTION
          even when expect_download() is correctly registered and listening.
          This is a known Playwright quirk — the download event still fires
          and dl_info.value is populated correctly. We swallow that specific
          error and continue; anything else is re-raised.
        """
        if not download_url or download_url == 'N/A':
            return None

        print(f"    Download URL: {download_url}")

        def _save_download(download_obj) -> Optional[bytes]:
            suffix = os.path.splitext(download_obj.suggested_filename)[1] or '.bin'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
            try:
                download_obj.save_as(tmp_path)
                return _read_and_delete(tmp_path)
            except Exception as e:
                print(f"      save_as failed: {e}")
                try:
                    pw_path = download_obj.path()
                    if pw_path and os.path.exists(pw_path):
                        return _read_and_delete(pw_path)
                except Exception:
                    pass
                return None

        def _is_retryable_exception(err: Exception) -> bool:
            msg = str(err)
            return any(tag in msg for tag in self._RETRYABLE_ERRORS)

        for attempt in range(1, self._MAX_RETRIES + 1):
            dl_page = None
            try:
                dl_page = context.new_page()
                with dl_page.expect_download(timeout=60000) as dl_info:
                    try:
                        dl_page.goto(download_url, wait_until="commit", timeout=60000)
                    except Exception as goto_err:
                        if "Download is starting" not in str(goto_err):
                            raise

                data = _save_download(dl_info.value)

                if not data:
                    # Empty file — not a transient error, give up immediately
                    print("    ✗ save_as returned no data")
                    return None

                # Check whether we actually got a Cloudflare error HTML page
                cf_reason = self._is_cloudflare_error_page(data)
                if cf_reason:
                    if attempt < self._MAX_RETRIES:
                        delay = self._RETRY_BACKOFF[attempt - 1]
                        print(f"    ⚠ Attempt {attempt}/{self._MAX_RETRIES} — {cf_reason}")
                        print(f"      Retrying in {delay}s...")
                        time.sleep(delay)
                        continue   # next attempt
                    else:
                        print(f"    ✗ {cf_reason} — all {self._MAX_RETRIES} attempts exhausted")
                        return None

                attempt_tag = f" (attempt {attempt})" if attempt > 1 else ""
                print(f"    ✓ Downloaded {len(data):,} bytes{attempt_tag}")
                return data

            except Exception as e:
                if _is_retryable_exception(e) and attempt < self._MAX_RETRIES:
                    delay = self._RETRY_BACKOFF[attempt - 1]
                    print(f"    ⚠ Attempt {attempt}/{self._MAX_RETRIES} failed (network): {e}")
                    print(f"      Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    print(f"    ✗ Download failed (attempt {attempt}/{self._MAX_RETRIES}): {e}")
                    return None
            finally:
                if dl_page:
                    try:
                        dl_page.close()
                    except Exception:
                        pass

        return None


def _read_and_delete(path: str) -> bytes:
    with open(path, 'rb') as f:
        data = f.read()
    try:
        os.unlink(path)
    except OSError:
        pass
    return data