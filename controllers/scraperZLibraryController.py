# controllers/scraperZLibraryController.py
import io
import json
import queue
import re
import threading
import time
import unicodedata
import uuid
import zipfile
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote

from flask import Response, jsonify, render_template, request
from playwright.sync_api import sync_playwright

from models.scraperZLibraryModel import ZLibraryScraperModel

# ---------------------------------------------------------------------------
# Temp file store: token -> {filename, content, size, expires}
# Each downloaded file is parked here for 5 minutes so the frontend can
# fetch it with a simple GET.  Expired entries are evicted lazily.
# ---------------------------------------------------------------------------
_file_store: Dict[str, Dict] = {}
_file_store_lock = threading.Lock()


def _store_file(filename: str, content: bytes) -> str:
    """Save file bytes under a short-lived token; return the token."""
    token = uuid.uuid4().hex
    with _file_store_lock:
        _file_store[token] = {
            'filename': filename,
            'content': content,
            'size': len(content),
            'expires': time.time() + 300,   # 5 minutes
        }
    return token


def _pop_file(token: str) -> Optional[Dict]:
    """Retrieve and delete a stored file by token. Returns None if expired."""
    with _file_store_lock:
        entry = _file_store.pop(token, None)
    if entry and time.time() > entry['expires']:
        return None
    return entry


def _evict_expired():
    """Remove any entries that have passed their TTL."""
    now = time.time()
    with _file_store_lock:
        for k in [k for k, v in _file_store.items() if now > v['expires']]:
            del _file_store[k]


def _content_disposition(filename: str) -> str:
    """
    Build a Content-Disposition header safe for all HTTP clients.

    Provides both:
      - legacy filename= with non-ASCII stripped (latin-1 safe)
      - RFC 5987 filename*= with full UTF-8 percent-encoding

    Example:
      attachment; filename="Lap_trinh_Python.pdf"; filename*=UTF-8''L%E1%BA%ADp%20tr%C3%ACnh%20Python.pdf
    """
    ascii_name = filename.encode('ascii', 'ignore').decode('ascii')
    ascii_name = ascii_name.replace('"', '_').replace('\\', '_') or 'download'
    encoded_name = quote(filename, safe='.-_~')
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


