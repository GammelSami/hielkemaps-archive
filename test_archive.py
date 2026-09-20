import io
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_hielke_archive_md as archive


class ArchiveTests(unittest.TestCase):
    def test_snapshot_deduplicates_and_rejects_non_zip(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as zipped:
            zipped.writestr("example.txt", "snapshot")
        with tempfile.TemporaryDirectory() as folder, patch.object(archive, "ARCHIVE_DIR", folder):
            first = archive.write_zip_snapshot("Example", "20260101000000", "1.21", payload.getvalue())
            second = archive.write_zip_snapshot("Example", "20260201000000", "1.21", payload.getvalue())
            self.assertEqual(first, second)
            with self.assertRaises(ValueError):
                archive.write_zip_snapshot("Example", "20260301000000", "Unknown", b"<html>Error</html>")
            self.assertEqual(len(list(Path(folder).rglob("*.zip"))), 1)

    def test_upload_keeps_multiple_snapshots_of_one_version(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(archive, "ARCHIVE_DIR", folder):
            target = Path(folder, "Example")
            target.mkdir()
            names = ["20260101000000__1.21.zip", "20260201000000__1.21.zip"]
            for name in names:
                (target / name).write_bytes(b"snapshot")
            with patch.object(archive, "release_assets", return_value={names[0]}), patch.object(archive, "gh") as gh:
                uploaded = archive.sync_release("Example", "https://example.com/map.zip", {})
            self.assertEqual(uploaded, {names[1]})
            uploads = [c.args for c in gh.call_args_list if c.args[:2] == ("release", "upload")]
            self.assertEqual(len(uploads), 1)
            self.assertEqual(uploads[0][3], str(target / names[1]))
            self.assertNotIn("--clobber", uploads[0])

    def test_release_lookup_only_treats_missing_release_as_absent(self):
        with patch.object(archive, "gh", return_value=subprocess.CompletedProcess([], 1, "", "release not found")):
            self.assertIsNone(archive.release_assets("map-example"))
        with patch.object(archive, "gh", return_value=subprocess.CompletedProcess([], 1, "", "network failure")):
            with self.assertRaises(RuntimeError):
                archive.release_assets("map-example")

    def test_double_slash_thumbnail_stays_in_destination(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(archive, "THUMB_DIR", folder):
            with patch.object(archive, "fetch_bytes", return_value=b"image"):
                result = archive.sync_thumbnails({"Example": "https://hielkemaps.com/media//maps/example/thumbnail.jpg"})
            self.assertEqual(result["Example"], os.path.join(folder, "maps/example/thumbnail.jpg"))
            with self.assertRaises(ValueError):
                archive.sync_thumbnails({"Example": "https://hielkemaps.com/media/../escape.jpg"})

    def test_markdown_links_local_snapshot_without_inventing_wayback(self):
        url = "https://hielkemaps.com/downloads/Example.zip"
        entry = {"timestamp": "20260101000000", "asset": "20260101000000__1.21.zip", "archive": None}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "archive.md")
            archive.write_markdown(str(path), "Example", [url], {url: {"1.21": entry}}, {}, {})
            text = path.read_text()
        self.assertIn("/releases/download/map-example/20260101000000__1.21.zip", text)
        self.assertNotIn("web.archive.org", text)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
