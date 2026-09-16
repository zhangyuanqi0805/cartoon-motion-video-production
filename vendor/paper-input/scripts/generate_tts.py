#!/usr/bin/env python3
"""Generate every approved scene with the frozen Jianying 真人播客女 adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

try:
    from scripts.auto_pipeline import AutoConfig
    from scripts.paper_card_core import load_job, sha256_file, verify_approval
except ModuleNotFoundError:
    from auto_pipeline import AutoConfig
    from paper_card_core import load_job, sha256_file, verify_approval


class TtsError(RuntimeError):
    """The frozen official-voice adapter cannot safely continue."""


def scene_text(scene: dict[str, Any]) -> str:
    return "".join(str(line).strip() for line in scene.get("lines", []))


def partial_wav_path(wav: Path) -> Path:
    return wav.with_name(f"{wav.stem}.partial{wav.suffix}")


def log_proves_generated_text(log_text: str, text: str, mp3: Path) -> bool:
    return text in log_text and f"audio-output\t{mp3}" in log_text


def _atomic_scene_receipt(path: Path, *, text_sha256: str, mp3: Path) -> None:
    payload = {
        "status": "GENERATED",
        "text_sha256": text_sha256,
        "mp3": str(mp3),
        "mp3_sha256": sha256_file(mp3),
    }
    temporary = path.with_suffix(".json.partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def verify_tts_adapter(
    *, binary: Path, binary_sha256: str, dylib: Path, dylib_sha256: str
) -> dict[str, str]:
    binary = binary.expanduser().resolve()
    dylib = dylib.expanduser().resolve()
    if not binary.is_file() or binary.stat().st_size == 0:
        raise TtsError(f"Jianying TTS binary missing or empty: {binary}")
    if not os.access(binary, os.X_OK):
        raise TtsError(f"Jianying TTS binary is not executable: {binary}")
    if not dylib.is_file() or dylib.stat().st_size == 0:
        raise TtsError(f"Jianying creator dylib missing or empty: {dylib}")
    observed_binary = sha256_file(binary)
    observed_dylib = sha256_file(dylib)
    if observed_binary != binary_sha256:
        raise TtsError(
            f"Jianying TTS binary SHA256 mismatch: expected {binary_sha256}, got {observed_binary}"
        )
    if observed_dylib != dylib_sha256:
        raise TtsError(
            f"Jianying creator dylib SHA256 mismatch: expected {dylib_sha256}, got {observed_dylib}; "
            "the app likely changed and private offsets must be revalidated"
        )
    return {
        "status": "PASS",
        "binary": str(binary),
        "binary_sha256": observed_binary,
        "jianying_dylib": str(dylib),
        "jianying_dylib_sha256": observed_dylib,
    }


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


def _valid_audio(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0 and _probe_duration(path) > 0.10
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def generate(args: argparse.Namespace) -> Path:
    job = load_job(args.job)
    verify_approval(job, args.approval)
    config = AutoConfig.load(args.config)
    binary = Path(config.tts_binary).expanduser().resolve()
    dylib = Path(config.jianying_dylib).expanduser().resolve()
    adapter = verify_tts_adapter(
        binary=binary,
        binary_sha256=config.tts_binary_sha256,
        dylib=dylib,
        dylib_sha256=config.jianying_dylib_sha256,
    )
    root = Path(job["_job_root"])
    raw_mp3 = root / "audio" / "official_raw_v1"
    raw_wav = root / "audio" / "official_raw"
    logs = root / "logs" / "tts"
    raw_mp3.mkdir(parents=True, exist_ok=True)
    raw_wav.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_wav / "tts-manifest.json"
    complete_path = raw_wav / "TTS_COMPLETE"
    prior: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TtsError(f"existing TTS manifest is invalid; do not overwrite it: {manifest_path}") from exc
    prior_rows = {row.get("id"): row for row in prior.get("scenes", []) if isinstance(row, dict)}
    rows: list[dict[str, Any]] = []
    framework_dir = str(dylib.parent)
    environment = os.environ.copy()
    environment["DYLD_LIBRARY_PATH"] = framework_dir
    environment["DYLD_FRAMEWORK_PATH"] = framework_dir
    for scene in job["scenes"]:
        scene_id = scene["id"]
        text = scene_text(scene)
        text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        mp3 = raw_mp3 / f"{scene_id}.mp3"
        wav = raw_wav / f"{scene_id}.wav"
        scene_receipt = raw_mp3 / f"{scene_id}.json"
        log = logs / f"{scene_id}.log"
        prior_row = prior_rows.get(scene_id, {})
        receipt: dict[str, Any] = {}
        if scene_receipt.is_file():
            try:
                receipt = json.loads(scene_receipt.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise TtsError(f"invalid per-scene TTS receipt; do not overwrite it: {scene_receipt}") from exc
        mp3_reusable = (
            receipt.get("text_sha256") == text_sha256
            and receipt.get("mp3_sha256") == (sha256_file(mp3) if mp3.is_file() else None)
            and _valid_audio(mp3)
        )
        if not receipt and _valid_audio(mp3) and log.is_file():
            log_text = log.read_text(encoding="utf-8", errors="replace")
            if log_proves_generated_text(log_text, text, mp3):
                _atomic_scene_receipt(scene_receipt, text_sha256=text_sha256, mp3=mp3)
                mp3_reusable = True
        reusable = (
            prior_row.get("text_sha256") == text_sha256
            and prior_row.get("mp3_sha256") == (sha256_file(mp3) if mp3.is_file() else None)
            and prior_row.get("wav_sha256") == (sha256_file(wav) if wav.is_file() else None)
            and _valid_audio(mp3) and _valid_audio(wav)
        )
        if not reusable:
            if wav.exists():
                raise TtsError(
                    f"existing {scene_id} WAV is incomplete or belongs to different text; "
                    "do not overwrite it, use a fresh production directory"
                )
            if not mp3_reusable:
                if mp3.exists():
                    raise TtsError(
                        f"existing {scene_id} MP3 has no exact text receipt or matching generation log; "
                        "do not overwrite it, use a fresh production directory"
                    )
                try:
                    result = subprocess.run(
                        [str(binary), str(mp3)],
                        input=text,
                        text=True,
                        capture_output=True,
                        timeout=float(args.timeout),
                        env=environment,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise TtsError(f"{scene_id} Jianying TTS timed out after {args.timeout}s") from exc
                log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
                if result.returncode != 0 or not _valid_audio(mp3):
                    raise TtsError(f"{scene_id} Jianying TTS failed; inspect sanitized log: {log}")
                _atomic_scene_receipt(scene_receipt, text_sha256=text_sha256, mp3=mp3)
            partial = partial_wav_path(wav)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3),
                 "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", "-f", "wav", str(partial)],
                check=True,
            )
            if not _valid_audio(partial):
                partial.unlink(missing_ok=True)
                raise TtsError(f"{scene_id} ffmpeg conversion produced invalid WAV")
            os.replace(partial, wav)
        rows.append({
            "id": scene_id,
            "text_sha256": text_sha256,
            "characters": len(text),
            "mp3": str(mp3),
            "mp3_sha256": sha256_file(mp3),
            "wav": str(wav),
            "wav_sha256": sha256_file(wav),
            "duration_seconds": round(_probe_duration(wav), 3),
            "resumed": reusable,
        })
    manifest = {
        "status": "PASS",
        "voice": job["voice"],
        "adapter": adapter,
        "scenes": rows,
    }
    temporary_manifest = manifest_path.with_suffix(".json.partial")
    temporary_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)
    temporary_complete = complete_path.with_suffix(".partial")
    temporary_complete.write_text("PASS\n", encoding="utf-8")
    os.replace(temporary_complete, complete_path)
    return manifest_path


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--job", required=True)
parser.add_argument("--approval", required=True)
parser.add_argument("--config", required=True)
parser.add_argument("--timeout", type=float, default=180.0)
if __name__ == "__main__":
    result = generate(parser.parse_args())
    print(json.dumps({"status": "OFFICIAL_TTS_READY", "manifest": str(result)}, ensure_ascii=False, indent=2))
