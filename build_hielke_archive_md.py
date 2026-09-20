#!/usr/bin/env python3
"""Baut das Hielke-Maps-Archiv: ZIP-Snapshots, Versionstabellen, Thumbnails.

Die ZIPs liegen lokal unter `archive_zips/` (nicht in Git) und werden als
Release-Assets zu GitHub hochgeladen -- ein Release pro Map. Die Markdown-
Tabellen verlinken auf diese Assets sowie auf archive.org.
"""
import io
import argparse
import configparser
import json
import hashlib
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import urllib.error
import zipfile
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from html import escape

from nbt2yaml.parse import parse_nbt


CDX_API = "https://web.archive.org/cdx/search/cdx"
OUT_OFFICIAL = "hielke-maps-archive-hielke.md"
OUT_COMMUNITY = "hielke-maps-archive-community.md"
ARCHIVE_DIR = "archive_zips"
THUMB_DIR = "thumbnails"
# ZIPs, deren Zeitstempel von der lokalen Uhr stammt statt von einem Wayback-
# Snapshot (z.B. weil web.archive.org waehrend des Laufs nicht erreichbar war).
NO_WAYBACK_INDEX = os.path.join(ARCHIVE_DIR, "_no_wayback.json")
WAYBACK_INDEX = os.path.join(ARCHIVE_DIR, "_wayback_verified.json")
WAYBACK_REPORT = "wayback-status.json"
GH_REPO = os.environ.get("ARCHIVE_REPO", "GammelSami/hielkemaps-archive")
UA = "Mozilla/5.0 (X11; Linux x86_64) HielkeArchiveBuilder/1.0"
REQUEST_DELAY_SECONDS = 0.25
MAX_RETRIES = 3


def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            time.sleep(REQUEST_DELAY_SECONDS)
            return body
        except Exception as exc:
            last_exc = exc
            # simple backoff for transient timeouts/limits
            time.sleep(min(2.0, 0.5 * attempt))
    raise last_exc


def fetch_text(url: str, timeout: int = 60) -> str:
    return fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")


def normalize_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%")
    query = urllib.parse.quote_plus(parts.query, safe="=&%")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


class PageAttributes(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def extract_download_urls(html: str) -> list[str]:
    urls = []
    for _, attrs in PageAttributes(html).elements:
        for key in ("href", "data-url"):
            raw = attrs.get(key) or ""
            abs_url = urllib.parse.urljoin("https://hielkemaps.com", raw)
            parsed = urllib.parse.urlsplit(abs_url)
            if parsed.netloc == "hielkemaps.com" and parsed.path.startswith("/downloads/") and parsed.path.lower().endswith(".zip"):
                urls.append(normalize_url(abs_url))
    return list(OrderedDict.fromkeys(urls))


def extract_map_slugs(html: str) -> list[str]:
    slugs = []
    for _, attrs in PageAttributes(html).elements:
        candidates = [attrs.get("href") or ""]
        candidates.extend(re.findall(r"(?:window\.)?location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]", attrs.get("onclick") or ""))
        for raw in candidates:
            parsed = urllib.parse.urlsplit(urllib.parse.urljoin("https://hielkemaps.com", raw))
            match = re.fullmatch(r"/maps/([^/]+)/?", parsed.path)
            if parsed.netloc == "hielkemaps.com" and match:
                slugs.append(match.group(1))
    return list(OrderedDict.fromkeys(slugs))


def extract_sitemap_slugs(xml: str) -> list[str]:
    return list(OrderedDict.fromkeys(
        match.group(1)
        for element in ET.fromstring(xml).iter()
        if element.tag.rsplit("}", 1)[-1] == "loc"
        for match in [re.fullmatch(r"/maps/([^/]+)/?", urllib.parse.urlsplit(element.text or "").path)]
        if match
    ))


def slug_to_official_download(slug: str) -> str:
    # /maps/parkour-volcano -> /downloads/Parkour%20Volcano.zip
    title = " ".join(part.capitalize() for part in slug.split("-"))
    return normalize_url(f"https://hielkemaps.com/downloads/{title}.zip")


def is_community(url: str) -> bool:
    return "/downloads/community/" in url


def http_status(url: str, timeout: int = 30) -> int | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode()
    except Exception:
        return None


def cdx_rows(original_url: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "url": original_url,
            "output": "json",
            "fl": "timestamp,original,statuscode,digest",
            "filter": "statuscode:200",
            "collapse": "digest",
        }
    )
    raw = fetch_text(f"{CDX_API}?{query}")
    data = json.loads(raw)
    if not data or len(data) == 1:
        return []
    return [
        {
            "timestamp": row[0],
            "original": row[1],
            "statuscode": row[2],
            "digest": row[3] if len(row) > 3 else "",
        }
        for row in data[1:]
    ]


