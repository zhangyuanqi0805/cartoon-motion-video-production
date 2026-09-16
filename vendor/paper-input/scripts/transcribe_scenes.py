#!/usr/bin/env python3
"""Create Whisper full JSON token-offset transcripts for every approved raw scene."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from scripts.paper_card_core import assert_new_output, flatten_whisper_tokens, load_job, verify_approval
except ModuleNotFoundError:
    from paper_card_core import assert_new_output, flatten_whisper_tokens, load_job, verify_approval


def main(args: argparse.Namespace) -> Path:
    job = load_job(args.job)
    verify_approval(job, args.approval)
    model = Path(args.model).expanduser().resolve()
    if not model.is_file() or model.stat().st_size == 0:
        raise FileNotFoundError(model)
    output = assert_new_output(args.output)
    root = Path(job["_job_root"])
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    try:
        pcm = staging / "pcm"
        pcm.mkdir()
        for scene in job["scenes"]:
            source = Path(scene["audio"]).expanduser()
            if not source.is_absolute():
                source = root / source
            source = source.resolve()
            if not source.is_file() or source.stat().st_size == 0:
                raise FileNotFoundError(source)
            wav = pcm / f"{scene['id']}.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], check=True)
            prefix = staging / scene["id"]
            log = staging / f"{scene['id']}.log"
            with log.open("w", encoding="utf-8") as handle:
                subprocess.run(["whisper-cli", "-ng", "-m", str(model), "-f", str(wav), "-l", "zh",
                                "-otxt", "-ojf", "-of", str(prefix)], stdout=handle, stderr=subprocess.STDOUT, check=True)
            payload_path = staging / f"{scene['id']}.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            if not flatten_whisper_tokens(payload):
                raise RuntimeError(f"{scene['id']}: no token offsets in Whisper full JSON")
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--job", required=True)
parser.add_argument("--approval", required=True)
parser.add_argument("--model", required=True)
parser.add_argument("--output", required=True)
if __name__ == "__main__":
    result = main(parser.parse_args())
    print(json.dumps({"status": "WHISPER_TOKEN_OFFSETS_READY", "output": str(result)}, ensure_ascii=False, indent=2))
