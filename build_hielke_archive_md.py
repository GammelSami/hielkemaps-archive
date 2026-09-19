#!/usr/bin/env python3
import io
import json
import hashlib
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone

from nbt2yaml.parse import parse_nbt


PAGES = [
    "https://hielkemaps.com/maps/",
    "https://hielkemaps.com/community-maps/",
]
CDX_API = "https://web.archive.org/cdx/search/cdx"
OUT_FILE = "hielke-maps-archive.md"
ARCHIVE_DIR = "archive_zips"
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


def extract_download_urls(html: str) -> list[str]:
    urls = []
    for raw in re.findall(r'href=["\']([^"\']+\.zip)["\']', html, flags=re.IGNORECASE):
        if "/downloads/" not in raw:
            continue
        abs_url = urllib.parse.urljoin("https://hielkemaps.com", raw)
        if abs_url.startswith("https://hielkemaps.com/downloads/"):
            urls.append(normalize_url(abs_url))
    unique = list(OrderedDict.fromkeys(urls))
    return unique


def extract_map_slugs(html: str) -> list[str]:
    slugs = []
    for raw in re.findall(r"location\.href='(/maps/[^']+)'", html):
        if raw.startswith("/maps/"):
            slugs.append(raw.removeprefix("/maps/"))
    return list(OrderedDict.fromkeys(slugs))


def slug_to_official_download(slug: str) -> str:
    # /maps/parkour-volcano -> /downloads/Parkour%20Volcano.zip
    title = " ".join(part.capitalize() for part in slug.split("-"))
    return normalize_url(f"https://hielkemaps.com/downloads/{title}.zip")


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
    api_url = f"{CDX_API}?{query}"
    raw = fetch_text(api_url)
    data = json.loads(raw)
    if not data or len(data) == 1:
        return []
    rows = []
    for row in data[1:]:
        rows.append(
            {
                "timestamp": row[0],
                "original": row[1],
                "statuscode": row[2],
                "digest": row[3] if len(row) > 3 else "",
            }
        )
    return rows


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
    except Exception:
        return None
    return None


def wayback_download_url(timestamp: str, original: str) -> str:
    return f"https://web.archive.org/web/{timestamp}if_/{original}"


def parse_wayback_timestamp(url: str) -> str | None:
    m = re.search(r"/web/(\d{14})", url)
    return m.group(1) if m else None