def find_named(compound_data, name: str):
    for item in compound_data:
        if item[1] == name:
            return item
    return None


def read_mc_version_from_level_dat(level_dat: bytes) -> str | None:
    for gz in (True, False):
        try:
            root = parse_nbt(io.BytesIO(level_dat), gzipped=gz)
        except Exception:
            continue
        try:
            data = find_named(root[2], "Data")
            if not data:
                continue
            version = find_named(data[2], "Version")
            if version:
                name = find_named(version[2], "Name")
                if name and isinstance(name[2], str):
                    return name[2]
            data_version = find_named(data[2], "DataVersion")
            if data_version is not None:
                return f"DataVersion {data_version[2]}"
        except Exception:
            continue
    return None


def read_version_from_zip(zip_bytes: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            candidates = [n for n in names if n.lower().endswith("/level.dat")]
            if "level.dat" in names:
                candidates.insert(0, "level.dat")
            for candidate in candidates:
                try:
                    data = zf.read(candidate)
                except Exception:
                    continue
                version = read_mc_version_from_level_dat(data)
                if version:
                    return version
            if any(n == "pack.mcmeta" or n.endswith("/pack.mcmeta") for n in names):
                return "Resource pack"
    except Exception:
        return None
    return None


def wayback_download_url(timestamp: str, original: str) -> str:
    return f"https://web.archive.org/web/{timestamp}if_/{original}"


def parse_wayback_timestamp(url: str) -> str | None:
    m = re.search(r"/web/(\d{14})", url)
    return m.group(1) if m else None


def wayback_headers() -> dict:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    config = configparser.ConfigParser(interpolation=None)
    explicit = os.environ.get("IA_CONFIG")
    paths = [explicit] if explicit else [
        os.path.expanduser("~/.config/ia.ini"),
        os.path.expanduser("~/.config/internetarchive/ia.ini"),
    ]
    config.read([p for p in paths if p])
    access = config.get("s3", "access", fallback="")
    secret = config.get("s3", "secret", fallback="")
    if access and secret:
        headers["Authorization"] = f"LOW {access}:{secret}"
    return headers


def save_current_to_wayback(original_url: str, timeout: int = 30, status: dict | None = None, checkpoint=None) -> str:
    """Submit a real Save Page Now job and wait for a completed capture."""
    status = status if status is not None else {}
    headers = wayback_headers()

    def request(url, data=None):
        for attempt in range(3):
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                retry_after = exc.headers.get("Retry-After", "60")
                try:
                    delay = max(60, int(retry_after))
                except ValueError:
                    delay = max(60, int((parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()))
            except urllib.error.URLError:
                if attempt == 2:
                    raise
                delay = 30 * (attempt + 1)
            print(f"  Wayback temporarily unavailable; retry in {delay}s", flush=True)
            while delay > 0:
                time.sleep(min(delay, 60))
                delay -= 60

    status.pop("error", None)
    if status.get("job_id"):
        result = {"job_id": status["job_id"], "status": "pending"}
    else:
        status.update(status="submitting", requested_at=datetime.now(timezone.utc).isoformat())
        result = request("https://web.archive.org/save/", urllib.parse.urlencode({"url": original_url, "capture_all": "1"}).encode())
    job_id = result.get("job_id")
    if job_id:
        status.update(status="submitted", job_id=job_id)
        if checkpoint:
            checkpoint()
        print(f"  Wayback job: {job_id}", flush=True)
    deadline = time.monotonic() + 300
    while result.get("status") != "success":
        if result.get("status") == "error" or not job_id:
            message = result.get("message") or result.get("status_ext") or "Save Page Now returned no completed capture or job ID"
            if "daily limit" in message.lower():
                today = datetime.now(timezone.utc).strftime("%Y%m%d")
                query = urllib.parse.urlencode({"url": original_url, "output": "json", "fl": "timestamp,original", "filter": "statuscode:200", "from": today})
                rows = json.loads(fetch_text(f"{CDX_API}?{query}"))[1:]
                captures = [row for row in rows if re.fullmatch(r"\d{14}", row[0]) and row[0].startswith(today)]
                if captures:
                    timestamp, original = max(captures)
                    capture = wayback_download_url(timestamp, original)
                    status.update(status="captured", capture_url=capture, note="Daily save limit reached; verifying today's existing capture")
                    return capture
            status["job_status"] = "error"
            raise RuntimeError(message)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Wayback job still pending: {job_id}")
        time.sleep(10)
        result = request(f"https://web.archive.org/save/status/{urllib.parse.quote(job_id, safe='')}?_t={int(time.time())}")
    timestamp = result.get("timestamp", "")
    if not re.fullmatch(r"\d{14}", timestamp) or int(result.get("http_status", 200)) != 200:
        raise RuntimeError("Wayback capture did not confirm a successful ZIP response")
    capture = wayback_download_url(timestamp, original_url)
    status.update(status="captured", job_status="success", capture_url=capture)
    return capture


def refresh_live_snapshot(url: str, payload: bytes, no_wayback: set, verified: dict, status: dict, skip_wayback: bool = False) -> dict:
    name = map_name(url)
    version = read_version_from_zip(payload) or "Unknown"
    sha1 = hashlib.sha1(payload).hexdigest()
    duplicate = find_identical_snapshot(name, sha1)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    path = write_zip_snapshot(name, timestamp, version, payload)
    timestamp = os.path.basename(path).split("__", 1)[0]
    if not duplicate:
        no_wayback.add(path)
    print(f"  {'unchanged' if duplicate else 'new snapshot'}: {path} ({version})", flush=True)
    archive_url = verified.get(path, {}).get("url")
    if archive_url is None and path not in no_wayback:
        archive_url = wayback_download_url(timestamp, url)
    status.update(local_zip=path, sha256=hashlib.sha256(payload).hexdigest())
    if skip_wayback:
        status["status"] = "skipped"
    else:
        try:
            capture = save_current_to_wayback(url, status=status)
            captured_payload = fetch_bytes(capture, timeout=180)
            if hashlib.sha256(captured_payload).hexdigest() != status["sha256"]:
                raise ValueError("Wayback ZIP differs from the live download; capture not linked")
            verified[path] = {"url": capture, "sha1": sha1, "sha256": status["sha256"]}
            no_wayback.discard(path)
            archive_url = capture
            status["status"] = "verified"
        except Exception as exc:
            status["status"] = "failed"
            status["error"] = str(exc)
            print(f"  Wayback FAILED: {exc}", flush=True)
    return {"timestamp": timestamp, "archive": archive_url, "local_zip": path,
            "asset": os.path.basename(path), "sha1": sha1, "version": version, "live_url": url}


def map_name(download_url: str) -> str:
    filename = urllib.parse.urlsplit(download_url).path.rsplit("/", 1)[-1]
    name = urllib.parse.unquote(filename)
    if name.lower().endswith(".zip"):
        name = name[:-4]
    return name


def slugify_filename(value: str) -> str:
    value = re.sub(r"[^\w\s.-]", "_", value.strip(), flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value[:180].strip("._") or "unknown"


def release_tag(map_display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", map_display_name.lower()).strip("-")
    return f"map-{slug}"


def asset_download_url(map_display_name: str, asset_name: str) -> str:
    return (
        f"https://github.com/{GH_REPO}/releases/download/"
        f"{release_tag(map_display_name)}/{urllib.parse.quote(asset_name)}"
    )


def map_folder_path(map_display_name: str) -> str:
    return os.path.join(ARCHIVE_DIR, slugify_filename(map_display_name))


def load_no_wayback_index() -> set[str]:
    try:
        with open(NO_WAYBACK_INDEX, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def save_no_wayback_index(paths: set[str]):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(NO_WAYBACK_INDEX, "w", encoding="utf-8") as f:
        json.dump(sorted(paths), f, indent=2)
        f.write("\n")


def find_identical_snapshot(map_display_name: str, payload_sha1: str) -> str | None:
    folder = map_folder_path(map_display_name)
    if not os.path.isdir(folder):
        return None
    for existing_name in sorted(os.listdir(folder)):
        if not existing_name.endswith(".zip"):
            continue
        existing_path = os.path.join(folder, existing_name)
        try:
            with open(existing_path, "rb") as f:
                if hashlib.sha1(f.read()).hexdigest() == payload_sha1:
                    return existing_path
        except Exception:
            continue
    return None


def write_zip_snapshot(map_display_name: str, timestamp: str, version: str, payload: bytes) -> str:
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise ValueError("Download ist keine ZIP-Datei")
    folder = map_folder_path(map_display_name)
    os.makedirs(folder, exist_ok=True)

    # De-duplicate identical payloads per map folder.
    existing = find_identical_snapshot(map_display_name, hashlib.sha1(payload).hexdigest())
    if existing:
        return existing

    rel_path = os.path.join(folder, f"{timestamp}__{slugify_filename(version)}.zip")
    with open(rel_path, "wb") as f:
        f.write(payload)
    return rel_path


def load_existing_entries(map_display_name: str, original_url: str, no_wayback: set[str], verified: dict | None = None) -> dict[str, dict]:
    folder = map_folder_path(map_display_name)
    out = {}
    if not os.path.isdir(folder):
        return out

    for name in os.listdir(folder):
        m = re.match(r"^(\d{14})__.*\.zip$", name)
        if not m:
            continue
        ts = m.group(1)
        rel_path = os.path.join(folder, name)
        try:
            with open(rel_path, "rb") as f:
                payload = f.read()
            version = read_version_from_zip(payload) or "Unknown"
            sha1 = hashlib.sha1(payload).hexdigest()
        except Exception:
            version, sha1 = "Unknown", ""
        out[ts] = {
            "timestamp": ts,
            "archive": (verified or {}).get(rel_path, {}).get("url") or (None if rel_path in no_wayback else wayback_download_url(ts, original_url)),
            "local_zip": rel_path,
            "asset": name,
            "sha1": sha1,
            "version": version,
            "live_url": original_url,
        }
    return out


def upsert_version_entry(per_map: dict, version: str, entry: dict):
    existing = per_map.get(version)
    if not existing:
        per_map[version] = entry
        return
    # Keep newest data per version.
    if entry["timestamp"] > existing["timestamp"]:
        per_map[version] = entry
        return
    # If timestamps equal, prefer entry that has a local file and archive link.
    if entry["timestamp"] == existing["timestamp"]:
        if not existing.get("local_zip") and entry.get("local_zip"):
            per_map[version] = entry


def gh(*args, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=check, timeout=1800
    )


def release_assets(tag: str) -> set[str] | None:
    """Asset-Namen eines Releases, oder None wenn es das Release nicht gibt."""
    proc = gh("release", "view", tag, "--repo", GH_REPO, "--json", "assets", check=False)
    if proc.returncode != 0:
        if "release not found" in proc.stderr.lower():
            return None
        raise RuntimeError(proc.stderr.strip() or "Release-Abfrage fehlgeschlagen")
    return {a["name"] for a in json.loads(proc.stdout)["assets"]}


def sync_release(map_display_name: str, live_url: str, versions: dict) -> set[str]:
    """Legt das Release der Map an und laedt fehlende ZIPs hoch."""
    tag = release_tag(map_display_name)
    folder = map_folder_path(map_display_name)
    wanted = {
        name: os.path.join(folder, name)
        for name in sorted(os.listdir(folder)) if name.endswith(".zip")
    } if os.path.isdir(folder) else {}
    if not wanted:
        return set()

    notes = (
        f"ZIP-Snapshots von **{map_display_name}**.\n\n"
        f"Quelle: {live_url}\n\n"
        "Dateiname: `<Snapshot-Zeit UTC>__<Minecraft-Version>.zip`\n\n"
        "Uebersicht aller Versionen: siehe `hielke-maps-archive-*.md` im Repo."
    )

    have = release_assets(tag)
    if have is None:
        gh(
            "release", "create", tag,
            "--repo", GH_REPO,
            "--title", map_display_name,
            "--notes", notes,
            "--target", "main",
        )
        have = set()
    else:
        gh("release", "edit", tag, "--repo", GH_REPO, "--notes", notes)

    uploaded = set()
    for asset, path in sorted(wanted.items()):
        if asset in have:
            continue
        print(f"  upload: {tag}/{asset}")
        gh("release", "upload", tag, path, "--repo", GH_REPO)
        uploaded.add(asset)
    return uploaded


def write_markdown(out_file: str, title: str, urls: list[str], results: dict, errors: dict, thumbs: dict):
    with io.StringIO() as f:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        f.write(f"# {title}\n\n")
        f.write(f"_Generated: {generated}_\n\n")
        f.write(
            "Quelle: `https://hielkemaps.com/maps/` und "
            "`https://hielkemaps.com/community-maps/`.\n\n"
        )
        f.write(
            "Versionen werden aus `level.dat` (NBT, via `nbt2yaml`) gelesen; bei "
            "unlesbaren Dateien steht `Unknown`. Die Spalte **Download** zeigt auf "
            "das ZIP im passenden GitHub-Release, **Archive.org** auf den Wayback-"
            "Snapshot (`-` = kein Wayback-Eintrag vorhanden).\n\n"
        )

        for url in sorted(urls, key=map_name):
            name = map_name(url)
            f.write(f"## [{name}]({url})\n\n")
            thumb = thumbs.get(name)
            if thumb:
                f.write(f'<img src="{urllib.parse.quote(thumb, safe="/")}" alt="{escape(name, quote=True)}" width="180">\n')
            versions = results.get(url, {})
            if not versions:
                f.write("- Keine Snapshots gefunden.\n\n")
                continue
            f.write("\n| Minecraft Java | Snapshot (UTC) | Download | Archive.org | SHA1 |\n")
            f.write("|---|---|---|---|---|\n")
            for version, data in sorted(
                versions.items(), key=lambda x: x[1]["timestamp"], reverse=True
            ):
                ts = datetime.strptime(data["timestamp"], "%Y%m%d%H%M%S").strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                asset = data.get("asset")
                dl = f"[ZIP]({asset_download_url(name, asset)})" if asset else "-"
                archive_cell = f"[Link]({data['archive']})" if data.get("archive") else "-"
                sha1 = data.get("sha1") or ""
                f.write(f"| {version} | {ts} | {dl} | {archive_cell} | `{sha1[:12] or '-'}` |\n")
            f.write("\n")

        relevant_errors = {u: e for u, e in errors.items() if u in set(urls) and e}
        if relevant_errors:
            f.write("## Fehler/Unklare Faelle\n\n")
            for url, entries in sorted(relevant_errors.items(), key=lambda x: map_name(x[0])):
                f.write(f"- {map_name(url)}\n")
                # Keep this section short.
                for msg in entries[:3]:
                    f.write(f"  - {msg}\n")
            f.write("\n")
        with open(out_file, "w", encoding="utf-8") as output:
            output.write(f.getvalue().rstrip() + "\n")


def extract_thumbnail_urls(maps_html: str, community_html: str) -> dict[str, str]:
    """Anzeigename -> absolute Bild-URL, fuer beide Map-Bereiche."""
    out = {}
    # Community-Karten tragen den Anzeigenamen im alt-Attribut.
    for src, alt in re.findall(
        r'<img[^>]+src=["\']([^"\']*/community-maps/[^"\']+)["\'][^>]*alt=["\']([^"\']+)["\']',
        community_html,
    ):
        out[alt.strip()] = normalize_url(urllib.parse.urljoin("https://hielkemaps.com", src))
    # Offizielle Karten tragen nur den Slug im Pfad.
    for src in re.findall(r'(?:src|content)=["\']([^"\']*/maps/[^"\']+/thumbnail[^"\']*)["\']', maps_html):
        slug = re.search(r"/maps/([^/]+)/", src)
        if not slug:
            continue
        name = " ".join(part.capitalize() for part in slug.group(1).split("-"))
        out.setdefault(name, normalize_url(urllib.parse.urljoin("https://hielkemaps.com", src)))
        # Die unkomprimierte Variante bevorzugen, wenn es sie gibt.
        if "thumbnail-compressed" in src:
            full = normalize_url(
                urllib.parse.urljoin(
                    "https://hielkemaps.com", src.replace("thumbnail-compressed", "thumbnail")
                )
            )
            if http_status(full) == 200:
                out[name] = full
    return out


def sync_thumbnails(thumb_urls: dict[str, str]) -> dict[str, str]:
    """Laedt fehlende Thumbnails, gibt Anzeigename -> lokaler Pfad zurueck."""
    local = {}
    for name, url in sorted(thumb_urls.items()):
        rel = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lstrip("/")
        rel = rel.removeprefix("media/").replace("//", "/").lstrip("/")
        if ".." in rel.split("/"):
            raise ValueError(f"Ungueltiger Thumbnail-Pfad: {url}")
        dest = os.path.join(THUMB_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            try:
                with open(dest, "wb") as f:
                    f.write(fetch_bytes(url, timeout=60))
                print(f"  thumbnail: {dest}")
            except Exception as exc:
                print(f"  thumbnail FAILED {url}: {exc}")
                continue
        local[name] = dest
    with open(os.path.join(THUMB_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Hielke Thumbnails\n\n")
        f.write(f"Gespeichert: {len(local)} Bilder\n\n")
        for name, path in sorted(local.items()):
            f.write(f"- {name}: `{path}` ({os.path.getsize(path)} bytes) <- {thumb_urls[name]}\n")
    return local


def collect_download_urls(maps_html: str, community_html: str, sitemap_xml: str, detail_pages: dict | None = None) -> list[str]:
    urls = []
    # Die Community-Seite verlinkt /downloads/community/*.zip direkt.
    urls.extend(extract_download_urls(community_html))
    listed = extract_map_slugs(maps_html)
    sitemap = extract_sitemap_slugs(sitemap_xml)
    if not listed or not sitemap or not urls:
        raise RuntimeError("Discovery incomplete: map listing, sitemap or community downloads are empty; inspect website structure")
    for slug in sorted(set(listed) | set(sitemap)):
        page = fetch_text(f"https://hielkemaps.com/maps/{slug}")
        downloads = extract_download_urls(page)
        if not downloads:
            raise RuntimeError(f"No ZIP links on /maps/{slug}; inspect page before excluding it")
        urls.extend(downloads)
        if detail_pages is not None:
            detail_pages[slug] = page
    # Fallback, falls kuenftiges HTML doch direkte Links enthaelt.
    urls.extend(extract_download_urls(maps_html))
    # Bereits archivierte Maps auch behalten, wenn die Website sie entfernt.
    for path in (OUT_OFFICIAL, OUT_COMMUNITY):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                previous = f.read()
                urls.extend(re.findall(r"Aktuelle Download-URL: (https://\S+)", previous))
                urls.extend(re.findall(r"^## \[[^\]]+\]\((https://hielkemaps\.com/downloads/[^)]+)\)", previous, re.MULTILINE))
    return list(OrderedDict.fromkeys(normalize_url(u) for u in urls))


def render_saved_archive():
    """Refresh tables from saved ZIPs and verified Wayback outcomes, without network requests."""
    with open(WAYBACK_REPORT, encoding="utf-8") as f:
        statuses = json.load(f)
    with open(WAYBACK_INDEX, encoding="utf-8") as f:
        verified = json.load(f)
    for status in statuses.values():
        if status.get("status") == "verified" and status.get("capture_url"):
            binding = verified.setdefault(status["local_zip"], {})
            binding.update(url=status["capture_url"], sha256=status["sha256"])
    no_wayback = load_no_wayback_index()
    with open(os.path.join(THUMB_DIR, "INDEX.md"), encoding="utf-8") as f:
        thumbs = dict(re.findall(r"^- (.+?): `([^`]+)`", f.read(), re.MULTILINE))
    results, errors = {}, {}
    for url, status in statuses.items():
        per_map = {}
        for entry in load_existing_entries(map_name(url), url, no_wayback, verified).values():
            upsert_version_entry(per_map, entry["version"], entry)
        results[url] = per_map
        if status.get("error"):
            errors[url] = [f"Wayback save failed: {status['error']}"]
    for path, title, urls in (
        (OUT_OFFICIAL, "Community Archive - Maps by Hielke", [u for u in statuses if not is_community(u)]),
        (OUT_COMMUNITY, "Community Archive - Maps by community creators", [u for u in statuses if is_community(u)]),
    ):
        write_markdown(path, title, urls, results, errors, thumbs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-wayback", action="store_true", help="Wayback bei Ausfall auslassen; bestehende Links behalten")
    parser.add_argument("--skip-history", action="store_true", help="Skip historical CDX discovery but still save every current download")
    parser.add_argument("--skip-upload", action="store_true", help="Nur lokal aktualisieren; keine Releases hochladen")
    args = parser.parse_args()
    maps_html = fetch_text("https://hielkemaps.com/maps/")
    community_html = fetch_text("https://hielkemaps.com/community-maps/")
    sitemap_xml = fetch_text("https://hielkemaps.com/sitemap.xml")
    detail_pages = {}
    all_urls = collect_download_urls(maps_html, community_html, sitemap_xml, detail_pages)

    print("Syncing thumbnails ...")
    thumbs = sync_thumbnails(extract_thumbnail_urls(maps_html + "".join(detail_pages.values()), community_html))

    no_wayback = load_no_wayback_index()
    try:
        with open(WAYBACK_INDEX, encoding="utf-8") as f:
            verified = json.load(f)
    except FileNotFoundError:
        verified = {}
    wayback_status = {url: {"status": "not_attempted"} for url in all_urls}
    results = {}
    errors = defaultdict(list)

    for idx, url in enumerate(all_urls, start=1):
        print(f"[{idx}/{len(all_urls)}] {url}")
        current_map_name = map_name(url)
        per_map = {}
        existing_by_ts = load_existing_entries(current_map_name, url, no_wayback, verified)
        for item in existing_by_ts.values():
            upsert_version_entry(per_map, item["version"], item)

        # 1) Den aktuellen Live-Download immer pruefen und lokal behalten.
        live_entry = None
        live_version = "Unknown"
        try:
            live_zip_bytes = fetch_bytes(url, timeout=180)
            live_entry = refresh_live_snapshot(url, live_zip_bytes, no_wayback, verified, wayback_status[url], args.skip_wayback)
            live_version = live_entry["version"]
            if wayback_status[url]["status"] == "failed":
                errors[url].append(f"Wayback save failed: {wayback_status[url]['error']}")
        except Exception as exc:
            errors[url].append(f"LIVE download failed: {exc}")
            wayback_status[url].update(status="download_failed", error=str(exc))

        try:
            rows = [] if args.skip_wayback or args.skip_history else cdx_rows(url)
        except Exception as exc:
            errors[url].append(f"CDX failed: {exc}")
            rows = []

        for row in rows:
            ts = row["timestamp"]
            if ts in existing_by_ts:
                # Wurde in einem frueheren Lauf schon lokal gesichert.
                continue
            wb = wayback_download_url(ts, row["original"])
            local_zip, sha1 = None, ""
            try:
                zip_bytes = fetch_bytes(wb, timeout=180)
                version = read_version_from_zip(zip_bytes) or "Unknown"
                sha1 = hashlib.sha1(zip_bytes).hexdigest()
                local_zip = write_zip_snapshot(current_map_name, ts, version, zip_bytes)
                previous_capture = verified.get(local_zip, {}).get("url", "")
                if (parse_wayback_timestamp(previous_capture) or "") < ts:
                    verified[local_zip] = {"url": wb, "sha1": sha1, "sha256": hashlib.sha256(zip_bytes).hexdigest()}
                no_wayback.discard(local_zip)
            except Exception as exc:
                version = "Unknown"
                errors[url].append(f"{ts}: {exc}")

            upsert_version_entry(
                per_map,
                version,
                {
                    "timestamp": ts,
                    "archive": wb,
                    "local_zip": local_zip,
                    "asset": os.path.basename(local_zip) if local_zip else None,
                    "sha1": sha1,
                    "live_url": url,
                },
            )

        # 3) Neu geholte Live-Version in der Tabelle sicherstellen.
        if live_entry:
            if not live_entry.get("archive"):
                live_entry["archive"] = verified.get(live_entry["local_zip"], {}).get("url")
            upsert_version_entry(per_map, live_version, live_entry)
            if per_map[live_version]["local_zip"] == live_entry["local_zip"]:
                per_map[live_version] = live_entry

        results[url] = per_map
        save_no_wayback_index(no_wayback)
        with open(WAYBACK_INDEX, "w", encoding="utf-8") as f:
            json.dump(verified, f, indent=2)
            f.write("\n")
        with open(WAYBACK_REPORT, "w", encoding="utf-8") as f:
            json.dump(wayback_status, f, indent=2)
            f.write("\n")

        if not args.skip_upload:
            sync_release(current_map_name, url, per_map)

    official = [u for u in all_urls if not is_community(u)]
    community = [u for u in all_urls if is_community(u)]
    write_markdown(
        OUT_OFFICIAL, "Community Archive - Maps by Hielke", official, results, errors, thumbs
    )
    write_markdown(
        OUT_COMMUNITY, "Hielke Maps Archive - Community", community, results, errors, thumbs
    )
    print(f"Wrote {OUT_OFFICIAL} ({len(official)} downloads) and {OUT_COMMUNITY} ({len(community)} maps).")
    return 1 if any(errors.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
