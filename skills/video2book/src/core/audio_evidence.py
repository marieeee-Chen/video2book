"""Validated audio caches. File existence is never a completion receipt."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from .local_media import TRANSCODE_TIMEOUT_SEC
from .proc import run_quiet


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def receipt_path(path):
    return Path(path).with_suffix(Path(path).suffix + '.receipt.json')


def temporary(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.stem + '-', suffix=path.suffix, dir=path.parent)
    import os
    os.close(fd)
    return Path(name)


def validate_audio(path, duration=None):
    """Probe duration AND decode once before promoting a generated artifact."""
    probe, decoder = shutil.which('ffprobe'), shutil.which('ffmpeg')
    if not probe or not decoder:
        raise ValueError('ffprobe and ffmpeg are required to validate audio')
    result = run_quiet([probe, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                        '-of', 'json', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=TRANSCODE_TIMEOUT_SEC)
    info = json.loads(result.stdout or '{}')
    seconds = float(info.get('format', {}).get('duration', 0))
    if result.returncode or not math.isfinite(seconds) or seconds <= 0 or not any(
            s.get('codec_type') == 'audio' for s in info.get('streams', [])):
        raise ValueError('Audio has no decodable stream/duration')
    if duration is not None:
        duration = float(duration)
        tolerance = max(0.5, min(2.0, duration * 0.005))
        if not math.isfinite(duration) or duration <= 0 or abs(seconds - duration) > tolerance:
            raise ValueError(f'Audio duration mismatch: expected {duration}, observed {seconds}')
    decoded = run_quiet([decoder, '-v', 'error', '-xerror', '-i', str(path), '-map', '0:a:0',
                          '-f', 'null', '-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, timeout=TRANSCODE_TIMEOUT_SEC)
    if decoded.returncode:
        raise ValueError('Audio decode failed: ' + (decoded.stderr or '')[:200])
    return seconds


def valid_cache(path, identity=None):
    try:
        record = json.loads(receipt_path(path).read_text(encoding='utf-8'))
        if record.get('schema_version') != 1 or record.get('validation') != 'decoded':
            return False
        if identity is not None and record.get('identity') != identity:
            return False
        if not math.isfinite(record['duration_sec']) or record['duration_sec'] <= 0:
            return False
        if sha256(path) != record['sha256']:
            return False
        # Missing disposable inputs do not falsify a validated artifact. Changed inputs do.
        return all(not Path(p).exists() or sha256(p) == sha
                   for p, sha in record.get('inputs', {}).items())
    except (OSError, ValueError, TypeError, KeyError):
        return False


def promote(temp, target, identity, *, inputs=(), duration=None):
    seconds = validate_audio(temp, duration)
    record = {'schema_version': 1, 'identity': identity, 'sha256': sha256(temp),
              'duration_sec': seconds, 'validation': 'decoded',
              'inputs': {str(Path(p).resolve()): sha256(p) for p in inputs}}
    staged = temporary(receipt_path(target))
    try:
        staged.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding='utf-8')
        # A crash between replacements yields a digest mismatch, never a cache hit.
        Path(temp).replace(target)
        staged.replace(receipt_path(target))
    finally:
        staged.unlink(missing_ok=True)
