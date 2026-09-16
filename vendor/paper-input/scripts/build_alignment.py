#!/usr/bin/env python3
"""Build the only permitted card timeline: Whisper full-JSON token-offset alignment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.paper_card_core import align_scene, load_job, verify_approval
except ModuleNotFoundError:
    from paper_card_core import align_scene, load_job, verify_approval


def main(args: argparse.Namespace) -> Path:
    job = load_job(args.job)
    verify_approval(job, args.approval)
    audio_path = Path(args.audio_manifest).expanduser().resolve()
    whisper_dir = Path(args.whisper_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"alignment output exists; create a new version: {output}")
    audio = json.loads(audio_path.read_text(encoding="utf-8"))
    tempo_ratio = float(audio.get("tempo_ratio", 1.0))
    if not 1.0 <= tempo_ratio <= 1.35:
        raise RuntimeError(f"audio manifest tempo_ratio is outside 1.00-1.35: {tempo_ratio}")
    token_time_scale = 1.0 / tempo_ratio
    audio_scenes = {scene["id"]: scene for scene in audio["scenes"]}
    rows = []
    for scene in job["scenes"]:
        scene_id = scene["id"]
        payload_path = whisper_dir / f"{scene_id}.json"
        if not payload_path.is_file():
            raise FileNotFoundError(payload_path)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        timing = audio_scenes.get(scene_id)
        if not timing:
            raise RuntimeError(f"audio manifest missing {scene_id}")
        rows.append(align_scene(
            scene_id=scene_id,
            lines=scene["lines"],
            whisper=payload,
            scene_start=float(timing["start"]),
            scene_end=float(timing["end"]),
            visual_lead=args.visual_lead,
            min_hold=args.min_hold,
            max_edit_ratio=args.max_edit_ratio,
            token_time_scale=token_time_scale,
        ))
    result = {
        "version": 2,
        "alignment_source": "whisper_full_json_token_offsets",
        "no_character_weight_fallback": True,
        "tempo_ratio": tempo_ratio,
        "whisper_token_time_scale": token_time_scale,
        "scenes": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--job", required=True)
parser.add_argument("--approval", required=True)
parser.add_argument("--audio-manifest", required=True)
parser.add_argument("--whisper-dir", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--visual-lead", type=float, default=0.08)
parser.add_argument("--min-hold", type=float, default=0.45)
parser.add_argument("--max-edit-ratio", type=float, default=0.28)
if __name__ == "__main__":
    result = main(parser.parse_args())
    print(json.dumps({"status": "TOKEN_OFFSET_ALIGNMENT_READY", "output": str(result)}, ensure_ascii=False, indent=2))
