#!/usr/bin/env python3
"""Build a deterministic local HyperFrames paper-card project from approved inputs."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.paper_card_core import assert_new_output, load_job, sha256_file, verify_approval
except ModuleNotFoundError:
    from paper_card_core import assert_new_output, load_job, sha256_file, verify_approval


HYPERFRAMES_VERSION = "0.8.17"
SKILL_ROOT = Path(__file__).resolve().parent.parent
PAPER_TEXTURE = SKILL_ROOT / "assets" / "paper-texture-v11.png"

MOTIONS = [
    {"variant": "vertical-blur", "x": 0, "y": -82, "sx": 0.96, "sy": 0.72, "r": 0, "d": 0.34},
    {"variant": "zoom-rotate-left", "x": 0, "y": -18, "sx": 1.38, "sy": 1.38, "r": -8, "d": 0.44},
    {"variant": "zoom-rotate-right", "x": 0, "y": -18, "sx": 1.38, "sy": 1.38, "r": 8, "d": 0.44},
    {"variant": "slide-left", "x": -126, "y": 4, "sx": 0.94, "sy": 0.94, "r": -3, "d": 0.36},
    {"variant": "slide-right", "x": 126, "y": 4, "sx": 0.94, "sy": 0.94, "r": 3, "d": 0.36},
    {"variant": "soft-pop", "x": 0, "y": 18, "sx": 0.56, "sy": 0.56, "r": 0, "d": 0.46},
    {"variant": "tilt-rise-left", "x": -54, "y": 72, "sx": 0.82, "sy": 0.82, "r": -10, "d": 0.42},
    {"variant": "tilt-rise-right", "x": 54, "y": 72, "sx": 0.82, "sy": 0.82, "r": 10, "d": 0.42},
]

ICON_BODIES = [
    '<rect x="28" y="24" width="64" height="48" rx="2"/><rect x="108" y="24" width="64" height="48" rx="2"/><rect x="68" y="112" width="64" height="48" rx="2"/><path d="M60 74v18h80V74M100 92v20"/>',
    '<path d="M68 64c0-30 20-48 50-48 31 0 52 18 52 46 0 22-13 35-34 48-17 11-23 21-23 39"/><circle cx="113" cy="174" r="8" class="solid"/><path d="M24 55h24M18 90h28M26 127h24"/>',
    '<path d="M112 10 52 99h46l-15 82 68-99H105z"/><path d="M16 48h36M8 88h40M16 128h36"/>',
    '<circle cx="100" cy="43" r="22"/><path d="M55 180c4-47 20-76 45-76s41 29 45 76M100 104v76"/><path d="M48 126H12m0 0 15-14M12 126l15 14M152 126h36m0 0-15-14m15 14-15 14"/>',
    '<path d="M30 166V48h68v118M98 80h72v86M14 166h172"/><path d="M54 75h22M54 104h22M54 133h22M122 108h22M122 137h22"/>',
    '<circle cx="100" cy="100" r="34"/><circle cx="100" cy="100" r="10" class="solid"/><circle cx="22" cy="22" r="14" class="solid"/><circle cx="178" cy="22" r="14" class="solid"/><circle cx="22" cy="178" r="14" class="solid"/><circle cx="178" cy="178" r="14" class="solid"/><path d="M45 45 74 74M126 74l29-29M45 155l29-29M126 126l29 29"/>',
    '<path d="M26 164 72 118l31 30 66-79"/><path d="M128 69h41v41"/><path d="M24 181h152"/>',
    '<path d="M35 28h130v144H35z"/><path d="m62 98 23 23 54-58M61 53h52M61 146h80"/>',
    '<circle cx="100" cy="100" r="70"/><path d="M100 42v61l42 24"/><circle cx="100" cy="100" r="7" class="solid"/>',
    '<path d="M28 155h144M46 132l29-38 30 20 49-68"/><path d="M140 46h14v16"/><circle cx="46" cy="132" r="7" class="solid"/><circle cx="75" cy="94" r="7" class="solid"/><circle cx="105" cy="114" r="7" class="solid"/>',
    '<path d="M28 52h144v96H28z"/><path d="m28 64 72 52 72-52M54 166h92"/>',
    '<path d="M26 78h148M52 38h96M52 118h96M72 158h56"/><circle cx="28" cy="78" r="10" class="solid"/><circle cx="172" cy="78" r="10" class="solid"/>',
    '<path d="M100 18 176 54v45c0 47-27 72-76 86-49-14-76-39-76-86V54z"/><path d="m64 100 24 24 51-56"/>',
    '<path d="M30 52h140v112H30z"/><path d="M30 82h140M64 28v48M136 28v48M58 111h26M102 111h40M58 139h84"/>',
    '<path d="M20 100h52M128 100h52M100 20v52M100 128v52"/><circle cx="100" cy="100" r="29"/><path d="m83 100 13 13 25-31"/>',
    '<path d="M38 165c0-38 25-65 62-65s62 27 62 65"/><circle cx="100" cy="61" r="29"/><path d="M22 34h36M142 34h36M22 34l16-15M22 34l16 15M178 34l-16-15M178 34l-16 15"/>',
]

ICON_DECORATIONS = [
    '<path d="M12 42h42M22 28 8 42l14 14M266 138h42m-10-14 14 14-14 14"/>',
    '<circle cx="28" cy="42" r="14"/><path d="M42 42h34M244 136h34"/><circle cx="292" cy="136" r="14"/>',
    '<path d="M10 128c28-36 48-42 76-14M236 58c27-31 48-31 74 0M18 146h54M248 76h52"/>',
    '<path d="M16 36h58M16 52h36M246 128h58M266 144h38"/>',
    '<path d="M22 104c18-38 37-54 58-65M80 39l-4 26M80 39l-25 7M240 137c22-6 42-23 59-50M299 87l-3 26M299 87l-25 7"/>',
    '<rect x="12" y="30" width="58" height="42" rx="8"/><path d="M70 51h26M224 131h26"/><rect x="250" y="110" width="58" height="42" rx="8"/>',
    '<path d="M14 44c20-19 39-19 59 0s39 19 59 0M188 136c20-19 39-19 59 0s39 19 59 0"/>',
    '<path d="M18 33h50l20 20-20 20H18zM302 147h-50l-20-20 20-20h50z"/>',
]

STANDARD_MOTION_PROFILES = [
    {"name": "breathe-left", "x": 12, "y": -6, "scale": 1.10, "rotation": -2.0, "cycle": 0.92},
    {"name": "breathe-right", "x": -14, "y": 6, "scale": 1.09, "rotation": 2.2, "cycle": 1.02},
    {"name": "pull-close", "x": 4, "y": -8, "scale": 1.16, "rotation": -1.2, "cycle": 0.84},
    {"name": "hand-drag", "x": 20, "y": 9, "scale": 1.07, "rotation": 2.8, "cycle": 1.12},
    {"name": "tilt-pulse", "x": -10, "y": -7, "scale": 1.12, "rotation": -3.2, "cycle": 0.96},
]

HIGH_FIDELITY_MOTION_PROFILES = [
    {"name": "drift-left", "x": -4.0, "y": -2.0, "scale": 1.020, "rotation": -0.70},
    {"name": "drift-right", "x": 4.0, "y": 2.0, "scale": 1.020, "rotation": 0.70},
    {"name": "slow-push", "x": 0.0, "y": -4.0, "scale": 1.020, "rotation": 0.0},
    {"name": "glide-left", "x": -4.0, "y": 3.0, "scale": 1.020, "rotation": -0.70},
    {"name": "lift-right", "x": 4.0, "y": -4.0, "scale": 1.020, "rotation": 0.70},
]


def _hash_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16)


def card_midpoints(timeline: dict[str, Any]) -> list[dict[str, float | str]]:
    return [
        {"id": str(card["id"]), "at": round((float(card["start"]) + float(card["end"])) / 2, 3)}
        for card in timeline.get("cards", [])
    ]


def high_fidelity_progressive_duration(remaining: float) -> float:
    """Keep long cards moving without exceeding the validated low-amplitude path."""
    return min(0.90, max(0.36, float(remaining) - 1.50))


def is_short_card(card: dict[str, Any]) -> bool:
    """Identify any card too short for normal ingress, readable hold, and exit."""
    hold = float(card["end"]) - float(card["start"])
    return hold < max(0.62, float(card["motion"]["d"]) + 0.10)


def make_timeline(
    job: dict[str, Any], alignment: dict[str, Any], audio: dict[str, Any], max_duration: float | None = None
) -> dict[str, Any]:
    if alignment.get("alignment_source") != "whisper_full_json_token_offsets":
        raise ValueError("alignment_source must be whisper_full_json_token_offsets")
    aligned = {scene["id"]: scene for scene in alignment.get("scenes", [])}
    audio_scenes = {scene["id"]: scene for scene in audio.get("scenes", [])}
    cards: list[dict[str, Any]] = []
    scenes_out: list[dict[str, Any]] = []
    full_duration = float(audio["duration"])
    if max_duration is not None and max_duration <= 0:
        raise ValueError("max_duration must be positive")
    duration = min(full_duration, float(max_duration)) if max_duration is not None else full_duration
    for scene_index, scene in enumerate(job["scenes"], start=1):
        scene_id = scene["id"]
        if scene_id not in aligned or scene_id not in audio_scenes:
            raise ValueError(f"missing alignment or audio scene: {scene_id}")
        starts = aligned[scene_id].get("starts", [])
        if len(starts) != len(scene["lines"]):
            raise ValueError(f"alignment count mismatch: {scene_id}")
        original_scene_end = float(audio_scenes[scene_id]["end"])
        scene_start = float(audio_scenes[scene_id]["start"])
        scene_end = min(original_scene_end, duration)
        if any(float(starts[i]) >= float(starts[i + 1]) for i in range(len(starts) - 1)):
            raise ValueError(f"non-increasing card starts: {scene_id}")
        if starts and float(starts[-1]) >= original_scene_end:
            raise ValueError(f"last card starts after scene end: {scene_id}")
        if scene_start >= duration:
            continue
        kept_count = sum(float(start) < duration for start in starts)
        scenes_out.append({
            "id": scene_id,
            "index": scene_index,
            "start": round(scene_start, 3),
            "end": round(scene_end, 3),
            "card_count": kept_count,
            "alignment_edit_ratio": aligned[scene_id].get("edit_ratio"),
        })
        for line_index, (line, english, start) in enumerate(
                zip(scene["lines"][:kept_count], scene["line_english"][:kept_count], starts[:kept_count]), start=1):
            unclipped_end = float(starts[line_index]) if line_index < len(starts) else original_scene_end
            end = min(unclipped_end, duration)
            index = len(cards) + 1
            value_hash = _hash_int(line)
            cards.append({
                "id": f"card-{index:03d}",
                "scene_id": scene_id,
                "scene_index": scene_index,
                "index_in_scene": line_index,
                "start": round(float(start), 3),
                "end": round(float(end), 3),
                "unclipped_end": round(unclipped_end, 3),
                "truncated_by_sample": end + 1e-6 < unclipped_end,
                "zh": line,
                "en": english,
                "emphasis": line_index == 1,
                "motion": MOTIONS[(index - 1) % len(MOTIONS)],
                "icon_index": value_hash % len(ICON_BODIES),
                "decoration_index": (value_hash >> 5) % len(ICON_DECORATIONS),
                "motion_profile": (value_hash >> 9) % len(HIGH_FIDELITY_MOTION_PROFILES),
            })
    timeline: dict[str, Any] = {
        "version": 3,
        "id": job["id"],
        "title": job["title"],
        "duration": round(duration, 3),
        "width": 720,
        "height": 960,
        "fps": 30,
        "header": job["header"],
        "footer": job["footer"],
        "voice": job["voice"],
        "production_profile": job.get("production_profile", "standard"),
        "scenes": scenes_out,
        "cards": cards,
        "invariants": {
            "timing_source": "whisper_token_offsets_only",
            "manuscript_sha256": job["_manuscript_sha256"],
            "card_count": len(cards),
            "scene_count": len(scenes_out),
            "sample_truncated": duration < full_duration,
            "full_duration": round(full_duration, 3),
        },
    }
    timeline["card_midpoints"] = card_midpoints(timeline)
    return timeline


def _icon_svg(card: dict[str, Any], *, high_fidelity: bool = False) -> str:
    width = (445 if card["emphasis"] else 360) if high_fidelity else (410 if card["emphasis"] else 320)
    height = (245 if card["emphasis"] else 200) if high_fidelity else (225 if card["emphasis"] else 178)
    body = ICON_BODIES[card["icon_index"]]
    decoration = ICON_DECORATIONS[card["decoration_index"]]
    return (
        f'<svg viewBox="0 0 320 180" width="{width}" height="{height}" aria-hidden="true">'
        f'<g class="icon-art"><g transform="translate(70 -9) scale(.9)">{body}</g>'
        f'<g class="scene-marks">{decoration}</g></g></svg>'
    )


def render_html(job: dict[str, Any], timeline: dict[str, Any]) -> str:
    high_fidelity = job.get("production_profile") == "benchmark-high-fidelity"
    motion_profiles = HIGH_FIDELITY_MOTION_PROFILES if high_fidelity else STANDARD_MOTION_PROFILES
    cards_html: list[str] = []
    tweens: list[str] = []
    last_index = len(timeline["cards"]) - 1
    for zero_index, card in enumerate(timeline["cards"]):
        hold = float(card["end"]) - float(card["start"])
        short_truncated = is_short_card(card)
        next_short_truncated = (
            zero_index < last_index and is_short_card(timeline["cards"][zero_index + 1])
        )
        extends_into_next = zero_index < last_index and not next_short_truncated
        section_duration = hold + (0.15 if extends_into_next else 0.0)
        track = 1 + zero_index % 2
        profile = motion_profiles[card["motion_profile"]]
        motion_path_attr = ' data-motion-path="progressive-single-leg"' if high_fidelity else ""
        short_truncation_attr = ' data-short-truncation-safe="true"' if short_truncated else ""
        icon_markup = (
            f'<div class="icon-entry">{_icon_svg(card, high_fidelity=True)}</div>'
            if high_fidelity else
            f'<div class="icon-entry"><div class="icon-boil">{_icon_svg(card)}</div></div>'
        )
        cards_html.append(
            f'<section id="{card["id"]}" class="clip content-card" data-start="{card["start"]}" '
            f'data-duration="{section_duration:.3f}" data-track-index="{track}" '
            f'data-motion-variant="{card["motion"]["variant"]}" data-motion-profile="{profile["name"]}"'
            f'{motion_path_attr}{short_truncation_attr}>'
            f'<div class="icon-layer{" emphasis" if card["emphasis"] else ""}" data-layout-allow-overflow>'
            f'{icon_markup}</div>'
            f'<div class="zh" data-fitted-font-size="" data-overflow="unchecked"><span>{html.escape(card["zh"])}</span></div>'
            f'<div class="en" data-fitted-font-size="" data-overflow="unchecked"><span>{html.escape(card["en"])}</span></div>'
            f'</section>'
        )
        motion = dict(card["motion"])
        if short_truncated:
            motion.update({
                "variant": "sample-tail-safe-fade",
                "x": 0,
                "y": 0,
                "sx": 1,
                "sy": 1,
                "r": 0,
                "d": min(0.08, max(0.04, hold * 0.35)),
            })
        start = float(card["start"])
        end = float(card["end"])
        hold_start = start + float(motion["d"]) + 0.002
        motion_end = end + (0.10 if extends_into_next else (-0.05 if not short_truncated else 0.0))
        remaining = max(0.0 if short_truncated else 0.12, motion_end - hold_start)
        if high_fidelity:
            if remaining > 0:
                progressive_duration = min(high_fidelity_progressive_duration(remaining), remaining)
                progressive_motion = (
                    f'tl.to("#{card["id"]} .icon-entry",{{x:{profile["x"]},y:{profile["y"]},scale:{profile["scale"]},'
                    f'rotation:{profile["rotation"]},duration:{progressive_duration:.3f},ease:"none",'
                    f'immediateRender:false}},{hold_start:.3f});'
                )
            else:
                progressive_motion = ""
        else:
            segments = max(1, math.ceil(remaining / float(profile["cycle"])))
            segment_duration = remaining / segments
            repeat = segments - 1
            progressive_motion = (
                f'tl.to("#{card["id"]} .icon-entry",{{x:{profile["x"]},y:{profile["y"]},scale:{profile["scale"]},'
                f'rotation:{profile["rotation"]},duration:{segment_duration:.3f},ease:"sine.inOut",yoyo:true,repeat:{repeat},'
                f'immediateRender:false}},{hold_start:.3f});'
                f'window.hwBoil(tl,"#{card["id"]} .icon-boil",{{amp:{3.0 if card["emphasis"] else 2.2},'
                f'rot:{1.0 if card["emphasis"] else 0.72},frameDrop:3,seed:{card["icon_index"] + 1}}});'
            )
        text_exit = max(start, end - 0.10)
        icon_exit = end + 0.10 if extends_into_next else max(start, end - 0.05)
        icon_hide = end + 0.15 if extends_into_next else end
        if short_truncated:
            zh_duration = min(0.08, max(0.04, hold * 0.35))
            en_delay = min(0.03, hold * 0.15)
            en_duration = min(0.07, max(0.04, hold * 0.35))
            text_exit_motion = f'tl.set("#{card["id"]} .zh, #{card["id"]} .en",{{opacity:0}},{end:.3f});'
            icon_exit_motion = f'tl.set("#{card["id"]} .icon-entry",{{opacity:0}},{end:.3f});'
        else:
            zh_duration = 0.26
            en_delay = 0.09
            en_duration = 0.18
            text_exit_motion = (
                f'tl.to("#{card["id"]} .zh, #{card["id"]} .en",{{opacity:0,duration:.10,ease:"power1.in",'
                f'overwrite:"auto",immediateRender:false}},{text_exit:.3f});'
                f'tl.set("#{card["id"]} .zh, #{card["id"]} .en",{{opacity:0}},{end:.3f});'
            )
            icon_exit_motion = (
                f'tl.to("#{card["id"]} .icon-entry",{{opacity:0,duration:.05,ease:"power1.in",'
                f'overwrite:"auto",immediateRender:false}},{icon_exit:.3f});'
                f'tl.set("#{card["id"]} .icon-entry",{{opacity:0}},{icon_hide:.3f});'
            )
        tweens.append(
            f'tl.fromTo("#{card["id"]} .icon-entry",'
            f'{{opacity:0,x:{motion["x"]},y:{motion["y"]},scaleX:{motion["sx"]},scaleY:{motion["sy"]},rotation:{motion["r"]}}},'
            f'{{opacity:1,x:0,y:0,scaleX:1,scaleY:1,rotation:0,duration:{motion["d"]},ease:"power3.out",immediateRender:false}},{start:.3f});'
            f'{progressive_motion}'
            f'tl.fromTo("#{card["id"]} .zh",{{clipPath:"inset(0 100% 0 0)",opacity:1}},'
            f'{{clipPath:"inset(0 0% 0 0)",opacity:1,duration:{zh_duration:.3f},ease:"power2.out",immediateRender:false}},{start + .03:.3f});'
            f'tl.fromTo("#{card["id"]} .en",{{opacity:0,y:3}},'
            f'{{opacity:.92,y:0,duration:{en_duration:.3f},ease:"power2.out",immediateRender:false}},{start + en_delay:.3f});'
            f'{text_exit_motion}'
            f'{icon_exit_motion}'
        )
    header = [html.escape(value) for value in job["header"]]
    profiles_json = json.dumps(motion_profiles, ensure_ascii=False, separators=(",", ":"))
    profile = "benchmark-high-fidelity" if high_fidelity else "standard"
    header_transforms = (
        '.one{top:35px;font-size:64px;color:#edcd00}.two{top:119px;font-size:64px;color:#f5f5f5}.three{top:203px;font-size:64px;color:#edcd00}'
        if high_fidelity else
        '.one{left:calc(50% - 2px);top:42px;font-size:51px;color:#edcd00;transform:translateX(-50%) scaleX(1.007)}.two{left:calc(50% - 2px);top:125px;font-size:51px;color:#f5f5f5;transform:translateX(-50%) scaleX(1.044)}.three{left:calc(50% - 1px);top:207px;font-size:51px;color:#edcd00;transform:translateX(-50%) scaleX(.88)}'
    )
    header_transform = "translateX(-50%)" if high_fidelity else "translateX(-50%) scaleX(var(--header-scale,1))"
    paper_before = (
        'background:linear-gradient(112deg,rgba(255,250,241,.15),rgba(94,55,44,.08) 42%,rgba(255,238,225,.12));filter:none;mix-blend-mode:multiply;opacity:.72'
        if high_fidelity else
        'background:radial-gradient(ellipse at 7% 22%,rgba(70,147,151,.20) 0 5%,transparent 31%),radial-gradient(ellipse at 81% 15%,rgba(228,169,87,.19) 0 6%,transparent 34%),radial-gradient(ellipse at 63% 80%,rgba(158,83,99,.16) 0 8%,transparent 35%),radial-gradient(ellipse at 19% 85%,rgba(211,116,84,.17) 0 7%,transparent 33%);filter:blur(18px);mix-blend-mode:multiply;opacity:.60'
    )
    paper_overlay_opacity = ".42" if high_fidelity else ".26"
    icon_stroke = 13 if high_fidelity else 11
    mark_stroke = 8 if high_fidelity else 7
    icon_color = "#666" if high_fidelity else "#707070"
    solid_color = "#696969" if high_fidelity else "#747474"
    text_color = "#050505" if high_fidelity else "#080808"
    zh_text_stroke = ".55" if high_fidelity else ".45"
    zh_size, zh_floor = (50, 36) if high_fidelity else (46, 22)
    en_size, en_floor = (21, 12) if high_fidelity else (19, 10)
    header_fit_call = "fitHeadersByFontSize(64,44,0.90);" if high_fidelity else ""
    standard_motion_helpers = "" if high_fidelity else '''
window.hwOnUpdate=function(timeline,fn){if(!timeline.__hwRenders){timeline.__hwRenders=[];timeline.eventCallback("onUpdate",function(){for(var i=0;i<timeline.__hwRenders.length;i++)timeline.__hwRenders[i]();});}timeline.__hwRenders.push(fn);fn();};
window.hwHash=function(n,seed){var value=Math.sin(n*127.1+(seed||1)*311.7)*43758.5453;return(value-Math.floor(value))*2-1;};
window.hwBoil=function(timeline,target,opts){opts=opts||{};var elements=gsap.utils.toArray(target);window.hwOnUpdate(timeline,function(){var step=Math.floor((timeline.time()*(opts.fps||30))/(opts.frameDrop||3));for(var i=0;i<elements.length;i++){gsap.set(elements[i],{x:window.hwHash(step*3+i*97,opts.seed||1)*(opts.amp||1.25),y:window.hwHash(step*3+1+i*97,opts.seed||1)*(opts.amp||1.25),rotation:window.hwHash(step*3+2+i*97,opts.seed||1)*(opts.rot||.42)});}});};'''
    icon_motion_css = ".icon-entry{display:flex;align-items:center;justify-content:center;transform-origin:50% 50%;will-change:transform,opacity}" if high_fidelity else ".icon-entry,.icon-boil{display:flex;align-items:center;justify-content:center;transform-origin:50% 50%;will-change:transform,opacity}"
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"/><meta name="viewport" content="width=720,height=960"/>
<title>{html.escape(job["title"])}</title><script src="node_modules/gsap/dist/gsap.min.js"></script>
<style>
@font-face{{font-family:HeaderFrozen;src:url("assets/header.ttf");font-weight:900;font-display:block}}
@font-face{{font-family:HandStyleFrozen;src:url("assets/handwriting.ttf");font-weight:700;font-display:block}}
@font-face{{font-family:SansFrozen;src:url("assets/sans.ttf");font-weight:400 900;font-display:block}}
@font-face{{font-family:EnglishFrozen;src:url("assets/english.ttf");font-weight:400;font-display:block}}
*{{box-sizing:border-box}}html,body{{margin:0;width:720px;height:960px;overflow:hidden;background:#000}}
#root{{position:relative;width:720px;height:960px;overflow:hidden;background:#000}}.clip{{position:absolute;overflow:hidden}}
.fixed-header{{position:absolute;z-index:10;left:0;top:0;width:720px;height:277px;background:#000;color:#f5f5f5;text-align:center;overflow:hidden;font-family:HeaderFrozen,SansFrozen,sans-serif;font-weight:900;letter-spacing:-2.4px}}
.header-row{{position:absolute;display:block;left:50%;width:max-content;line-height:1;white-space:nowrap;transform:{header_transform};transform-origin:50% 50%;-webkit-text-stroke:1.2px currentColor}}
{header_transforms}
.paper{{position:absolute;left:0;top:277px;width:720px;height:406px;overflow:hidden;background:#d9c1b8}}.paper img{{position:absolute;inset:0;width:720px;height:406px;display:block}}
.paper::before{{content:"";position:absolute;inset:-24px;z-index:1;{paper_before}}}
.paper::after{{content:"";position:absolute;inset:0;z-index:2;background:repeating-linear-gradient(17deg,rgba(255,255,255,.16) 0 .55px,rgba(66,39,30,.10) .7px 1.25px,transparent 1.45px 3.15px),repeating-linear-gradient(107deg,rgba(255,255,255,.10) 0 .45px,rgba(76,48,38,.08) .65px 1.1px,transparent 1.3px 3.7px);mix-blend-mode:overlay;opacity:{paper_overlay_opacity}}}
.content-card{{left:0;top:277px;width:720px;height:406px;color:#080808;z-index:3}}.icon-layer{{position:absolute;left:0;top:39px;width:720px;height:205px;display:flex;align-items:center;justify-content:center;color:#747474;transform-origin:50% 50%}}.icon-layer.emphasis{{top:12px;height:248px}}
{icon_motion_css}.icon-layer svg{{display:block;overflow:visible}}.icon-art{{fill:none;stroke:{icon_color};stroke-width:{icon_stroke};stroke-linecap:round;stroke-linejoin:round}}.icon-art .scene-marks{{stroke-width:{mark_stroke}}}.icon-art .solid{{fill:{solid_color};stroke:none}}
.zh{{position:absolute;left:33px;top:255px;width:654px;height:62px;display:block;white-space:nowrap;text-align:center;color:{text_color};font-family:HandStyleFrozen,SansFrozen,sans-serif;font-size:{zh_size}px;font-weight:700;line-height:1.15;letter-spacing:-1.5px;-webkit-text-stroke:{zh_text_stroke}px {text_color}}}
.en{{position:absolute;left:24px;top:339px;width:672px;height:42px;text-align:center;white-space:nowrap;color:{text_color};font-family:EnglishFrozen,SansFrozen,sans-serif;font-size:{en_size}px;font-weight:400;line-height:24px;letter-spacing:-.15px}}
.zh span,.en span{{display:inline-block;white-space:nowrap}}
</style></head><body><div id="root" data-composition-id="{job['id']}" data-production-profile="{profile}" data-duration="{timeline['duration']}" data-fps="30" data-width="720" data-height="960" aria-label="纸纹手写风格字形逐句卡片视频；字形不冒充真人手写">
<header class="fixed-header"><div class="header-row one" data-horizontal-scale="1" data-fitted-font-size="" data-rendered-width-ratio="" data-overflow="unchecked">{header[0]}</div><div class="header-row two" data-horizontal-scale="1" data-fitted-font-size="" data-rendered-width-ratio="" data-overflow="unchecked">{header[1]}</div><div class="header-row three" data-horizontal-scale="1" data-fitted-font-size="" data-rendered-width-ratio="" data-overflow="unchecked">{header[2]}</div></header>
<div class="paper" aria-hidden="true"><img src="assets/paper-texture-v11.png" alt=""/></div>{''.join(cards_html)}
<audio id="voiceover" src="assets/voiceover_master.m4a" data-start="0" data-duration="{timeline['duration']}" data-track-index="10" data-volume="1"></audio>
<script>
window.__timelines=window.__timelines||{{}};const motionProfiles={profiles_json};{standard_motion_helpers}
function fitText(selector,start,min,step){{document.querySelectorAll(selector).forEach(function(el){{var inner=el.querySelector("span")||el;var size=start;var renderedWidth=function(){{return Math.max(inner.getBoundingClientRect().width,el.scrollWidth);}};el.style.fontSize=size+"px";while(size>min&&renderedWidth()>el.clientWidth+.25){{size=Math.max(min,size-step);el.style.fontSize=size+"px";}}var overflow=renderedWidth()>el.clientWidth+.5;el.dataset.fittedFontSize=String(size);el.dataset.overflow=overflow?"true":"false";if(overflow)document.documentElement.dataset.layoutOverflow="true";}});}}
function fitHeadersByFontSize(start,min,maxRatio){{document.querySelectorAll(".header-row").forEach(function(el){{var size=start;var maximum=720*maxRatio;el.style.fontSize=size+"px";var rendered=function(){{return Math.max(1,el.getBoundingClientRect().width);}};while(size>min&&rendered()>maximum+.25){{size=Math.max(min,size-1);el.style.fontSize=size+"px";}}var width=rendered();var overflow=width>maximum+.5;el.dataset.fittedFontSize=String(size);el.dataset.renderedWidthRatio=String(width/720);el.dataset.horizontalScale="1";el.dataset.overflow=overflow?"true":"false";if(overflow)document.documentElement.dataset.layoutOverflow="true";}});}}
const tl=gsap.timeline({{paused:true}});{''.join(tweens)}
document.fonts.ready.then(function(){{fitText(".zh",{zh_size},{zh_floor},1);fitText(".en",{en_size},{en_floor},.5);{header_fit_call}window.__timelines["{job['id']}"]=tl;}});
</script></div></body></html>'''


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build(args: argparse.Namespace) -> Path:
    job = load_job(args.job)
    verify_approval(job, args.approval)
    output = assert_new_output(args.output)
    alignment_path = Path(args.alignment).expanduser().resolve()
    audio_manifest_path = Path(args.audio_manifest).expanduser().resolve()
    master_audio = Path(args.master_audio).expanduser().resolve()
    for path in (alignment_path, audio_manifest_path, master_audio, PAPER_TEXTURE):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    font_paths = {
        "header.ttf": Path(args.header_font).expanduser().resolve(),
        "handwriting.ttf": Path(args.handwriting_font).expanduser().resolve(),
        "sans.ttf": Path(args.sans_font).expanduser().resolve(),
        "english.ttf": Path(args.english_font).expanduser().resolve(),
    }
    for path in font_paths.values():
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    alignment, audio = _load_json(alignment_path), _load_json(audio_manifest_path)
    timeline = make_timeline(job, alignment, audio, max_duration=getattr(args, "max_duration", None))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.building-", dir=output.parent))
    try:
        assets = staging / "assets"
        shared = staging / "shared"
        qc = staging / "qc"
        for folder in (assets, shared, qc, staging / "renders"):
            folder.mkdir(parents=True, exist_ok=True)
        for name, source in font_paths.items():
            shutil.copy2(source, assets / name)
        shutil.copy2(master_audio, assets / "voiceover_master.m4a")
        shutil.copy2(PAPER_TEXTURE, assets / "paper-texture-v11.png")
        (shared / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (shared / "card-midpoints.json").write_text(json.dumps(timeline["card_midpoints"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "index.html").write_text(render_html(job, timeline), encoding="utf-8")
        (staging / "package.json").write_text(json.dumps({
            "name": job["id"], "private": True, "type": "module",
            "scripts": {
                "check": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} check",
                "render": f"npx --yes hyperframes@{HYPERFRAMES_VERSION} render",
            },
            "dependencies": {"gsap": "3.14.2"},
        }, indent=2) + "\n", encoding="utf-8")
        (staging / "hyperframes.json").write_text(json.dumps({
            "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
            "media": {"autoProxy": True}, "authoringSkill": "yuanqi-paper-card-video",
        }, indent=2) + "\n", encoding="utf-8")
        middle = timeline["cards"][len(timeline["cards"]) // 2]["id"]
        last = timeline["cards"][-1]["id"]
        (staging / "index.motion.json").write_text(json.dumps({
            "duration": timeline["duration"],
            "maxStaticSec": 1.0,
            "assertions": [
                {"kind": "appearsBy", "selector": ".header-row.one", "bySec": 0.1},
                {"kind": "staysInFrame", "selector": f"#{middle}"},
                {"kind": "staysInFrame", "selector": f"#{last}"},
            ],
        }, indent=2) + "\n", encoding="utf-8")
        (staging / "design.md").write_text(
            "# Design truth\n\n720x960 / 30fps。顶部 277px 黑底黄白黄三行标题；中部 406px V11 纸纹；底部 277px 纯黑。"
            "中文 46px、英文 19px 起步，字体加载后按真实宽度缩小。横向语义线稿持续微动，换卡图标延迟退场防空闪。"
            "正文使用冻结的手写风格字形，不宣称真人手写。\n",
            encoding="utf-8",
        )
        manifest = {
            "status": "BUILT_NOT_RENDERED",
            "job": str(Path(args.job).expanduser().resolve()),
            "manuscript_sha256": job["_manuscript_sha256"],
            "alignment_sha256": sha256_file(alignment_path),
            "audio_manifest_sha256": sha256_file(audio_manifest_path),
            "master_audio_sha256": sha256_file(master_audio),
            "hyperframes_version": HYPERFRAMES_VERSION,
            "card_midpoints": len(timeline["card_midpoints"]),
            "frozen_assets": {
                **{name: sha256_file(path) for name, path in font_paths.items()},
                "paper-texture-v11.png": sha256_file(PAPER_TEXTURE),
            },
        }
        (staging / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--job", required=True)
    result.add_argument("--approval", required=True)
    result.add_argument("--alignment", required=True)
    result.add_argument("--audio-manifest", required=True)
    result.add_argument("--master-audio", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--header-font", required=True)
    result.add_argument("--handwriting-font", required=True)
    result.add_argument("--sans-font", required=True)
    result.add_argument("--english-font", required=True)
    result.add_argument("--max-duration", type=float)
    return result


if __name__ == "__main__":
    built = build(parser().parse_args())
    print(json.dumps({"status": "BUILT_NOT_RENDERED", "project": str(built)}, ensure_ascii=False, indent=2))
