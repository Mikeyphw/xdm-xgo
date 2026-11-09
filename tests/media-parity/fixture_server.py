#!/usr/bin/env python3
"""MP00 localhost-only deterministic media-fixture HTTP server.

Do not publish this deliberately fault-injecting fixture server on the internet.
Request telemetry never stores header values, query values or raw request targets.
"""
import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

MAX_LOG = 2000
MAX_BODY = 32 * 1024 * 1024
SAFE_ENDPOINTS = {'/health', '/metrics', '/auth/refresh', '/auth/echo',
                  '/auth/segment.ts', '/redirect/cross-origin',
                  '/redirect/same-origin', '/stall', '/slow', '/abort',
                  '/status/404once', '/status/429once',
                  '/live/hls/playlist.m3u8', '/live/dash/stream.mpd'}
SAFE_QUERY_KEYS = {'tick', 'token', 'end', 'seconds'}
SAFE_HEADER_NAMES = {'accept', 'host', 'user-agent', 'range', 'content-type',
                     'accept-encoding', 'connection'}


def safe_route(route):
    if route in SAFE_ENDPOINTS:
        return route
    if route.startswith('/vod/'):
        return '/vod/*'
    if route.startswith('/live/hls/seg/'):
        return '/live/hls/seg/*'
    if route.startswith('/range/'):
        return '/range/*'
    return '/unknown'


class State:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.events = deque(maxlen=MAX_LOG)
        self.counters = Counter()
        self.lock = threading.RLock()

    def record(self, method, route, query, headers):
        # Never record header values, URL query values or a URL with a query.
        item = {'method': method, 'path': safe_route(route),
                'query_keys': sorted(k if k in SAFE_QUERY_KEYS else '<other>' for k in set(query)),
                'header_names': sorted(k.lower() for k in headers.keys()
                                       if k.lower() in SAFE_HEADER_NAMES),
                'authorization_present': bool(headers.get('Authorization')),
                'cookie_present': bool(headers.get('Cookie'))}
        with self.lock:
            safe = safe_route(route)
            self.counters[safe] += 1
            self.events.append(item)
            # One-shot faults need actual route counts; routes are fixed here.
            return self.counters[safe]

    def summary(self):
        with self.lock:
            return {'request_count': sum(self.counters.values()),
                    'counts': dict(self.counters), 'events': list(self.events)}


