#!/usr/bin/env python3
"""Pure contracts and token-offset alignment for the paper-card pipeline."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class PipelineError(RuntimeError):
    """Base class for intentional stop-line failures."""


class ContractError(PipelineError):
    """The job or evidence contract is incomplete or unsafe."""


class ApprovalError(PipelineError):
    """The manuscript is not bound to a valid boss approval receipt."""


class AlignmentError(PipelineError):
    """Whisper token offsets cannot support a reliable sentence timeline."""


class OutputExistsError(PipelineError):
    """The requested output already exists and must not be overwritten."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _require_timezone(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{field} must be ISO-8601: {value}") from exc
    _require(parsed.tzinfo is not None, f"{field} must include a timezone")


def load_job(path: str | Path) -> dict[str, Any]:
    """Load and validate the source, manuscript, visual, voice and scene contract."""
    job_path = Path(path).expanduser().resolve()
    _require(job_path.is_file(), f"job file not found: {job_path}")
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid job JSON: {exc}") from exc
    _require(isinstance(job, dict), "job root must be an object")
    _require(job.get("schema_version") == 1, "schema_version must be 1")
    _require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", str(job.get("id", "")))),
             "id must be 3-64 lowercase letters, digits or hyphens")
    _require(isinstance(job.get("title"), str) and job["title"].strip(), "title is required")
    production_profile = job.get("production_profile", "standard")
    _require(production_profile in {"standard", "benchmark-high-fidelity"},
             "production_profile must be standard or benchmark-high-fidelity")

    manuscript_raw = job.get("manuscript")
    _require(isinstance(manuscript_raw, str) and manuscript_raw.strip(), "manuscript path is required")
    manuscript = Path(manuscript_raw).expanduser()
    if not manuscript.is_absolute():
        manuscript = job_path.parent / manuscript
    manuscript = manuscript.resolve()
    _require(manuscript.is_file() and manuscript.stat().st_size > 0,
             f"manuscript not found or empty: {manuscript}")

    evidence = job.get("source_evidence")
    _require(isinstance(evidence, dict), "source_evidence object is required")
    url = str(evidence.get("url", ""))
    parsed_url = urlparse(url)
    _require(parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc),
             "source_evidence.url must be a public http(s) URL")
    _require(isinstance(evidence.get("title"), str) and evidence["title"].strip(),
             "source_evidence.title is required")
    observed_at = evidence.get("observed_at")
    _require(isinstance(observed_at, str), "source_evidence.observed_at is required")
    _require_timezone(observed_at, "source_evidence.observed_at")
    metrics = evidence.get("public_metrics")
    _require(isinstance(metrics, list) and len(metrics) > 0,
             "source_evidence.public_metrics must contain public evidence")
    for metric in metrics:
        _require(isinstance(metric, dict), "each public metric must be an object")
        _require(isinstance(metric.get("name"), str) and metric["name"].strip(),
                 "public metric name is required")
        _require(metric.get("value") is not None, "public metric value is required; unknown is not zero")
    _require(evidence.get("reuse_scope") == "topic_hook_structure_only",
             "reuse_scope must be topic_hook_structure_only")
    _require(evidence.get("full_text_copied") is False,
             "full_text_copied must be false; third-party full text cannot enter this pipeline")

    header = job.get("header")
    _require(isinstance(header, list) and len(header) == 3 and all(isinstance(x, str) and x.strip() for x in header),
             "header must contain exactly three non-empty lines")
    _require(isinstance(job.get("footer"), str) and job["footer"].strip(), "footer is required")

    voice = job.get("voice")
    _require(isinstance(voice, dict), "voice object is required")
    for key in ("provider", "label", "resource_id", "speaker"):
        _require(isinstance(voice.get(key), str) and voice[key].strip(), f"voice.{key} is required")

    scenes = job.get("scenes")
    _require(isinstance(scenes, list) and scenes, "at least one scene is required")
    flattened: list[str] = []
    for index, scene in enumerate(scenes, start=1):
        _require(isinstance(scene, dict), f"scene {index} must be an object")
        expected_id = f"scene-{index:02d}"
        _require(scene.get("id") == expected_id, f"scene id must be contiguous: expected {expected_id}")
        lines = scene.get("lines")
        _require(isinstance(lines, list) and lines, f"{expected_id}.lines must be non-empty")
        line_english = scene.get("line_english")
        _require(isinstance(line_english, list) and len(line_english) == len(lines),
                 f"{expected_id}.line_english must match lines one-to-one")
        english_bases: list[str] = []
        for english in line_english:
            _require(isinstance(english, str) and english.strip(),
                     f"{expected_id}.line_english contains an empty label")
            base = re.sub(r"(?:\s*[·#-]\s*)?\d{1,3}$", "", english.strip(), flags=re.IGNORECASE).strip().casefold()
            english_bases.append(base)
        _require(len(set(english_bases)) == len(english_bases),
                 f"{expected_id}.line_english must be unique per card; scene labels with counters are forbidden")
        for line in lines:
            _require(isinstance(line, str) and normalize_text(line), f"{expected_id} contains an empty line")
            _require(len(normalize_text(line)) <= 24,
                     f"{expected_id} line exceeds 24 normalized characters; split it before production")
            flattened.append(line.strip())
        _require(isinstance(scene.get("audio"), str) and scene["audio"].strip(),
                 f"{expected_id}.audio is required")

    render = job.get("render")
    _require(render == {"width": 720, "height": 960, "fps": 30},
             "render contract must be exactly 720x960 at 30fps")

    manuscript_text = manuscript.read_text(encoding="utf-8")
    normalized_manuscript = normalize_text(manuscript_text)
    normalized_lines = normalize_text("".join(flattened))
    _require(normalized_lines and normalized_lines in normalized_manuscript,
             "scene lines must be traceable as an ordered contiguous block in the manuscript")

    if production_profile == "benchmark-high-fidelity":
        lengths = sorted(len(normalize_text(line)) for line in flattened)
        mean_length = sum(lengths) / len(lengths)
        p90_length = lengths[max(0, math.ceil(len(lengths) * 0.90) - 1)]
        maximum = lengths[-1]
        _require(
            mean_length <= 11.5 and p90_length <= 13 and maximum <= 16,
            "high-fidelity card length distribution must satisfy mean<=11.5, p90<=13, max<=16; "
            f"got mean={mean_length:.2f}, p90={p90_length}, max={maximum}",
        )

    job["_job_path"] = str(job_path)
    job["_job_root"] = str(job_path.parent)
    job["_manuscript_path"] = str(manuscript)
    job["_manuscript_sha256"] = sha256_file(manuscript)
    return job


