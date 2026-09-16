#!/usr/bin/env python3
"""Pure contracts and resumable state for the one-input paper-card handler."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts.paper_card_core import normalize_text, sha256_file
except ModuleNotFoundError:
    from paper_card_core import normalize_text, sha256_file


class AutoPipelineError(RuntimeError):
    """Intentional stop-line failure in the automatic handler."""


@dataclass(frozen=True)
class JobBundle:
    root: Path
    source_copy: Path
    manuscript: Path
    job: Path
    approval: Path
    provenance: Path
    content_plan: Path
    normalization_log: Path


@dataclass(frozen=True)
class AutoConfig:
    whisper_model: str
    benchmark_video: str
    approved_baseline_video: str
    approved_baseline_timeline: str
    benchmark_whisper_json: str
    header_font: str
    handwriting_font: str
    sans_font: str
    english_font: str
    tts_binary: str
    jianying_dylib: str
    tts_binary_sha256: str
    jianying_dylib_sha256: str
    hyperframes_version: str = "0.8.17"
    asset_sha256: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "AutoConfig":
        source = Path(path).expanduser().resolve()
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AutoPipelineError(f"auto config not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise AutoPipelineError(f"invalid auto config JSON: {exc}") from exc
        try:
            return cls(**payload)
        except TypeError as exc:
            raise AutoPipelineError(f"auto config fields are incomplete: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AutoPipelineError(message)


def clean_markdown(raw: str) -> str:
    """Remove presentation markup while preserving every spoken body character."""
    value = raw.replace("\r\n", "\n").replace("\r", "\n")
    if value.startswith("---\n"):
        end = value.find("\n---\n", 4)
        if end != -1:
            value = value[end + 5:]
    output: list[str] = []
    for source_line in value.splitlines():
        line = source_line.strip()
        if not line or re.fullmatch(r"[-*_]{3,}", line):
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level = len(heading.group(1))
            heading_text = heading.group(2).strip()
            if level == 1:
                continue
            if not re.search(r"[：，。！？!?—-]", heading_text) and len(normalize_text(heading_text)) < 10:
                continue
            line = heading_text
        line = re.sub(r"^>\s?", "", line)
        line = re.sub(r"^(?:[-+*]|\d+[.)])\s+", "", line)
        line = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"(?<!\\)(?:\*\*|__)(.+?)(?<!\\)(?:\*\*|__)", r"\1", line)
        line = re.sub(r"(?<!\\)(?:\*|_)(.+?)(?<!\\)(?:\*|_)", r"\1", line)
        line = line.replace("`", "")
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            output.append(line)
    return "\n".join(output) + ("\n" if output else "")


def _canonical_spoken(value: str) -> str:
    return re.sub(r"\s+", "", value)


AGE_RANGE_DISPLAY_PATTERN = re.compile(r"(?<![\d-])3---12岁(?![\d-])")
NATURAL_CARD_ENDINGS = frozenset("，。！？；：、,.!?;:…—）】》”’")


def apply_display_normalizations(value: str) -> tuple[str, list[dict[str, Any]]]:
    """Apply the narrow, auditable display-only allowlist without general rewriting."""
    entries: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        displayed = "3—12岁"
        entries.append({
            "rule_id": "age-range-ascii-hyphens-to-em-dash-v1",
            "source": match.group(0),
            "display": displayed,
            "source_start": match.start(),
            "source_end": match.end(),
        })
        return displayed

    return AGE_RANGE_DISPLAY_PATTERN.sub(replace, value), entries


def audit_word_boundaries(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """Return advisory card-boundary risks without changing or failing ordinary text."""
    cards: list[dict[str, str]] = []
    warnings: list[dict[str, Any]] = []
    for scene in scenes:
        scene_id = str(scene.get("id", "scene"))
        for index, line in enumerate(scene.get("lines", []), start=1):
            text = str(line)
            card_id = f"{scene_id}-card-{index:03d}"
            cards.append({"id": card_id, "text": text})
            if len(normalize_text(text)) == 1:
                warnings.append({
                    "code": "RISK_SINGLE_CHARACTER_FLASH",
                    "card_ids": [card_id],
                    "reason": "single normalized character requires duration/readability review",
                })
    for previous, current in zip(cards, cards[1:]):
        left = previous["text"].rstrip()
        right = current["text"].lstrip()
        if not left or not right or left[-1] in NATURAL_CARD_ENDINGS:
            continue
        warnings.append({
            "code": "WARN_WORD_BOUNDARY",
            "card_ids": [previous["id"], current["id"]],
            "reason": "card boundary is inside a phrase; rebalance before production when lossless",
            "left_tail": left[-8:],
            "right_head": right[:8],
        })
    return {
        "status": "WARN_WORD_BOUNDARY" if warnings else "PASS",
        "warnings": warnings,
        "blocking": False,
        "joined_text_sha256": _digest_bytes("".join(card["text"] for card in cards).encode("utf-8")),
    }


def _validate_timezone(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AutoPipelineError(f"{field} must be ISO-8601") from exc
    _require(parsed.tzinfo is not None, f"{field} must include timezone")


def validate_content_plan(source: Path, cleaned: str, plan: dict[str, Any]) -> None:
    _require(plan.get("schema_version") == 1, "content plan schema_version must be 1")
    actual_source_hash = sha256_file(source)
    _require(
        plan.get("source_markdown_sha256") == actual_source_hash,
        "content plan source Markdown SHA256 does not match the current file",
    )
    _require(plan.get("approved_by") == "老大", "content plan approved_by must be 老大")
    _validate_timezone(plan.get("approved_at"), "approved_at")
    _require(isinstance(plan.get("title"), str) and plan["title"].strip(), "title is required")
    header = plan.get("header")
    _require(
        isinstance(header, list) and len(header) == 3
        and all(isinstance(item, str) and item.strip() for item in header),
        "header must contain exactly three readable lines",
    )
    scenes = plan.get("scenes")
    _require(isinstance(scenes, list) and scenes, "at least one content-plan scene is required")
    raw_flattened: list[str] = []
    display_flattened: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        expected_id = f"scene-{index:02d}"
        _require(scene.get("id") == expected_id, f"scene id must be contiguous: expected {expected_id}")
        lines = scene.get("lines")
        english = scene.get("line_english")
        _require(isinstance(lines, list) and lines, f"{expected_id}.lines must be non-empty")
        _require(
            isinstance(english, list) and len(english) == len(lines),
            f"{expected_id}.line_english must match lines one-to-one",
        )
        english_seen: set[str] = set()
        for line, translation in zip(lines, english):
            _require(isinstance(line, str) and line.strip(), f"{expected_id} contains an empty Chinese line")
            display_line, _ = apply_display_normalizations(line)
            _require(
                len(normalize_text(display_line)) <= 24,
                f"{expected_id} line exceeds 24 normalized characters: {line}",
            )
            _require(
                isinstance(translation, str) and translation.strip(),
                f"{expected_id} contains an empty English line",
            )
            normalized_english = re.sub(r"\s+", " ", translation.strip()).casefold()
            _require(normalized_english not in english_seen, f"{expected_id} repeats an English placeholder")
            english_seen.add(normalized_english)
            raw_flattened.append(line)
            display_flattened.append(display_line)
    _require(
        _canonical_spoken("".join(raw_flattened)) == _canonical_spoken(cleaned),
        "content plan Chinese content differs from the raw cleaned approved manuscript",
    )
    display_cleaned, _ = apply_display_normalizations(cleaned)
    _require(
        _canonical_spoken("".join(display_flattened)) == _canonical_spoken(display_cleaned),
        "content plan Chinese content differs from the cleaned approved manuscript after the narrow display allowlist; keep an age range on one card",
    )


def _normalized_plan(plan: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(plan, ensure_ascii=False))
    for scene in normalized["scenes"]:
        scene["lines"] = [apply_display_normalizations(line)[0] for line in scene["lines"]]
    return normalized


def _source_evidence(plan: dict[str, Any]) -> dict[str, Any]:
    supplied = plan.get("source_evidence")
    if supplied is not None:
        return supplied
    return {
        "url": "https://www.douyin.com/video/7676317205022703609",
        "title": "抖音纸纹手写逐句卡片对标视频",
        "observed_at": "2026-08-29T18:46:47+08:00",
        "public_metrics": [
            {"name": "public_video_id", "value": "7676317205022703609", "page": "Douyin public URL"}
        ],
        "reuse_scope": "topic_hook_structure_only",
        "full_text_copied": False,
    }


def build_job_bundle(source_path: str | Path, plan: dict[str, Any], output_path: str | Path) -> JobBundle:
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    _require(source.is_file() and source.stat().st_size > 0, f"source Markdown not found or empty: {source}")
    _require(not output.exists(), f"output already exists; choose a new directory: {output}")
    cleaned = clean_markdown(source.read_text(encoding="utf-8"))
    _require(cleaned.strip(), "cleaned manuscript is empty")
    validate_content_plan(source, cleaned, plan)
    display_manuscript, normalization_entries = apply_display_normalizations(cleaned)
    production_plan = _normalized_plan(plan)
    boundary_audit = audit_word_boundaries(production_plan["scenes"])
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    try:
        source_dir = staging / "source"
        source_dir.mkdir()
        source_copy = source_dir / source.name
        shutil.copy2(source, source_copy)
        manuscript = staging / "manuscript_approved.txt"
        manuscript.write_text(display_manuscript, encoding="utf-8")
        job_id = f"paper-card-{sha256_file(manuscript)[:12]}"
        job_payload = {
            "schema_version": 1,
            "id": job_id,
            "production_profile": "standard",
            "title": plan["title"].strip(),
            "manuscript": "manuscript_approved.txt",
            "source_evidence": _source_evidence(plan),
            "header": [item.strip() for item in plan["header"]],
            "footer": "纯黑底部｜无水印",
            "voice": {
                "provider": "Jianying official text reading",
                "label": "真人播客女",
                "resource_id": "7516816955475512615",
                "speaker": "zh_female_mizai_saturn_bigtts",
            },
            "scenes": [
                {
                    "id": scene["id"],
                    "audio": f"audio/official_raw/{scene['id']}.wav",
                    "lines": [line.strip() for line in scene["lines"]],
                    "line_english": [line.strip() for line in scene["line_english"]],
                }
                for scene in production_plan["scenes"]
            ],
            "render": {"width": 720, "height": 960, "fps": 30},
        }
        job = staging / "job.json"
        job.write_text(json.dumps(job_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        normalization_payload = {
            "schema_version": 1,
            "policy": "display-only-narrow-allowlist",
            "source_markdown_sha256": sha256_file(source),
            "display_manuscript_sha256": sha256_file(manuscript),
            "entries": normalization_entries,
            "word_boundary_audit": boundary_audit,
            "prohibited": "general punctuation cleanup, copyediting, polishing, or semantic rewriting",
        }
        normalization_log = staging / "normalization-log.json"
        normalization_log.write_text(
            json.dumps(normalization_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        approval_payload = {
            "status": "APPROVED_BY_BOSS",
            "approved_by": "老大",
            "approved_at": plan["approved_at"],
            "manuscript_sha256": sha256_file(manuscript),
            "display_manuscript_sha256": sha256_file(manuscript),
            "source_markdown_sha256": sha256_file(source),
            "normalization_log_sha256": sha256_file(normalization_log),
        }
        approval = staging / "approval.json"
        approval.write_text(json.dumps(approval_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        provenance_payload = {
            "schema_version": 1,
            "source_markdown": str(source),
            "source_markdown_sha256": sha256_file(source),
            "source_copy": f"source/{source.name}",
            "source_copy_sha256": sha256_file(source_copy),
            "production_manuscript": "manuscript_approved.txt",
            "production_manuscript_sha256": sha256_file(manuscript),
            "content_plan_sha256": _digest_bytes(
                (json.dumps(plan, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            ),
            "normalization": "Markdown presentation markup removed; only the audited display allowlist may change spoken-body glyphs",
            "normalization_log": "normalization-log.json",
            "normalization_log_sha256": sha256_file(normalization_log),
            "word_boundary_audit": boundary_audit,
            "content_preservation": "PASS_WITH_AUDITED_DISPLAY_NORMALIZATION" if normalization_entries else "PASS",
        }
        provenance = staging / "provenance.json"
        provenance.write_text(json.dumps(provenance_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        content_plan = staging / "content-plan.json"
        content_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return JobBundle(
        root=output,
        source_copy=output / "source" / source.name,
        manuscript=output / "manuscript_approved.txt",
        job=output / "job.json",
        approval=output / "approval.json",
        provenance=output / "provenance.json",
        content_plan=output / "content-plan.json",
        normalization_log=output / "normalization-log.json",
    )


def inspect_environment(config: AutoConfig) -> dict[str, Any]:
    failures: list[str] = []
    files: dict[str, dict[str, Any]] = {}
    path_fields = (
        "whisper_model", "benchmark_video", "approved_baseline_video",
        "approved_baseline_timeline", "benchmark_whisper_json", "header_font",
        "handwriting_font", "sans_font", "english_font", "tts_binary", "jianying_dylib",
    )
    for field in path_fields:
        path = Path(getattr(config, field)).expanduser().resolve()
        exists = path.is_file() and path.stat().st_size > 0
        digest = sha256_file(path) if exists else None
        files[field] = {"path": str(path), "exists": exists, "sha256": digest}
        if not exists:
            failures.append(f"{field} missing or empty: {path}")
    for path_field, hash_field in (
        ("tts_binary", "tts_binary_sha256"),
        ("jianying_dylib", "jianying_dylib_sha256"),
    ):
        observed = files[path_field]["sha256"]
        expected = getattr(config, hash_field)
        if observed is not None and observed != expected:
            failures.append(f"{hash_field} mismatch: expected {expected}, got {observed}")
    for path_field, expected in config.asset_sha256.items():
        if path_field not in files:
            failures.append(f"asset_sha256 contains unknown path field: {path_field}")
            continue
        observed = files[path_field]["sha256"]
        if observed is not None and observed != expected:
            failures.append(f"{path_field} SHA256 mismatch: expected {expected}, got {observed}")
    commands = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "whisper-cli", "npm", "python3")}
    for name, path in commands.items():
        if not path:
            failures.append(f"required command missing: {name}")
    return {
        "status": "PASS" if not failures else "FAIL",
        "files": files,
        "commands": commands,
        "hyperframes_version": config.hyperframes_version,
        "failures": failures,
    }


def _review_pass(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return payload.get("status") == "PASS"


def next_action(root_path: str | Path) -> str:
    root = Path(root_path).expanduser().resolve()
    if not all((root / name).is_file() for name in ("job.json", "approval.json", "provenance.json")):
        return "BUILD_JOB_BUNDLE"
    sample = root / "sample30"
    full = root / "full"
    if (sample / "TECH_PASS").is_file() and not _review_pass(sample / "human-review.json"):
        return "REVIEW_SAMPLE30"
    if (full / "TECH_PASS").is_file() and not _review_pass(full / "human-review.json"):
        return "REVIEW_FULL"
    if (full / "PASS").is_file() and _review_pass(full / "human-review.json"):
        return "COMPLETE"
    if not (root / "audio" / "official_raw" / "TTS_COMPLETE").is_file():
        return "GENERATE_TTS"
    if not (sample / "PASS").is_file():
        return "BUILD_SAMPLE30"
    return "BUILD_FULL"


def sample_master_output(stage_path: str | Path) -> Path:
    stage = Path(stage_path).expanduser()
    return stage / "audio-master-v1" / "voiceover_sample30_master.m4a"
