#!/usr/bin/env python3
"""
bulk_mealie_import.py  —  delete-then-import with optional --token

• Scrapes an Apache directory index for *.html recipe files
• For each file:
    – Downloads HTML
    – Extracts recipe "name" from JSON-LD
    – Searches Mealie for same name → DELETE any matches
    – Imports via /api/recipes/create/url (includeTags=true)

USAGE examples
--------------
# 1) use env var
export MEALIE_TOKEN="eyJh..."
python3 bulk_mealie_import.py --index-url https://.../recipes/ --server http://mealie:9925

# 2) pass token explicitly
python3 bulk_mealie_import.py --index-url https://.../recipes/ --server http://mealie:9925 \
                              --token eyJh...

"""

import argparse, html.parser, json, os, re, sys, urllib.parse, urllib.request
import subprocess

# ---------- helpers ----------
class IndexParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.lower().endswith(".html"):
                self.links.append(href)

def fetch_listing(index_url):
    with urllib.request.urlopen(index_url) as r:
        html = r.read().decode("utf-8", "ignore")
    p = IndexParser(); p.feed(html)
    base = index_url.rstrip("/") + "/"
    return sorted(urllib.parse.urljoin(base, link) for link in p.links)

def extract_name(html_text):
    m = re.search(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                  html_text, re.S | re.I)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        return data.get("name")
    except json.JSONDecodeError:
        return None

def api_get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)

def api_delete(url, token):
    req = urllib.request.Request(url,
                                 headers={"Authorization": f"Bearer {token}"},
                                 method="DELETE")
    with urllib.request.urlopen(req) as r:
        return r.status

def curl_import(token, server, url):
    endpoint = server.rstrip("/") + "/api/recipes/create/url"
    payload  = f'{{"url":"{url}","includeTags":true}}'
    cmd = [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "-X", "POST", endpoint,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-d", payload
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-url", required=True,
                    help="Directory listing URL with *.html recipes")
    ap.add_argument("--server", required=True,
                    help="Mealie base URL, e.g. http://host:9925")
    ap.add_argument("--token", help="JWT token for Mealie API (optional)")
    ap.add_argument("--token-env", default="MEALIE_TOKEN",
                    help="Env var fallback if --token not given (default MEALIE_TOKEN)")
    args = ap.parse_args()

    token = args.token or os.getenv(args.token_env)
    if not token:
        sys.exit("Provide --token or set the MEALIE_TOKEN environment variable.")

    try:
        recipe_urls = fetch_listing(args.index_url)
    except Exception as e:
        sys.exit(f"Unable to fetch index: {e}")

    if not recipe_urls:
        sys.exit("No .html files found.")

    base_api = args.server.rstrip("/") + "/api/recipes"

    for url in recipe_urls:
        try:
            html = urllib.request.urlopen(url).read().decode("utf-8", "ignore")
            name = extract_name(html)
        except Exception as e:
            print(f"⚠️  {url}: cannot read/parse ({e})"); continue
        if not name:
            print(f"⚠️  {url}: no recipe name found"); continue

        # delete duplicates
        try:
            data = api_get(f"{base_api}?search={urllib.parse.quote(name)}", token)
            for item in data.get("items", []):
                if item.get("name", "").lower() == name.lower():
                    rid = item["id"]
                    status = api_delete(f"{base_api}/{rid}", token)
                    print(f"🗑  Deleted '{name}' (id {rid}) → {status}")
        except Exception as e:
            print(f"⚠️  delete error for '{name}': {e}")

        # import fresh
        status = curl_import(token, args.server, url)
        print(f"⬆️  Import '{name}' → HTTP {status}")

if __name__ == "__main__":
    main()
