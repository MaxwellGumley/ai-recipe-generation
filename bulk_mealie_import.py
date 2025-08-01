#!/usr/bin/env python3
"""
bulk_mealie_import.py — Delete recipes by tag, or bulk import recipes with duplicate removal

Features
--------
• Delete all recipes from a Mealie server by a specific tag (`--delete-tagged`)
• Or: Scrape an Apache directory index for *.html recipe files, and for each:
    – Downloads HTML
    – Extracts recipe "name" and tags from JSON-LD
    – Only processes recipes with the specified --tag
    – Searches Mealie for recipes with the same name and deletes any duplicates
    – Imports recipe via /api/recipes/create/url (includeTags=true)

USAGE examples
--------------
# 1) Use environment variable for authentication:
export MEALIE_TOKEN="eyJh..."
python3 bulk_mealie_import.py --index-url https://.../recipes/ --server http://mealie:9925 --tag "My Sisters' Kitchen"

# 2) Pass token explicitly:
python3 bulk_mealie_import.py --index-url https://.../recipes/ --server http://mealie:9925 --token eyJh... --tag "My Sisters' Kitchen"

# 3) Delete all recipes for a tag (no import):
python3 bulk_mealie_import.py --server http://mealie:9925 --tag "My Sisters' Kitchen" --delete-tagged

Required Arguments
------------------
--server      : Mealie base URL (e.g. http://host:9925)
--tag         : Tag/group name used to filter recipes and/or delete

Other Arguments
---------------
--index-url   : Apache directory listing containing recipe .html files (required for import, not for --delete-tagged)
--token       : JWT token for Mealie API (can also be set via $MEALIE_TOKEN or --token-env)
--token-env   : Name of env var for token (default: MEALIE_TOKEN)
--delete-tagged : If set, delete ALL recipes matching the tag and exit (no import)
"""


import argparse, html.parser, json, os, re, sys, urllib.parse, urllib.request
import subprocess
import re

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

def extract_tags(html_text):
    m = re.search(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                  html_text, re.S | re.I)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        keywords = data.get("keywords")
        if isinstance(keywords, str):
            return [s.strip() for s in re.split(r'[;,]', keywords)]
        elif isinstance(keywords, list):
            return keywords
        else:
            return []
    except Exception:
        return []

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

def _canon(text: str) -> str:
    """lower-case and strip all non-alphanumerics for robust comparisons"""
    return re.sub(r"[^a-z0-9]", "", text.lower())

def delete_all_tagged(server: str, token: str, tag: str) -> None:
    """Delete every recipe that carries the specified tag (name or slug)."""
    base_api   = server.rstrip("/") + "/api/recipes"
    page_size  = 100
    page       = 1
    victims    = []
    wanted     = _canon(tag)

    while True:
        url = f"{base_api}?page={page}&perPage={page_size}"
        print(f"[DEBUG] curl -H 'Authorization: Bearer {token}' '{url}'")
        data = api_get(url, token)
        items = data.get("items", [])
        print(f"[DEBUG] Got {len(items)} items from server")

        if not items:
            break

        for item in items:
            tag_objs = item.get("tags", [])
            # pull 'name' and 'slug' from each tag object
            tag_texts = [t.get("name", "") for t in tag_objs] + [t.get("slug", "") for t in tag_objs]
            if any(_canon(t) == wanted for t in tag_texts):
                victims.append(item)

        if len(items) < page_size:
            break
        page += 1

    # --- perform deletions ---
    for item in victims:
        rid   = item["id"]
        name  = item.get("name", "(unnamed)")
        match = next(t for t in item["tags"] if _canon(t.get("name", "")) == wanted or
                                               _canon(t.get("slug", "")) == wanted)
        status = api_delete(f"{base_api}/{rid}", token)
        print(f"🗑  Deleted '{name}' (id {rid}) [tag: {match['name']}] → HTTP {status}")

    print(f"Deleted {len(victims)} recipes with tag '{tag}'.")


def import_recipes(index_url, server, token, tag=None):
    """
    Download each *.html file in `index_url`, optionally filter by `tag`,
    delete any recipe with the same name already on the Mealie server,
    then import the fresh copy.
    """
    try:
        recipe_urls = fetch_listing(index_url)
    except Exception as e:
        sys.exit(f"Unable to fetch index: {e}")

    if not recipe_urls:
        sys.exit("No .html files found.")

    base_api = server.rstrip("/") + "/api/recipes"

    for url in recipe_urls:
        try:
            html = urllib.request.urlopen(url).read().decode("utf-8", "ignore")
            name = extract_name(html)
            tags = [t.strip().lower() for t in extract_tags(html)]
        except Exception as e:
            print(f"⚠️  {url}: cannot read/parse ({e})")
            continue

        if not name:
            print(f"⚠️  {url}: no recipe name found")
            continue

        # If a tag filter is supplied, skip recipes that don’t contain it
        if tag and tag.strip().lower() not in tags:
            print(f"↩︎  Skipping '{name}' – tag '{tag}' not present in {tags}")
            continue

        # ---------- delete duplicates ----------
        try:
            data = api_get(f"{base_api}?search={urllib.parse.quote(name)}", token)
            for item in data.get("items", []):
                if item.get("name", "").lower() == name.lower():
                    rid = item["id"]
                    status = api_delete(f"{base_api}/{rid}", token)
                    print(f"🗑  Deleted duplicate '{name}' (id {rid}) → HTTP {status}")
        except Exception as e:
            print(f"⚠️  delete error for '{name}': {e}")

        # ---------- import fresh copy ----------
        status = curl_import(token, server, url)
        print(f"⬆️  Imported '{name}' → HTTP {status}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-url",
        help="Apache directory index containing *.html recipes (needed for import)")
    ap.add_argument("--server", required=True,
        help="Mealie base URL, e.g. http://host:9925")
    ap.add_argument("--token", help="JWT token for Mealie API (optional)")
    ap.add_argument("--token-env", default="MEALIE_TOKEN",
        help="Env-var fallback if --token not given (default MEALIE_TOKEN)")
    ap.add_argument("--tag",
        help="When importing, only process recipes whose keywords contain this tag")
    ap.add_argument("--delete-tagged", metavar="TAG",
        help="Delete ALL recipes carrying TAG, then exit (no import)")

    args   = ap.parse_args()
    token  = args.token or os.getenv(args.token_env)
    if not token:
        sys.exit("Provide --token or set the MEALIE_TOKEN environment variable.")

    if args.delete_tagged:
        delete_all_tagged(args.server, token, args.delete_tagged)
        return

    if not args.index_url:
        sys.exit("--index-url is required when not using --delete-tagged.")

    # Import (optionally filtered by --tag)
    import_recipes(args.index_url, args.server, token, tag=args.tag)


if __name__ == "__main__":
    main()
