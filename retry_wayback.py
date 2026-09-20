"""Retry incomplete Save Page Now jobs without repeating successful captures."""
import hashlib
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import build_hielke_archive_md as archive


def write_json(path, data):
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def main():
    statuses = json.loads(Path(archive.WAYBACK_REPORT).read_text())
    verified_path = Path(archive.WAYBACK_INDEX)
    verified = json.loads(verified_path.read_text()) if verified_path.exists() else {}
    missing = archive.load_no_wayback_index()
    for url, status in statuses.items():
        if status["status"] == "verified":
            continue
        print(f"Retrying {url}", flush=True)
        # Old reports predate the explicit job_status field.
        terminal = status.get("job_status") == "error" or "target server didn't respond" in status.get("error", "")
        requested_at = status.get("requested_at")
        stale = requested_at and (datetime.now(timezone.utc) - datetime.fromisoformat(requested_at)).total_seconds() > 3600
        if (terminal or stale) and status.get("job_id"):
            status.setdefault("previous_jobs", []).append(status.pop("job_id"))
            status.pop("job_status", None)
        try:
            path = status["local_zip"]
            local = Path(path).read_bytes()
            if hashlib.sha256(local).hexdigest() != status["sha256"]:
                raise ValueError("Local ZIP changed since the live download was checked")
            capture = archive.save_current_to_wayback(url, status=status, checkpoint=lambda: write_json(archive.WAYBACK_REPORT, statuses))
            payload = archive.fetch_bytes(capture, timeout=180)
            if hashlib.sha256(payload).hexdigest() != status["sha256"]:
                raise ValueError("Captured ZIP differs from the checked live download")
            verified[path] = {"url": capture, "sha1": hashlib.sha1(payload).hexdigest(), "sha256": status["sha256"]}
            missing.discard(path)
            status.update(status="verified", capture_url=capture)
            status.pop("error", None)
        except Exception as exc:
            status.update(status="failed", error=str(exc))
        write_json(archive.WAYBACK_REPORT, statuses)
        write_json(archive.WAYBACK_INDEX, verified)
        archive.save_no_wayback_index(missing)
        print(status["status"], status.get("error", ""), flush=True)
        time.sleep(15)
    remaining = sum(row["status"] != "verified" for row in statuses.values())
    archive.render_saved_archive()
    print(f"{len(statuses) - remaining}/{len(statuses)} current ZIPs verified on Wayback")
    return 1 if remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
