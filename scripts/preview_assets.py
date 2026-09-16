#!/usr/bin/env python3
"""Unadmitted preview only. No build manifest; not accepted by production render/check."""
import argparse
import json
import shutil
from pathlib import Path
import generated_assets as g
import make_video as m

def preview(job_path, bindings_path, output, seconds=30):
    if output.exists(): g.fail('OUTPUT_EXISTS',str(output))
    job=g.read(job_path);selection=[None]*len(job['visuals'])
    for b in g.read(bindings_path):
        i=b['visual_index'];v=job['visuals'][i];src=Path(b['source']).resolve()
        tech=g.measure(src,v['preset'],b['background_mode'])
        if tech['findings']:g.fail('ASSET_TECH_FAILED',','.join(tech['findings']))
        key=f'{v["preset"]}-{g.sha(src)[:16]}'
        selection[i]={'ordinal':i+1,'asset_family':'generated-'+v['preset'],'variant_id':key,
                      'source_path':str(src),'sha256':g.sha(src),'bind_mode':'sprite',
                      'overlay':tech['placement'],'background_mode':b['background_mode'],
                      'output_path':f'assets/generated/{key}.png'}
    sel={'render_mode':'diverse-v55','opening':None,'visuals':selection}
    markup,caps,scenes=m.compose(job,min(seconds,job['duration']),sel)
    output.mkdir(parents=True);shutil.copytree(m.TEMPLATE/'assets',output/'assets')
    shutil.copy2(m.TEMPLATE/'caption-types.js',output/'caption-types.js')
    for r in selection:
        if r:
            dest=output/r['output_path'];dest.parent.mkdir(exist_ok=True)
            shutil.copy2(r['source_path'],dest)
    shutil.copy2(job['narration']['path'],output/'assets'/('narration'+Path(job['narration']['path']).suffix))
    (output/'index.html').write_text(markup)
    g.write(output/'preview-only.json',{'status':'UNADMITTED_COMPONENT_PREVIEW','selections':sel,
                                      'duration':min(seconds,job['duration']),'captions':caps,'scenes':scenes})
    from review_page import create_review
    review=create_review(output,output/'review.html')
    return {'status':'UNADMITTED_COMPONENT_PREVIEW','html':str((output/'index.html').resolve()),'review_page':review['path']}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job',type=Path,required=True);p.add_argument('--bindings',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=float,default=30)
    a=p.parse_args();print(json.dumps(preview(a.job,a.bindings,a.output,a.seconds),ensure_ascii=False))
