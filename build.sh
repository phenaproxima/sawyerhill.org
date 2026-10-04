#!/bin/sh
# Build the static site and its search index into public/.
# Usage: ./build.sh
set -e
cd "$(dirname "$0")"
hugo --minify --destination public
npx --yes pagefind --site public --output-subdir _pagefind
echo "Built to ./public"
