# Sawyer Hill EcoVillage — static site

This is the old Drupal site (was at sawyerhill.org) rebuilt as a static
[Hugo](https://gohugo.io) site. It looks the same as the original on purpose.
The theme is a copy of the old "Mayo" theme's HTML and CSS, not a fresh design.

## What's here

- `content/` — one Markdown file per page. Page bodies are raw HTML copied from
  the old site, so tables and images keep their original look.
- `themes/mayo/` — the theme. `layouts/_default/baseof.html` is the page shell
  (header, menu, footer). The CSS/JS is the old Drupal site's, served as-is.
- `static/files/` — images and the old CSS/JS bundles. Served at `/files/...`.
- `migrate.py` — the script that copied the old site's content. See below.
- `build.sh` — builds the site and the search index into `public/`.

## Build and preview

You need Hugo and Node.js (Node is only used to run Pagefind for search).

```sh
./build.sh                 # builds into ./public
python3 -m http.server --directory public 8000
```

Then open http://localhost:8000.

For local editing, `hugo server` is fine, but the search index is only built by
`./build.sh`.

## Search

Search uses [Pagefind](https://pagefind.app). It indexes the built HTML at build
time and runs entirely in the browser. The search box in the header submits to
`/search/`, which loads the index. No server and no third-party service needed.

## Contact form

The contact form posts to [Formspree](https://formspree.io), a free service that
emails form submissions to an address you choose. To make it live:

1. Sign up at formspree.io with the site owner's email and create a form.
2. Copy the form ID (the part after `https://formspree.io/f/`).
3. Paste it into `hugo.toml` as the value of `formspreeFormId`.
4. Rebuild and redeploy.

Spam is handled by a hidden honeypot field plus Formspree's own filtering. The
old reCAPTCHA is gone; it is not needed.

## Re-running the migration

You should not normally need this. It exists in case content is re-pulled from
the old Drupal site. The old site must be running locally.

```sh
python3 migrate.py --copy-assets   # copy images from the old codebase on disk
python3 migrate.py                 # crawl pages -> content/*.md
```

Images are copied from `~/sawyerhill/sites/sawyerhill.org/files`. The aggregated
CSS/JS was downloaded from the running site because Drupal builds those bundles.
A few images that were already broken (404) on the old site are still broken
here on purpose; see below.

## Known broken images

These images returned 404 on the old site too, so they were left as-is. If you
want clean pages, delete the matching `<img>` tags from `content/`:

- `/files/CommunityRendering-small.jpg` (home page)
- `/files/fullsite.jpg` (/cohousing)
- `/files/cch_1stfloor.gif` and `/files/cch_basement.gif` (/camelot-commonhouse)
- `mc-ch_basement.gif` and `mc-ch_first_floor700.gif` (/mosaic-commonhouse,
  hot-linked from the old live site)

## Deploying to GitHub Pages

`.github/workflows/deploy.yml` builds the site and search index and publishes
`public/` to GitHub Pages on every push to `main`. To go live:

1. Create a GitHub repo and push this folder to it.
2. In the repo settings, set Pages to deploy from "GitHub Actions".
3. Set `baseURL` in `hugo.toml` to the real Pages URL
   (for example `https://yourname.github.io/sawyerhill/`).
