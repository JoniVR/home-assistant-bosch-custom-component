#!/bin/bash
# Full OAuth flow: captures callback, exchanges code, tests API.
set -e
cd "$(dirname "$0")"
uv run --with playwright --with playwright-stealth --with aiohttp python pointt_oauth_playwright.py
