#!/usr/bin/env python3
"""Scan the project's code for URLs and download the referenced assets.

Creates a folder ``backup_YYYY-MM-DD`` (the current date) and downloads every
unique URL found in the scanned source files into it. A ``manifest.json`` maps
each URL to its saved file and the source files that referenced it.

Usage:
    python scripts/backup_assets.py                 # scan whole repo
    python scripts/backup_assets.py TTSLUA TTSJSON  # scan only these dirs
    python scripts/backup_assets.py --hosts steamusercontent-a.akamaihd.net
    python scripts/backup_assets.py --workers 16 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

# Matches http/https URLs, stopping at quotes, whitespace, backslashes and a few
# delimiters that commonly terminate a URL inside Lua/JSON string literals.
URL_RE = re.compile(r"""https?://[^\s"'\\)<>\]}]+""")

# File extensions worth keeping. Empty set => keep everything.
DEFAULT_EXTS = ".png .jpg .jpeg .gif .bmp .webp .tga .obj .mtl .mp3 .wav .ogg .mp4 .pdf".split()

# Text-ish files we scan for URLs.
SCAN_SUFFIXES = (".ttslua", ".lua", ".json", ".txt", ".xml", ".md")

USER_AGENT = "Mozilla/5.0 (asset-backup-script)"


def find_files(roots: list[str]) -> list[str]:
    files: list[str] = []
    for root in roots:
        if os.path.isfile(root):
            files.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # skip VCS / backup dirs
            dirnames[:] = [d for d in dirnames if d != ".git" and not d.startswith("backup_")]
            for name in filenames:
                if name.lower().endswith(SCAN_SUFFIXES):
                    files.append(os.path.join(dirpath, name))
    return files


def extract_urls(files: list[str]) -> dict[str, set[str]]:
    """Return {url: {source files that referenced it}}."""
    urls: dict[str, set[str]] = {}
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"  ! could not read {path}: {exc}", file=sys.stderr)
            continue
        for match in URL_RE.findall(text):
            url = match.rstrip(".,;")  # trailing punctuation is rarely part of the URL
            urls.setdefault(url, set()).add(path)
    return urls


def safe_name(url: str) -> str:
    """Build a stable, filesystem-safe base filename for a URL."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    last = os.path.basename(path) or parsed.netloc
    # Steam UGC urls look like /ugc/<id>/<hash>/ -> use the hash segment.
    if not last or last == parsed.netloc:
        segs = [s for s in path.split("/") if s]
        last = segs[-1] if segs else parsed.netloc
    last = re.sub(r"[^A-Za-z0-9._-]", "_", last)[:80]
    digest = hashlib.sha1(url.encode()).hexdigest()[:10]
    return f"{last}_{digest}" if last else digest


def guess_ext(url: str, content_type: str | None) -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext and len(ext) <= 5:
        return ext
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed
    return ""


def download(url: str, out_dir: str, exts: set[str], timeout: int) -> tuple[str, str, str]:
    """Returns (url, status, detail)."""
    base = safe_name(url)
    # already downloaded? (any file starting with base)
    for existing in os.listdir(out_dir):
        if existing.startswith(base + ".") or existing == base:
            return url, "skip", existing
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type")
            data = resp.read()
    except Exception as exc:  # noqa: BLE001 - report any failure, keep going
        return url, "error", str(exc)

    ext = guess_ext(url, content_type)
    if exts and ext.lower() not in exts:
        return url, "skip-ext", ext or "(none)"

    filename = base + ext
    with open(os.path.join(out_dir, filename), "wb") as fh:
        fh.write(data)
    return url, "ok", filename


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="*", default=["."], help="files/dirs to scan (default: repo root)")
    ap.add_argument("--out", help="output dir (default: backup_<today> in repo root)")
    ap.add_argument("--hosts", nargs="*", help="only download URLs from these hostnames (substring match)")
    ap.add_argument("--all-exts", action="store_true", help="download every URL regardless of extension")
    ap.add_argument("--workers", type=int, default=8, help="parallel downloads (default: 8)")
    ap.add_argument("--timeout", type=int, default=30, help="per-request timeout seconds (default: 30)")
    ap.add_argument("--dry-run", action="store_true", help="list URLs but do not download")
    args = ap.parse_args()

    out_dir = args.out or f"backup_{dt.date.today().isoformat()}"
    exts = set() if args.all_exts else {e.lower() for e in DEFAULT_EXTS}

    print(f"Scanning: {', '.join(args.roots)}")
    files = find_files(args.roots)
    print(f"  {len(files)} source files")

    url_map = extract_urls(files)
    if args.hosts:
        url_map = {u: s for u, s in url_map.items() if any(h in urlparse(u).netloc for h in args.hosts)}
    urls = sorted(url_map)
    print(f"  {len(urls)} unique URLs found")

    if args.dry_run:
        for u in urls:
            print(u)
        return 0

    os.makedirs(out_dir, exist_ok=True)
    print(f"Downloading into: {out_dir}/  ({args.workers} workers)")

    manifest: dict[str, dict] = {}
    counts = {"ok": 0, "skip": 0, "skip-ext": 0, "error": 0}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download, u, out_dir, exts, args.timeout): u for u in urls}
        for fut in as_completed(futures):
            url, status, detail = fut.result()
            counts[status] = counts.get(status, 0) + 1
            done += 1
            manifest[url] = {
                "status": status,
                "file": detail if status in ("ok", "skip") else None,
                "detail": detail,
                "sources": sorted(url_map[url]),
            }
            if status in ("ok", "error"):
                print(f"  [{done}/{len(urls)}] {status:5} {detail[:60]:60} {url[:70]}")

    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print("\nSummary:")
    for k, v in counts.items():
        print(f"  {k:9}: {v}")
    print(f"  manifest : {os.path.join(out_dir, 'manifest.json')}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
