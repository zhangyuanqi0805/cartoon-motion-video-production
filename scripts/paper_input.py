"""Import the paper-card content/audio contract for the cartoon renderer.

This module is deliberately a data boundary.  It never renders a paper-card
project and it never copies the paper renderer's canvas, motion, icon, or
layout fields into the cartoon input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


SKILL_ROOT = Path(__file__).resolve().parent.parent
# Distribution carries the exact compatible input helpers. The public paper-card
# repository uses a different interface and is not a drop-in dependency.
_paper_default = SKILL_ROOT / "vendor/paper-input"
PAPER_SKILL_ROOT = Path(os.environ.get("CARTOON_PAPER_SKILL", str(_paper_default))).expanduser().resolve()
PAPER_SKILL_SCRIPTS = PAPER_SKILL_ROOT / "scripts"


class PaperInputError(RuntimeError):
    """An input contract cannot be proved from the supplied production."""


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise PaperInputError(f"required JSON file is missing or empty: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PaperInputError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PaperInputError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        raise PaperInputError(f"required file is missing or empty: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(production: Path, value: str | Path, *fallbacks: str) -> Path:
    """Prefer a production-relative asset over stale absolute worktree paths."""
    raw = Path(value).expanduser()
    candidates: list[Path] = []
    for fallback in fallbacks:
        candidates.append(production / fallback)
    if not raw.is_absolute():
        candidates.append(production / raw)
    else:
        candidates.append(raw)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise PaperInputError(
        "asset path is unavailable; checked production-relative candidates and "
        f"the recorded path: {value}"
    )


def _ref(production: Path, path: Path) -> str:
    """Return a portable POSIX path relative to the production bundle."""
    try:
        return Path(os.path.relpath(path.resolve(), production.resolve())).as_posix()
    except ValueError as exc:
        raise PaperInputError(f"asset is not portable from production bundle: {path}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PaperInputError(message)


def _paper_contract_helpers() -> tuple[Any, Any, Any]:
    if str(PAPER_SKILL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(PAPER_SKILL_SCRIPTS))
    try:
        from paper_card_core import load_job, verify_approval
        from build_hyperframes_project import make_timeline
    except Exception as exc:  # pragma: no cover - environment/installation failure
        raise PaperInputError(f"paper input helpers are unavailable: {exc}") from exc
    return load_job, verify_approval, make_timeline


def _verified_jobs(production: Path, approval_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the high-fidelity and original job contracts through paper helpers."""
    load_job, verify_approval, _ = _paper_contract_helpers()
    high_path = production / "job-high-fidelity.json"
    original_path = production / "job.json"
    verified = []
    # Resolve copied-bundle paths, then run the complete upstream contract.
    # A contract failure must never become a "stale path" validation bypass.
    with tempfile.TemporaryDirectory(prefix="cartoon-input-check-") as temp:
        for path in (high_path, original_path):
            job = _json(path)
            manuscript = _portable_path(production, job.get("manuscript", ""), "manuscript_approved.txt")
            job["manuscript"] = str(manuscript)
            for scene in job.get("scenes", []):
                scene_id = str(scene.get("id", ""))
                scene["audio"] = str(_portable_path(
                    production, scene.get("audio", ""), f"audio/official_raw/{scene_id}.wav"))
            portable = Path(temp) / path.name
            portable.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            checked = load_job(portable)
            verify_approval(checked, approval_path)
            checked["_job_path"] = str(path)
            checked["_job_root"] = str(production)
            verified.append(checked)
    return verified[0], verified[1]


