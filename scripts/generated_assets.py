#!/usr/bin/env python3
"""Candidate V55 asset intake. Generates briefs, validates, archives and binds; no hidden image API."""
import argparse
import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
# Derived from final V55 CSS/runtime, not the obsolete atlas boxes.
SLOTS = {
    'choices': (467.3496659242761, 33.619153674832944, 350.1113585746103, 277.9510022271715, 'preserved_v12_vertical_drop_choices'),
    'blocks': ((274-337/415*275)/2, -.5, 337/415*275, 275, 'fine_child_vertical_extended_blur_v24'),
    'notes': (450.2262443438914, 36.53846153846155, 374.6606334841629, 279.63800904977376, 'preserved_v12_horizontal_fast'),
    'listen': (495.625, 57.995866, 288.75, 230.008268, 'listen_horizontal_repeat_active_v23'),
    'shelf': (490, 37.93103448, 300, 274.137931, 'preserved_v12_horizontal_fast'),
    'draw': ((400-385/446*275)/2, 37.5, 385/446*275, 275, 'fine_prop_horizontal_repeat_slow'),
    'together': ((400-465/401*290*.9)/2, 30+(290-290*.9)/2, 465/401*290*.9, 290*.9, 'fine_pair_central_growth'),
}
CHECKS = ('style_matches_v55', 'anatomy_and_objects_clear', 'no_text_logo_frame',
          'edges_clean', 'background_composite_clean', 'size_and_proportions_match',
          'meaning_reasonable')
