#!/usr/bin/env python3
"""Check actual decode, stream selection, duration and bounded A/V skew."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def command_json(argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise RuntimeError('ffprobe failed; output withheld to avoid leaking source URLs')
    return json.loads(p.stdout)


def fingerprint(ffmpeg, media_path, stream):
    # Decoded fingerprints are comparative evidence, not a promise of bitwise
    # FFmpeg output stability across decoders / platforms.
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-i', str(media_path),
           '-map', f'0:{stream}', '-f', 'framemd5', '-']
    p = subprocess.run(cmd, capture_output=True, timeout=45)
    if p.returncode:
        raise RuntimeError('decoded frame fingerprint failed')
    return hashlib.sha256(p.stdout).hexdigest()


def sha256_file(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def verify(path, expect_video=True, expect_audio=True, min_duration=0.1,
           max_av_skew=0.5, ffprobe='ffprobe', ffmpeg='ffmpeg'):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size < 100:
        raise ValueError('empty or incomplete media file')
    probe = command_json([ffprobe, '-v', 'error', '-show_entries',
                          'format=duration:stream=index,codec_name,codec_type,duration,width,height',
                          '-of', 'json', str(path)])
    streams = probe.get('streams', [])
    videos = [s for s in streams if s.get('codec_type') == 'video']
    audios = [s for s in streams if s.get('codec_type') == 'audio']
    if expect_video and not videos:
        raise ValueError('required video stream absent')
    if expect_audio and not audios:
        raise ValueError('required audio stream absent')
    duration = float(probe.get('format', {}).get('duration') or 0)
    if duration < min_duration:
        raise ValueError('media duration shorter than acceptance bound')
    if videos and audios:
        vduration = float(videos[0].get('duration') or duration)
        aduration = float(audios[0].get('duration') or duration)
        if abs(vduration - aduration) > max_av_skew:
            raise ValueError('audio/video stream durations diverge')
    # Decode all streams; successful metadata-only probes are insufficient.
    p = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-xerror', '-i', str(path), '-f', 'null', '-'],
                       capture_output=True, timeout=45)
    if p.returncode:
        raise ValueError('full media decode failed')
    compact = [{'index': s['index'], 'type': s['codec_type'], 'codec': s.get('codec_name'),
                'duration': s.get('duration'), 'width': s.get('width'), 'height': s.get('height')}
               for s in streams if s.get('codec_type') in ('video', 'audio', 'subtitle')]
    return {'verified': True, 'duration_s': duration, 'streams': compact,
            'container_bytes': path.stat().st_size,
            'sha256': sha256_file(path),
            'decoded_fingerprints': {
                s['codec_type']: fingerprint(ffmpeg, path, s['index'])
                for s in (videos[:1] + audios[:1])}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--video-only', action='store_true')
    ap.add_argument('--audio-only', action='store_true')
    ap.add_argument('--min-duration', type=float, default=0.1)
    ap.add_argument('--output', default='-')
    a = ap.parse_args()
    if a.video_only and a.audio_only:
        ap.error('choose one stream contract')
    try:
        value = verify(a.path, not a.audio_only, not a.video_only, a.min_duration)
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f'MP00_VERIFY_FAIL: {type(exc).__name__}') from exc
    rendered = json.dumps(value, indent=2, sort_keys=True) + '\n'
    if a.output == '-':
        print(rendered, end='')
    else:
        Path(a.output).write_text(rendered)
    print('MP00_VERIFY_PASS', flush=True) if a.output != '-' else None


if __name__ == '__main__':
    main()
