#!/usr/bin/env python3
"""
Quick test — checks one dom.com.cy URL against Wayback Machine
Shows raw findings so you can verify parsing before running the full script

Usage:
    python test_one.py https://dom.com.cy/catalog/sale/12345/
"""

import asyncio
import sys
import re
import aiohttp
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; research/archival)'}

async def test(url: str):
    async with aiohttp.ClientSession() as session:

        # Step 1: Wayback CDX
        print(f'\n1. Checking Wayback Machine for: {url}')
        params = {
            'url': url, 'output': 'json', 'limit': 1,
            'filter': 'statuscode:200', 'fl': 'timestamp,original',
        }
        async with session.get('http://web.archive.org/cdx/search/cdx', params=params) as r:
            rows = await r.json(content_type=None)

        if len(rows) < 2:
            print('   ✗ No Wayback snapshot found — nothing to do.')
            return
        else:
            ts, orig = rows[1]
            archived_url = f'https://web.archive.org/web/{ts}/{orig}'
            print(f'   ✓ Snapshot found: {ts[:8]}')
            print(f'   → {archived_url}')

        # Step 2: Fetch HTML
        print(f'\n2. Fetching page...')
        async with session.get(archived_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as r:
            html = await r.text(errors='replace')
        print(f'   ✓ Got {len(html):,} bytes of HTML')

        soup = BeautifulSoup(html, 'html.parser')

        # Step 3: Show all image candidates
        print(f'\n3. Image candidates found in HTML:')

        print('\n   [A] <a href> links with /upload/:')
        a_imgs = [a['href'] for a in soup.find_all('a', href=True)
                  if '/upload/' in a['href'] and re.search(r'\.(jpe?g|png|webp)', a['href'], re.I)]
        for u in a_imgs[:8]:
            print(f'      {u}')
        if not a_imgs:
            print('      (none)')

        print('\n   [B] <img> tags with /upload/:')
        img_tags = []
        for img in soup.find_all('img'):
            for attr in ('src','data-src','data-lazy-src','data-original'):
                val = img.get(attr,'')
                if '/upload/' in val:
                    img_tags.append(val)
                    break
        for u in img_tags[:8]:
            print(f'      {u}')
        if not img_tags:
            print('      (none)')

        print('\n   [C] /upload/ URLs in <script> tags:')
        script_imgs = []
        for script in soup.find_all('script'):
            text = script.string or ''
            if '/upload/' in text:
                found = re.findall(r'["\']([^"\']*?/upload/[^"\']*?\.jpe?g)["\']', text, re.I)
                script_imgs.extend(found)
        for u in script_imgs[:8]:
            print(f'      {u}')
        if not script_imgs:
            print('      (none)')

        # Step 4: Delivery date
        print(f'\n4. Delivery date search:')
        body = soup.get_text(' ', strip=True)
        patterns = [
            r'\b(Q[1-4]\s*20[2-3]\d)\b',
            r'\b(20[2-3]\d)\s*(?:year|completion|delivery)',
            r'\b(ready\s*(?:now|for\s*occupancy)?)\b',
            r'\b(immediate\s*(?:delivery|occupancy))\b',
            r'\b(completed?)\b',
        ]
        found_delivery = None
        for pat in patterns:
            m = re.search(pat, body, re.I)
            if m:
                found_delivery = m.group(1).strip()
                break
        print(f'   → {found_delivery or "not found"}')

        # Step 5: Raw page title for context
        title = soup.find('title')
        print(f'\n5. Page title: {title.get_text(strip=True) if title else "(none)"}')

        # Step 6: First 500 chars of body text
        print(f'\n6. First 300 chars of body text:')
        print(f'   {body[:300]}')

        print('\n─────────────────────────────────────')
        total_found = len(a_imgs) + len(img_tags) + len(script_imgs)
        print(f'Summary: {total_found} image candidates, delivery: {found_delivery or "not found"}')
        if total_found == 0:
            print('\nNOTE: No images found — the page may load images via JavaScript.')
            print('Check if dom.com.cy uses client-side rendering for the gallery.')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python test_one.py <dom.com.cy listing URL>')
        sys.exit(1)
    asyncio.run(test(sys.argv[1]))
