#!/usr/bin/env python3
"""MP08B3 hosted real-media, non-DRM FFmpeg/FFprobe acceptance.

This is a native Linux codec/fixture acceptance only, NOT Android runtime,
MediaStore, Go MP08Host or physical ARM64 qualification. No network required.
"""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, tempfile
from pathlib import Path


def refuse(message: str):
    raise RuntimeError('MP08B3_HOST_REFUSED: ' + message)


def run(argv, timeout=100):
    p = subprocess.run([str(x) for x in argv], text=True, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        refuse('real FFmpeg/FFprobe command failed, stderr withheld')
    return p.stdout


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()


def probe(ffprobe, path):
    return json.loads(run([ffprobe, '-v', 'error', '-show_format', '-show_streams',
                           '-of', 'json', str(path)]))


def verify(ffmpeg, ffprobe, path, audio: bool):
    if not path.is_file() or path.stat().st_size < 1024:
        refuse('no verified local output bytes')
    report = probe(ffprobe, path)
    fmt = report.get('format', {})
    duration = float(fmt.get('duration') or 0)
    if not 0.80 <= duration <= 2.00:
        refuse('unexpected media duration')
    streams = report.get('streams', [])
    if len([x for x in streams if x.get('codec_type') == 'video']) != 1:
        refuse('required video stream absent')
    if audio and len([x for x in streams if x.get('codec_type') == 'audio']) != 1:
        refuse('required audio stream absent')
    run([ffmpeg, '-nostdin', '-hide_banner', '-v', 'error', '-xerror',
         '-i', str(path), '-f', 'null', '-'], timeout=60)
    return {'bytes': path.stat().st_size, 'sha256': sha256(path),
            'duration_ms': int(duration * 1000),
            'streams': [x.get('codec_type') for x in streams]}


def acceptance(ffmpeg, ffprobe, evidence):
    if not run([ffmpeg, '-version']).startswith('ffmpeg version '):
        refuse('FFmpeg tool identity invalid')
    if not run([ffprobe, '-version']).startswith('ffprobe version '):
        refuse('FFprobe tool identity invalid')
    with tempfile.TemporaryDirectory(prefix='mp08b3-real-',dir=os.getenv('RUNNER_TEMP') or None) as td:
        root = Path(td)
        video, audio, merged = [root / name for name in ('video.mp4','audio.m4a','final.mp4')]
        # Two separate stream sources, with no DRM and no remote URLs.
        run([ffmpeg, '-nostdin', '-hide_banner', '-v', 'error', '-y',
             '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10', '-t', '1',
             '-an', '-c:v', 'mpeg4', '-q:v', '5', str(video)])
        run([ffmpeg, '-nostdin', '-hide_banner', '-v', 'error', '-y',
             '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1',
             '-vn', '-c:a', 'aac', '-b:a', '64k', str(audio)])
        if not video.is_file() or not audio.is_file():
            refuse('source fixtures missing')
        run([ffmpeg, '-nostdin', '-hide_banner', '-v', 'error', '-y',
             '-i', str(video), '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0',
             '-c', 'copy', '-movflags', '+faststart', str(merged)])
        verified = verify(ffmpeg, ffprobe, merged, audio=True)
        # A zero exit and an MP4 suffix are not evidence. Negative fixture:
        # truncate the last third and insist on a failed decode/probe/identity.
        corrupt = root/'truncated.mp4'
        with merged.open('rb') as source, corrupt.open('wb') as sink:
            sink.write(source.read()[:max(1, merged.stat().st_size // 3)])
        if sha256(corrupt) == verified['sha256']:
            refuse('corrupt fixture kept original digest')
        try:
            verify(ffmpeg, ffprobe, corrupt, audio=True)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        else:
            refuse('corrupt media unexpectedly qualified')
        # Removing the entire audio track must never satisfy required audio.
        try:
            verify(ffmpeg, ffprobe, video, audio=True)
        except RuntimeError:
            pass
        else:
            refuse('silent video unexpectedly qualified')
        receipt = {'schema': 1, 'type': 'host_linux_real_media_only',
                   'android_qualified': False, 'device_emulator_qualified': False,
                   'physical_arm64_qualified': False, 'publication_qualified': False,
                   'passed': True, 'tests': ['mux_real_streams', 'full_decode',
                     'truncation_rejected', 'silent_video_rejected'], 'output': verified}
        if evidence:
            target = Path(evidence)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(receipt, sort_keys=True, indent=2)+'\n')
        print('MP08B3_LINUX_REAL_MEDIA_ACCEPTANCE_PASS')
        return receipt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ffmpeg', default='ffmpeg')
    ap.add_argument('--ffprobe', default='ffprobe')
    ap.add_argument('--evidence')
    args=ap.parse_args()
    acceptance(args.ffmpeg,args.ffprobe,args.evidence)


if __name__ == '__main__':
    main()
