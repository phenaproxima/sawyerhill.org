#!/usr/bin/env python3
"""Migrate the local Drupal site (http://sawyerhill.ddev.site) to Hugo content.

What this does:
  - Copies binary content files (images, etc.) from the live Drupal codebase on
    disk into Hugo's static/ directory. (--copy-assets)
  - Crawls the 13 real pages over HTTP and writes content/*.md. Each page's body
    is kept as raw HTML so it looks the same as the old site. Internal links and
    asset URLs are rewritten from Drupal paths to the new static paths.

Run it from the Hugo project root:
  python3 migrate.py --copy-assets   # copy images from disk
  python3 migrate.py                 # crawl pages -> content/*.md
"""
import argparse
import html
import os
import re
import shutil
import urllib.request
from html.parser import HTMLParser

BASE = "http://sawyerhill.ddev.site"
# Where the Drupal files live on disk (read-only source for images).
FILES_DISK = os.path.expanduser("~/sawyerhill/sites/sawyerhill.org/files")
# Hugo project dirs.
STATIC_FILES = "static/files"
CONTENT_DIR = "content"

# The 13 real pages to migrate. The /book/export/html/* print duplicates and the
# /node/N aliases are deliberately skipped.
PAGES = [
    ("/home", "index", "Welcome"),          # home page -> content/_index.md
    ("/ecovillages", "ecovillages", None),
    ("/cohousing", "cohousing", None),
    ("/photos", "photos", None),
    ("/calendar", "calendar", None),
    ("/directions", "directions", None),
    ("/forsale", "forsale", None),
    ("/31", "31", None),
    ("/camelot-commonhouse", "camelot-commonhouse", None),
    ("/mosaic-commonhouse", "mosaic-commonhouse", None),
    ("/mosaic/35", "mosaic/35", None),
    # /contact is hand-written as a Formspree form, not crawled.
]

# External image hosts we leave alone (Flickr, weather sticker, the other
# cohousing site's photo album). These are not ours to copy.
KEEP_EXTERNAL = (
    "farm3.static", "farm4.static", "farm5.static",
    "c3.staticflickr.com", "banners.wunderground.com",
    "photos.mosaic-commons.org",
)

# sawyerhill.org hot-links that already 404 on the live site. Left broken on
# purpose: they were broken before the migration too.
BROKEN_HOTLINKS = (
    "http://www.sawyerhill.org/files/mc-ch_basement.gif",
    "http://www.sawyerhill.org/files/mc-ch_first_floor700.gif",
)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "hugo-migrate"})
    with urllib.request.urlopen(req) as r:
        return r.read()


def local_files_path(url_path):
    """Map a /sites/sawyerhill.org/files/... or /files/... URL to a source path
    on disk. Returns None if the file is not under the files dir."""
    m = re.match(r"^/sites/sawyerhill\.org/files/(.+)$", url_path)
    if not m:
        m = re.match(r"^/files/(.+)$", url_path)
    if not m:
        return None
    # URL-decode (the map image has a %20 space in its real filename).
    from urllib.parse import unquote
    return os.path.join(FILES_DISK, unquote(m.group(1)))


def to_static_rel(url_path):
    """Map a Drupal files URL to its new /files/... static path."""
    m = re.match(r"^/sites/sawyerhill\.org/files/(.+)$", url_path)
    if m:
        return "/files/" + m.group(1)
    return url_path  # already /files/...


# --- asset copying -----------------------------------------------------------

def collect_asset_urls():
    """Fetch every page and pull out image/file URLs."""
    pages = ["/", "/ecovillages", "/cohousing", "/photos", "/calendar",
             "/directions", "/forsale", "/contact", "/31",
             "/camelot-commonhouse", "/mosaic-commonhouse", "/mosaic/35"]
    urls = set()
    for p in pages:
        raw = fetch(BASE + p).decode("utf-8", "replace")
        for m in re.finditer(r'(?:src|href)="([^"]+)"', raw):
            urls.add(html.unescape(m.group(1)))
    return urls


