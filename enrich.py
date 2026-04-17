#!/usr/bin/env python3
"""
IntelProp — Wayback Machine bulk enrichment
Reads dom.com.cy listing URLs from Google Sheet
Extracts images + delivery date from archived pages
Writes results back to sheet

Requirements:
    pip install aiohttp beautifulsoup4 gspread

Usage:
    python enrich.py
"""

import asyncio
import re
import json
from pathlib import Path
import aiohttp
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

CONCURRENCY  = 8       # concurrent Wayback requests
BATCH_DELAY  = 0.5     # seconds between batches (be polite)
PROGRESS_FILE = Path('enrich_progress.json')

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; research/archival)'}

# ── Resume support ───────────────────────────────────────────────
def load_progress():
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()))
    return set()

def save_progress(done: set):
    PROGRESS_FILE.write_text(json.dumps(list(done)))

# ── Wayback CDX API ──────────────────────────────────────────────
async def get_wayback_url(session: aiohttp.ClientSession, url: str) -> str | None:
    """Return most recent archived URL from Wayback Machine, or None."""
    params = {
        'url': url, 'output': 'json', 'limit': 1,
        'filter': 'statuscode:200', 'fl': 'timestamp,original',
    }
    try:
        async with session.get(
            'http://web.archive.org/cdx/search/cdx',
            params=params, timeout=aiohttp.ClientTimeout(total=12)
        ) as r:
            if r.status != 200:
                return None
            rows = await r.json(content_type=None)
            if len(rows) < 2:
                return None
            ts, orig = rows[1]
            return f'https://web.archive.org/web/{ts}/{orig}'
    except Exception:
        return None

# ── Fetch HTML ───────────────────────────────────────────────────
async def fetch_html(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(
            url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=25),
            allow_redirects=True
        ) as r:
            if r.status == 200:
                return await r.text(errors='replace')
    except Exception:
        pass
    return None

# ── Parse Bitrix listing page ────────────────────────────────────
WAYBACK_BASE = 'https://web.archive.org'

def to_wayback_img(src: str) -> str:
    """Ensure image URL is served from archive.org, never from dom.com.cy directly."""
    if not src:
        return ''
    # Already a full Wayback URL
    if 'web.archive.org' in src:
        # Normalise: ensure im_ modifier is present for direct image serving
        src = re.sub(r'(web\.archive\.org/web/)(\d+)([a-z_]*)(/)','\\1\\2im_\\4', src)
        if not src.startswith('http'):
            src = WAYBACK_BASE + src
        return src
    # Relative Wayback path like /web/20240115im_/https://dom.com.cy/...
    if src.startswith('/web/'):
        src = re.sub(r'^(/web/)(\d+)([a-z_]*)(/)','\\1\\2im_\\4', src)
        return WAYBACK_BASE + src
    # Raw dom.com.cy URL — should not happen if we always fetch from Wayback
    # but handle it: prefix is not stored, return empty to avoid direct hit
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

    # Strategy 1: <a href> links to full-size Bitrix upload images
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/upload/' in href and re.search(r'\.(jpe?g|png|webp)', href, re.I):
            add_img(href)

    # Strategy 2: <img src / data-src> with upload path
    if len(images) < 4:
        for img in soup.find_all('img'):
            for attr in ('src', 'data-src', 'data-lazy-src', 'data-original'):
                src = img.get(attr, '')
                if '/upload/' in src:
                    add_img(src)
                    break

    # Strategy 3: JSON in <script> tags
    if len(images) < 4:
        for script in soup.find_all('script'):
            text = script.string or ''
            if '/upload/' not in text:
                continue
            for url in re.findall(r'["\']([^"\']*?/upload/[^"\']*?\.jpe?g)["\']', text, re.I):
                add_img(url)

    # ── Delivery date ────────────────────────────────────────────
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

    # ── Developer & complex ──────────────────────────────────────
    developer = None
    complex_name = None

    # Bitrix often puts developer in a specific field/label
    for label in soup.find_all(string=re.compile(r'developer|developer|κατασκευαστής', re.I)):
        parent = label.find_parent()
        if parent:
            sibling = parent.find_next_sibling()
            if sibling:
                developer = sibling.get_text(strip=True) or None
                break

    return {
        'images':    images[:4],
        'delivery':  delivery,
        'developer': developer,
        'complex':   complex_name,
    }

# ── Process one listing ──────────────────────────────────────────
async def process(session: aiohttp.ClientSession, row_idx: int, row: list) -> dict | None:
    listing_url = row[COL_LISTING_URL].strip() if len(row) > COL_LISTING_URL else ''
    if not listing_url.startswith('http'):
        return None

    # Skip if images already filled
    already_has = len(row) > COL_IMG1 and row[COL_IMG1].strip()
    if already_has:
        return None

    wayback_url = await get_wayback_url(session, listing_url)

    if not wayback_url:
        print(f'  [no archive] row {row_idx}: {listing_url}')
        return None

    html = await fetch_html(session, wayback_url)
    if not html:
        return None

    data = parse_page(html)
    if not data['images'] and not data['delivery']:
        return None

    imgs = (data['images'] + ['', '', '', ''])[:4]
    print(f'  [wayback] row {row_idx}: {len(data["images"])} imgs  delivery={data["delivery"]}')
    return {'row': row_idx, 'imgs': imgs, 'delivery': data['delivery'] or ''}

# ── Main ─────────────────────────────────────────────────────────
async def main():
    print('Connecting to Google Sheet…')
    gc = gspread.oauth()
    sh = gc.open_by_key(SHEET_ID)
    ws = next(w for w in sh.worksheets() if w.id == WORKSHEET_GID)

    rows = ws.get_all_values()
    data_rows = rows[1:]   # skip header
    total = len(data_rows)
    print(f'Loaded {total} listings')

    done = load_progress()
    pending = [
        (i + 2, row)                      # +2: 1-based + skip header
        for i, row in enumerate(data_rows)
        if str(i + 2) not in done
    ]
    print(f'{len(pending)} listings to process  ({len(done)} already done)\n')

    updates = []
    connector = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        for batch_start in range(0, len(pending), CONCURRENCY):
            batch = pending[batch_start:batch_start + CONCURRENCY]
            results = await asyncio.gather(*[
                process(session, row_idx, row) for row_idx, row in batch
            ])

            for (row_idx, _), result in zip(batch, results):
                done.add(str(row_idx))
                if result:
                    updates.append(result)

            save_progress(done)

            completed = batch_start + len(batch)
            print(f'Progress: {completed}/{len(pending)}  '
                  f'({len(updates)} enriched so far)\n')

            await asyncio.sleep(BATCH_DELAY)

    # ── Write to sheet ───────────────────────────────────────────
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

    # Sheet API allows 300 writes/min — chunk into 200 at a time
    for chunk_start in range(0, len(batch_updates), 200):
        ws.batch_update(batch_updates[chunk_start:chunk_start + 200])
        if chunk_start + 200 < len(batch_updates):
            await asyncio.sleep(2)

    print(f'Done. {len(updates)} listings enriched.')
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()   # clean up

if __name__ == '__main__':
    asyncio.run(main())
