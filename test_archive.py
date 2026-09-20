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

    def test_discovery_includes_sitemap_only_map_and_resource_pack(self):
        listing = '<div onclick="location.href=\'/maps/listed\';"></div>'
        community = '<a href="/downloads/community/Example.zip">Download</a>'
        sitemap = '<urlset><url><loc>https://hielkemaps.com/maps/arrow-fight</loc></url></urlset>'
        pages = {
            'https://hielkemaps.com/maps/listed': '<a href="/downloads/Actual Name.zip">Download</a>',
            'https://hielkemaps.com/maps/arrow-fight': '<a href="/downloads/Arrow Fight.zip">Map</a><a href="/downloads/Arrow Fight Resource Pack.zip">Pack</a>',
        }
        with patch.object(archive, 'fetch_text', side_effect=pages.__getitem__):
            with patch.object(archive.os.path, 'exists', return_value=False):
                urls = archive.collect_download_urls(listing, community, sitemap)
        self.assertEqual(len(urls), 4)
        self.assertIn('https://hielkemaps.com/downloads/Actual%20Name.zip', urls)
        self.assertIn('https://hielkemaps.com/downloads/Arrow%20Fight%20Resource%20Pack.zip', urls)

    def test_discovery_supports_anchor_links_and_fails_on_empty_listing(self):
        self.assertEqual(archive.extract_map_slugs('<a href="/maps/arrow-fight/">Map</a>'), ['arrow-fight'])
        self.assertEqual(archive.extract_map_slugs('<div onclick="window.location.href = &quot;/maps/arrow-fight&quot;"></div>'), ['arrow-fight'])
        with self.assertRaises(RuntimeError):
            archive.collect_download_urls('<div>New layout</div>', '', '<urlset/>')

    def test_unchanged_zip_is_resubmitted_and_verified_without_renaming(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as zipped:
            zipped.writestr('example.txt', 'snapshot')
        payload = stream.getvalue()
        capture = 'https://web.archive.org/web/20260920000000if_/https://hielkemaps.com/downloads/Example.zip'
        with tempfile.TemporaryDirectory() as folder, patch.object(archive, 'ARCHIVE_DIR', folder):
            path = archive.write_zip_snapshot('Example', '20260101000000', 'Unknown', payload)
            missing, verified, status = {path}, {}, {}
            with patch.object(archive, 'save_current_to_wayback', return_value=capture) as save:
                with patch.object(archive, 'fetch_bytes', return_value=payload):
                    entry = archive.refresh_live_snapshot('https://hielkemaps.com/downloads/Example.zip', payload, missing, verified, status)
            save.assert_called_once()
            self.assertEqual(entry['local_zip'], path)
            self.assertEqual(entry['timestamp'], '20260101000000')
            self.assertEqual(entry['archive'], capture)
            self.assertEqual(status['status'], 'verified')
            self.assertNotIn(path, missing)
            self.assertEqual(verified[path]['url'], capture)
            self.assertEqual(len(list(Path(folder).rglob('*.zip'))), 1)

    def test_mismatching_wayback_zip_is_not_marked_saved(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as zipped:
            zipped.writestr('example.txt', 'snapshot')
        with tempfile.TemporaryDirectory() as folder, patch.object(archive, 'ARCHIVE_DIR', folder):
            missing, verified, status = set(), {}, {}
            with patch.object(archive, 'save_current_to_wayback', return_value='https://web.archive.org/web/20260920000000if_/https://example.com/'):
                with patch.object(archive, 'fetch_bytes', return_value=b'wrong bytes'):
                    entry = archive.refresh_live_snapshot('https://hielkemaps.com/downloads/Example.zip', stream.getvalue(), missing, verified, status)
            self.assertIsNone(entry['archive'])
            self.assertIn(entry['local_zip'], missing)
            self.assertFalse(verified)
            self.assertEqual(status['status'], 'failed')

    def test_thumbnail_is_rendered_as_small_image(self):
        url = 'https://hielkemaps.com/downloads/Example.zip'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder, 'maps.md')
            archive.write_markdown(str(output), 'Maps', [url], {}, {}, {'Example': 'thumbnails/example image.jpg'})
            text = output.read_text()
        self.assertIn('<img src="thumbnails/example%20image.jpg" alt="Example" width="180">', text)
        self.assertNotIn('Thumbnail: `', text)
        self.assertIn('## [Example](https://hielkemaps.com/downloads/Example.zip)', text)
        self.assertNotIn('Aktuelle Download-URL:', text)
        self.assertNotIn('/releases/tag/', text)

    def test_save_page_now_polls_job_before_returning_capture(self):
        import json
        responses = [io.StringIO(json.dumps({'job_id': 'test-job'})),
                     io.StringIO(json.dumps({'job_id': 'test-job', 'status': 'pending'})),
                     io.StringIO(json.dumps({'job_id': 'test-job', 'status': 'success', 'timestamp': '20260920000000', 'http_status': 200}))]
        status = {}
        with patch.object(archive, 'wayback_headers', return_value={'Accept': 'application/json'}):
            with patch.object(archive.urllib.request, 'urlopen', side_effect=responses) as request:
                with patch.object(archive.time, 'sleep'):
                    url = archive.save_current_to_wayback('https://hielkemaps.com/downloads/Example.zip', status=status)
        self.assertIn('/web/20260920000000if_/', url)
        self.assertEqual(status['status'], 'captured')
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[0].args[0].get_method(), 'POST')
        self.assertIn('/save/status/test-job?', request.call_args_list[1].args[0].full_url)

    def test_save_page_now_rejects_failed_capture(self):
        import json
        response = io.StringIO(json.dumps({'status': 'error', 'message': 'capture failed'}))
        with patch.object(archive, 'wayback_headers', return_value={}):
            with patch.object(archive.urllib.request, 'urlopen', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                    archive.save_current_to_wayback('https://hielkemaps.com/downloads/Example.zip')

    def test_daily_limit_uses_only_todays_capture_for_verification(self):
        import json
        today = archive.datetime.now(archive.timezone.utc).strftime('%Y%m%d')
        response = io.StringIO(json.dumps({'message': 'This URL has reached a daily limit'}))
        rows = [['timestamp', 'original'], [today+'010203', 'https://hielkemaps.com/downloads/Example.zip']]
        status = {}
        with patch.object(archive, 'wayback_headers', return_value={}):
            with patch.object(archive.urllib.request, 'urlopen', return_value=response):
                with patch.object(archive, 'fetch_text', return_value=json.dumps(rows)):
                    capture = archive.save_current_to_wayback(rows[1][1], status=status)
        self.assertIn('/web/'+today+'010203if_/', capture)
        self.assertEqual(status['status'], 'captured')
        self.assertNotEqual(status['status'], 'verified')

    def test_known_downloads_survive_linked_heading_format(self):
        with tempfile.TemporaryDirectory() as folder:
            table = Path(folder, 'maps.md')
            table.write_text('## [Removed Map](https://hielkemaps.com/downloads/Removed%20Map.zip)\n')
            with patch.object(archive, 'OUT_OFFICIAL', str(table)), patch.object(archive, 'OUT_COMMUNITY', str(Path(folder, 'absent.md'))):
                with patch.object(archive, 'fetch_text', return_value='<a href="/downloads/Listed.zip">Map</a>'):
                    urls = archive.collect_download_urls('<a href="/maps/listed">Map</a>', '<a href="/downloads/community/Example.zip">Map</a>', '<urlset><url><loc>/maps/listed</loc></url></urlset>')
            self.assertIn('https://hielkemaps.com/downloads/Removed%20Map.zip', urls)

    def test_retry_preserves_success_and_restarts_stale_job(self):
        import json
        import hashlib
        import retry_wayback as retry
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = b'previously verified local payload'
            local = root / 'snapshot.zip'
            local.write_bytes(payload)
            report = root / 'status.json'
            index = root / 'verified.json'
            missing = root / 'missing.json'
            done = {'status': 'verified', 'capture_url': 'https://web.archive.org/web/20260101000000if_/https://example.com/done'}
            pending = {'status': 'failed', 'job_id': 'stale-job', 'requested_at': '2000-01-01T00:00:00+00:00', 'local_zip': str(local), 'sha256': hashlib.sha256(payload).hexdigest()}
            report.write_text(json.dumps({'https://example.com/done': done, 'https://example.com/pending': pending}))
            missing.write_text(json.dumps([str(local)]))
            capture = 'https://web.archive.org/web/20260920000000if_/https://example.com/pending'
            def save(url, status, checkpoint):
                self.assertNotIn('job_id', status)
                self.assertEqual(status['previous_jobs'], ['stale-job'])
                status['job_id'] = 'new-job'
                checkpoint()
                self.assertEqual(json.loads(report.read_text())[url]['job_id'], 'new-job')
                return capture
            with patch.multiple(archive, WAYBACK_REPORT=str(report), WAYBACK_INDEX=str(index), NO_WAYBACK_INDEX=str(missing)):
                with patch.object(archive, 'save_current_to_wayback', side_effect=save) as request, patch.object(archive, 'fetch_bytes', return_value=payload):
                    with patch.object(archive, 'render_saved_archive'), patch.object(retry.time, 'sleep'):
                        self.assertEqual(retry.main(), 0)
                request.assert_called_once()
            result = json.loads(report.read_text())
            self.assertEqual(result['https://example.com/done'], done)
            self.assertEqual(result['https://example.com/pending']['status'], 'verified')
            self.assertEqual(json.loads(index.read_text())[str(local)]['url'], capture)
            self.assertEqual(json.loads(missing.read_text()), [])


if __name__ == "__main__":
    unittest.main()
