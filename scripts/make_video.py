#!/usr/bin/env python3
"""Build new content with the packaged V55 renderer; never draw a replacement style."""
import argparse
import copy
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
if str(SKILL/'scripts') not in sys.path:
    sys.path.insert(0, str(SKILL/'scripts'))
TEMPLATE = SKILL / 'assets/v55'
ALLOWED = {'schema_version', 'title', 'duration', 'manuscript', 'narration',
           'alignment', 'captions', 'visuals', 'opening', 'provenance',
           'render_mode', 'asset_bundle'}
RENDER_MODES = {'fixed-v55', 'diverse-v55'}
# New manuscripts should automatically receive a traceable visual variant.
# `fixed-v55` remains available as an explicit regression/reference mode.
DEFAULT_RENDER_MODE = 'diverse-v55'
VISUAL_FIELDS = {'preset', 'start', 'end', 'meaning', 'asset_family', 'variant_id'}


def fail(code, detail):
    raise ValueError(f'{code}: {detail}')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def write_json(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def normalized(s):
    return ''.join(c.lower() for c in s if c.isalnum())


def manuscript_text(s):
    return ''.join(s.split())


def bundle_lock():
    lock = read_json(TEMPLATE / 'baseline.lock.json')
    for rel, expected in lock['files'].items():
        p = TEMPLATE / rel
        if not p.is_file() or sha(p) != expected:
            fail('TEMPLATE_TAMPERED', rel)
    return lock


def _stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def resolve_asset_selection(job):
    """Fixed layout; only SHA-bound, reviewed body sprites may differ."""
    mode = job.get('render_mode', DEFAULT_RENDER_MODE)
    if mode not in RENDER_MODES:
        fail('RENDER_MODE', str(mode))
    if mode == 'fixed-v55':
        if job.get('asset_bundle'):
            fail('FIXED_MODE_WITH_BUNDLE', 'remove unused bundle or choose diverse-v55')
        visuals = []
    else:
        if not job.get('asset_bundle'):
            fail('ASSET_GENERATION_REQUIRED', 'run generated_assets.py plan; generate/review/bind assets before build')
        if job.get('opening', {}).get('variant_id') or job.get('opening', {}).get('asset_family'):
            fail('OPENING_LAYOUT_LOCKED', 'the V55 opening layout is fixed')
        from generated_assets import load_bundle
        visuals = load_bundle(job['asset_bundle'], job)
        for i, visual in enumerate(job['visuals']):
            if visual.get('variant_id') and (not visuals[i] or visual['variant_id'] != visuals[i]['variant_id']):
                fail('BUNDLE_VARIANT_MISMATCH', str(i))
    payload = {'render_mode': mode, 'pool_version': None,
               'selection_policy': 'fixed-v55' if mode == 'fixed-v55' else 'reviewed-manuscript-bound-body-bundle-v1',
               'manuscript_sha256': job.get('manuscript', {}).get('sha256'),
               'opening': None, 'opening_policy': 'fixed-v55', 'visuals': visuals,
               'candidate_status': 'NOT_USER_APPROVED' if mode == 'diverse-v55' else None}
    payload['selection_sha256'] = sha256_text(_stable_json(payload))
    return payload


def sha256_text(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def append_to_main_wrap(markup, child):
    """Insert one variant layer into the existing main wrap without new motion."""
    match = re.search(r'<div\b[^>]*class="motion-plane main"[^>]*>', markup)
    main = match.start() if match else -1
    if main < 0:
        fail('ASSET_BIND_TARGET_MISSING', 'main motion plane')
    wrap = markup.find('<div class="wrap">', main)
    if wrap < 0:
        fail('ASSET_BIND_TARGET_MISSING', 'main wrap')
    depth = 0
    for match in re.finditer(r'<div\b[^>]*>|</div>', markup[wrap:], re.S):
        token = match.group(0)
        if token.startswith('<div'):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                close = wrap + match.start()
                return markup[:close] + child + markup[close:]
    fail('ASSET_BIND_TARGET_MISSING', 'unclosed main wrap')


def template_parts():
    source = (TEMPLATE / 'index.html').read_text()
    declaration = re.search(r'<script>const captions=(.*?),scenes=(.*?),duration=180;', source)
    if not declaration:
        fail('TEMPLATE_PARSE', 'V55 content declaration missing')
    scenes = json.loads(declaration.group(2))
    presets = {}
    for scene in scenes:
        art = scene['art']
        if art not in presets:
            sid = scene['scene']
            markup = re.search(r'<section id="art-' + str(sid) + r'".*?</section>', source, re.S).group()
            presets[art] = {'meta': scene, 'markup': markup, 'slot': sid}
    return source, presets


def checked_input(info, base):
    p = Path(info['path']).expanduser()
    p = p if p.is_absolute() else base / p
    p = p.resolve()
    if not p.is_file():
        fail('MISSING_INPUT', str(p))
    if sha(p) != info['sha256']:
        fail('INPUT_HASH_MISMATCH', str(p))
    info['path'] = str(p)
    return p


def validate_job(job, base, require_assets=True):
    extra = set(job) - ALLOWED
    if extra:
        fail('UNKNOWN_FIELD', ', '.join(sorted(extra)))
    if job.get('schema_version') != 2:
        fail('SCHEMA', 'schema_version must be 2')
    if job.get('render_mode', DEFAULT_RENDER_MODE) not in RENDER_MODES:
        fail('RENDER_MODE', f'expected one of {sorted(RENDER_MODES)}')
    lock = bundle_lock()
    _, presets = template_parts()
    source = checked_input(job['manuscript'], base)
    checked_input(job['narration'], base)
    aligned = checked_input(job['alignment'], base)
    voice = job['narration']
    if voice['source_sha256'] != job['manuscript']['sha256']:
        fail('AUDIO_SOURCE_MISMATCH', 'audio must belong to this exact manuscript')
    if voice.get('provider') != lock['voice']['provider'] or voice.get('voice_id') != lock['voice']['id']:
        fail('VOICE_MISMATCH', 'use the validated 真人播客女 voice and its provenance')
    alignment = read_json(aligned)
    if job['alignment'].get('format') == 'paper-card-token-offsets':
        if alignment.get('alignment_source') != 'whisper_full_json_token_offsets' or not alignment.get('scenes'):
            fail('TOKEN_ALIGNMENT_REQUIRED', str(aligned))
        if any(s.get('alignment_source') != 'whisper_token_offsets' for s in alignment['scenes']):
            fail('TOKEN_ALIGNMENT_REQUIRED', 'every scene needs real token alignment')
    elif not (alignment.get('source') == 'whisper_token_offsets' and alignment.get('tokens')):
        fail('TOKEN_ALIGNMENT_REQUIRED', str(aligned))
    duration = float(job['duration'])
    if not math.isfinite(duration) or duration <= 0:
        fail('DURATION', 'positive finite seconds required')
    if manuscript_text(''.join(c['text'] for c in job['captions'])) != manuscript_text(source.read_text()):
        fail('MANUSCRIPT_MISMATCH', 'captions must preserve the full approved text, not a summary')
    if job['alignment'].get('format') != 'paper-card-token-offsets':
        tokens = alignment['tokens']
        if len(tokens) != len(job['captions']):
            fail('CAPTION_ALIGNMENT_MISMATCH', 'the direct token contract needs one aligned phrase per caption')
        for caption, token in zip(job['captions'], tokens):
            if (normalized(caption['text']) != normalized(token['text']) or
                    abs(float(caption['start']) - float(token['start'])) > .002 or
                    abs(float(caption['end']) - float(token['end'])) > .002):
                fail('CAPTION_ALIGNMENT_MISMATCH', caption['text'])
    previous = 0
    for i, c in enumerate(job['captions']):
        start, end = float(c['start']), float(c['end'])
        if not c['text'].strip() or not c.get('en', '').strip():
            fail('CAPTION_TEXT', f'caption {i} needs Chinese and corresponding English')
        if not all(math.isfinite(v) for v in (start, end)) or start < previous - .002 or end <= start or end > duration + .034:
            fail('CAPTION_TIMING', f'caption {i}')
        if start - previous > .5:
            fail('CAPTION_GAP', f'caption {i} leaves more than .5 seconds blank')
        previous = end
    if duration - previous > .5:
        fail('CAPTION_TAIL', 'last caption does not cover the ending')
    opening = job.get('opening', {'duration': 4.86})
    opening_end = float(opening.get('duration', 4.86))
    if not 0 <= opening_end <= min(8, duration):
        fail('OPENING_DURATION', '0–8 seconds within the narration')
    if opening_end and (len(opening.get('lines', [])) != 3 or not opening.get('tag')):
        fail('OPENING_COPY', 'three blackboard lines and one short tag are required')
    previous = opening_end
    for i, v in enumerate(job['visuals']):
        if set(v) - VISUAL_FIELDS:
            fail('UNKNOWN_VISUAL_FIELD', str(i))
        if v['preset'] not in presets:
            fail('UNKNOWN_PRESET', v['preset'])
        start, end = float(v['start']), float(v['end'])
        if not all(math.isfinite(t) for t in (start, end)) or abs(start - previous) > .034 or end <= start or end > duration + .034:
            fail('VISUAL_TIMING', f'visual {i} must cover the content continuously after the opening')
        if not v.get('meaning', '').strip():
            fail('VISUAL_MEANING', 'record why this illustration fits this sentence')
        previous = end
    if abs(previous - duration) > .034:
        fail('VISUAL_TAIL', 'illustrations do not cover the ending')
    # Resolve before building so unknown/unauthorized variants fail closed.
    if require_assets:
        if job.get('asset_bundle'):
            checked_input(job['asset_bundle'], base)
        resolve_asset_selection(job)
    for record in job.get('provenance', {}).values():
        if isinstance(record, dict) and 'path' in record and 'sha256' in record:
            checked_input(record, base)
    if job['alignment'].get('format') == 'paper-card-token-offsets':
        from paper_input import validate_imported_job
        validate_imported_job(job)
    return lock


def caption_html(c, opening_end):
    opening = c['start'] < opening_end
    width = 104 if opening else 72
    # V55 fixed type size. Long strings are an input splitting problem, not a reason to shrink the style.
    max_chars = 11 if opening else 16
    if len(c['text']) > max_chars:
        fail('CAPTION_TOO_LONG', f"{c['text']}: split at actual token boundaries (max {max_chars})")
    glyphs = []
    for char in c['text']:
        escaped = html.escape(char)
        text = f'<text x="{width/2}" y="90" style="font-size:{width}px">{escaped}</text>'
        if not opening:
            text += f'<text class="white-core" data-layout-allow-overlap x="{width/2}" y="90" style="font-size:{width}px">{escaped}</text>'
        glyphs.append(f'<span class="glyph" data-width="{width}"><svg width="{width}" height="120" viewBox="0 0 {width} 120" aria-hidden="true">{text}</svg></span>')
    english = ''.join(f'<span class="eglyph" data-width="20"><svg width="20" height="70" viewBox="0 0 20 70" aria-hidden="true"><text x="0" y="45">{html.escape(ch)}</text></svg></span>' for ch in c['en'])
    cursors = c['caption_mode'] == 'cursor'
    return (f'<section id="caption-{c["index"]}" data-entrance-type="{c["entrance_type"]}" class="caption clip {"opening-caption" if opening else "body-caption"}" data-start="{c["start"]}" data-duration="{c["end"]-c["start"]}" data-track-index="2">'
            f'<div class="zh" aria-label="{html.escape(c["text"], quote=True)}">' + ''.join(glyphs) + ('<i class="cursor-zh" aria-hidden="true"></i>' if cursors else '') + '</div>'
            f'<div class="en" aria-label="{html.escape(c["en"], quote=True)}">' + english + ('<i class="cursor-en" aria-hidden="true"></i>' if cursors else '') + '</div></section>')


def compose(job, output_duration, selection=None):
    source, presets = template_parts()
    selection = selection or resolve_asset_selection(job)
    opening_end = float(job.get('opening', {}).get('duration', 4.86))
    head = source[:source.index('<div id="root"')]
    # Preserve slot-specific calibrated geometry even when new content changes order or repeats an illustration.
    head = re.sub(r'#art-(\d+)\b', r'.art[data-preset="art-\1"]', head)
    head = re.sub(r'<title>.*?</title>', '<title>卡通动效视频生产 V2</title>', head)
    diverse_css = []
    for record in selection.get('visuals', []):
        if record and record['bind_mode'] == 'sprite':
            diverse_css.append(f'#art-{record["ordinal"] - 1} .sprite{{visibility:hidden!important}}')

    if diverse_css:
        head += '<style>' + ''.join(diverse_css) + '</style>'
    root = f'<div id="root" data-composition-id="cartoon-v55" data-duration="{output_duration}" data-fps="30" data-width="1280" data-height="720">'
    paper_filter = re.search(r'<filter id="paper-grade".*?</filter>', source, re.S).group()
    phone_filter = re.search(r'<filter id="phone-diagonal".*?</filter>', source, re.S).group()
    filters = [paper_filter, phone_filter.replace('id="phone-diagonal"', 'id="phone-diagonal-template"')]
    if any(r and r.get('background_mode') == 'white-key' for r in selection.get('visuals', [])):
        # Display-only key mask for opaque white-backed sprites. Keep RGB fills;
        # the unmodified source PNG is archived with its actual background mode.
        filters.append('<filter id="asset-white-key" x="-2%" y="-2%" width="104%" height="104%" color-interpolation-filters="sRGB"><feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -1 -1 -1 0 3" result="key"/><feComponentTransfer in="key" result="keyAlpha"><feFuncA type="linear" slope="25" intercept="-3"/></feComponentTransfer><feMorphology in="keyAlpha" operator="erode" radius="0.5" result="edgeMask"/><feComposite in="SourceGraphic" in2="edgeMask" operator="in"/></filter>')
    opening = ''
    if opening_end:
        opening = re.search(r'<section id="intro".*?</section>', source, re.S).group()
        opening = opening.replace('data-duration="4.86"', f'data-duration="{opening_end}"')
        opening_record = selection.get('opening')
        if opening_record and opening_record['bind_mode'] == 'intro':
            opening = opening.replace('src="assets/intro.png"', f'src="{opening_record["output_path"]}"', 1)
            opening = opening.replace(
                '<section id="intro"',
                f'<section id="intro" data-asset-family="{html.escape(opening_record["asset_family"], quote=True)}" data-variant-id="{html.escape(opening_record["variant_id"], quote=True)}"',
                1,
            )
        opening = re.sub(r'(<div class="board-copy"[^>]*>).*?(</div>)', lambda m: m[1] + '<br>'.join(html.escape(x) for x in job['opening']['lines']) + m[2], opening)
        opening = re.sub(r'(<div class="tag"[^>]*>).*?(</div>)', lambda m: m[1] + html.escape(job['opening']['tag']) + m[2], opening)
    arts, scenes = [], []
    for i, visual in enumerate(job['visuals']):
        if visual['start'] >= output_duration:
            break
        preset = presets[visual['preset']]
        s = copy.deepcopy(preset['meta'])
        s.update(scene=i, start=visual['start'], visual_start=visual['start'], end=visual['end'])
        asset_record = selection.get('visuals', [])[i] if i < len(selection.get('visuals', [])) else None
        if asset_record:
            s.update(asset_family=asset_record['asset_family'], variant_id=asset_record['variant_id'],
                     asset_sha256=asset_record['sha256'])
        scenes.append(s)
        markup = preset['markup'].replace(f'id="art-{preset["slot"]}"', f'id="art-{i}" data-preset="art-{preset["slot"]}"')
        if asset_record:
            attrs = (f' data-asset-family="{html.escape(asset_record["asset_family"], quote=True)}"'
                     f' data-variant-id="{html.escape(asset_record["variant_id"], quote=True)}"'
                     f' data-bind-mode="{html.escape(asset_record["bind_mode"], quote=True)}"')
            markup = markup.replace(f'<section id="art-{i}"', f'<section id="art-{i}"{attrs}', 1)
        markup = re.sub(r'data-start="[^"]+"', f'data-start="{visual["start"]}"', markup, count=1)
        markup = re.sub(r'data-duration="[^"]+"', f'data-duration="{visual["end"]-visual["start"]}"', markup, count=1)
        markup = markup.replace('phone-diagonal)', f'phone-diagonal-{i})')
        markup = markup.replace('v14-family-horizontal', f'v14-family-horizontal-{i}')
        arts.append(markup)
        filters.append(phone_filter.replace('id="phone-diagonal"', f'id="phone-diagonal-{i}"'))
        for kind in ['listen-horizontal', 'blocks-vertical']:
            filters.append(f'<filter id="v23-{kind}-{i}" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="0 0"/></filter>')
        if asset_record and asset_record['bind_mode'] == 'sprite':
            ov = asset_record['overlay']
            overlay = (f'<img class="diverse-asset" data-asset-family="{html.escape(asset_record["asset_family"], quote=True)}" '
                       f'data-variant-id="{html.escape(asset_record["variant_id"], quote=True)}" '
                       f'src="{asset_record["output_path"]}" alt="" aria-hidden="true" '
                       f'style="position:absolute;left:{float(ov["left"]):g}px;top:{float(ov["top"]):g}px;'
                       f'width:{float(ov["width"]):g}px;height:{float(ov["height"]):g}px;'
                       f'display:block;pointer-events:none;z-index:3;object-fit:contain;filter:{"url(#asset-white-key)" if asset_record.get("background_mode") == "white-key" else "none"};"/>')
            markup = append_to_main_wrap(markup, overlay)
            arts[-1] = markup
    caps = []
    for i, raw in enumerate(job['captions']):
        if raw['start'] >= output_duration:
            break
        c = copy.deepcopy(raw)
        c.update(index=i, duration=c['end']-c['start'], alignment_source='whisper_token_offsets')
        is_open = c['start'] < opening_end
        c['caption_mode'] = 'cursor' if (not is_open and i % 4 == 3) else 'pop'
        c['entrance_type'] = 'cursor_reveal' if c['caption_mode'] == 'cursor' else 'pop'
        c['reveal_family'] = 'preserved_v12_opening' if is_open else 'v55_body'
        # The packaged reveal style is reused; short captions finish early enough to remain readable.
        step = min(1/30 if is_open else .045, max(.012, (c['duration']-.5)/max(1,len(c['text']))))
        c['reveal'] = {'zh_step': step, 'zh_tail': .16 if is_open else .22,
                        'en_start': .02, 'en_step': min(.013, max(.003, (c['duration']-.45)/max(1,len(c['en'])))), 'en_tail': .1}
        caps.append(c)
    captions = ''.join(caption_html(c, opening_end) for c in caps)
    runtime = source[source.index('// V31: general English'):source.index('</script><svg width="0" height="0"', source.index('// V31: general English'))]
    # Generalize original id-specific loaders; absent, unused presets are not missing assets.
    for old in (12,18,20,21,22,30):
        runtime = runtime.replace(f"'#art-{old} .sprite'", f"'.art[data-preset=\"art-{old}\"] .sprite'")
    runtime = runtime.replace("if(!sprites.length){reject(new Error('Identity target missing: '+url));return;}", "if(!sprites.length){resolve();return;}")
    runtime = runtime.replace("if(!sprites.length){reject(new Error('Flat target missing: '+s.selector));return;}", "if(!sprites.length){resolve();return;}")
    runtime = runtime.replace("tl.set('#intro',{opacity:0},4.86)", f"tl.set('#intro',{{opacity:0}},{opening_end})")
    runtime = runtime.replace("document.querySelector('#v14-family-horizontal feGaussianBlur')", "document.querySelector('#v14-family-horizontal-'+s.scene+' feGaussianBlur')")
    runtime = runtime.replace("filter:'url(#v14-family-horizontal)'", "filter:'url(#v14-family-horizontal-'+s.scene+')'")
    runtime = runtime.replace("'#phone-diagonal feOffset'", "'#phone-diagonal-'+s.scene+' feOffset'")
    runtime = runtime.replace("'#phone-diagonal feGaussianBlur'", "'#phone-diagonal-'+s.scene+' feGaussianBlur'")
    runtime = runtime.replace("document.querySelector('#phone-diagonal')", "document.querySelector('#phone-diagonal-template')")
    # This prop switch belongs to the old manuscript, not to the template.
    runtime = re.sub(r"tl.set\('#art-16',\{attr:.*?;\n", '', runtime)
    runtime = runtime.replace('c.end<=4.861', f'c.end<={opening_end+.001}')
    runtime = runtime.replace("window.__timelines['f26-v29']", "window.__timelines['cartoon-v55']")
    runtime = runtime.replace("tl.set(el,{opacity:1},start);\nif(s.art", "tl.set(el,{opacity:1},start);\nif(s.end-start<.9){tl.set(wrap,{x:0,y:0,scale:1,rotation:0},start);tl.fromTo(el,{opacity:0},{opacity:1,duration:Math.min(.15,(s.end-start)/3),ease:'none'},start);tl.set(el,{opacity:0},s.end);continue;}\nif(s.art", 1)
    # Preload every used image before the seekable timeline is registered.
    media = [str(p.relative_to(TEMPLATE)) for p in (TEMPLATE/'assets').iterdir() if p.suffix in {'.png','.jpg','.svg'}]
    media.extend(record['output_path'] for record in [selection.get('opening')] + selection.get('visuals', []) if record)
    preload = 'const mediaReady=Promise.all('+json.dumps(media)+'.map(url=>new Promise((resolve,reject)=>{const im=new Image();im.onload=resolve;im.onerror=()=>reject(new Error("Asset load: "+url));im.src=url;})));\n'
    runtime = runtime.replace('Promise.all([document.fonts.ready,englishMetricsReady', 'Promise.all([mediaReady,document.fonts.ready,englishMetricsReady')
    declarations = f'const captions={json.dumps(caps,ensure_ascii=False)},scenes={json.dumps(scenes,ensure_ascii=False)},duration={output_duration};\n'
    # Stop silent promise failures from being mistaken for a finished frame.
    runtime = runtime.replace('window.__sampleReady=true;});', 'window.__sampleReady=true;}).catch(e=>{window.__buildError=String(e);console.error(e);});')
    return (head+root+'<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'+''.join(filters)+'</defs></svg><div class="paper"></div>'+opening+''.join(arts)+captions+
            f'<audio id="voiceover" src="assets/narration{Path(job["narration"]["path"]).suffix}" data-start="0" data-duration="{output_duration}" data-track-index="10" data-volume="1"></audio></div>'+
            '<script>'+declarations+preload+runtime+'</script></body></html>'), caps, scenes


def asset_coverage(visuals, records, duration, mode):
    rows=[]
    for i,v in enumerate(visuals):
        if v['start']>=duration:break
        record=records[i] if i<len(records) else None
        rows.append({'visual_index':i,'preset':v['preset'],'start':v['start'],
                     'end':min(v['end'],duration),'status':'replaced' if record else 'kept_v55',
                     'variant_id':record['variant_id'] if record else None,
                     'reason':record['reason'] if record else ('explicit fixed-v55' if mode=='fixed-v55' else 'no reviewed replacement bound; disclose in report')})
    return {'scope_seconds':duration,'body_segments':len(rows),
            'replaced_segments':sum(r['status']=='replaced' for r in rows),
            'kept_v55_segments':sum(r['status']=='kept_v55' for r in rows),'rows':rows}


def build(job_path, output, seconds=None):
    if output.exists():
        fail('OUTPUT_EXISTS', str(output))
    job = read_json(job_path)
    # Make the implicit policy explicit in every build artifact. This keeps
    # old plans readable while ensuring a new manuscript never silently falls
    # back to the fixed V55 artwork.
    job.setdefault('render_mode', DEFAULT_RENDER_MODE)
    lock = validate_job(job, job_path.parent)
    selection = resolve_asset_selection(job)
    duration = min(float(seconds),job['duration']) if seconds else job['duration']
    if job['render_mode'] == 'diverse-v55' and not any(r and job['visuals'][i]['start'] < duration for i,r in enumerate(selection['visuals'])):
        fail('SAMPLE_HAS_NO_VARIATION', 'bind at least one reviewed sprite inside sample range')
    if duration <= 0:
        fail('DURATION', 'sample seconds must be positive')
    markup, caps, scenes = compose(job, duration, selection)
    output.mkdir(parents=True)
    shutil.copytree(TEMPLATE/'assets', output/'assets')
    selected = [r for r in [selection.get('opening')] + selection.get('visuals', []) if r]
    for record in selected:
        src = SKILL / record['source_path']
        dst = output / record['output_path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    if job.get('asset_bundle'):
        shutil.copytree(Path(job['asset_bundle']['path']).parent, output/'asset-evidence')
    shutil.copy2(TEMPLATE/'caption-types.js', output/'caption-types.js')
    shutil.copy2(job['narration']['path'], output/'assets'/('narration'+Path(job['narration']['path']).suffix))
    (output/'index.html').write_text(markup,encoding='utf-8')
    write_json(output/'content-job.json',job)
    write_json(output/'asset-selection.json',selection)
    write_json(output/'timeline.json',{'duration':duration,'full_duration':job['duration'],'captions':caps,'visuals':scenes})
    write_json(output/'hyperframes.json',{'paths':{'assets':'assets'},'media':{'autoProxy':False},'authoringSkill':'cartoon-motion-video-production'})
    write_json(output/'package.json',{'private':True,'scripts':{'render':f'npx hyperframes@{lock["hyperframes_version"]} render --quality high','check':f'npx hyperframes@{lock["hyperframes_version"]} check'}})
    manifest = {'status':'BUILT_NOT_REVIEWED','schema_version':2,'template':'F30-V55','template_sha256':sha(TEMPLATE/'baseline.lock.json'),
                'builder_sha256':sha(__file__),'asset_intake_sha256':sha(SKILL/'scripts/generated_assets.py'),'source_job_sha256':sha(job_path),'source_sha256':job['manuscript']['sha256'],
                'narration_sha256':job['narration']['sha256'],'duration':duration,'full_duration':job['duration'],'canvas':lock['canvas'],
                'render_mode':job.get('render_mode',DEFAULT_RENDER_MODE),'asset_selection_sha256':selection['selection_sha256'],
                'asset_coverage':asset_coverage(job['visuals'],selection['visuals'],duration,job['render_mode']),
                'files':{str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file()}}
    write_json(output/'build-manifest.json',manifest)
    return manifest


def check(project):
    bundle_lock()
    m = read_json(project/'build-manifest.json')
    if m['template_sha256'] != sha(TEMPLATE/'baseline.lock.json'):
        fail('TEMPLATE_VERSION_MISMATCH','rebuild in a new version directory')
    for rel, expected in m['files'].items():
        p = project/rel
        if not p.is_file() or sha(p) != expected:
            fail('PROJECT_TAMPERED',rel)
    return m


def hf(command, project, *args):
    version = read_json(TEMPLATE/'baseline.lock.json')['hyperframes_version']
    subprocess.run(['npx','--yes',f'hyperframes@{version}',command,str(project),*map(str,args)],check=True)


def render(project, output, workers):
    check(project)
    if output.exists():
        fail('OUTPUT_EXISTS',str(output))
    hf('render',project,'--quality','high','--fps','30','--workers',workers,'--output',output)
    return {'status':'RENDERED_NOT_REVIEWED','video':str(output),'sha256':sha(output)}


def verify(project,video,output):
    m=check(project)
    if output.exists():
        fail('OUTPUT_EXISTS',str(output))
    output.mkdir(parents=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
    write_json(output/'ffprobe.json',probe)
    vs=[s for s in probe['streams'] if s['codec_type']=='video']
    aus=[s for s in probe['streams'] if s['codec_type']=='audio']
    findings=[]
    if len(vs)!=1 or (vs[0]['width'],vs[0]['height'],vs[0]['r_frame_rate'])!=(1280,720,'30/1'):
        findings.append('CANVAS_OR_FPS_MISMATCH')
    if len(aus)!=1:findings.append('AUDIO_TRACK_MISSING')
    if vs and abs(int(vs[0].get('nb_frames','0'))-round(m['duration']*30))>1:findings.append('FRAME_COUNT_MISMATCH')
    decode=subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],capture_output=True,text=True)
    (output/'decode.txt').write_text(decode.stderr)
    if decode.returncode or decode.stderr.strip():findings.append('DECODE_FAILED')
    # Only the illustration area: moving captions must not hide a frozen subject.
    timeline=read_json(project/'timeline.json')
    # V55 has a held blackboard opening. Test the requested continuously moving
    # body illustrations separately, rather than letting that intro change the result.
    body_start = timeline['visuals'][0]['visual_start'] if timeline['visuals'] else 0
    freeze=subprocess.run(['ffmpeg','-hide_banner','-i',str(video),'-vf',f'trim=start={body_start},crop=1280:365:0:65,freezedetect=n=-55dB:d=0.5','-an','-f','null','-'],capture_output=True,text=True)
    (output/'subject-freeze.txt').write_text(freeze.stderr)
    if freeze.returncode:findings.append('SUBJECT_CHECK_FAILED')
    if re.search(r'freeze_start:',freeze.stderr):findings.append('SUBJECT_FREEZE_REVIEW_REQUIRED')
    interval=max(1,m['duration']/12)
    subprocess.run(['ffmpeg','-v','error','-i',str(video),'-vf',f'fps=1/{interval},scale=426:240,tile=4x3','-frames:v','1',str(output/'contact-sheet.png')],check=True)
    # Every subtitle must have a review frame, not just twelve overview samples.
    pages = output/'all-caption-pages'
    pages.mkdir()
    page_index = []
    for offset in range(0,len(timeline['captions']),16):
        group = timeline['captions'][offset:offset+16]
        records = []
        for c in group:
            end = min(c['end'],m['duration'])
            at = min(end-1/30,c['start']+(end-c['start'])*.86)
            frame = max(0,min(round(at*30),round(m['duration']*30)-1))
            records.append({'caption':c['index'],'frame':frame,'seconds':frame/30,'text':c['text'],'en':c['en']})
        select = '+'.join(f'eq(n,{r["frame"]})' for r in records)
        page = pages/f'page-{offset//16+1:02d}.png'
        subprocess.run(['ffmpeg','-v','error','-i',str(video),'-vf',f"select='{select}',scale=426:240,tile=4x4",'-frames:v','1',str(page)],check=True)
        page_index.append({'path':str(page.resolve()),'captions':records})
    write_json(output/'caption-page-index.json',page_index)
    signal = subprocess.run(['ffmpeg','-hide_banner','-i',str(video.resolve()),'-vf',
        'signalstats,blackdetect=d=0.033,metadata=mode=print:file=video-signalstats.txt',
        '-an','-f','null','-'],cwd=output,capture_output=True,text=True)
    (output/'black-frame-check.txt').write_text(signal.stderr)
    if signal.returncode:findings.append('FRAME_SIGNAL_CHECK_FAILED')
    if 'black_start:' in signal.stderr:findings.append('BLACK_FRAME_REVIEW_REQUIRED')
    values = [float(x) for x in re.findall(r'lavfi.signalstats.YAVG=([0-9.]+)',(output/'video-signalstats.txt').read_text())]
    spikes = []
    for i in range(1,len(values)-1):
        before,after=values[i]-values[i-1],values[i+1]-values[i]
        if before*after<0 and min(abs(before),abs(after))>8 and abs(values[i+1]-values[i-1])<2:
            spikes.append({'frame':i,'seconds':i/30,'luma_before':values[i-1],'luma':values[i],'luma_after':values[i+1]})
    write_json(output/'single-frame-spikes.json',{'threshold_luma':8,'return_tolerance_luma':2,'candidates':spikes})
    if spikes:findings.append('SINGLE_FRAME_SPIKE_REVIEW_REQUIRED')
    # Cut-boundary strips are produced from the final encoded file, not browser stills.
    for i,s in enumerate(timeline['visuals']):
        t=s['visual_start']
        if t<=0 or t>=m['duration']:continue
        subprocess.run(['ffmpeg','-v','error','-ss',str(max(0,t-.2)),'-i',str(video),'-t','0.5','-vf','fps=20,scale=256:144,tile=10x1','-frames:v','1',str(output/f'cut-{i:02d}.png')],check=True)
    content_job=read_json(project/'content-job.json')
    selection=read_json(project/'asset-selection.json')
    coverage=asset_coverage(content_job['visuals'],selection['visuals'],m['duration'],m.get('render_mode','fixed-v55'))
    report={'status':'TECH_FAIL' if findings else 'TECH_PASS_REVIEW_REQUIRED','video':str(video.resolve()),'video_sha256':sha(video),
            'template_sha256':m['template_sha256'],'source_sha256':m['source_sha256'],'duration':m['duration'],
            'findings':findings,'asset_coverage':coverage,'subject_check':{'start':body_start,'crop':'1280:365:0:65','noise_db':-55,'freeze_seconds':0.5},
            'review_required':['V55 side-by-side visual identity including held opening','all scene subjects and cut boundaries','Chinese and English correspondence','speech and audio synchronization'],
            'score':None,'contact_sheet':str((output/'contact-sheet.png').resolve()),
            'contact_sheet_pages':[p['path'] for p in page_index],'single_frame_spike_candidates':len(spikes)}
    write_json(output/'verification.json',report)
    return report


def main():
    from paper_input import PAPER_SKILL_ROOT
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    sub.add_parser('presets')
    b=sub.add_parser('build');b.add_argument('--job',type=Path,required=True);b.add_argument('--output',type=Path,required=True);b.add_argument('--seconds',type=float)
    c=sub.add_parser('check');c.add_argument('--project',type=Path,required=True);c.add_argument('--runtime',action='store_true')
    r=sub.add_parser('render');r.add_argument('--project',type=Path,required=True);r.add_argument('--output',type=Path,required=True);r.add_argument('--workers',type=int,default=2)
    v=sub.add_parser('verify');v.add_argument('--project',type=Path,required=True);v.add_argument('--video',type=Path,required=True);v.add_argument('--output',type=Path,required=True)
    imp=sub.add_parser('import-paper');imp.add_argument('--production',type=Path,required=True);imp.add_argument('--visual-plan',type=Path,required=True);imp.add_argument('--output',type=Path,required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--manuscript',type=Path,required=True);prep.add_argument('--content-plan',type=Path,required=True);prep.add_argument('--output',type=Path,required=True)
    prep.add_argument('--config',type=Path,default=PAPER_SKILL_ROOT/'references/auto-config.local.json')
    prep.add_argument('--whisper-model',type=Path);prep.add_argument('--tempo',type=float,default=1.0)
    a=p.parse_args()
    if a.command=='doctor':
        lock=bundle_lock()
        available={name:shutil.which(name) for name in ('node','npx','ffmpeg','ffprobe','magick')}
        hf_probe={'status':'not_checked','required_version':lock['hyperframes_version']}
        if available['npx']:
            try:
                probe=subprocess.run(['npx','--no-install','--yes',f'hyperframes@{lock["hyperframes_version"]}','--version'],capture_output=True,text=True,timeout=20)
                match=bool(re.search(r'(?<![0-9.])'+re.escape(lock['hyperframes_version'])+r'(?![0-9.])',probe.stdout))
                hf_probe.update(status='ready' if probe.returncode==0 and match else 'unavailable',output=(probe.stdout+probe.stderr)[-1000:])
            except subprocess.TimeoutExpired:
                hf_probe['status']='timeout'
        result={'status':'TEMPLATE_OK','template':lock['template'],'canvas':lock['canvas'],'packaged_files':len(lock['files']),
                'historical_project_required':False,'paper_input_dependency':str(PAPER_SKILL_ROOT),
                'paper_input_present':(PAPER_SKILL_ROOT/'scripts').is_dir(),'executables':available,'hyperframes':hf_probe,
                'dependencies_ready':all(available.values()) and hf_probe['status']=='ready' and (PAPER_SKILL_ROOT/'scripts').is_dir(),
                'image_generation_tool':'Agent must check availability; CLI cannot verify it','candidate_only':False}
    elif a.command=='presets':
        _,presets=template_parts();result={k:{'source_slot':v['slot'],'motion_family':v['meta'].get('motion_family')} for k,v in presets.items()}
    elif a.command=='build':result=build(a.job.resolve(),a.output.resolve(),a.seconds)
    elif a.command=='check':
        result=check(a.project.resolve());result={'status':'PROJECT_INTEGRITY_OK','template_sha256':result['template_sha256']}
        if a.runtime:hf('check',a.project.resolve())
    elif a.command=='render':result=render(a.project.resolve(),a.output.resolve(),a.workers)
    elif a.command=='verify':result=verify(a.project.resolve(),a.video.resolve(),a.output.resolve())
    elif a.command=='import-paper':
        if a.output.exists():fail('OUTPUT_EXISTS',str(a.output))
        from paper_input import import_production
        job=import_production(a.production.resolve(),a.visual_plan.resolve())
        validate_job(job,a.production.resolve(),require_assets=False)
        a.output.parent.mkdir(parents=True,exist_ok=True);write_json(a.output,job)
        result={'status':'CONTENT_IMPORTED','job':str(a.output.resolve()),'duration':job['duration'],'captions':len(job['captions'])}
    elif a.command=='prepare':
        for required in (a.manuscript,a.content_plan,a.config):
            if not required.is_file():fail('MISSING_INPUT',str(required))
        if a.output.exists():fail('OUTPUT_EXISTS',str(a.output))
        model=a.whisper_model or Path(read_json(a.config)['whisper_model'])
        if not model.is_file():fail('MISSING_INPUT',str(model))
        from paper_input import prepare_new
        result=prepare_new(a.manuscript.resolve(),a.content_plan.resolve(),a.output.resolve(),a.config.resolve(),model.resolve(),a.tempo)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result.get('status')=='TECH_FAIL' or result.get('dependencies_ready') is False:sys.exit(2)


if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,RuntimeError,FileNotFoundError,subprocess.CalledProcessError) as e:
        print(str(e),file=sys.stderr);sys.exit(2)