def verify_approval(job: dict[str, Any], receipt_path: str | Path) -> dict[str, Any]:
    """Require a receipt that binds boss approval to the exact manuscript bytes."""
    path = Path(receipt_path).expanduser().resolve()
    if not path.is_file():
        raise ApprovalError(f"approval receipt not found: {path}")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApprovalError(f"invalid approval receipt JSON: {exc}") from exc
    if receipt.get("status") != "APPROVED_BY_BOSS":
        raise ApprovalError("approval status must be APPROVED_BY_BOSS")
    if receipt.get("approved_by") != "老大":
        raise ApprovalError("approved_by must be 老大")
    approved_at = receipt.get("approved_at")
    if not isinstance(approved_at, str):
        raise ApprovalError("approved_at is required")
    try:
        parsed = datetime.fromisoformat(approved_at)
    except ValueError as exc:
        raise ApprovalError("approved_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ApprovalError("approved_at must include a timezone")
    if receipt.get("manuscript_sha256") != job.get("_manuscript_sha256"):
        raise ApprovalError("approval receipt does not match the current manuscript SHA256")
    return receipt


def assert_new_output(path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists():
        raise OutputExistsError(f"output already exists; create a new version instead: {output}")
    return output


@lru_cache(maxsize=1)
def _t2s_dictionaries() -> tuple[dict[str, str], dict[str, str], int]:
    root = Path(__file__).resolve().parent.parent / "vendor" / "opencc-t2s"

    def load(name: str) -> dict[str, str]:
        path = root / name
        if not path.is_file():
            return {}
        result: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.startswith("#") or "\t" not in raw:
                continue
            source, targets = raw.split("\t", 1)
            target = targets.split()[0] if targets.split() else ""
            if source and target:
                result[source] = target
        return result

    phrases = load("TSPhrases.txt")
    characters = load("TSCharacters.txt")
    return phrases, characters, max((len(key) for key in phrases), default=1)


def _traditional_to_simplified(value: str) -> str:
    phrases, characters, max_phrase = _t2s_dictionaries()
    if not phrases and not characters:
        return value
    output: list[str] = []
    index = 0
    while index < len(value):
        matched = False
        for length in range(min(max_phrase, len(value) - index), 1, -1):
            source = value[index:index + length]
            target = phrases.get(source)
            if target is not None:
                output.append(target)
                index += length
                matched = True
                break
        if not matched:
            output.append(characters.get(value[index], value[index]))
            index += 1
    return "".join(output)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).lower()
    value = _traditional_to_simplified(value)
    return "".join(char for char in value if _is_supported_char(char))


def _is_supported_char(char: str) -> bool:
    if char.isascii() and char.isalnum():
        return True
    return "CJK" in unicodedata.name(char, "") or "IDEOGRAPH" in unicodedata.name(char, "")


def flatten_whisper_tokens(
    payload: dict[str, Any], *, time_scale: float = 1.0
) -> list[dict[str, float | str]]:
    """Expand whisper.cpp full-JSON tokens into timestamped normalized characters."""
    if not 0 < time_scale <= 1.0:
        raise AlignmentError(f"Whisper token time scale must be in (0, 1], got {time_scale}")
    chars: list[dict[str, float | str]] = []
    segments = payload.get("transcription")
    if not isinstance(segments, list):
        segments = payload.get("segments")
    if not isinstance(segments, list):
        return chars
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        tokens = segment.get("tokens")
        if not isinstance(tokens, list):
            tokens = segment.get("words")
        if not isinstance(tokens, list):
            continue
        segment_offsets = segment.get("offsets") or {}
        for token in tokens:
            if not isinstance(token, dict):
                continue
            raw = str(token.get("text", token.get("word", "")))
            if raw.startswith("["):
                continue
            text = normalize_text(raw)
            if not text:
                continue
            offsets = token.get("offsets") or {}
            start_raw = offsets.get("from", token.get("start"))
            end_raw = offsets.get("to", token.get("end"))
            if start_raw is None:
                start_raw = segment_offsets.get("from")
            if end_raw is None:
                end_raw = segment_offsets.get("to")
            if start_raw is None or end_raw is None:
                continue
            start = float(start_raw)
            end = float(end_raw)
            # whisper.cpp offsets are milliseconds; generic words commonly use seconds.
            if start > 50 or end > 50 or isinstance(offsets.get("from"), int):
                start /= 1000.0
                end /= 1000.0
            start *= time_scale
            end *= time_scale
            end = max(start + 0.01, end)
            for index, char in enumerate(text):
                chars.append({
                    "char": char,
                    "start": start + (end - start) * index / len(text),
                    "end": start + (end - start) * (index + 1) / len(text),
                })
    return chars


def _levenshtein_mapping(expected: str, actual: list[dict[str, Any]]) -> tuple[dict[int, int], int]:
    rows, cols = len(expected) + 1, len(actual) + 1
    matrix = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        matrix[i][0] = i
    for j in range(cols):
        matrix[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            substitution = matrix[i - 1][j - 1] + (expected[i - 1] != actual[j - 1]["char"])
            matrix[i][j] = min(substitution, matrix[i - 1][j] + 1, matrix[i][j - 1] + 1)
    mapping: dict[int, int] = {}
    i, j = len(expected), len(actual)
    while i > 0 or j > 0:
        diagonal = (matrix[i - 1][j - 1] + (expected[i - 1] != actual[j - 1]["char"])) if i and j else 10**9
        if i and j and matrix[i][j] == diagonal:
            mapping[i - 1] = j - 1
            i -= 1
            j -= 1
        elif i and matrix[i][j] == matrix[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return mapping, matrix[-1][-1]


def _mapped_time(mapping: dict[int, int], actual: list[dict[str, Any]], expected_index: int,
                 radius_limit: int = 24) -> float:
    if expected_index in mapping:
        return float(actual[mapping[expected_index]]["start"])
    for radius in range(1, radius_limit + 1):
        after = expected_index + radius
        before = expected_index - radius
        if after in mapping:
            return float(actual[mapping[after]]["start"])
        if before >= 0 and before in mapping:
            return float(actual[mapping[before]]["end"])
    raise AlignmentError(f"no token-offset neighbor within {radius_limit} characters at expected index {expected_index}")


def align_scene(
    *,
    scene_id: str,
    lines: list[str],
    whisper: dict[str, Any],
    scene_start: float,
    scene_end: float,
    visual_lead: float = 0.08,
    min_hold: float = 0.45,
    max_edit_ratio: float = 0.28,
    token_time_scale: float = 1.0,
) -> dict[str, Any]:
    """Align line starts to Whisper token offsets; never use character-weight timing fallback."""
    if not lines:
        raise AlignmentError(f"{scene_id}: no lines")
    if scene_end <= scene_start:
        raise AlignmentError(f"{scene_id}: invalid scene time span")
    if scene_end - scene_start < len(lines) * min_hold:
        raise AlignmentError(f"{scene_id}: audio too short for {len(lines)} cards at {min_hold}s minimum hold")
    actual = flatten_whisper_tokens(whisper, time_scale=token_time_scale)
    if not actual:
        raise AlignmentError(f"{scene_id}: Whisper full JSON token offsets are required")
    ranges: list[tuple[int, int]] = []
    expected = ""
    for line in lines:
        text = normalize_text(line)
        if not text:
            raise AlignmentError(f"{scene_id}: empty normalized line")
        ranges.append((len(expected), len(text)))
        expected += text
    mapping, distance = _levenshtein_mapping(expected, actual)
    ratio = distance / max(1, len(expected), len(actual))
    if ratio > max_edit_ratio:
        raise AlignmentError(
            f"{scene_id}: ASR edit ratio {ratio:.4f} exceeds {max_edit_ratio:.4f}; regenerate or inspect this scene"
        )
    local_starts = [_mapped_time(mapping, actual, start) for start, _ in ranges]
    speech_starts = [scene_start + max(0.0, value) for value in local_starts]
    raw_starts = [scene_start] + [max(scene_start, value - visual_lead) for value in speech_starts[1:]]
    starts = [scene_start]
    for index in range(1, len(raw_starts)):
        earliest = starts[index - 1] + min_hold
        latest = scene_end - (len(raw_starts) - index) * min_hold
        if latest < earliest:
            raise AlignmentError(f"{scene_id}: minimum-hold constraints overlap")
        starts.append(min(latest, max(earliest, raw_starts[index])))
    return {
        "id": scene_id,
        "alignment_source": "whisper_token_offsets",
        "distance": distance,
        "edit_ratio": round(ratio, 6),
        "expected_chars": len(expected),
        "asr_chars": len(actual),
        "visual_lead_seconds": visual_lead,
        "min_hold_seconds": min_hold,
        "token_time_scale": token_time_scale,
        "speech_starts": [round(value, 3) for value in speech_starts],
        "starts": [round(value, 3) for value in starts],
        "lines": lines,
    }
