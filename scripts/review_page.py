#!/usr/bin/env python3
"""Create clickable visual review controls; never alter the production HTML."""
import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

def create_review(project,output):
    project,output=Path(project).resolve(),Path(output).resolve()
    if output.exists():raise ValueError('OUTPUT_EXISTS: '+str(output))
    if not (project/'index.html').is_file():raise ValueError('PROJECT_MISSING')
    timeline_path=project/'timeline.json'
    if timeline_path.is_file():
        timeline=json.loads(timeline_path.read_text());duration=float(timeline['duration']);scenes=timeline['visuals']
    else:
        preview=json.loads((project/'preview-only.json').read_text())
        scenes=preview['scenes'];duration=float(preview['duration'])
    times=[0]+[round(min(duration-.1,float(s['visual_start'])+min(1.5,(float(s['end'])-float(s['visual_start']))/2)),2) for s in scenes if float(s['visual_start'])<duration]
    relative=quote(os.path.relpath(project/'index.html',output.parent),safe='/')
    buttons=''.join('<button type="button" data-time="'+str(t)+'">'+('开场' if i==0 else '片段 '+str(i))+' · '+str(t)+' 秒</button>' for i,t in enumerate(times))
    page="""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>卡通动效候选预览</title>
<style>body{margin:0;background:#202a26;color:#fff;font:16px sans-serif}header{padding:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}button,input{font:inherit}button{padding:7px 12px;cursor:pointer}button:disabled{cursor:wait}#status{padding:0 12px 12px}iframe{width:1280px;height:720px;border:0;display:block}input[type=range]{width:260px}p{margin:8px 12px;color:#ced9d2}</style>
<header><strong>候选页面预览</strong>__BUTTONS__<button id="play" type="button">播放</button><button id="pause" type="button">暂停</button><label>时间 <input aria-label="时间" id="seek" type="range" min="0" max="__DURATION__" step="0.033333" value="0"></label></header>
<div id="status" role="status">正在加载素材与字体</div><iframe id="frame" title="V55候选画面" src="__SOURCE__"></iframe>
<p>这是候选页面预览。最终流畅度、闪屏与声音，以输出 MP4 的验收为准。直接打开文件若受浏览器限制，请从本机 HTTP 地址打开此页。</p>
<script>
const frame=document.getElementById('frame'),statusEl=document.getElementById('status'),slider=document.getElementById('seek');
const duration=__DURATION__;let timeline=null,voice=null,timer=null,playing=false;
document.querySelectorAll('button,input').forEach(e=>e.disabled=true);
function syncVoice(t){if(voice){voice.pause();voice.currentTime=t;}}
function seek(t){if(!timeline)return;playing=false;timeline.pause(t);syncVoice(t);slider.value=t;statusEl.textContent=t.toFixed(2)+' / '+duration.toFixed(2)+' 秒';}
function pause(){if(timeline)seek(timeline.time());}
function play(){if(!timeline)return;let t=timeline.time();if(t>=duration-0.04)t=0;timeline.play(t);if(voice){voice.currentTime=t;voice.play().catch(()=>{statusEl.textContent='画面播放中，浏览器未启动声音';});}playing=true;}
document.querySelectorAll('[data-time]').forEach(b=>b.addEventListener('click',()=>seek(+b.dataset.time)));
document.getElementById('play').addEventListener('click',play);
document.getElementById('pause').addEventListener('click',pause);
slider.addEventListener('input',()=>seek(+slider.value));
frame.addEventListener('load',()=>{
const started=Date.now();
function ready(){try{
const w=frame.contentWindow;
if(w.__sampleReady){timeline=w.__timelines['cartoon-v55'];voice=w.document.querySelector('#voiceover');document.querySelectorAll('button,input').forEach(e=>e.disabled=false);seek(0);
clearInterval(timer);timer=setInterval(()=>{if(playing){let t=timeline.time();slider.value=t;statusEl.textContent=t.toFixed(2)+' / '+duration.toFixed(2)+' 秒';if(t>=duration-0.034)seek(duration);}},50);return;}
if(w.__buildError)throw Error(w.__buildError);
if(Date.now()-started>45000)throw Error('素材或字体加载超过45秒');
setTimeout(ready,80);
}catch(e){statusEl.textContent='预览未就绪：'+e.message+'。请通过本机 HTTP 入口打开并检查资源。';}}
ready();});
</script></html>"""
    page=page.replace('__BUTTONS__',buttons).replace('__DURATION__',str(duration)).replace('__SOURCE__',html.escape(relative,quote=True))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(page,encoding='utf-8')
    return {'status':'REVIEW_PAGE_NOT_VIDEO','path':str(output),'duration':duration,'seek_times':times}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(create_review(a.project,a.output),ensure_ascii=False,indent=2))
