window.CaptionTypes=Object.freeze({prepare({el,c,start,end,requested}){
 const glyphs=[...el.querySelectorAll('.glyph')],r=c.reveal,offsets=glyphs.map((_,i)=>r.zh_offsets?r.zh_offsets[i]:i*r.zh_step),lead=1/30;
 const finalGlyph=start+offsets.at(-1)+lead,terminalAt=Math.max(finalGlyph,start+offsets.at(-1)+r.zh_tail),endFrame=Math.ceil(end*30-1e-8),hold=endFrame-Math.ceil(terminalAt*30-1e-8);
 const en=el.querySelector('.en'),enCount=el.querySelectorAll('.eglyph').length,enHold=endFrame-Math.ceil((start+r.en_start+(enCount-1)*r.en_step+r.en_tail)*30-1e-8);
 const native=el.querySelector('.cursor-zh'),reserve=native?native.offsetWidth:0,row=el.querySelector('.zh'),box=row.getBoundingClientRect(),parent=el.getBoundingClientRect(),sx=box.width/row.clientWidth,sy=box.height/row.clientHeight,widths=glyphs.map(g=>+g.dataset.width);
 const total=widths.reduce((a,b)=>a+b,0);
 const left=w=>box.left-parent.left+((row.clientWidth-total-reserve)/2+w+(reserve?0:8))*sx;
 let sum=0;const positions=[left(0)];for(const w of widths.slice(0,-1)){sum+=w;positions.push(left(sum));}
 const top=box.top-parent.top+90*sy,clip=positions.some(x=>parent.left+x-6<0||parent.left+x+47*sx+6>1280)||parent.top+top-6<0||parent.top+top+8*sy+6>720;
 const reason=hold<15?'insufficient-Chinese-stable-frames':getComputedStyle(en).display!=='none'&&enHold<14?'insufficient-English-stable-frames':clip?'transient-cursor-outside-frame':null;
 const use=requested==='cursor_reveal'&&!reason;
 const audit={index:c.index,requested,actual:use?'cursor_reveal':'baseline',fallback:requested==='cursor_reveal'?reason:null,start,end,lead:use?lead:0,offsets,terminalAt:use?terminalAt:start+offsets.at(-1)+r.zh_tail,completeGlyphAt:use?finalGlyph:start+offsets.at(-1)+r.zh_tail,plannedChineseFrames:hold,plannedEnglishFrames:enHold};
 if(!use)return {audit,apply:null};
 // Preserve final layout width while opacity controls actual glyph visibility.
 glyphs.forEach(g=>gsap.set(g,{width:+g.dataset.width}));
 const enLetters=[...el.querySelectorAll('.eglyph')];
 enLetters.forEach(g=>gsap.set(g,{width:+g.dataset.width}));
 const enWidths=enLetters.map(g=>parseFloat(getComputedStyle(g).width)),enTotal=enWidths.reduce((a,b)=>a+b,0),enCursor=el.querySelector('.cursor-en');
 if(enCursor)enCursor.style.position='relative';
 audit.layout='fixed-final-origin';
 const cursor=document.createElement('i');cursor.className='entry-cursor';cursor.setAttribute('aria-hidden','true');el.appendChild(cursor);Object.assign(cursor.style,{top:top+'px',width:47*sx+'px',height:8*sy+'px'});
 return {audit,apply(tl){if(enCursor){tl.set(enCursor,{left:-enTotal},0);let shownEn=0;enLetters.forEach((g,i)=>{shownEn+=enWidths[i];tl.set(enCursor,{left:shownEn-enTotal},start+r.en_start+i*r.en_step);});}tl.set(cursor,{left:left(0),opacity:1},start);if(native){tl.set(native,{visibility:'hidden'},0);tl.set(native,{visibility:'visible'},terminalAt);}let shown=0;glyphs.forEach((glyph,i)=>{const width=widths[i],at=start+offsets[i]+lead;shown+=width;tl.set(glyph,{width,opacity:1,scale:1,y:0},at);tl.set(cursor,{left:left(shown)},at);});tl.set(cursor,{opacity:0},finalGlyph);}};
}});
