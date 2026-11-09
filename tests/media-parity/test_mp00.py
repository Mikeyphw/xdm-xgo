#!/usr/bin/env python3
"""Offline suite; validates fixture bytes, server behavior and evidence hygiene."""
import hashlib
from http.client import HTTPConnection
import json
import os
from unittest.mock import patch
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from acceptance import inventory
from apk_fingerprint import fingerprint
from zipfile import ZipFile
from fixture_server import make_server
from generate_fixtures import generate, sha256
from reference_oracle import validate
from scoped_http import opener
from verify_output import verify

HERE = Path(__file__).resolve().parent


class InventoryTests(unittest.TestCase):
    def test_matrix_no_made_up_passes(self):
        report = inventory(HERE / 'test_matrix.csv')
        self.assertEqual(report['total'], 140)
        self.assertEqual(report['counts'].get('passed', 0), 0)
        self.assertEqual(report['counts']['not_run'], 140)

    def test_reference_baseline_unmeasured(self):
        ref = json.loads((HERE / 'reference_1dm.json').read_text())
        summary = validate(ref, HERE / 'test_matrix.csv')
        self.assertEqual(summary['not_run'], 10)
        self.assertFalse(ref['reference']['signer_identity_verified'])

    def test_apk_fingerprint_is_noninstalling_and_not_signer_authority(self):
        with tempfile.TemporaryDirectory(prefix='mp00-fake-apk-') as folder:
            path = Path(folder) / 'synthetic.apk'
            with ZipFile(path, 'w') as file:
                file.writestr('classes.dex', b'testdata')
                file.writestr('lib/arm64-v8a/libtest.so', b'not-a-real-elf')
            result = fingerprint(path)
            self.assertEqual(result['abi'], ['arm64-v8a'])
            self.assertEqual(result['dex_files'], 1)
            self.assertFalse(result['signer_identity_verified'])
            self.assertFalse(result['installed_or_behaviorally_tested'])

    def test_ffmpeg_pin_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix='mp00-pin-') as folder:
            with self.assertRaises(ValueError):
                generate(Path(folder) / 'no', expected_version='0.0.0-not-available')
            with self.assertRaises(ValueError):
                generate(Path(folder) / 'also-no', expected_binary_sha256='0' * 64)
            with patch.dict(os.environ, {'MP00_FFMPEG_VERSION': '0.0.0-bad-pin'}):
                with self.assertRaises(ValueError):
                    generate(Path(folder) / 'bad-ci-env')

    def test_no_unobserved_evidence(self):
        ref = json.loads((HERE / 'reference_1dm.json').read_text())
        ref['observations']['REF01']['status'] = 'measured'
        with self.assertRaises(ValueError):
            validate(ref, HERE / 'test_matrix.csv')

    def test_reference_rejects_private_values(self):
        ref = json.loads((HERE / 'reference_1dm.json').read_text())
        ref['observations']['REF01'] = {'status': 'measured', 'observed_at': '2026-11-09T03:00:00Z',
                                        'evidence': {'headers': {'Cookie': 'secret'}}}
        with self.assertRaises(ValueError):
            validate(ref, HERE / 'test_matrix.csv')


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='mp00-unittest-')
        cls.root = Path(cls.tmp.name) / 'fixtures'
        cls.manifest = generate(cls.root)
        cls.server, cls.state = make_server(cls.root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def request(self, path, headers=None):
        try:
            with urlopen(Request(self.url + path, headers=headers or {}), timeout=5) as f:
                return f.status, f.headers, f.read()
        except HTTPError as e:
            return e.code, e.headers, e.read()

    def test_manifest_inventory_verified(self):
        manifest = json.loads((self.root / 'fixture_manifest.json').read_text())
        self.assertGreater(len(manifest['files']), 12)
        for item in manifest['files']:
            target = self.root / item['path']
            self.assertTrue(target.is_file())
            self.assertEqual(item['sha256'], sha256(target))
            self.assertEqual(item['size'], target.stat().st_size)

    def test_fixture_bytes_reproducible_same_toolchain(self):
        other = Path(self.tmp.name) / 'regenerated'
        fresh = generate(other)
        self.assertEqual(
            [(x['path'], x['sha256']) for x in self.manifest['files']],
            [(x['path'], x['sha256']) for x in fresh['files']])

    def test_progressive_decodable(self):
        receipt = verify(self.root / 'vod' / 'progressive.mp4', min_duration=5)
        self.assertTrue(receipt['verified'])
        self.assertIn('video', receipt['decoded_fingerprints'])
        self.assertIn('audio', receipt['decoded_fingerprints'])

    def test_hls_master_and_renditions(self):
        status, headers, body = self.request('/vod/hls/master.m3u8')
        self.assertEqual(status, 200)
        self.assertIn(b'LANGUAGE="es"', body)
        self.assertIn(b'AUDIO="aud"', body)
        for media in ('/vod/hls/v/360p.m3u8', '/vod/hls/v/180p.m3u8',
                      '/vod/hls/a/en.m3u8', '/vod/hls/a/es.m3u8',
                      '/vod/hls/fmp4/playlist.m3u8'):
            s, _, raw = self.request(media)
            self.assertEqual(s, 200)
            self.assertIn(b'#EXTM3U', raw)
            self.assertIn(b'#EXT-X-ENDLIST', raw)
        mpd = self.request('/vod/dash/static.mpd')[2]
        self.assertIn(b'<MPD', mpd)
        self.assertIn(b'AdaptationSet', mpd)

    def test_hls_mux_playable(self):
        destination = Path(self.tmp.name) / 'hls-mux.mp4'
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                   '-i', self.url + '/vod/hls/master.m3u8',
                   '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', str(destination)]
        p = subprocess.run(command, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, 'HLS remux failed')
        self.assertTrue(verify(destination, min_duration=5)['verified'])

    def test_dash_mux_playable(self):
        destination = Path(self.tmp.name) / 'dash-mux.mp4'
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                   '-i', self.url + '/vod/dash/static.mpd',
                   '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', str(destination)]
        p = subprocess.run(command, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, 'DASH remux failed')
        self.assertTrue(verify(destination, min_duration=5)['verified'])

    def test_byte_range_and_suffix(self):
        whole = self.request('/range/progressive.mp4')[2]
        status, h, data = self.request('/range/progressive.mp4', {'Range': 'bytes=10-30'})
        self.assertEqual((status, data), (206, whole[10:31]))
        self.assertEqual(h['Content-Range'], f'bytes 10-30/{len(whole)}')
        status, _, data = self.request('/range/progressive.mp4', {'Range': 'bytes=-17'})
        self.assertEqual((status, data), (206, whole[-17:]))
        status, _, _ = self.request('/range/progressive.mp4', {'Range': 'bytes=999999999-'})
        self.assertEqual(status, 416)
        status, _, _ = self.request('/range/progressive.mp4', {'Range': 'bytes=0-1,8-9'})
        self.assertEqual(status, 416)

    def test_live_tick_and_end(self):
        _, _, body = self.request('/live/hls/playlist.m3u8?tick=4&token=hush')
        self.assertIn(b'#EXT-X-MEDIA-SEQUENCE:2', body)
        self.assertNotIn(b'#EXT-X-ENDLIST', body)
        _, _, done = self.request('/live/hls/playlist.m3u8?tick=4&end=1')
        self.assertIn(b'#EXT-X-ENDLIST', done)
        s, _, mpd = self.request('/live/dash/stream.mpd?tick=3')
        self.assertEqual(s, 200)
        self.assertIn(b'<MPD', mpd)

    def test_auth_refresh_and_no_values_in_metrics(self):
        self.assertEqual(self.request('/auth/segment.ts?token=S3CRET')[0], 403)
        self.assertEqual(self.request('/auth/segment.ts?token=mp00-token-v2')[0], 200)
        self.assertEqual(self.request('/auth/segment.ts', {'Cookie': 'mp00_session=fixture'})[0], 200)
        self.assertEqual(self.request('/auth/refresh')[0], 200)
        self.request('/vod/progressive.mp4?token=QUERY_HIDDEN&SECRET_AS_KEY=1',
                     {'Authorization': 'Bearer HEADER_HIDDEN', 'Cookie': 'session=COOKIE_HIDDEN',
                      'X-HEADER-SECRET': 'badvalue'})
        self.request('/vod/SECRET_IN_PATH.mp4')
        recorded = self.request('/metrics')[2]
        for secret in (b'S3CRET', b'QUERY_HIDDEN', b'HEADER_HIDDEN', b'COOKIE_HIDDEN', b'SECRET_IN_PATH', b'SECRET_AS_KEY', b'X-HEADER-SECRET',
                       b'Bearer', b'mp00-token-v2'):
            self.assertNotIn(secret, recorded)
        metrics = json.loads(recorded)
        self.assertTrue(any(row['authorization_present'] for row in metrics['events']))
        self.assertTrue(any(row['cookie_present'] for row in metrics['events']))

    def test_retry_faults(self):
        self.assertEqual(self.request('/status/404once')[0], 404)
        self.assertEqual(self.request('/status/404once')[0], 200)
        s, h, _ = self.request('/status/429once')
        self.assertEqual((s, h['Retry-After']), (429, '1'))
        self.assertEqual(self.request('/status/429once')[0], 200)

    def test_traversal_and_unknown_fail_closed(self):
        for path in ('/vod/missing.mp4', '/vod/%2e%2e/README.md', '/unknown'):
            self.assertEqual(self.request(path)[0], 404)

    def test_redirect_origin_rewritten(self):
        # Python urllib does not reliably drop credentials across hosts.
        # Test the intentionally scoped fixture client, not XDM production.
        with opener().open(Request(self.url + '/redirect/cross-origin',
                                   headers={'Authorization': 'Bearer TEST',
                                            'Cookie': 'session=TEST'}), timeout=5) as response:
            status, data = response.status, response.read()
        self.assertEqual(status, 200)
        result = json.loads(data)
        self.assertFalse(result['authorization_present'])
        self.assertFalse(result['cookie_present'])

    def test_head_and_content_type(self):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request('HEAD', '/vod/hls/master.m3u8')
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.read(), b'')
        self.assertEqual(response.getheader('Content-Type'), 'application/vnd.apple.mpegurl')
        connection.close()


if __name__ == '__main__':
    unittest.main()
