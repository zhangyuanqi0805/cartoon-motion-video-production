#!/usr/bin/env python3
"""Restore licensed local fonts and report renderer/TTS readiness separately."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def restore_fonts(roots):
    from fontTools.ttLib import TTCollection, TTFont
    rows = json.loads((ROOT / 'references/local-fonts.json').read_text())
    results = []
    for row in rows:
        target = ROOT / 'assets/v55' / row['file']
        if target.exists():
            if digest(target) != row['sha256']:
                raise ValueError(f'Existing font differs; preserve it and inspect: {target}')
            results.append({'font': row['file'], 'status': 'HASH_MATCH'})
            continue
        matched = False
        for root in roots:
            if not root.is_dir():
                continue
            for source in root.rglob(row['collection']):
                collection = TTCollection(source, lazy=True)
                indices = [i for i, font in enumerate(collection.fonts)
                           if font['name'].getDebugName(1) == row['family']
                           and font['name'].getDebugName(2) == row['style']]
                collection.close()
                for index in indices:
                    # Reopen lazily: decoding/recompiling the name table changes bytes.
                    font = TTFont(source, fontNumber=index, lazy=True, recalcTimestamp=False)
                    font['head'].created = row['created']
                    font['head'].modified = row['modified']
                    buf = io.BytesIO()
                    font.save(buf)
                    font.close()
                    data = buf.getvalue()
                    if hashlib.sha256(data).hexdigest() != row['sha256']:
                        continue
                    with target.open('xb') as handle:
                        handle.write(data)
                    results.append({'font': row['file'], 'status': 'RESTORED_HASH_MATCH'})
                    matched = True
                    break
                if matched:
                    break
            if matched:
                break
        if not matched:
            results.append({'font': row['file'], 'status': 'MISSING_MATCHING_LOCAL_FONT',
                            'family': row['family'], 'style': row['style']})
    return results


def inspect(config=None):
    import make_video
    import paper_input
    missing = []
    try:
        make_video.bundle_lock()
        template = True
    except (ValueError, OSError) as exc:
        template = False
        missing.append(str(exc))
    try:
        paper_input._paper_contract_helpers()
        from auto_pipeline import build_job_bundle, AutoConfig
        modules = True
    except Exception as exc:
        modules = False
        missing.append(f'INPUT_MODULES: {exc}')
    commands = {name: bool(shutil.which(name))
                for name in ('node', 'npx', 'ffmpeg', 'ffprobe', 'magick')}
    hyperframes = False
    if commands['npx']:
        try:
            proc = subprocess.run(['npx', '--no-install', '--yes', 'hyperframes@0.8.35', '--version'],
                                  capture_output=True, text=True, timeout=30)
            hyperframes = proc.returncode == 0 and proc.stdout.strip().splitlines()[-1] == '0.8.35'
        except (subprocess.TimeoutExpired, IndexError):
            pass
    if not all(commands.values()):
        missing.extend(name for name, present in commands.items() if not present)
    if not hyperframes:
        missing.append('HYPERFRAMES_0.8.35_CACHE')
    config = Path(config) if config else paper_input.PAPER_SKILL_ROOT / 'references/auto-config.local.json'
    tts = False
    whisper = False
    if modules and config.is_file():
        try:
            from generate_tts import verify_tts_adapter
            cfg = AutoConfig.load(config)
            verify_tts_adapter(binary=Path(cfg.tts_binary), binary_sha256=cfg.tts_binary_sha256,
                               dylib=Path(cfg.jianying_dylib), dylib_sha256=cfg.jianying_dylib_sha256)
            tts = True
            whisper = bool(shutil.which('whisper-cli')) and Path(cfg.whisper_model).is_file()
            if not whisper:
                missing.append('WHISPER_CLI_OR_MODEL')
        except Exception as exc:
            missing.append(f'LOCAL_INPUT_CONFIG: {exc}')
    else:
        missing.append('LOCAL_TTS_CONFIG_AND_VALIDATED_ADAPTER_REQUIRED')
    renderer = template and modules and all(commands.values()) and hyperframes
    return {'status': 'LOCAL_DEPENDENCIES_READY' if renderer and tts and whisper else 'SETUP_REQUIRED',
            'template_hashes_match': template, 'compatible_input_modules': modules,
            'input_modules_path': str(paper_input.PAPER_SKILL_ROOT),
            'renderer_ready': renderer, 'tts_adapter_verified': tts, 'whisper_ready': whisper,
            'new_manuscript_dependencies_ready': renderer and tts and whisper,
            'missing': missing, 'image_generation_tool': 'Agent must verify availability',
            'full_production_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-fonts', action='store_true')
    parser.add_argument('--font-root', type=Path, action='append')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    if args.restore_fonts:
        roots = args.font_root or [Path('/System/Library/Fonts'), Path('/Library/Fonts'),
                                   Path.home() / 'Library/Fonts']
        roots += list(Path('/System/Library/AssetsV2').glob('*Font*'))
        rows = restore_fonts(roots)
        print(json.dumps({'fonts': rows}, ensure_ascii=False, indent=2))
        if any(row['status'] == 'MISSING_MATCHING_LOCAL_FONT' for row in rows):
            return 2
    result = inspect(args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['new_manuscript_dependencies_ready'] else 2


if __name__ == '__main__':
    sys.exit(main())
