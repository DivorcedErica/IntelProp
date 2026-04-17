#!/usr/bin/env python3
"""
IntelProp — Wayback Machine bulk enrichment
Reads dom.com.cy listing URLs from Google Sheet
Extracts images + delivery date from archived pages
Writes results back to sheet

Requirements:
    pip install beautifulsoup4 gspread

Usage:
    python enrich.py
"""

import re
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import gspread

# ── Config ──────────────────────────────────────────────────────
SHEET_ID      = '1A4e51pB7O6BxYrXDAaWH2ZvjxLIQjiq-a2WpuhSs9dc'
WORKSHEET_GID = 248082817

COL_LISTING_URL = 18   # column S  — dom.com.cy listing URL
COL_IMG1        = 13   # column N
COL_IMG2        = 14   # column O
COL_IMG3        = 15   # column P
COL_IMG4        = 16   # column Q
COL_DELIVERY    = 17   # column R

CONCURRENCY   = 6      # parallel Wayback requests
BATCH_SIZE    = 20     # rows per batch before writing progress
BATCH_DELAY   = 1.0    # seconds between batches
MAX_ROWS      = 5      # set to None to process all
PROGRESS_FILE = Path('enrich_progress.json')

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; research/archival)'}

# ── Resume support ───────────────────────────────────────────────
def load_progress():
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()))
    return set()

def save_progress(done: set):
    PROGRESS_FILE.write_text(json.dumps(list(done)))

# ── HTTP helpers ─────────────────────────────────────────────────
def http_get(url: str, timeout: int = 20) -> str | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode('utf-8', errors='replace')
    except Exception:
        return None

# ── Wayback CDX API ──────────────────────────────────────────────
def get_wayback_url(url: str) -> str | None:
    params = urllib.parse.urlencode({
        'url': url, 'output': 'json', 'limit': 1,
        'filter': 'statuscode:200', 'fl': 'timestamp,original',
    })
    text = http_get(f'https://web.archive.org/cdx/search/cdx?{params}', timeout=15)
    if not text or not text.strip() or text.strip() == '[]':
        return None
    try:
        rows = json.loads(text)
        if len(rows) < 2:
            return None
        ts, orig = rows[1]
        return f'https://web.archive.org/web/{ts}/{orig}'
    except Exception:
        return None

# ── Parse Bitrix listing page ────────────────────────────────────
WAYBACK_BASE = 'https://web.archive.org'

def to_wayback_img(src: str) -> str:
    if not src:
        return ''
    if 'web.archive.org' in src:
        src = re.sub(r'(web\.archive\.org/web/)(\d+)([a-z_]*)(/)','\\1\\2im_\\4', src)
        if not src.startswith('http'):
            src = WAYBACK_BASE + src
        return src
    if src.startswith('/web/'):
        src = re.sub(r'^(/web/)(\d+)([a-z_]*)(/)','\\1\\2im_\\4', src)
        return WAYBACK_BASE + src
    return ''

def parse_page(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    images = []
    seen   = set()

    def add_img(src: str):
        if not src or len(images) >= 4:
            return
        url = to_wayback_img(src)
        if url and url not in seen:
            seen.add(url)
            images.append(url)

    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/upload/' in href and re.search(r'\.(jpe?g|png|webp)', href, re.I):
            add_img(href)

    if len(images) < 4:
        for img in soup.find_all('img'):
            for attr in ('src', 'data-src', 'data-lazy-src', 'data-original'):
                src = img.get(attr, '')
                if '/upload/' in src:
                    add_img(src)
                    break

    if len(images) < 4:
        for script in soup.find_all('script'):
            text = script.string or ''
            if '/upload/' not in text:
                continue
            for url in re.findall(r'["\']([^"\']*?/upload/[^"\']*?\.jpe?g)["\']', text, re.I):
                add_img(url)

    delivery = None
    body = soup.get_text(' ', strip=True)
    patterns = [
        r'\b(Q[1-4]\s*20[2-3]\d)\b',
        r'\b(20[2-3]\d)\s*(?:year|completion|delivery|г\.?)',
        r'\b(ready\s*(?:now|for\s*occupancy)?)\b',
        r'\b(immediate\s*(?:delivery|occupancy))\b',
        r'\b(completed?)\b',
    ]
    for pat in patterns:
        m = re.search(pat, body, re.I)
        if m:
            delivery = m.group(1).strip().title()
            break

    return {'images': images[:4], 'delivery': delivery}

# ── Process one listing ──────────────────────────────────────────
def process(row_idx: int, row: list) -> dict | None:
    listing_url = row[COL_LISTING_URL].strip() if len(row) > COL_LISTING_URL else ''
    if not listing_url.startswith('http'):
        return None

    already_has = len(row) > COL_IMG1 and row[COL_IMG1].strip()
    if already_has:
        return None

    wayback_url = get_wayback_url(listing_url)
    if not wayback_url:
        print(f'  [no archive] row {row_idx}')
        return None

    html = http_get(wayback_url, timeout=25)
    if not html:
        return None

    data = parse_page(html)
    if not data['images'] and not data['delivery']:
        return None

    imgs = (data['images'] + ['', '', '', ''])[:4]
    print(f'  [ok] row {row_idx}: {len(data["images"])} imgs  delivery={data["delivery"]}')
    return {'row': row_idx, 'imgs': imgs, 'delivery': data['delivery'] or ''}

# ── Main ─────────────────────────────────────────────────────────
def main():
    print('Connecting to Google Sheet…')
    gc = gspread.oauth()
    sh = gc.open_by_key(SHEET_ID)
    ws = next(w for w in sh.worksheets() if w.id == WORKSHEET_GID)

    rows = ws.get_all_values()
    data_rows = rows[1:]
    total = len(data_rows)
    print(f'Loaded {total} listings')

    done = load_progress()
    pending = [
        (i + 2, row)
        for i, row in enumerate(data_rows)
        if str(i + 2) not in done
    ]
    if MAX_ROWS:
        pending = pending[:MAX_ROWS]
    print(f'{len(pending)} listings to process  ({len(done)} already done)\n')

    updates = []

    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start:batch_start + BATCH_SIZE]

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
            futures = {ex.submit(process, row_idx, row): row_idx for row_idx, row in batch}
            for future in as_completed(futures):
                row_idx = futures[future]
                done.add(str(row_idx))
                result = future.result()
                if result:
                    updates.append(result)

        save_progress(done)
        completed = batch_start + len(batch)
        print(f'Progress: {completed}/{len(pending)}  ({len(updates)} enriched so far)\n')
        time.sleep(BATCH_DELAY)

    if not updates:
        print('Nothing to write.')
        return

    print(f'\nWriting {len(updates)} rows to sheet…')
    batch_updates = []
    for u in updates:
        r = u['row']
        i = u['imgs']
        batch_updates += [
            {'range': f'N{r}', 'values': [[i[0]]]},
            {'range': f'O{r}', 'values': [[i[1]]]},
            {'range': f'P{r}', 'values': [[i[2]]]},
            {'range': f'Q{r}', 'values': [[i[3]]]},
        ]
        if u['delivery']:
            batch_updates.append({'range': f'R{r}', 'values': [[u['delivery']]]})

    for chunk_start in range(0, len(batch_updates), 200):
        ws.batch_update(batch_updates[chunk_start:chunk_start + 200])
        if chunk_start + 200 < len(batch_updates):
            time.sleep(2)

    print(f'Done. {len(updates)} listings enriched.')
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

if __name__ == '__main__':
    main()