def copy_assets():
    os.makedirs(STATIC_FILES, exist_ok=True)
    copied, missing, skipped = [], [], []
    for u in sorted(collect_asset_urls()):
        if not re.search(r"\.(png|jpe?g|gif|svg|webp|ico)(\?|$)", u, re.I):
            continue
        # Truly external: leave the URL as-is, don't copy.
        if any(h in u for h in KEEP_EXTERNAL) or u in BROKEN_HOTLINKS:
            skipped.append(u)
            continue

        if u.startswith("http") and "sawyerhill.org" in u:
            # Working hot-link to the live site's files dir. Point at the local
            # on-disk copy instead of downloading.
            m = re.search(r"/sites/sawyerhill\.org/files/(.+)$", u)
            rel = m.group(1) if m else None
            src = os.path.join(FILES_DISK, rel) if rel else None
            dest_rel = "/files/" + rel if rel else None
        elif u.startswith("/"):
            src = local_files_path(u)
            dest_rel = to_static_rel(u)
        else:
            skipped.append(u)
            continue

        if not src or not os.path.exists(src):
            missing.append(u)
            continue
        # Store the file under its URL-decoded name. A browser requests
        # "/files/.../numbered%20map...png" decoded ("numbered map ...png"), so
        # the on-disk name must be the decoded one or it 404s.
        from urllib.parse import unquote
        dest = "static" + unquote(dest_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
        copied.append((u, dest_rel))

    print(f"copied {len(copied)} files")
    for u, d in copied:
        print(f"  {u}  ->  {d}")
    if missing:
        print(f"\nMISSING on disk ({len(missing)}):")
        for u in missing:
            print(f"  {u}")
    print(f"\nleft as external ({len(skipped)}):")
    for u in skipped:
        print(f"  {u}")


# --- page crawling -----------------------------------------------------------

class BodyExtractor(HTMLParser):
    """Pull the page <title> and the main content HTML out of a Drupal page.

    The content lives in <div id="block-mayo-content" ...><div class="content">.
    That works for regular article bodies and for the contact form, which is not
    wrapped in a field--name-body div. We capture the inner HTML of the .content
    div. This deliberately skips the mailman subscribe block, which lives in the
    separate bottom-column region.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.title = ""
        self._in_title = False
        self.body = None
        self._capture = None      # list of html chunks while capturing
        self._depth = 0           # div nesting depth while capturing
        self._await_content = False  # saw block-mayo-content, want next .content

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        if self.body is None and self._capture is None and tag == "div":
            cls = a.get("class", "")
            if a.get("id") == "block-mayo-content":
                self._await_content = True
            elif self._await_content and "content" in cls.split():
                self._capture = []
                self._depth = 1
                self._await_content = False
                return
        if self._capture is not None:
            if tag == "div":
                self._depth += 1
            self._capture.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if self._capture is not None:
            self._capture.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self._capture is None:
            return
        if tag == "div":
            self._depth -= 1
            if self._depth == 0:
                self.body = "".join(self._capture)
                self._capture = None
                return
        self._capture.append(f"</{tag}>")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._capture is not None:
            self._capture.append(data)

    def handle_entityref(self, name):
        if self._capture is not None:
            self._capture.append(f"&{name};")

    def handle_charref(self, name):
        if self._capture is not None:
            self._capture.append(f"&#{name};")


def clean_title(t):
    # "Welcome | Sawyer Hill EcoVillage" -> "Welcome"
    return t.split("|")[0].strip()


def rewrite_urls(body):
    """Rewrite Drupal URLs in body HTML to the new static paths."""
    # Live-site hot-links to files that exist locally -> local path.
    body = re.sub(
        r"https://www\.sawyerhill\.org/sites/sawyerhill\.org/files/([^\"'\s]+)",
        r"/files/\1", body)
    # Local files URLs -> /files/...
    body = body.replace("/sites/sawyerhill.org/files/", "/files/")
    return body


def clean_body(body):
    """Strip the redundant article wrapper and Drupal-only cruft from the
    captured .content HTML, leaving just the page body markup."""
    # Unwrap the <article>...<div class="node__content">... boilerplate so the
    # template owns the page structure.
    body = re.sub(r"(?s)^\s*<article[^>]*>.*?<div class=\"node__content[^\"]*\"[^>]*>",
                  "", body, count=1)
    body = re.sub(r"(?s)<div class=\"node__links\".*</article>\s*$", "", body, count=1)
    # Drop the body-field wrapper div too; the template re-adds it.
    body = re.sub(r'(?s)^\s*<div class="field field--name-body[^"]*"[^>]*>', "",
                  body, count=1)
    # Remove any leftover "Printer-friendly version" links to the skipped
    # /book/export pages.
    body = re.sub(r'(?s)<div class="node__links".*?</div>', "", body)
    body = re.sub(r'(?s)<a href="/book/export/html/\d+"[^>]*>.*?</a>', "", body)
    return body.strip()


def slug_to_content(slug):
    if slug == "index":
        return os.path.join(CONTENT_DIR, "_index.md")
    # Keep nested Drupal paths (e.g. /mosaic/35) as nested Hugo pages.
    if "/" in slug:
        return os.path.join(CONTENT_DIR, slug + ".md")
    return os.path.join(CONTENT_DIR, slug + ".md")


def crawl():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    for path, slug, title_override in PAGES:
        raw = fetch(BASE + path).decode("utf-8", "replace")
        ex = BodyExtractor()
        ex.feed(raw)
        title = title_override or clean_title(ex.title)
        body = clean_body(rewrite_urls((ex.body or "").strip()))

        fm = [
            "+++",
            f'title = "{title}"',
        ]
        if slug == "index":
            fm.append("type = 'page'")
        fm.append("+++")
        out = "\n".join(fm) + "\n\n" + body + "\n"
        dest = slug_to_content(slug)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"{path:22} -> {dest}  ({title})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-assets", action="store_true",
                    help="copy images from the Drupal files dir on disk")
    args = ap.parse_args()
    if args.copy_assets:
        copy_assets()
    else:
        crawl()