HEX = re.compile(r'^[0-9a-f]{64}$')
def fail(code, detail=''):
    raise ValueError(f'{code}: {detail}')
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path, data):
    path=Path(path)
    if path.exists(): fail('OUTPUT_EXISTS',str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def confined(root, rel):
    if Path(rel).is_absolute(): fail('BUNDLE_PATH_ESCAPE',str(rel))
    path=(root/rel).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file(): fail('BUNDLE_FILE_MISSING_OR_ESCAPE',str(rel))
    return path

def measure(path, preset, background):
    """Read source pixels only. This function never edits/resamples the image."""
    path=Path(path).resolve()
    if preset not in SLOTS: fail('SLOT_NOT_SUPPORTED',preset)
    if path.suffix.lower() != '.png': fail('PNG_REQUIRED',str(path))
    raw=subprocess.check_output(['magick','identify','-format','%m %w %h %[opaque]',str(path)],timeout=20).decode().split()
    if raw[0] != 'PNG': fail('PNG_REQUIRED', raw[0])
    w,h=int(raw[1]),int(raw[2])
    if w*h > 16000000 or min(w,h)<512 or max(w,h)<900: fail('SOURCE_RESOLUTION',f'{w}x{h}')
    if background not in ('alpha','white-key'): fail('BACKGROUND_MODE',background)
    pixels=subprocess.check_output(['magick',str(path),'-alpha','on','-depth','8','RGBA:-'],timeout=30)
    if len(pixels)!=w*h*4: fail('PIXEL_DECODE',str(path))
    opaque=transparent=foreground=border_good=border_total=0
    x0,y0,x1,y1=w,h,-1,-1
    for y in range(h):
        for x in range(w):
            i=(y*w+x)*4
            r,g,b,a=pixels[i:i+4]
            transparent+=a<=8
            opaque+=a>=247
            is_white=min(r,g,b)>=247 and max(r,g,b)-min(r,g,b)<=5
            visible=a>16 if background=='alpha' else not is_white
            if visible:
                foreground+=1;x0=min(x0,x);y0=min(y0,y);x1=max(x1,x);y1=max(y1,y)
            if x<3 or x>=w-3 or y<3 or y>=h-3:
                border_total+=1
                border_good+=((a<=8) if background=='alpha' else (is_white and a>=247))
    findings=[]
    n=w*h
    if background=='alpha' and (transparent/n<.08 or opaque/n<.12): findings.append('REAL_ALPHA_REQUIRED')
    if background=='white-key' and opaque/n<.999: findings.append('OPAQUE_WHITE_SOURCE_REQUIRED')
    if border_good/max(1,border_total)<.995: findings.append('DIRTY_OR_CROPPED_BORDER')
    if not foreground or x1<x0: fail('EMPTY_SUBJECT',str(path))
    bw,bh=x1-x0+1,y1-y0+1
    margins=[x0/w,y0/h,(w-1-x1)/w,(h-1-y1)/h]
    if min(margins)<.008: findings.append('SUBJECT_TOUCHES_EDGE')
    if bw/w<.68 or bh/h<.68: findings.append('SUBJECT_TOO_SMALL')
    l,t,sw,sh,motion=SLOTS[preset]
    scale=min(sw/bw,sh/bh)
    cover_x,cover_y=bw*scale/sw,bh*scale/sh
    if min(cover_x,cover_y)<.78: findings.append('ASPECT_INCOMPATIBLE_WITH_SLOT')
    placement={'left':l+(sw-bw*scale)/2-x0*scale, 'top':t+(sh-bh*scale)/2-y0*scale,
               'width':w*scale,'height':h*scale}
    return {'schema_version':1,'status':'TECH_FAIL' if findings else 'TECH_PASS_VISUAL_REVIEW_REQUIRED',
            'source_sha256':sha(path),'preset':preset,'background_mode':background,
            'width':w,'height':h,'bounds':[x0,y0,bw,bh],
            'transparent_fraction':transparent/n,'opaque_fraction':opaque/n,
            'border_clean_fraction':border_good/max(1,border_total),
            'slot_fill':[cover_x,cover_y], 'placement':placement,
            'slot':{'left':l,'top':t,'width':sw,'height':sh},
            'motion_family':motion,'findings':findings}

def prompt_for(preset,subject,background):
    if preset not in SLOTS: fail('SLOT_NOT_SUPPORTED',preset)
    _,_,w,h,_=SLOTS[preset]
    bg=('Real transparent PNG with alpha=0 outside the silhouette, never a drawn checkerboard.'
        if background=='alpha' else
        'Pure solid #FFFFFF white background and clean white gaps. No grey, checkerboard, shadow or texture. Interior major areas use color, not white. This source will be displayed with a near-white key mask on green paper; avoid pale/white props.')
    return f"""Create one independent cartoon illustration for the existing V55 video.
Reference images are STYLE REFERENCES ONLY, not page layouts.
Subject: {subject}
Flat editorial cartoon, thick clean black outlines, simple expressive faces, cyan/teal and orange/yellow accents. Complete natural body/hand/object contours. Clear at 300px.
Visible subject width/height target {w/h:.3f}; fill approximately 92 percent of canvas, 2-5 percent safe margin each edge. At least 1024 pixels on the long edge and 768 on the short edge.
{bg}
No title, caption, words, logo, watermark, card, panel, decorative frame, scene background, paper texture or animation. Do not generate a whole video page. Do not change V55 fonts, layout, timing or background.
"""

def brief(preset,subject,background,output):
    refs=[SKILL/'assets/v55/assets/choices-editorial-v40.png',SKILL/'assets/v55/assets/notes-editorial-v40.png']
    data={'schema_version':1,'status':'GENERATION_REQUIRED','preset':preset,'subject':subject,
          'background_mode':background,'prompt':prompt_for(preset,subject,background),
          'reference_images':[{'path':str(x),'sha256':sha(x),'role':'style-only'} for x in refs],
          'generator':'Agent invokes available image generation tool; this CLI does not generate images'}
    write(output,data)
    return data

def review_valid(review, source_sha, preset, background, root=None, require_frame=False):
    if review.get('source_sha256')!=source_sha or review.get('preset')!=preset or review.get('background_mode')!=background:
        fail('REVIEW_SOURCE_MISMATCH',preset)
    if review.get('decision')!='candidate_pass' or not str(review.get('reviewer','')).strip():
        fail('VISUAL_REVIEW_REQUIRED',preset)
    if any(review.get('checks',{}).get(k) is not True for k in CHECKS): fail('VISUAL_REVIEW_INCOMPLETE',preset)
    if not str(review.get('observations','')).strip(): fail('VISUAL_REVIEW_OBSERVATIONS_REQUIRED')
    evidence=review.get('evidence',[])
    if not evidence: fail('REVIEW_EVIDENCE_REQUIRED')
    portable_frames=0
    for item in evidence:
        p=confined(root,item['path']) if root else Path(item['path']).resolve()
        if not p.is_file() or sha(p)!=item.get('sha256'): fail('REVIEW_EVIDENCE_HASH',str(p))
        if p.suffix.lower()=='.png' and p.read_bytes()[:8]==b'\x89PNG\r\n\x1a\n':
            info=subprocess.check_output(['magick','identify','-format','%m %w %h',str(p)],timeout=20).decode().split()
            if info[0]=='PNG' and int(info[1])>=320 and int(info[2])>=180:
                portable_frames+=1
    if require_frame and not portable_frames:
        fail('PORTABLE_PREVIEW_FRAME_REQUIRED','save an actual V55 composite PNG, at least 320x180; HTML/report alone is not portable visual evidence')

def admit(source,brief_path,review_path,library):
    brief_data=read(brief_path); review=read(review_path)
    preset,bg=brief_data['preset'],brief_data['background_mode']
    if not brief_data.get('prompt') or not brief_data.get('reference_images'):
        fail('GENERATION_BRIEF_REQUIRED')
    for ref in brief_data['reference_images']:
        if not Path(ref['path']).is_file() or sha(ref['path']) != ref.get('sha256'):
            fail('STYLE_REFERENCE_HASH', ref.get('path',''))
    measured=measure(source,preset,bg)
    if measured['findings']: fail('ASSET_TECH_FAILED',','.join(measured['findings']))
    review_valid(review,sha(source),preset,bg,require_frame=True)
    key=f'{preset}-{sha(source)[:16]}'
    out=Path(library).resolve()/key
    if out.exists(): fail('OUTPUT_EXISTS',str(out))
    out.mkdir(parents=True)
    shutil.copy2(source,out/'source.png')
    shutil.copy2(brief_path,out/'generation-brief-original.json')
    brief_data=copy.deepcopy(brief_data)
    for i,ref in enumerate(brief_data['reference_images']):
        src=Path(ref['path']).resolve();dest=out/'references'/f'{i:02d}{src.suffix}'
        dest.parent.mkdir(exist_ok=True);shutil.copy2(src,dest);ref['path']=str(dest.relative_to(out))
    write(out/'brief.json',brief_data)
    write(out/'technical.json',measured)
    review=copy.deepcopy(review)
    for i,item in enumerate(review['evidence']):
        src=Path(item['path']).resolve();dest=out/'evidence'/f'{i:02d}{src.suffix}'
        dest.parent.mkdir(exist_ok=True);shutil.copy2(src,dest);item['path']=str(dest.relative_to(out))
    write(out/'review.json',review)
    entry={'schema_version':1,'status':'candidate_pass_not_user_approved',
           'review_evidence_policy':'portable-v55-frame-v1',
           'asset_id':key,'preset':preset,'background_mode':bg,'source_sha256':sha(source),
           'generation_origin':'generated in authorized local task; no public redistribution asserted',
           'files':{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}}
    write(out/'entry.json',entry)
    return {'entry':str(out/'entry.json'),'sha256':sha(out/'entry.json'),'status':entry['status']}

def load_entry(path):
    path=Path(path).resolve();root=path.parent;e=read(path)
    if e.get('schema_version')!=1 or e.get('status')!='candidate_pass_not_user_approved': fail('ENTRY_STATUS',str(path))
    for required in ('source.png','technical.json','review.json','brief.json'):
        if required not in e.get('files',{}): fail('ENTRY_FILE_REQUIRED',required)
    for rel,digest in e['files'].items():
        if sha(confined(root,rel))!=digest: fail('ENTRY_TAMPERED',rel)
    actual=measure(root/'source.png',e['preset'],e['background_mode'])
    if actual['findings']:fail('ASSET_TECH_FAILED',','.join(actual['findings']))
    if read(root/'technical.json')!=actual:fail('TECHNICAL_REPORT_MISMATCH')
    if sha(root/'source.png')!=e['source_sha256']:fail('ENTRY_SOURCE_HASH')
    brief_data=read(root/'brief.json')
    if brief_data.get('preset')!=e['preset'] or brief_data.get('background_mode')!=e['background_mode'] or not brief_data.get('prompt'):
        fail('GENERATION_BRIEF_MISMATCH')
    for ref in brief_data.get('reference_images',[]):
        if sha(confined(root,ref['path']))!=ref['sha256']:fail('STYLE_REFERENCE_HASH')
    review_valid(read(root/'review.json'),e['source_sha256'],e['preset'],e['background_mode'],root,
                 require_frame=e.get('review_evidence_policy')=='portable-v55-frame-v1')
    return e,actual

def bind(job_path, bindings, output):
    job=read(job_path); out=Path(output).resolve()
    if out.exists():fail('OUTPUT_EXISTS',str(out))
    seen=set();items=[]
    # Validate everything before creating output.
    for b in bindings:
        idx=int(b['visual_index'])
        if idx in seen or not 0<=idx<len(job['visuals']):fail('BINDING_INDEX',str(idx))
        seen.add(idx);p=Path(b['entry']).resolve();e,tech=load_entry(p)
        if e['preset']!=job['visuals'][idx]['preset']:fail('BINDING_PRESET',str(idx))
        items.append((idx,p,e,tech))
    if not items:fail('DIVERSITY_ASSETS_REQUIRED')
    out.mkdir(parents=True);entries=[]
    for idx,p,e,tech in items:
        rel=f'entries/{e["asset_id"]}'
        if not (out/rel).exists():shutil.copytree(p.parent,out/rel)
        entries.append({'visual_index':idx,'entry':f'{rel}/entry.json','entry_sha256':sha(p)})
    manifest={'schema_version':1,'status':'candidate_not_user_approved','opening_policy':'fixed-v55',
              'manuscript_sha256':job['manuscript']['sha256'],'bindings':entries}
    write(out/'bundle.json',manifest)
    return {'path':str(out/'bundle.json'),'sha256':sha(out/'bundle.json')}

def load_bundle(info,job):
    path=Path(info['path']).expanduser().resolve()
    if not path.is_file() or sha(path)!=info.get('sha256'):fail('ASSET_BUNDLE_HASH')
    b=read(path)
    if b.get('schema_version')!=1 or b.get('status')!='candidate_not_user_approved' or b.get('opening_policy')!='fixed-v55':
        fail('ASSET_BUNDLE_SCHEMA')
    if b.get('manuscript_sha256')!=job['manuscript']['sha256']:fail('ASSET_BUNDLE_MANUSCRIPT')
    result=[None]*len(job['visuals']);seen=set()
    for binding in b.get('bindings',[]):
        idx=binding['visual_index']
        if type(idx) is not int or not 0<=idx<len(result) or idx in seen:fail('BINDING_INDEX',str(idx))
        seen.add(idx);p=confined(path.parent,binding['entry'])
        if sha(p)!=binding['entry_sha256']:fail('ENTRY_HASH',str(p))
        e,tech=load_entry(p);preset=job['visuals'][idx]['preset']
        if e['preset']!=preset:fail('BINDING_PRESET',str(idx))
        result[idx]={'ordinal':idx+1,'asset_family':'generated-'+preset,'variant_id':e['asset_id'],
                     'source_path':str(p.parent/'source.png'),'sha256':e['source_sha256'],
                     'bind_mode':'sprite','geometry_profile':'v55-final-visible-bounds-v1',
                     'motion_family':tech['motion_family'],'overlay':tech['placement'],
                     'background_mode':e['background_mode'],'slot':tech['slot'],
                     'license':e['generation_origin'],'review_entry_path':str(p),
                     'output_path':f'assets/generated/{e["asset_id"]}.png',
                     'reason':'reviewed asset in immutable manuscript-bound candidate bundle'}
    if not seen:fail('DIVERSITY_ASSETS_REQUIRED')
    return result

def plan(job_path,library,output,seconds=None,history=None):
    job=read(job_path)
    digest=job['manuscript']['sha256']
    ledger=read(history) if history and Path(history).is_file() else {'runs':[]}
    recent_manuscripts=[]
    for run in reversed(ledger['runs']):
        old_sha=run['manuscript_sha256']
        if old_sha!=digest and old_sha not in recent_manuscripts:
            recent_manuscripts.append(old_sha)
        if len(recent_manuscripts)==5:break
    runs=[r for r in ledger['runs'] if r['manuscript_sha256'] in recent_manuscripts]
    recent=[a for r in runs for a in r['asset_ids']]
    pool=[];invalid_entries=[]
    for p in sorted(Path(library).glob('*/entry.json')):
        try:
            e,_=load_entry(p);pool.append((p,e))
        except (ValueError,KeyError,subprocess.SubprocessError) as exc:
            invalid_entries.append({'entry':str(p),'reason':str(exc)})
            continue
    rows=[];used=set()
    for i,v in enumerate(job['visuals']):
        if seconds and v['start']>=seconds:break
        if v['preset'] not in SLOTS:
            rows.append({'visual_index':i,'preset':v['preset'],'action':'keep_baseline','reason':'slot not calibrated'});continue
        eligible=[(p,e) for p,e in pool if e['preset']==v['preset'] and e['asset_id'] not in recent and e['asset_id'] not in used]
        eligible.sort(key=lambda pe:hashlib.sha256(f'{digest}|{i}|{pe[1]["asset_id"]}'.encode()).hexdigest())
        if eligible:
            p,e=eligible[0];used.add(e['asset_id'])
            rows.append({'visual_index':i,'preset':v['preset'],'action':'reuse_reviewed_candidate','entry':str(p.resolve()),'asset_id':e['asset_id']})
        else:
            rows.append({'visual_index':i,'preset':v['preset'],'action':'generate','meaning':v['meaning'],
                         'reason':'no compatible reviewed asset outside last five manuscripts'})
    data={'schema_version':1,'status':'PLAN_NOT_VIDEO','manuscript_sha256':digest,
          'opening':'keep_baseline','library':str(Path(library).resolve()),'rows':rows,'invalid_entries':invalid_entries,
          'note':'Agent generates only the assets required for this job; do not pre-stock a fixed count'}
    write(output,data);return data

def record(project,verification,history):
    import make_video
    manifest=make_video.check(Path(project))
    qc=read(verification)
    if qc.get('status')!='TECH_PASS_REVIEW_REQUIRED' or qc.get('source_sha256')!=manifest['source_sha256']:
        fail('VERIFICATION_REQUIRED')
    video=Path(qc['video'])
    if not video.is_file() or sha(video)!=qc.get('video_sha256'):fail('VIDEO_HASH')
    sel=read(Path(project)/'asset-selection.json')
    row={'manuscript_sha256':manifest['source_sha256'],'selection_sha256':sel['selection_sha256'],
         'video_sha256':qc['video_sha256'],'asset_ids':[r['variant_id'] for r in sel['visuals'] if r],
         'status':'rendered_candidate_not_user_approved'}
    ledger=read(history) if Path(history).exists() else {'runs':[]}
    if not any(r['video_sha256']==row['video_sha256'] for r in ledger['runs']):
        ledger['runs'].append(row)
        # A history update is explicit; keep a content-addressed previous snapshot.
        if Path(history).exists():
            prev=Path(str(history)+'.'+sha(history)[:12]+'.previous.json')
            if not prev.exists():shutil.copy2(history,prev)
        Path(history).parent.mkdir(parents=True,exist_ok=True)
        Path(history).write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    return row

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    b=s.add_parser('brief');b.add_argument('--preset',required=True,choices=SLOTS);b.add_argument('--subject',required=True);b.add_argument('--background',default='alpha',choices=['alpha','white-key']);b.add_argument('--output',type=Path,required=True)
    c=s.add_parser('check');c.add_argument('--source',type=Path,required=True);c.add_argument('--preset',choices=SLOTS,required=True);c.add_argument('--background',required=True,choices=['alpha','white-key']);c.add_argument('--output',type=Path,required=True)
    a=s.add_parser('admit');a.add_argument('--source',type=Path,required=True);a.add_argument('--brief',type=Path,required=True);a.add_argument('--review',type=Path,required=True);a.add_argument('--library',type=Path,required=True)
    b=s.add_parser('bind');b.add_argument('--job',type=Path,required=True);b.add_argument('--bindings',type=Path,required=True);b.add_argument('--output',type=Path,required=True)
    b=s.add_parser('plan');b.add_argument('--job',type=Path,required=True);b.add_argument('--library',type=Path,required=True);b.add_argument('--output',type=Path,required=True);b.add_argument('--seconds',type=float);b.add_argument('--history',type=Path)
    b=s.add_parser('record');b.add_argument('--project',type=Path,required=True);b.add_argument('--verification',type=Path,required=True);b.add_argument('--history',type=Path,required=True)
    a=p.parse_args()
    if a.command=='brief':r=brief(a.preset,a.subject,a.background,a.output)
    elif a.command=='check':r=measure(a.source,a.preset,a.background);write(a.output,r)
    elif a.command=='admit':r=admit(a.source,a.brief,a.review,a.library)
    elif a.command=='bind':r=bind(a.job,read(a.bindings),a.output)
    elif a.command=='plan':r=plan(a.job,a.library,a.output,a.seconds,a.history)
    else:r=record(a.project,a.verification,a.history)
    print(json.dumps(r,ensure_ascii=False,indent=2))
    if r.get('status')=='TECH_FAIL':sys.exit(2)
if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,FileNotFoundError,subprocess.SubprocessError) as e:
        print(str(e),file=sys.stderr);sys.exit(2)
