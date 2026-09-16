#!/usr/bin/env python3
"""Create a non-overwriting high-fidelity job by splitting approved cards without changing Chinese bytes."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.paper_card_core import assert_new_output, load_job, normalize_text
except ModuleNotFoundError:
    from paper_card_core import assert_new_output, load_job, normalize_text


BREAK_MARKS = set("，。！？；：、,.!?;:』」】）)")


def split_chinese_preserving(line: str, *, target: int = 10, maximum: int = 12) -> list[str]:
    if not 1 <= target <= maximum <= 16:
        raise ValueError("card split limits must satisfy 1 <= target <= maximum <= 16")
    chunks: list[str] = []
    current = ""
    normalized_count = 0
    preferred_max = min(12, maximum)
    for position, char in enumerate(line):
        current += char
        normalized_count = len(normalize_text(current))
        cut = normalized_count >= target and char in BREAK_MARKS
        if not cut and normalized_count >= preferred_max:
            lookahead = ""
            for following in line[position + 1:]:
                lookahead += following
                if following in BREAK_MARKS or len(normalize_text(current + lookahead)) >= maximum:
                    break
            short_tail_to_semantic_stop = (
                bool(lookahead)
                and lookahead[-1] in BREAK_MARKS
                and len(normalize_text(lookahead)) <= 1
                and len(normalize_text(current + lookahead)) <= maximum
            )
            cut = not short_tail_to_semantic_stop or normalized_count >= maximum
        if cut:
            chunks.append(current)
            current = ""
            normalized_count = 0
    if current:
        if chunks and len(normalize_text(current)) <= 2 and len(normalize_text(chunks[-1] + current)) <= maximum:
            chunks[-1] += current
        else:
            chunks.append(current)
    if "".join(chunks) != line or any(not normalize_text(chunk) for chunk in chunks):
        raise ValueError(f"lossless Chinese card split failed: {line!r}")
    return chunks


def split_english_balanced(value: str, count: int) -> list[str]:
    words = value.split()
    if count <= 0 or len(words) < count:
        raise ValueError(f"English line has {len(words)} words but needs {count} semantic card fragments: {value!r}")
    quotient, remainder = divmod(len(words), count)
    output: list[str] = []
    cursor = 0
    for index in range(count):
        width = quotient + (1 if index < remainder else 0)
        output.append(" ".join(words[cursor:cursor + width]))
        cursor += width
    return output


def transform_job(payload: dict[str, Any], *, job_id: str, target: int = 10, maximum: int = 12) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result["id"] = job_id
    result["production_profile"] = "benchmark-high-fidelity"
    for scene in result["scenes"]:
        new_lines: list[str] = []
        new_english: list[str] = []
        for line, english in zip(scene["lines"], scene["line_english"]):
            chunks = split_chinese_preserving(line, target=target, maximum=maximum)
            translations = split_english_balanced(english, len(chunks))
            new_lines.extend(chunks)
            new_english.extend(translations)
        bases = [re.sub(r"(?:\s*[·#-]\s*)?\d{1,3}$", "", value).strip().casefold() for value in new_english]
        if len(bases) != len(set(bases)):
            raise ValueError(f"{scene['id']} generated repeated English fragments; edit semantics before production")
        scene["lines"] = new_lines
        scene["line_english"] = new_english
    return result


def main(args: argparse.Namespace) -> Path:
    source = Path(args.source_job).expanduser().resolve()
    original = load_job(source)
    clean = {key: value for key, value in original.items() if not key.startswith("_")}
    clean["manuscript"] = original["_manuscript_path"]
    source_root = Path(original["_job_root"])
    for scene in clean["scenes"]:
        audio = Path(scene["audio"]).expanduser()
        if not audio.is_absolute():
            audio = source_root / audio
        scene["audio"] = str(audio.resolve())
    transformed = transform_job(
        clean, job_id=args.id, target=int(args.target_chars), maximum=int(args.max_chars)
    )
    output = assert_new_output(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(transformed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        load_job(temporary)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source-job", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--id", required=True)
    result.add_argument("--target-chars", type=int, default=10)
    result.add_argument("--max-chars", type=int, default=12)
    return result


if __name__ == "__main__":
    path = main(parser().parse_args())
    print(json.dumps({"status": "HIGH_FIDELITY_JOB_READY", "output": str(path)}, ensure_ascii=False))
