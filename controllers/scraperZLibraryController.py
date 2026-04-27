# controllers/scraperZLibraryController.py
import io
import json
import re
import zipfile
from datetime import datetime
from typing import Dict, List, Optional

from flask import Response, jsonify, render_template, request
from playwright.sync_api import sync_playwright

from models.scraperZLibraryModel import ZLibraryScraperModel


class ScraperController:
    """
    Controller owns all business logic:
      - orchestrating login + scraping + download flows
      - streaming individual files directly to the client (no ZIP)
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
    def download_books(cls):
        """
        Download books and stream each file individually to the client.

        Because browsers can only receive one file per HTTP response, this
        endpoint returns a JSON manifest of results. The frontend should call
        /api/download/book/<idx> for each book, or we return a ZIP as a
        fallback for multi-book requests.

        For a single book: stream the file directly.
        For multiple books: still ZIP (browser limitation), but the root cause
        fix (expect_download order) means files are now actually captured.
        """
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        books = data.get('books', [])
        max_books = data.get('max_books')
        headless = data.get('headless', True)

        if not books:
            return jsonify({'error': 'No books provided'}), 400

        try:
            books_to_fetch = books[:max_books] if max_books else books
            print(f"\n📚 Controller: Starting download of {len(books_to_fetch)} books...")
            downloaded_files = cls._run_download(books_to_fetch, headless)

            if not downloaded_files:
                return jsonify({'error': 'No files could be downloaded'}), 500

            # Single book → stream directly with its native mimetype
            if len(downloaded_files) == 1:
                f = downloaded_files[0]
                mimetype = _mimetype_for(f['filename'])
                print(f"📤 Streaming single file: {f['filename']} ({f['size']:,} bytes)")
                return Response(
                    f['content'],
                    mimetype=mimetype,
                    headers={
                        'Content-Disposition': f'attachment;filename="{f["filename"]}"',
                        'Content-Length': str(f['size']),
                    },
                )

            # Multiple books → ZIP (only viable option in a single HTTP response)
            print(f"📦 Multiple files ({len(downloaded_files)}), returning ZIP...")
            safe_query = re.sub(r'[^\w]', '_', data.get('query', 'download'))[:50]
            zip_bytes = cls._build_zip(downloaded_files)
            return Response(
                zip_bytes,
                mimetype='application/zip',
                headers={
                    'Content-Disposition': f'attachment;filename=zlib_books_{safe_query}.zip',
                    'Content-Length': str(len(zip_bytes)),
                },
            )

        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"❌ Controller error: {e}")
            return jsonify({'error': str(e)}), 500

    # Keep old route name as alias so existing frontend calls still work
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
    # Business logic — download
    # ------------------------------------------------------------------

    @classmethod
    def _run_download(cls, books: List[Dict], headless: bool) -> List[Dict]:
        """
        Login once, iterate books, download each file.
        Returns list of {filename, content, size} dicts for successful downloads.
        """
        downloaded_files = []

        with sync_playwright() as p:
            context = cls._model.create_context(p, headless)
            try:
                page, ok = cls._model.login(context)
                if not ok:
                    print("⚠ Proceeding without confirmed login — downloads may fail")

                for idx, book_data in enumerate(books, 1):
                    title_preview = book_data.get('title', '')[:50]
                    print(f"\n[{idx}/{len(books)}] Processing: {title_preview}...")

                    book_link = book_data.get('link', 'N/A')
                    if not book_link or book_link == 'N/A':
                        print("  ⚠ No link, skipping")
                        continue

                    try:
                        print(f"  Navigating to: {book_link}")
                        page.goto(book_link, timeout=30000)
                        page.wait_for_load_state("networkidle")

                        download_url, file_size = cls._model.extract_download_info(page)
                        if download_url == 'N/A':
                            print("  ✗ Could not find download URL, skipping")
                            continue

                        # download_file opens its own fresh page internally
                        file_content = cls._model.download_file(page, context, download_url)
                        if not file_content:
                            print("  ❌ No file content received")
                            continue

                        filename = cls._build_filename(book_data, idx)
                        downloaded_files.append({
                            'filename': filename,
                            'content': file_content,
                            'size': len(file_content),
                        })
                        print(f"  ✅ Ready: {filename} ({len(file_content):,} bytes)")

                    except Exception as e:
                        print(f"  ❌ Error processing book: {e}")

            finally:
                context.close()

        return downloaded_files

    # ------------------------------------------------------------------
    # Business logic — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filename(book_data: Dict, idx: int) -> str:
        """Derive a safe filename from book metadata."""
        safe_title = re.sub(r'[^\w\s-]', '', book_data.get('title', '')[:50])
        safe_title = re.sub(r'[-\s]+', '_', safe_title).strip('_') or f"book_{idx}"
        extension = book_data.get('file', 'txt').split(',')[0].strip().lower()
        if not extension or extension == 'n/a':
            extension = 'txt'
        return f"{safe_title}.{extension}"

    @staticmethod
    def _build_zip(files: List[Dict]) -> bytes:
        """Pack a list of {filename, content} dicts into a ZIP and return bytes."""
        print(f"\n📦 Creating ZIP archive with {len(files)} files...")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.writestr(f['filename'], f['content'])
                print(f"  Added: {f['filename']} ({f['size']:,} bytes)")
        buf.seek(0)
        total = buf.getbuffer().nbytes
        print(f"✅ ZIP archive ready: {total:,} bytes, {len(files)} files")
        return buf.getvalue()

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


# ------------------------------------------------------------------
# Module-level helper
# ------------------------------------------------------------------

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