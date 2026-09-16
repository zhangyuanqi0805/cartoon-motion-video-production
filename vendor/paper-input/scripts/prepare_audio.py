#!/usr/bin/env python3
"""Create a 44.1kHz stereo two-pass loudness-normalized master from approved scene audio."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    from scripts.paper_card_core import assert_new_output, load_job, sha256_file, verify_approval
except ModuleNotFoundError:
    from paper_card_core import assert_new_output, load_job, sha256_file, verify_approval


MIN_TEMPO_RATIO = 1.0
MAX_TEMPO_RATIO = 1.35
# Conservative starting point calibrated between the original benchmark and the
# boss-approved V3.3.  It is only a starting point: the mandatory 30-second
# reference parity gate may still reject it for a differently paced source TTS.
HIGH_FIDELITY_DEFAULT_TEMPO = 1.27


def resolve_tempo(job: dict, requested_tempo: float | None) -> float:
    if requested_tempo is None:
        tempo = (
            HIGH_FIDELITY_DEFAULT_TEMPO
            if job.get("production_profile") == "benchmark-high-fidelity"
            else 1.0
        )
    else:
        tempo = float(requested_tempo)
    if not MIN_TEMPO_RATIO <= tempo <= MAX_TEMPO_RATIO:
        raise ValueError(f"tempo must be within 1.00-1.35, got {tempo}")
    return tempo


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def probe_duration(path: Path) -> float:
    result = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)
    ], capture=True)
    return float(result.stdout.strip())


def parse_loudnorm(stderr: str) -> dict[str, str]:
    matches = re.findall(r"\{\s*\"input_i\".*?\}", stderr, flags=re.DOTALL)
    if not matches:
        raise RuntimeError("ffmpeg loudnorm analysis did not return JSON")
    return json.loads(matches[-1])


def measure_encoded_audio(path: Path) -> dict[str, float]:
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-filter_complex", "ebur128=peak=true", "-f", "null", "-",
    ], text=True, capture_output=True, check=True)
    integrated = re.findall(r"I:\s*(-?[0-9.]+)\s*LUFS", result.stderr)
    lra = re.findall(r"LRA:\s*([0-9.]+)\s*LU", result.stderr)
    peak = re.findall(r"Peak:\s*(-?[0-9.]+)\s*dBFS", result.stderr)
    if not integrated or not lra or not peak:
        raise RuntimeError("ffmpeg ebur128 analysis did not return a complete summary")
    return {
        "integrated_lufs": float(integrated[-1]),
        "lra_lu": float(lra[-1]),
        "true_peak_dbfs": float(peak[-1]),
    }


def required_attenuation_db(
    measured_true_peak: float,
    ceiling: float,
    safety_margin: float = 0.1,
) -> float:
    if measured_true_peak <= ceiling:
        return 0.0
    return round(measured_true_peak - ceiling + safety_margin, 6)


def concat_line(path: Path) -> str:
    return "file '" + str(path).replace("'", "'\\''") + "'"


def main(args: argparse.Namespace) -> Path:
    job = load_job(args.job)
    verify_approval(job, args.approval)
    output = assert_new_output(args.output)
    requested_tempo = getattr(args, "tempo", None)
    tempo = resolve_tempo(job, requested_tempo)
    root = Path(job["_job_root"])
    sources: list[Path] = []
    for scene in job["scenes"]:
        source = Path(scene["audio"]).expanduser()
        if not source.is_absolute():
            source = root / source
        source = source.resolve()
        if not source.is_file() or source.stat().st_size == 0:
            raise FileNotFoundError(f"missing approved official scene audio: {source}")
        sources.append(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    try:
        work = staging / "work"
        work.mkdir()
        normalized: list[Path] = []
        durations: list[float] = []
        for scene, source in zip(job["scenes"], sources):
            target = work / f"{scene['id']}.wav"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
            if tempo != 1.0:
                command.extend(["-af", f"atempo={tempo:.6f}"])
            command.extend(["-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(target)])
            run(command)
            normalized.append(target)
            durations.append(probe_duration(target))
        gap = work / "gap.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "anullsrc=r=44100:cl=stereo", "-t", str(args.gap), "-c:a", "pcm_s16le", str(gap)])
        concat = work / "concat.txt"
        lines: list[str] = []
        for index, source in enumerate(normalized):
            lines.append(concat_line(source))
            if index < len(normalized) - 1:
                lines.append(concat_line(gap))
        concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
        raw_master = work / "raw-master.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(raw_master)])
        master = staging / "voiceover_master.m4a"
        effective_true_peak = float(args.true_peak)
        loudnorm_attempts = []
        for attempt in range(1, 4):
            first_filter = (
                f"loudnorm=I={args.lufs}:LRA={args.lra}:TP={effective_true_peak}:print_format=json"
            )
            first = subprocess.run([
                "ffmpeg", "-hide_banner", "-nostats", "-i", str(raw_master), "-af", first_filter,
                "-f", "null", "-",
            ], text=True, capture_output=True, check=True)
            measured = parse_loudnorm(first.stderr)
            second_filter = (
                f"loudnorm=I={args.lufs}:LRA={args.lra}:TP={effective_true_peak}:"
                f"measured_I={measured['input_i']}:measured_LRA={measured['input_lra']}:"
                f"measured_TP={measured['input_tp']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}:linear=true:print_format=summary"
            )
            run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw_master),
                "-af", second_filter, "-ar", "44100", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(master),
            ])
            final_audio_metrics = measure_encoded_audio(master)
            correction = required_attenuation_db(
                final_audio_metrics["true_peak_dbfs"],
                float(args.true_peak),
            )
            loudnorm_attempts.append({
                "attempt": attempt,
                "effective_true_peak_target_dbfs": round(effective_true_peak, 3),
                "first_pass": measured,
                "encoded_metrics": final_audio_metrics,
                "next_attenuation_db": correction,
            })
            if correction == 0.0:
                break
            effective_true_peak -= correction
        else:
            raise RuntimeError(
                f"encoded AAC true peak remains above {args.true_peak} dBFS after 3 attempts"
            )
        cursor = 0.0
        scene_rows = []
        for index, (scene, source, duration) in enumerate(zip(job["scenes"], sources, durations)):
            start = cursor
            speech_end = start + duration
            end = speech_end + (args.gap if index < len(sources) - 1 else 0.0)
            scene_rows.append({
                "id": scene["id"], "start": round(start, 3), "speech_end": round(speech_end, 3),
                "end": round(end, 3), "source": str(source), "source_sha256": sha256_file(source),
            })
            cursor = end
        manifest = {
            "version": 2,
            "audio_contract": "V10-derived 44.1kHz stereo two-pass loudnorm with encoded-AAC peak verification",
            "tempo_ratio": tempo,
            "tempo_source": "explicit" if requested_tempo is not None else "production_profile_default",
            "tempo_method": "ffmpeg_atempo_constant_no_pitch_shift",
            "voice_label": job["voice"]["label"],
            "sample_rate": 44100,
            "channels": 2,
            "gap_seconds": args.gap,
            "target_lufs": args.lufs,
            "target_lra": args.lra,
            "true_peak_ceiling_dbfs": args.true_peak,
            "effective_true_peak_target_dbfs": round(effective_true_peak, 3),
            "duration": round(probe_duration(master), 3),
            "master_sha256": sha256_file(master),
            "loudnorm_first_pass": measured,
            "loudnorm_attempts": loudnorm_attempts,
            "final_audio_metrics": final_audio_metrics,
            "scenes": scene_rows,
        }
        (staging / "audio-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--job", required=True)
parser.add_argument("--approval", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--gap", type=float, default=0.24)
parser.add_argument("--lufs", type=float, default=-11.2)
parser.add_argument("--lra", type=float, default=2.5)
parser.add_argument("--true-peak", type=float, default=-1.3)
parser.add_argument("--tempo", type=float, default=None)
if __name__ == "__main__":
    result = main(parser.parse_args())
    print(json.dumps({"status": "AUDIO_MASTER_READY_NOT_RENDERED", "output": str(result)}, ensure_ascii=False, indent=2))