def handler_factory(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'XDM-MP00-Fixtures/1'
        sys_version = ''

        def log_message(self, format, *args):
            # BaseHTTPRequestHandler normally prints the full target including tokens.
            pass

        def do_HEAD(self):
            self.respond(send_body=False)

        def do_GET(self):
            self.respond(send_body=True)

        def send_blob(self, code, data, mime='application/octet-stream', extra=None,
                      send_body=True):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if send_body:
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def resolve_fixture(self, route):
            # Deny traversal, symlinks and arbitrary directory listing. Only /vod/ files.
            if not route.startswith('/vod/') or '\\' in route or '\x00' in route:
                return None
            path = (state.root / route.lstrip('/')).resolve()
            if not path.is_relative_to(state.root / 'vod') or not path.is_file():
                return None
            if path.stat().st_size > MAX_BODY:
                return None
            return path

        def respond(self, send_body):
            parsed = urlsplit(self.path)
            route = parsed.path
            query = parse_qs(parsed.query, keep_blank_values=True)
            count = state.record(self.command, route, query, self.headers)
            mime = {'m3u8': 'application/vnd.apple.mpegurl',
                    'mpd': 'application/dash+xml', 'mp4': 'video/mp4',
                    'm4s': 'video/iso.segment', 'ts': 'video/mp2t',
                    'vtt': 'text/vtt', 'json': 'application/json'}

            if route == '/health':
                return self.send_blob(200, b'{"status":"ok","schema":1}\n', 'application/json', send_body=send_body)
            if route == '/metrics':
                body = (json.dumps(state.summary(), sort_keys=True) + '\n').encode()
                return self.send_blob(200, body, 'application/json', send_body=send_body)
            if route == '/auth/refresh':
                # Fixed test credential; it must never appear in request telemetry.
                body = b'{"fixture_token":"mp00-token-v2","expires_after_requests":2}\n'
                return self.send_blob(200, body, 'application/json', send_body=send_body)
            if route == '/auth/echo':
                body = json.dumps({'authorization_present': bool(self.headers.get('Authorization')),
                                   'cookie_present': bool(self.headers.get('Cookie'))}).encode()
                return self.send_blob(200, body, 'application/json', send_body=send_body)
            if route == '/redirect/cross-origin':
                # localhost vs 127.0.0.1 intentionally changes HTTP origin.
                _, port = self.server.server_address
                self.send_response(302)
                self.send_header('Location', f'http://localhost:{port}/auth/echo')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if route == '/redirect/same-origin':
                self.send_response(302)
                self.send_header('Location', '/auth/echo')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if route == '/stall':
                time.sleep(min(3, max(0, int(query.get('seconds', ['1'])[0]))))
                return self.send_blob(200, b'eventual', 'text/plain', send_body=send_body)
            if route == '/slow':
                time.sleep(.15)
                return self.send_blob(200, b'slow', 'text/plain', send_body=send_body)
            if route == '/abort':
                self.close_connection = True
                return
            if route == '/status/404once' and count == 1:
                return self.send_blob(404, b'not found', 'text/plain', send_body=send_body)
            if route == '/status/429once' and count == 1:
                return self.send_blob(429, b'rate limited', 'text/plain', {'Retry-After': '1'}, send_body)
            if route in ('/status/404once', '/status/429once'):
                route = '/vod/progressive.mp4'
            if route == '/auth/segment.ts':
                authorized = (query.get('token') == ['mp00-token-v2'] or
                              self.headers.get('Cookie') == 'mp00_session=fixture')
                if not authorized:
                    return self.send_blob(403, b'forbidden', 'text/plain', send_body=send_body)
                route = '/vod/hls/v/180p/seg000.ts'
            if route == '/live/hls/playlist.m3u8':
                try:
                    tick = min(60, max(0, int(query.get('tick', ['2'])[0])))
                except ValueError:
                    return self.send_blob(400, b'invalid tick', 'text/plain', send_body=send_body)
                start = max(0, tick - 2)
                parts = ['#EXTM3U', '#EXT-X-VERSION:3', '#EXT-X-TARGETDURATION:2',
                         f'#EXT-X-MEDIA-SEQUENCE:{start}']
                for i in range(start, tick + 1):
                    parts.extend(['#EXTINF:2.000,', f'/live/hls/seg/{i}.ts'])
                if query.get('end') == ['1']:
                    parts.append('#EXT-X-ENDLIST')
                return self.send_blob(200, ('\n'.join(parts) + '\n').encode(),
                                      mime['m3u8'], send_body=send_body)
            if route.startswith('/live/hls/seg/'):
                match = re.fullmatch(r'/live/hls/seg/(\d{1,4})\.ts', route)
                if match:
                    route = f'/vod/hls/v/180p/seg{int(match.group(1)) % 3:03d}.ts'
            if route == '/live/dash/stream.mpd':
                file = self.resolve_fixture('/vod/dash/static.mpd')
                if file is None:
                    return self.send_blob(503, b'fixtures not generated', send_body=send_body)
                # Static segment references intentionally remain pinned to a fixed
                # timeline; the dynamic type is only a deterministic resolver probe.
                body = file.read_bytes().replace(b'type="static"',
                     b'type="dynamic" availabilityStartTime="2020-01-01T00:00:00Z" minimumUpdatePeriod="PT2S"')
                return self.send_blob(200, body, mime['mpd'], send_body=send_body)
            if route.startswith('/range/'):
                # Single known file, never a path supplied by the client.
                route = '/vod/progressive.mp4' if route == '/range/progressive.mp4' else '/invalid'
            path = self.resolve_fixture(route)
            if path is None:
                return self.send_blob(404, b'unknown fixture', 'text/plain', send_body=send_body)
            data = path.read_bytes()
            extra = {'Accept-Ranges': 'bytes', 'ETag': '"mp00-' + str(len(data)) + '"'}
            range_header = self.headers.get('Range')
            if range_header:
                m = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header.strip())
                if not m or (not m.group(1) and not m.group(2)):
                    return self.send_blob(416, b'', extra={'Content-Range': f'bytes */{len(data)}'}, send_body=send_body)
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else len(data) - 1
                else:
                    suffix = int(m.group(2))
                    start, end = max(0, len(data) - suffix), len(data) - 1
                if start >= len(data) or start > end:
                    return self.send_blob(416, b'', extra={'Content-Range': f'bytes */{len(data)}'}, send_body=send_body)
                end = min(end, len(data) - 1)
                extra['Content-Range'] = f'bytes {start}-{end}/{len(data)}'
                return self.send_blob(206, data[start:end+1],
                                      mime.get(path.suffix.lstrip('.'), 'application/octet-stream'),
                                      extra, send_body)
            return self.send_blob(200, data, mime.get(path.suffix.lstrip('.'), 'application/octet-stream'),
                                  extra, send_body)
    return Handler


def make_server(root, host='127.0.0.1', port=0):
    if host not in ('127.0.0.1', 'localhost', '::1'):
        # ADB reverse supports a bound loopback listener; broad bind is unsafe.
        raise ValueError('MP00 server is loopback-only; use adb reverse for ARM64 devices')
    state = State(root)
    server = ThreadingHTTPServer((host, port), handler_factory(state))
    server.daemon_threads = True
    return server, state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixtures', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server, _ = make_server(args.fixtures, args.host, args.port)
    print(f'MP00 listening on http://{args.host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