def save_current_to_wayback(original_url: str, timeout: int = 120) -> str | None:
    # Save current live file and return the created archive snapshot URL if available.
    save_url = f"https://web.archive.org/save/{original_url}"
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(save_url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                final_url = resp.geturl()
                if "/web/" in final_url:
                    time.sleep(REQUEST_DELAY_SECONDS)
                    return final_url
            time.sleep(REQUEST_DELAY_SECONDS)
            return None
        except Exception as exc:
            last_exc = exc
            time.sleep(min(3.0, 0.75 * attempt))
    raise last_exc


def map_name(download_url: str) -> str:
    filename = download_url.rsplit("/", 1)[-1]
    name = urllib.parse.unquote(filename)
    if name.lower().endswith(".zip"):
        name = name[:-4]
    return name


def slugify_filename(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^\w\s.-]", "_", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value[:180].strip("._") or "unknown"


def write_zip_snapshot(map_display_name: str, timestamp: str, version: str, payload: bytes) -> str:
    folder = os.path.join(ARCHIVE_DIR, slugify_filename(map_display_name))
    os.makedirs(folder, exist_ok=True)
    safe_version = slugify_filename(version)
    filename = f"{timestamp}__{safe_version}.zip"
    rel_path = os.path.join(folder, filename)
    payload_sha1 = hashlib.sha1(payload).hexdigest()

    # De-duplicate identical payloads per map folder.
    for existing_name in os.listdir(folder):
        if not existing_name.endswith(".zip"):
            continue
        existing_path = os.path.join(folder, existing_name)
        try:
            with open(existing_path, "rb") as f:
                existing_sha1 = hashlib.sha1(f.read()).hexdigest()
            if existing_sha1 == payload_sha1:
                return existing_path
        except Exception:
            continue

    with open(rel_path, "wb") as f:
        f.write(payload)
    return rel_path


def map_folder_path(map_display_name: str) -> str:
    return os.path.join(ARCHIVE_DIR, slugify_filename(map_display_name))


def load_existing_entries(map_display_name: str, original_url: str) -> dict[str, dict]:
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
        except Exception:
            version = "Unknown"
        out[ts] = {
            "timestamp": ts,
            "archive": wayback_download_url(ts, original_url),
            "local_zip": rel_path,
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


def main():
    maps_html = fetch_text("https://hielkemaps.com/maps/")
    community_html = fetch_text("https://hielkemaps.com/community-maps/")

    all_urls = []
    # Community pages provide direct /downloads/community/*.zip links.
    all_urls.extend(extract_download_urls(community_html))
    # Some official map pages do not expose direct ZIP links on /maps/,
    # so derive them from slug and verify availability.
    for slug in extract_map_slugs(maps_html):
        candidate = slug_to_official_download(slug)
        if http_status(candidate) == 200:
            all_urls.append(candidate)
        else:
            print(f"Skipping (not found): {candidate}")

    # Keep a fallback in case future HTML contains direct zip links too.
    all_urls.extend(extract_download_urls(maps_html))
    all_urls = [normalize_url(u) for u in all_urls]
    all_urls = list(OrderedDict.fromkeys(all_urls))

    results = {}
    errors = defaultdict(list)

    for idx, url in enumerate(all_urls, start=1):
        print(f"[{idx}/{len(all_urls)}] {url}")
        current_map_name = map_name(url)
        per_map = {}
        existing_by_ts = load_existing_entries(current_map_name, url)
        for item in existing_by_ts.values():
            upsert_version_entry(
                per_map,
                item["version"],
                {
                    "timestamp": item["timestamp"],
                    "archive": item["archive"],
                    "local_zip": item["local_zip"],
                    "live_url": item["live_url"],
                },
            )
        live_version = "Unknown"
        live_local_zip = None
        live_archive_url = None
        live_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        # 1) Always inspect the current live download and keep a local copy.
        try:
            live_zip_bytes = fetch_bytes(url, timeout=120)
            parsed = read_version_from_zip(live_zip_bytes)
            live_version = parsed if parsed else "Unknown"
            live_local_zip = write_zip_snapshot(current_map_name, live_timestamp, live_version, live_zip_bytes)
        except Exception as exc:
            errors[url].append(f"LIVE download failed: {exc}")

        # 2) Ask Wayback to archive the current live file now.
        try:
            live_archive_url = save_current_to_wayback(url)
            if live_archive_url:
                ts = parse_wayback_timestamp(live_archive_url)
                if ts:
                    live_timestamp = ts
        except Exception as exc:
            errors[url].append(f"LIVE save failed: {exc}")

        try:
            rows = cdx_rows(url)
        except Exception as exc:
            errors[url].append(f"CDX failed: {exc}")
            rows = []

        for row in rows:
            ts = row["timestamp"]
            if ts in existing_by_ts:
                # Already downloaded locally in a previous run.
                continue
            wb = wayback_download_url(ts, row["original"])
            local_zip = None
            try:
                zip_bytes = fetch_bytes(wb, timeout=120)
                version = read_version_from_zip(zip_bytes)
                if not version:
                    version = "Unknown"
                local_zip = write_zip_snapshot(current_map_name, ts, version, zip_bytes)
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
                    "live_url": url,
                },
            )

        # 3) Ensure current live version is represented in the table
        # (important for versions that are newer than historical snapshots).
        upsert_version_entry(
            per_map,
            live_version,
            {
                "timestamp": live_timestamp,
                "archive": live_archive_url,
                "local_zip": live_local_zip,
                "live_url": url,
            },
        )

        results[url] = per_map

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        f.write("# Hielke Maps Archive (Wayback)\n\n")
        f.write(f"_Generated: {generated}_\n\n")
        f.write(
            "Quelle: `https://hielkemaps.com/maps/` und "
            "`https://hielkemaps.com/community-maps/`.\n\n"
        )
        f.write(
            "Hinweis: Versionen werden aus `level.dat` (NBT, via `nbt2yaml`-Parser) "
            "gelesen. Bei unlesbaren Dateien steht `Unknown`.\n\n"
        )

        for url in sorted(results.keys(), key=map_name):
            f.write(f"## {map_name(url)}\n\n")
            f.write(f"- Aktuelle Download-URL: {url}\n")
            versions = results[url]
            if not versions:
                f.write("- Keine Archive.org-Snapshots gefunden.\n\n")
                continue
            f.write(
                "\n| Minecraft Java | Snapshot (UTC) | Archive.org | Lokal gespeicherte ZIP |\n"
            )
            f.write("|---|---|---|---|\n")
            for version, data in sorted(
                versions.items(), key=lambda x: x[1]["timestamp"], reverse=True
            ):
                ts = datetime.strptime(data["timestamp"], "%Y%m%d%H%M%S").strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                local_zip = data.get("local_zip")
                local_cell = local_zip if local_zip else "-"
                archive_cell = f"[Link]({data['archive']})" if data.get("archive") else "-"
                f.write(
                    f"| {version} | {ts} | {archive_cell} | `{local_cell}` |\n"
                )
            f.write("\n")

        if errors:
            f.write("## Fehler/Unklare Fälle\n\n")
            for url, entries in sorted(errors.items(), key=lambda x: map_name(x[0])):
                if not entries:
                    continue
                f.write(f"- {map_name(url)}\n")
                # Keep this section short.
                for msg in entries[:3]:
                    f.write(f"  - {msg}\n")
            f.write("\n")

    print(f"Wrote {OUT_FILE} with {len(results)} maps.")


if __name__ == "__main__":
    main()