def _mimetype_for(filename: str) -> str:
    """Return a sensible Content-Type for common ebook/document extensions."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return {
        'pdf':  'application/pdf',
        'epub': 'application/epub+zip',
        'mobi': 'application/x-mobipocket-ebook',
        'azw':  'application/vnd.amazon.ebook',
        'azw3': 'application/vnd.amazon.ebook',
        'fb2':  'application/x-fictionbook+xml',
        'djvu': 'image/vnd.djvu',
        'txt':  'text/plain',
        'doc':  'application/msword',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }.get(ext, 'application/octet-stream')


class ScraperController:
    """
    Controller owns all business logic:
      - orchestrating login + scraping + download flows
      - streaming individual files directly to the client via SSE + token fetch
      - computing statistics
      - formatting responses
    The model is only called for browser/scraping primitives.
    """

    _model = ZLibraryScraperModel()

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @classmethod
    def index(cls):
        return render_template('scraperZLibraryPages/scraperZLibraryMain.html')

    @classmethod
    def search_books(cls):
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Invalid request data'}), 400

        query = data.get('query', '').strip()
        page_num = data.get('page', 1)
        headless = data.get('headless', True)

        if not query:
            return jsonify({'success': False, 'error': 'Query is required'}), 400
        if len(query) < 2:
            return jsonify({'success': False, 'error': 'Query must be at least 2 characters'}), 400

        try:
            books, total_pages, total_books = cls._run_search(query, page_num, headless)
            statistics = cls._calculate_statistics(books)

            return jsonify({
                'success': True,
                'query': query,
                'books': [b.to_dict() for b in books],
                'statistics': statistics,
                'total_count': len(books),
                'current_page': page_num,
                'total_pages': total_pages,
                'total_books_count': total_books,
            })

        except Exception as e:
            import traceback; traceback.print_exc()
            return jsonify({'success': False, 'error': str(e), 'books': [], 'statistics': {}}), 500

    @classmethod
    def download_txt(cls):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No results provided'}), 400

        text_content = cls._format_results_as_text(data)
        return Response(
            text_content,
            mimetype='text/plain',
            headers={
                'Content-Disposition': (
                    f'attachment;filename=zlib_{data.get("query", "search")}_results.txt'
                )
            },
        )

    @classmethod
    def download_json(cls):
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No results provided'}), 400

        return Response(
            json.dumps(data, indent=2, ensure_ascii=False),
            mimetype='application/json',
            headers={
                'Content-Disposition': (
                    f'attachment;filename=zlib_{data.get("query", "search")}_results.json'
                )
            },
        )

    @classmethod
    def download_books_stream(cls):
        """
        SSE endpoint. Opens one browser session, iterates through the requested
        books, and for each book:
          1. Downloads the file in the background thread.
          2. Parks the bytes in _file_store under a one-time token.
          3. Emits a 'ready' SSE event with the token.
          4. The frontend immediately triggers GET /api/download/file/<token>
             which streams the file to the user with its native MIME type.

        Events emitted (newline-delimited JSON after 'data: '):
          {"type": "progress", "index": i, "total": n, "title": "..."}
          {"type": "ready",    "index": i, "total": n, "title": "...",
                               "token": "<hex>", "filename": "book.pdf"}
          {"type": "error",    "index": i, "total": n, "title": "...", "message": "..."}
          {"type": "done",     "total": n, "success": k, "failed": m}
        """
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        books = data.get('books', [])
        headless = data.get('headless', True)

        if not books:
            return jsonify({'error': 'No books provided'}), 400

        q: queue.Queue = queue.Queue()

        def _worker():
            with sync_playwright() as p:
                context = cls._model.create_context(p, headless)
                try:
                    page, ok = cls._model.login(context)
                    if not ok:
                        print("⚠ Proceeding without confirmed login — downloads may fail")

                    success = failed = 0

                    for idx, book_data in enumerate(books, 1):
                        title = book_data.get('title', f'Book {idx}')
                        q.put({'type': 'progress', 'index': idx,
                               'total': len(books), 'title': title})

                        book_link = book_data.get('link', 'N/A')
                        if not book_link or book_link == 'N/A':
                            failed += 1
                            q.put({'type': 'error', 'index': idx, 'total': len(books),
                                   'title': title, 'message': 'No link available'})
                            continue

                        try:
                            print(f"\n[{idx}/{len(books)}] Navigating to: {book_link}")
                            page.goto(book_link, timeout=30000)
                            page.wait_for_load_state('networkidle')

                            download_url, _ = cls._model.extract_download_info(page)
                            if download_url == 'N/A':
                                raise ValueError('Could not find download URL')

                            content = cls._model.download_file(page, context, download_url)
                            if not content:
                                raise ValueError('No file content received')

                            filename = cls._build_filename(book_data, idx)
                            token = _store_file(filename, content)
                            success += 1

                            print(f"  ✅ Ready: {filename} ({len(content):,} bytes) — token: {token}")
                            q.put({'type': 'ready', 'index': idx, 'total': len(books),
                                   'title': title, 'token': token, 'filename': filename})

                        except Exception as e:
                            failed += 1
                            print(f"  ❌ Error: {e}")
                            q.put({'type': 'error', 'index': idx, 'total': len(books),
                                   'title': title, 'message': str(e)})

                    q.put({'type': 'done', 'total': len(books),
                           'success': success, 'failed': failed})

                finally:
                    context.close()
                    q.put(None)   # sentinel — tells generator to stop

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

        def _generate():
            while True:
                event = q.get()
                if event is None:
                    break
                yield f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
            _evict_expired()

        return Response(
            _generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',   # disable nginx buffering if present
            },
        )

    @classmethod
    def fetch_stored_file(cls, token: str):
        """
        GET endpoint. Pops a previously stored file by token and streams it
        to the client with the correct MIME type. One-time use — token is
        consumed on first access.
        """
        entry = _pop_file(token)
        if not entry:
            return jsonify({'error': 'File not found or expired'}), 404

        mimetype = _mimetype_for(entry['filename'])
        print(f"📤 Serving: {entry['filename']} ({entry['size']:,} bytes)")
        return Response(
            entry['content'],
            mimetype=mimetype,
            headers={
                'Content-Disposition': _content_disposition(entry['filename']),
                'Content-Length': str(entry['size']),
            },
        )

    # Keep old route names as aliases so any existing calls still work
    @classmethod
    def download_books(cls):
        return cls.download_books_stream()

    download_books_zip = download_books

    # ------------------------------------------------------------------
    # Business logic — search
    # ------------------------------------------------------------------

    @classmethod
    def _run_search(cls, query: str, page_num: int, headless: bool):
        """Open browser, login, scrape one results page, return raw data."""
        encoded = query.replace(' ', '%20')
        url = f"{cls._model.BASE_URL}/s/{encoded}?view=table"
        if page_num > 1:
            url += f"&page={page_num}"

        with sync_playwright() as p:
            context = cls._model.create_context(p, headless)
            try:
                page, ok = cls._model.login(context)
                if not ok:
                    print("⚠ Proceeding without confirmed login")

                print(f"Accessing: {url}")
                page.goto(url, timeout=60000)
                page.wait_for_load_state("networkidle")

                total_pages = cls._model.get_total_pages(page)
                total_books = cls._model.get_total_books_count(page)
                print(f"Total pages available: {total_pages}")
                print(f"Total books found: {total_books}")

                try:
                    page.wait_for_selector('table.table_book tbody tr', timeout=10000)
                except Exception:
                    print(f"No table found on page {page_num}")
                    return [], total_pages, total_books

                books = cls._model.extract_books_from_table(page)
                print(f"Found {len(books)} books on page {page_num}")
                return books, total_pages, total_books

            except Exception as e:
                import traceback; traceback.print_exc()
                raise
            finally:
                context.close()

    # ------------------------------------------------------------------
    # Business logic — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filename(book_data: Dict, idx: int) -> str:
        """Derive a safe ASCII filename from book metadata."""
        raw_title = book_data.get('title', '')[:50]
        # Normalize unicode → closest ASCII, then drop anything remaining non-ASCII
        ascii_title = unicodedata.normalize('NFKD', raw_title)
        ascii_title = ascii_title.encode('ascii', 'ignore').decode('ascii')
        safe_title = re.sub(r'[^\w\s-]', '', ascii_title)
        safe_title = re.sub(r'[-\s]+', '_', safe_title).strip('_') or f"book_{idx}"
        extension = book_data.get('file', 'txt').split(',')[0].strip().lower()
        if not extension or extension == 'n/a':
            extension = 'txt'
        return f"{safe_title}.{extension}"

    @staticmethod
    def _calculate_statistics(books) -> Dict:
        """Compute language/year/format distribution from a list of Book objects."""
        if not books:
            return {}

        stats: Dict = {
            'total_books': len(books),
            'languages': {},
            'years': {},
            'formats': {},
        }

        for book in books:
            lang = book.language
            stats['languages'][lang] = stats['languages'].get(lang, 0) + 1

            year = book.year
            if year != 'N/A' and year.isdigit():
                stats['years'][year] = stats['years'].get(year, 0) + 1

            if book.file != 'N/A':
                m = re.match(r'([a-zA-Z0-9]+)', book.file)
                if m:
                    fmt = m.group(1).upper()
                    stats['formats'][fmt] = stats['formats'].get(fmt, 0) + 1

        return stats

    @classmethod
    def _format_results_as_text(cls, results: Dict) -> str:
        if not results.get('success'):
            return f"Error: {results.get('error', 'Unknown error')}"

        lines = [
            "=" * 80,
            "Z-Library Search Results",
            "=" * 80,
            f"Search Query: {results['query']}",
            f"Total Books Found: {results.get('total_books_count', results['total_count'])}",
            f"Books in this export: {results['total_count']}",
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 80,
            "",
        ]

        for idx, book in enumerate(results['books'], 1):
            authors_str = ', '.join(book.get('authors', [])) or 'N/A'
            lines += [
                f"Book #{idx}",
                "-" * 60,
                f"Title:     {book['title']}",
                f"Author(s): {authors_str}",
                f"Publisher: {book.get('publisher', 'N/A')}",
                f"Year:      {book.get('year', 'N/A')}",
                f"Pages:     {book.get('pages', 'N/A')}",
                f"Language:  {book.get('language', 'N/A')}",
                f"File:      {book.get('file', 'N/A')}",
                f"Link:      {book.get('link', 'N/A')}",
            ]
            if book.get('download_url') and book['download_url'] != 'N/A':
                lines.append(f"Download:  {book['download_url']}")
            if book.get('file_size') and book['file_size'] != 'N/A':
                lines.append(f"Size:      {book['file_size']}")
            lines += ["=" * 80, ""]

        stats = results.get('statistics', {})
        if stats:
            total = results['total_count']
            lines += ["", "=" * 80, "SUMMARY STATISTICS", "=" * 80,
                      f"Total Books: {stats.get('total_books', 0)}"]

            if stats.get('languages'):
                lines.append("\nLanguages:")
                for lang, count in sorted(stats['languages'].items(), key=lambda x: -x[1]):
                    pct = count / total * 100 if total else 0
                    lines.append(f"  {lang}: {count} ({pct:.1f}%)")

            if stats.get('formats'):
                lines.append("\nFormats:")
                for fmt, count in sorted(stats['formats'].items(), key=lambda x: -x[1]):
                    pct = count / total * 100 if total else 0
                    lines.append(f"  {fmt}: {count} ({pct:.1f}%)")

            if stats.get('years'):
                lines.append("\nPublication Years (Top 10):")
                for year, count in sorted(stats['years'].items(), key=lambda x: -x[1])[:10]:
                    lines.append(f"  {year}: {count}")

        return "\n".join(lines)