def _verify_tts(
    production: Path,
    original_job: Mapping[str, Any],
    high_job: Mapping[str, Any],
    audio_manifest: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    tts_path = production / "audio/official_raw/tts-manifest.json"
    tts = _json(tts_path)
    expected_voice = high_job.get("voice", {})
    voice = tts.get("voice")
    _require(isinstance(voice, dict), "TTS manifest voice is missing")
    for key in ("provider", "label", "resource_id", "speaker"):
        if key == "provider":
            expected = "Jianying official text reading"
        elif key == "label":
            expected = "真人播客女"
        else:
            expected = expected_voice.get("resource_id" if key == "resource_id" else "speaker")
        _require(voice.get(key) == expected, f"TTS voice.{key} does not match the approved job")

    source_scenes = {str(scene["id"]): scene for scene in original_job.get("scenes", [])}
    tts_rows = {str(row.get("id")): row for row in tts.get("scenes", []) if isinstance(row, dict)}
    _require(source_scenes and set(tts_rows) == set(source_scenes), "TTS scenes do not match job.json")
    audio_rows = {
        str(row.get("id")): row
        for row in audio_manifest.get("scenes", [])
        if isinstance(row, dict)
    }
    _require(set(audio_rows) == set(source_scenes), "audio manifest scenes do not match job.json")
    for scene_id, scene in source_scenes.items():
        row = tts_rows[scene_id]
        text = "".join(str(value).strip() for value in scene.get("lines", []))
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _require(row.get("text_sha256") == text_sha, f"TTS text SHA mismatch: {scene_id}")
        wav = _portable_path(production, row.get("wav", ""), f"audio/official_raw/{scene_id}.wav")
        wav_sha = _sha256(wav)
        _require(row.get("wav_sha256") == wav_sha, f"TTS WAV SHA mismatch: {scene_id}")
        audio_row = audio_rows[scene_id]
        _require(audio_row.get("source_sha256") == wav_sha, f"audio manifest source SHA mismatch: {scene_id}")
        _require(float(audio_row.get("end", 0)) >= float(audio_row.get("start", 0)),
                 f"audio scene has invalid interval: {scene_id}")
    master = _portable_path(
        production,
        audio_manifest.get("master", ""),
        "audio-high-fidelity-v1/voiceover_master.m4a",
    )
    _require(audio_manifest.get("master_sha256") == _sha256(master), "master audio SHA mismatch")
    return master, tts


def _visuals(
    visual_plan: Path,
    *,
    default_lines: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    plan = _json(visual_plan)
    # A new manuscript gets deterministic visual variation by default. Keep
    # fixed-v55 as an explicit opt-in for reference reproduction/regression.
    render_mode = plan.get("render_mode", "diverse-v55")
    _require(render_mode in {"fixed-v55", "diverse-v55"},
             "visual plan render_mode must be fixed-v55 or diverse-v55")
    raw_visuals = plan.get("visuals", [])
    _require(isinstance(raw_visuals, list), "visual plan visuals must be a list")
    visuals: list[dict[str, Any]] = []
    for index, item in enumerate(raw_visuals, start=1):
        _require(isinstance(item, dict), f"visual plan item {index} must be an object")
        for key in ("preset", "start", "end", "meaning"):
            _require(key in item, f"visual plan item {index} missing {key}")
        start, end = float(item["start"]), float(item["end"])
        _require(0 <= start < end, f"visual plan item {index} has invalid interval")
        visuals.append({key: item[key] for key in ("preset", "start", "end", "meaning") if key in item})
        for key in ("asset_family", "variant_id"):
            if key in item:
                visuals[-1][key] = item[key]
    opening = plan.get("opening")
    if opening is None:
        opening = {
            "duration": 4.86,
            "lines": list(default_lines or ["", "", ""]),
            "tag": "短标注",
        }
    _require(isinstance(opening, dict), "visual plan opening must be an object")
    _require(set(("duration", "lines", "tag")) <= set(opening), "visual plan opening requires duration/lines/tag")
    lines = opening["lines"]
    _require(isinstance(lines, list) and len(lines) == 3 and all(isinstance(line, str) for line in lines),
             "visual plan opening.lines must contain exactly three strings")
    _require(float(opening["duration"]) > 0 and isinstance(opening["tag"], str),
             "visual plan opening has invalid duration or tag")
    opening_result = {"duration": float(opening["duration"]), "lines": list(lines), "tag": opening["tag"]}
    for key in ("asset_family", "variant_id"):
        if key in opening:
            opening_result[key] = opening[key]
    return visuals, opening_result, render_mode


def import_production(production: Path, visual_plan: Path) -> dict[str, Any]:
    """Return a V2 cartoon input from a verified paper production bundle."""
    production = Path(production).expanduser().resolve()
    visual_plan = Path(visual_plan).expanduser().resolve()
    _require(production.is_dir(), f"production directory not found: {production}")
    _require(visual_plan.is_file(), f"visual plan not found: {visual_plan}")
    approval_path = production / "approval.json"
    high_job, original_job = _verified_jobs(production, approval_path)
    manuscript = _portable_path(production, high_job["manuscript"], "manuscript_approved.txt")
    alignment_path = production / "alignment-high-fidelity-v1.json"
    alignment = _json(alignment_path)
    _require(alignment.get("alignment_source") == "whisper_full_json_token_offsets",
             "alignment must come from Whisper full JSON token offsets")
    _require(alignment.get("no_character_weight_fallback") is True,
             "alignment character-weight fallback is forbidden")
    audio_manifest_path = production / "audio-high-fidelity-v1/audio-manifest.json"
    audio_manifest = _json(audio_manifest_path)
    master, tts_manifest = _verify_tts(production, original_job, high_job, audio_manifest)

    _, _, make_timeline = _paper_contract_helpers()
    # make_timeline is a pure in-memory extractor here.  Discard its paper
    # motion/icon fields immediately and retain only caption content/timing.
    timeline = make_timeline(high_job, alignment, audio_manifest, max_duration=None)
    captions = [
        {key: card[key] for key in ("text", "en", "start", "end")}
        for card in (
            {"text": card["zh"], "en": card["en"], "start": card["start"], "end": card["end"]}
            for card in timeline.get("cards", [])
        )
    ]
    header = high_job.get("header")
    fallback_lines = list(header) if isinstance(header, list) and len(header) == 3 else None
    visuals, opening, render_mode = _visuals(visual_plan, default_lines=fallback_lines)
    for index, visual in enumerate(visuals, start=1):
        _require(float(visual["end"]) <= float(timeline["duration"]) + 1e-6,
                 f"visual plan item {index} extends beyond narration duration")
    manuscript_sha = _sha256(manuscript)

    def record(path: Path) -> dict[str, str]:
        return {"path": _ref(production, path), "sha256": _sha256(path)}

    job_path = production / "job-high-fidelity.json"
    result = {
        "schema_version": 2,
        "render_mode": render_mode,
        "duration": float(timeline["duration"]),
        "title": high_job.get("title"),
        "manuscript": {"path": _ref(production, manuscript), "sha256": manuscript_sha},
        "narration": {
            "path": _ref(production, master),
            "sha256": _sha256(master),
            "source_sha256": manuscript_sha,
            "provider": "Jianying official text reading",
            "voice_id": "zh_female_mizai_saturn_bigtts",
        },
        "alignment": {
            "path": _ref(production, alignment_path),
            "sha256": _sha256(alignment_path),
            "format": "paper-card-token-offsets",
        },
        "captions": captions,
        "visuals": visuals,
        "opening": opening,
        "provenance": {
            "manuscript": record(manuscript),
            "approval": record(approval_path),
            "tts_manifest": record(production / "audio/official_raw/tts-manifest.json"),
            "audio_manifest": record(audio_manifest_path),
            "job": record(job_path),
            "source_markdown_sha256": _json(production / "provenance.json").get("source_markdown_sha256"),
            "tts_voice": copy.deepcopy(tts_manifest.get("voice")),
        },
    }
    return result


def validate_imported_job(job: Mapping[str, Any]) -> None:
    """Re-derive captions and audio provenance before accepting a new build."""
    provenance = job.get("provenance", {})
    required = {"job", "approval", "audio_manifest", "tts_manifest"}
    _require(required <= set(provenance), "PAPER_PROVENANCE_REQUIRED: import the verified production bundle")
    production = Path(provenance["job"]["path"]).resolve().parent
    high, original = _verified_jobs(production, Path(provenance["approval"]["path"]))
    audio_manifest = _json(Path(provenance["audio_manifest"]["path"]))
    master, _ = _verify_tts(production, original, high, audio_manifest)
    _require(_sha256(master) == job["narration"]["sha256"], "AUDIO_SOURCE_MISMATCH: imported master")
    _require(high["_manuscript_sha256"] == job["manuscript"]["sha256"], "MANUSCRIPT_MISMATCH: approved bundle")
    alignment = _json(Path(job["alignment"]["path"]))
    _, _, make_timeline = _paper_contract_helpers()
    expected = make_timeline(high, alignment, audio_manifest, max_duration=None)
    _require(abs(float(expected["duration"]) - float(job["duration"])) < .002, "DURATION_MISMATCH: imported audio")
    _require(len(expected["cards"]) == len(job["captions"]), "CAPTION_ALIGNMENT_MISMATCH: count")
    for wanted, actual in zip(expected["cards"], job["captions"]):
        _require(wanted["zh"] == actual["text"] and wanted["en"] == actual["en"] and
                 abs(float(wanted["start"]) - float(actual["start"])) < .002 and
                 abs(float(wanted["end"]) - float(actual["end"])) < .002,
                 "CAPTION_ALIGNMENT_MISMATCH: captions must come from the matching token timeline")


def _run(args: list[str], *, cwd: Path) -> None:
    subprocess.run(args, cwd=str(cwd), check=True)


def prepare_new(
    source: Path,
    plan: Mapping[str, Any] | Path,
    output: Path,
    tts_config: Path,
    whisper_model: Path,
    tempo: float | None = None,
) -> dict[str, str]:
    """Prepare manuscript/audio/token data in a new directory; never render."""
    if str(PAPER_SKILL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(PAPER_SKILL_SCRIPTS))
    try:
        from auto_pipeline import build_job_bundle
    except Exception as exc:  # pragma: no cover
        raise PaperInputError(f"paper auto pipeline unavailable: {exc}") from exc
    source, output, tts_config, whisper_model = map(Path, (source, output, tts_config, whisper_model))
    if isinstance(plan, Path):
        plan_data = _json(plan)
    else:
        plan_data = dict(plan)
    bundle = build_job_bundle(source, plan_data, output)
    job, approval = bundle.job, bundle.root / "approval.json"
    _run([sys.executable, str(PAPER_SKILL_SCRIPTS / "preflight.py"), "--job", str(job), "--approval", str(approval)], cwd=PAPER_SKILL_SCRIPTS)
    _run([sys.executable, str(PAPER_SKILL_SCRIPTS / "generate_tts.py"), "--job", str(job), "--approval", str(approval), "--config", str(tts_config)], cwd=PAPER_SKILL_SCRIPTS)
    high_job = bundle.root / "job-high-fidelity.json"
    _run([sys.executable, str(PAPER_SKILL_SCRIPTS / "build_high_fidelity_job.py"), "--source-job", str(job), "--output", str(high_job), "--id", f"{_json(job)['id']}-high-fidelity", "--target-chars", "10", "--max-chars", "16"], cwd=PAPER_SKILL_SCRIPTS)
    _run([sys.executable, str(PAPER_SKILL_SCRIPTS / "preflight.py"), "--job", str(high_job), "--approval", str(approval)], cwd=PAPER_SKILL_SCRIPTS)
    audio = bundle.root / "audio-high-fidelity-v1"
    audio_cmd = [sys.executable, str(PAPER_SKILL_SCRIPTS / "prepare_audio.py"), "--job", str(high_job), "--approval", str(approval), "--output", str(audio)]
    if tempo is not None:
        audio_cmd.extend(["--tempo", str(tempo)])
    _run(audio_cmd, cwd=PAPER_SKILL_SCRIPTS)
    whisper = bundle.root / "whisper-v1"
    _run([sys.executable, str(PAPER_SKILL_SCRIPTS / "transcribe_scenes.py"), "--job", str(high_job), "--approval", str(approval), "--model", str(whisper_model), "--output", str(whisper)], cwd=PAPER_SKILL_SCRIPTS)
    alignment = bundle.root / "alignment-high-fidelity-v1.json"
    _run([sys.executable, str(PAPER_SKILL_SCRIPTS / "build_alignment.py"), "--job", str(high_job), "--approval", str(approval), "--audio-manifest", str(audio / "audio-manifest.json"), "--whisper-dir", str(whisper), "--output", str(alignment)], cwd=PAPER_SKILL_SCRIPTS)
    return {"production": str(bundle.root), "job": str(high_job), "audio": str(audio), "whisper": str(whisper), "alignment": str(alignment), "status": "INPUT_READY_NOT_RENDERED"}
