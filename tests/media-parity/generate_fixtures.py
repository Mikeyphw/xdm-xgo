#!/usr/bin/env python3
"""Generate a small deterministic, non-DRM media corpus from local FFmpeg."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"FFmpeg failed ({result.returncode}): {result.stderr[-1600:]}")


def version(tool):
    line = subprocess.check_output([tool, '-version'], text=True).splitlines()[0]
    return line


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def generate(root, ffmpeg='ffmpeg', ffprobe='ffprobe', expected_version=None,
             expected_binary_sha256=None):
    expected_version = expected_version or os.environ.get('MP00_FFMPEG_VERSION')
    expected_binary_sha256 = expected_binary_sha256 or os.environ.get('MP00_FFMPEG_SHA256')
    root = Path(root).resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    actual_version = version(ffmpeg)
    match = re.search(r'^ffmpeg version ([^ ]+)', actual_version)
    if not match:
        raise ValueError('Unexpected FFmpeg version format')
    if expected_version and not match.group(1).startswith(expected_version):
        raise ValueError(f'FFmpeg pin mismatch: expected {expected_version}; got {actual_version}')
    exe = subprocess.check_output(['which', ffmpeg], text=True).strip() if '/' not in ffmpeg else ffmpeg
    digest = sha256(exe)
    if expected_binary_sha256 and digest.lower() != expected_binary_sha256.lower():
        raise ValueError('Pinned FFmpeg executable SHA-256 mismatch')
    version(ffprobe)
    with tempfile.TemporaryDirectory(prefix='mp00-generate-', dir=root.parent) as tmp:
        out = Path(tmp)
        vod = out / 'vod'
        vod.mkdir()
        progressive = vod / 'progressive.mp4'
        common = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-threads', '1']
        run(common + ['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=25',
                      '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                      '-t', '6', '-map', '0:v:0', '-map', '1:a:0',
                      '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                      '-g', '50', '-keyint_min', '50', '-sc_threshold', '0',
                      '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart',
                      '-map_metadata', '-1', '-metadata', 'creation_time=1970-01-01T00:00:00Z',
                      '-fflags', '+bitexact', '-flags', '+bitexact', str(progressive)])
        hls = vod / 'hls'
        (hls / 'v').mkdir(parents=True)
        (hls / 'a').mkdir()
        (hls / 'fmp4').mkdir()
        (hls / 'sub').mkdir()
        for label, scale in (('180p', '320:180'), ('360p', '640:360')):
            dest = hls / 'v' / label
            dest.mkdir()
            run(common + ['-i', str(progressive), '-map', '0:v:0', '-vf', f'scale={scale}',
                          '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                          '-g', '50', '-keyint_min', '50', '-sc_threshold', '0',
                          '-an', '-hls_time', '2', '-hls_list_size', '0',
                          '-hls_playlist_type', 'vod', '-hls_flags', 'independent_segments',
                          '-hls_base_url', f'{label}/',
                          '-hls_segment_filename', str(dest / 'seg%03d.ts'),
                          str(hls / 'v' / f'{label}.m3u8')])
        for lang, freq in (('en', 440), ('es', 660)):
            run(common + ['-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate=48000',
                          '-t', '6', '-vn', '-c:a', 'aac', '-b:a', '64k',
                          '-hls_time', '2', '-hls_list_size', '0',
                          '-hls_playlist_type', 'vod',
                          '-hls_segment_filename', str(hls / 'a' / f'{lang}%03d.ts'),
                          str(hls / 'a' / f'{lang}.m3u8')])
        (hls / 'master.m3u8').write_text(
            '#EXTM3U\n#EXT-X-VERSION:3\n'
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",LANGUAGE="en",DEFAULT=YES,AUTOSELECT=YES,URI="a/en.m3u8"\n'
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="Español",LANGUAGE="es",DEFAULT=NO,AUTOSELECT=YES,URI="a/es.m3u8"\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=350000,RESOLUTION=320x180,CODECS="avc1.42e01e,mp4a.40.2",AUDIO="aud"\n'
            'v/180p.m3u8\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,CODECS="avc1.42e01e,mp4a.40.2",AUDIO="aud"\n'
            'v/360p.m3u8\n', encoding='utf-8')
        (hls / 'sub' / 'en.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nFixture subtitle\n', encoding='utf-8')
        run(common + ['-i', str(progressive), '-map', '0:v:0', '-c:v', 'copy', '-an',
                      '-hls_segment_type', 'fmp4', '-hls_fmp4_init_filename', 'init.mp4',
                      '-hls_time', '2', '-hls_list_size', '0', '-hls_playlist_type', 'vod',
                      '-hls_segment_filename', str(hls / 'fmp4' / 'chunk%03d.m4s'),
                      str(hls / 'fmp4' / 'playlist.m3u8')])
        dash = vod / 'dash'
        dash.mkdir()
        run(common + ['-i', str(progressive), '-map', '0:v:0', '-map', '0:a:0',
                      '-c:v', 'copy', '-c:a', 'copy', '-f', 'dash',
                      '-seg_duration', '2', '-use_template', '1', '-use_timeline', '1',
                      '-adaptation_sets', 'id=0,streams=v id=1,streams=a',
                      '-init_seg_name', 'init-$RepresentationID$.m4s',
                      '-media_seg_name', 'chunk-$RepresentationID$-$Number%05d$.m4s',
                      str(dash / 'static.mpd')])
        # Publishing is last; never replace an existing corpus with a partial one.
        files = sorted(p for p in out.rglob('*') if p.is_file())
        inventory = {'schema_version': 1,
                     'ffmpeg_version': actual_version,
                     'ffmpeg_executable_sha256': digest,
                     'ffprobe_version': version(ffprobe),
                     'files': [{'path': str(p.relative_to(out)), 'size': p.stat().st_size,
                                'sha256': sha256(p)} for p in files]}
        (out / 'fixture_manifest.json').write_text(json.dumps(inventory, indent=2, sort_keys=True) + '\n')
        # Atomically expose the complete corpus with a rollback directory.
        import shutil
        backup = root.with_name(root.name + f'.mp00-old-{os.getpid()}')
        if backup.exists():
            raise FileExistsError('stale fixture rollback directory: refusing overwrite')
        had_old = root.exists()
        if had_old:
            if not root.is_dir():
                raise NotADirectoryError('fixture output must be a directory')
            root.rename(backup)
        try:
            out.rename(root)
        except BaseException:
            if had_old and backup.exists() and not root.exists():
                backup.rename(root)
            raise
        if had_old:
            shutil.rmtree(backup)
    return inventory


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--ffmpeg', default='ffmpeg')
    ap.add_argument('--ffprobe', default='ffprobe')
    ap.add_argument('--expected-version', default=os.environ.get('MP00_FFMPEG_VERSION'))
    ap.add_argument('--expected-binary-sha256', default=os.environ.get('MP00_FFMPEG_SHA256'))
    args = ap.parse_args()
    data = generate(args.out, args.ffmpeg, args.ffprobe, args.expected_version,
                    args.expected_binary_sha256)
    print(f"MP00_GENERATED {len(data['files'])} files; FFmpeg SHA256 {data['ffmpeg_executable_sha256']}")


if __name__ == '__main__':
    main()
