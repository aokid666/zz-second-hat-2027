"""Vector-PDF matching and answer-only blue cloze. All extraction/rendering runs in Actions."""
import argparse,collections,concurrent.futures,hashlib,json,pathlib,re
import fitz
import matching
import semantic
ROOT=pathlib.Path(__file__).resolve().parents[1];BASE='https://aokid666.github.io/zz-second-hat-2027/'
SOURCES=json.loads((ROOT/'tools/sources.json').read_text());ERRORS=[]
OVERRIDES=json.loads((ROOT/'tools/prompt-overrides.json').read_text())
def dump(n,d):p=ROOT/'data'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':')))
def norm(t):return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]','',t).lower()
def layout(doc):
 ps=[]
 for pn,page in enumerate(doc,1):
  lines=[]
  for bi,b in enumerate(page.get_text('rawdict')['blocks']):
   for li,l in enumerate(b.get('lines',[])):
    spans=[];chars=[]
    for s in l['spans']:
     t=''.join(c['c'] for c in s['chars']);spans.append({'text':t,'font':s['font'],'size':s['size'],'color':s['color'],'bbox':list(s['bbox']),'origin':list(s['origin'])})
     chars.extend({'c':c['c'],'b':list(c['bbox']),'color':s['color'],'p':pn,'line':f'{pn}-{bi}-{li}','block':f'{pn}-{bi}'} for c in s['chars'])
    if chars:lines.append({'t':''.join(c['c'] for c in chars),'b':list(l['bbox']),'spans':spans,'chars':chars,'block':f'{pn}-{bi}'})
  lines.sort(key=lambda l:(round(l['b'][1],1),l['b'][0]));ps.append({'page':pn,'width':page.rect.width,'height':page.rect.height,'text':page.get_text(),'lines':lines})
 return ps

def sig(q):return [*[norm(i['text']) for i in q['left']],'RIGHT',*[norm(i['text']) for i in q['right']],q['matchMap']]
def matches(src,ps,site):
 matching.layouts={'history-second':ps};qs=matching.matching('history-second')
 for n,q in enumerate(qs,1):
  q.update(id=f'pr-{src["id"]}-matching-{n:04}',bookId=src['id'],module=src['module'])
  # Clip question and answer independently, including a table which continues across pages.
  rs=q['keyRefs'];al=None
  for r in rs:
   pg=ps[r['page']-1]
   for l in pg['lines']:
    if r['b'][1]<=l['b'][1]<=r['b'][1]+r['b'][3] and re.match(r'^答案[：:]|^解析[：:]',l['t']):al=(r['page'],l['b'][1]);break
   if al:break
  if not al:ERRORS.append(f'{src["id"]}/{n}: no answer boundary');continue
  q['qRefs']=[];q['keyRefs']=[]
  for r in rs:
   x,y,w,h=r['b'];bottom=min(ps[r['page']-1]['height']-20,y+h)
   if r['page']<=al[0]:
    end=min(bottom,al[1]-4) if r['page']==al[0] else bottom
    if end>y:q['qRefs'].append({'page':r['page'],'b':[x,y,w,end-y]})
   if r['page']>=al[0]:
    start=max(y,al[1]) if r['page']==al[0] else y
    if bottom>start:q['keyRefs'].append({'page':r['page'],'b':[x,start,w,bottom-start]})
  if set(q['matchMap'])!={i['key'] for i in q['left']} or any(not x['text'] for x in q['left']+q['right']):ERRORS.append(f'{src["id"]}/{n}: missing items/map')
  if any(not v or any(k not in {i['key'] for i in q['right']} for k in v) for v in q['matchMap'].values()):ERRORS.append(f'{src["id"]}/{n}: invalid targets')
 # Existing matching exercises keep their IDs and learning records if all item mappings agree.
 if src['id'] in ['history-second','ethics-match']:
  old=json.loads((site/'data/practice'/f'{src["id"]}.json').read_text())['questions']
  if len(qs)==len(old) and sorted(json.dumps(sig(q),sort_keys=True) for q in qs)==sorted(json.dumps(sig(q),sort_keys=True) for q in old):return old,True
  ERRORS.append(src['id']+': existing source differs; review before replacing records')
 return qs,False

def outside_positions(t):
 stack=[];pairs={'“':'”','‘':'’','《':'》','（':'）','(':')'};out=[]
 for i,c in enumerate(t):
  if c in pairs:stack.append(pairs[c]);continue
  if stack and c==stack[-1]:stack.pop();continue
  if not stack:out.append(i)
 return set(out)
def protections(text):
 outside=outside_positions(text)
 colons=[i for i,c in enumerate(text) if c in ':：' and i in outside and not re.search(r'(指出|强调|说|认为|写道)\s*$',text[max(0,i-8):i])]
 if colons:return [(0,colons[0]+1)],'colon'
 # Prefer explicit causal/source predicates to an incidental 是 in a long prompt.
 for pattern,label in [(r'是因为|根本在于|关键在于|原因在于|取决于|来自|源于|在于|意味着','explicit'),(r'指的是|体现为|表现为|就是|是指|是|包括','predicate')]:
  ms=[m for m in re.finditer(pattern,text) if m.start() in outside]
  if ms:
   protected=[(0,ms[0].end())]
   # Separate parallel statements retain each statement's blue subject/prompt.
   for sep in re.finditer('[；。，]',text):
    if sep.start() not in outside:continue
    end=next((i for i in range(sep.end(),len(text)) if text[i] in '；。' and i in outside),len(text))
    m=next((m for m in re.finditer(r'指的是|就是|是指|是|在于|来自',text[sep.end():end]) if sep.end()+m.start() in outside),None)
    if m:protected.append((sep.end(),sep.end()+m.end()))
   return protected,label
 return [(0,len(text))],'review'
def blue(c):return c['color']==0x1f497d

def clozes(src,ps):
 entries=[];cur=None;chapter='导论';section='单选';audits=[]
 for p in ps:
  for l in p['lines']:
   t=l['t'].strip()
   if l['b'][1]>p['height']-45 or l['b'][1]<35 or re.match(r'^\d+\s*/\s*\d+$',t) or 'b站/公众号' in t or re.match(r'^肖\s*1000',t):continue
   if t.startswith('#'):
    if cur:entries.append(cur);cur=None
    if t.startswith('##'):section=t.lstrip('#').strip()
    else:chapter=t.lstrip('#').strip()
    continue
   m=re.match(r'^(\d+)[.．]\s*',t)
   if m:
    if cur:entries.append(cur)
    cur={'no':int(m[1]),'chapter':chapter,'section':section,'lines':[]}
   if cur:cur['lines'].append((p['page'],l))
 if cur:entries.append(cur)
 qs=[];needs=[];skip=[]
 for ei,e in enumerate(entries,1):
  chars=[]
  for pn,l in e['lines']:
   if chars:chars.append({'c':'\n','color':0,'p':pn,'break':chars[-1].get('block')!=l['block']})
   chars.extend(l['chars'])
  text=''.join(c['c'] for c in chars);protected,rule=protections(text)
  anchor=OVERRIDES.get(src['id'],{}).get(str(ei))
  if anchor:
   compact=''.join(c for c in text if not c.isspace());needle=''.join(anchor.split());idx=compact.find(needle)
   if idx<0:ERRORS.append(src['id']+': manual prompt anchor missing '+str(ei))
   else:
    positions=[i for i,c in enumerate(text) if not c.isspace()];protected=[(0,positions[idx+len(needle)-1]+1)];rule='reviewed-prompt'
  reference=semantic.find(src['module'],text)
  norm_indices=[i for i,c in enumerate(text) if re.match(r'[\u4e00-\u9fffA-Za-z0-9]',c)]
  left=set(norm_indices[j] for j in reference['leftPositions']) if reference else set()
  right=set(norm_indices[j] for j in reference['rightPositions']) if reference else set()
  isprotected=lambda i:any(lo<=i<hi for lo,hi in protected)
  groups=[];active=[]
  def flush():
   if active:groups.append(active[:]);active.clear()
  for i,c in enumerate(chars):
   if blue(c):
    active.append((i,c))
    if c['c'] in '；;。':flush()
   elif c['c'].isspace() and active:
    nxt=chars[i+1] if i+1<len(chars) else None;prev=active[-1][1]
    # Word sometimes emits a wrapped final syllable as a new PDF block.
    # Join only at the page's right margin into the following indented line.
    wrap=bool(nxt and blue(nxt) and prev['b'][2]>=ps[prev['p']-1]['width']-70 and nxt['b'][0]<ps[nxt['p']-1]['width']*.2 and ((nxt['p']==prev['p'] and 0<nxt['b'][1]-prev['b'][1]<40) or (nxt['p']==prev['p']+1 and prev['b'][1]>ps[prev['p']-1]['height']*.75 and nxt['b'][1]<ps[nxt['p']-1]['height']*.25)))
    if not c.get('break') or wrap:continue
    flush()
   else:flush()
  flush()
  atoms=groups;groups=[];protected_blue=[]
  for g in atoms:
   ids={j for j,c in g};l=len(ids&(left-right));r=len(ids&(right-left));eligible=any(not isprotected(j) for j,c in g)
   if r>=2 and r>=l:eligible=True
   elif l>=2 and l>r:eligible=False
   (groups if eligible else protected_blue).append(g)
  if reference and rule=='review':rule='question-answer-evidence'
  protected=[(g[0][0],g[-1][0]+1) for g in protected_blue]
  audit={'entry':ei,'chapter':e['chapter'],'no':e['no'],'section':e['section'],'text':text,'rule':rule,'protected':protected,'bluePrompt':[''.join(c['c'] for g in protected_blue for j,c in g)],'matchedPrompt':reference['prompt'] if reference else None,'answers':[''.join(c['c'] for _,c in g) for g in groups]}
  audits.append(audit)
  if rule=='review' and any(blue(c) for c in chars):needs.append(audit);continue
  if not groups:skip.append(audit);continue
  masks=[]
  for mi,g in enumerate(groups,1):
   rects=[]
   for key in dict.fromkeys((c['p'],c['line']) for _,c in g):
    cs=[c for _,c in g if (c['p'],c['line'])==key];x=min(c['b'][0] for c in cs);y=min(c['b'][1] for c in cs);r=max(c['b'][2] for c in cs);b=max(c['b'][3] for c in cs)
    rects.append({'page':key[0],'b':[x,y,r-x,b-y]})
   masks.append({'id':f'{src["id"]}-{ei}-{mi}','text':''.join(c['c'] for _,c in g),'rects':rects,'indices':[j for j,_ in g]})
  refs=[];spans=[]
  for pn in dict.fromkeys(n for n,l in e['lines']):
   ls=[l for n,l in e['lines'] if n==pn];x=max(0,min(l['b'][0] for l in ls)-3);y=max(0,min(l['b'][1] for l in ls)-3);right=min(ps[pn-1]['width'],max(l['b'][2] for l in ls)+3);bottom=min(ps[pn-1]['height'],max(l['b'][3] for l in ls)+3)
   refs.append({'page':pn,'b':[x,y,right-x,bottom-y]})
   spans.extend({'page':pn,'text':s['text'],'x':s['origin'][0],'y':s['origin'][1],'size':s['size'],'font':s['font'],'color':s['color'],'b':s['bbox']} for l in ls for s in l['spans'])
  masked={j:k for k,g in enumerate(groups) for j,c in g};seen=set();parts=[]
  for j,c in enumerate(chars):
   if j in masked:
    key=masked[j]
    if key not in seen:parts.append('［　］');seen.add(key)
   else:parts.append(c['c'])
  prompt=re.sub(r'^\d+[.．]\s*','',''.join(parts)).strip()[:200]
  q=matching.common(src['id'],'cloze',len(qs)+1,src['module'],e['chapter'],prompt)
  q.update(originalNo=e['no'],section='蓝色考点挖空 · '+e['section'],qRefs=refs,keyRefs=refs,analysis=[{'k':'原文蓝色考点','t':'；'.join(m['text'] for m in masks)}],cloze={'masks':masks,'spans':spans,'text':text,'protected':protected,'rule':rule,'sourceEntry':ei})
  qs.append(q)
 return qs,{'entries':len(entries),'cards':len(qs),'maskGroups':sum(len(q['cloze']['masks']) for q in qs),'audit':audits,'needsReview':needs,'skippedPromptOnly':skip}

def match_sources(qs,site):
 docs={k:json.loads((site/'data'/f'lecture-{k}.json').read_text()) for k in ['k','s']};docs['m']={p['id']:p['text'] for p in json.loads((site/'data/manual-index.json').read_text())['pages']}
 for kind,pages in docs.items():
  ix=collections.defaultdict(set)
  for key,t in pages.items():
   t=norm(t)
   for i in range(len(t)-11):ix[t[i:i+12]].add(key)
  for q in qs:
   raw=' '.join(i['text'] for i in q['left']+q['right']) if q['type']=='matching' else q['cloze']['text'];t=norm(raw);scores=collections.Counter()
   for g in {t[i:i+12] for i in range(len(t)-11)}:
    keys=ix.get(g,())
    if len(keys)<=4:scores.update(keys)
   hits=[k for k,n in scores.most_common(2) if n>=6];q[{'k':'kPages','s':'sPages','m':'mRefs'}[kind]]=list(map(int,hits)) if kind!='m' else hits

def render(job):
 id,pn=job;d=fitz.open(ROOT/'pdf'/f'{id}.pdf');out=ROOT/'img'/id/f'{pn:03}.png';out.parent.mkdir(parents=True,exist_ok=True);d[pn-1].get_pixmap(matrix=fitz.Matrix(3.125,3.125),alpha=False).save(out);b=out.read_bytes();return {'page':pn,'ext':'png','bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def main():
 p=argparse.ArgumentParser();p.add_argument('--site',type=pathlib.Path,required=True);args=p.parse_args();books=[];banks={};reports={};reused=[];manifests=[]
 for filename in ['cf-upper','cf-lower']:
  for q in json.loads((args.site/'data/practice'/f'{filename}.json').read_text())['questions']:
   semantic.add(q['module'],q['stem'][-200:],'；'.join(q['options'].get(k,'') for k in q['answer']),'choice')
 for src in SOURCES:
  if src['kind']=='cloze' and not semantic.indexes:semantic.prepare()
  doc=fitz.open(ROOT/'pdf'/f'{src["id"]}.pdf');ps=layout(doc);id=src['id'];sha=hashlib.sha256((ROOT/'pdf'/f'{id}.pdf').read_bytes()).hexdigest()
  if src['kind']=='matching':qs,reuse=matches(src,ps,args.site);report={'cards':len(qs),'reused':reuse};reused.extend([id] if reuse else [])
  else:qs,report=clozes(src,ps);reuse=False
  if report.get('needsReview'):ERRORS.append(id+': '+str(len(report['needsReview']))+' prompts need semantic review')
  if src['kind']=='matching':
   for q in qs:
    for item in q['left']:
     answer='；'.join(r['text'] for key in q['matchMap'][item['key']] for r in q['right'] if r['key']==key)
     semantic.add(src['module'],item['text'],answer,'matching')
  reports[id]=report;dump(id+'-audit.json',report)
  if not reuse:
   match_sources(qs,args.site);chapters=[]
   for q in qs:
    key=q['module']+' · '+q['chapter'];ch=next((c for c in chapters if c['key']==key),None)
    if ch is None:ch={'key':key,'title':q['chapter'],'firstPage':q['qRefs'][0]['page'],'count':0};chapters.append(ch)
    ch['count']+=1
   book={**src,'pages':len(ps),'count':len(qs),'sha256':sha,'sourceBase':BASE,'url':BASE+'pdf/'+id+'.pdf','counts':dict(collections.Counter(q['type'] for q in qs)),'chapters':chapters,'pageSizes':[{'width':p['width'],'height':p['height']} for p in ps],'studyStage':'second' if src['kind']=='matching' else 'hats'}
   books.append(book);banks[id]={'bookId':id,'questions':qs,'pages':[{k:p[k] for k in ['page','width','height','text']} for p in ps]};dump(id+'.json',banks[id])
  print(id,len(qs),'reuse',reuse,'review',len(report.get('needsReview',[])),flush=True)
 dump('build-report.json',{'errors':ERRORS,'reused':reused,'books':[{k:b[k] for k in ['id','count','pages','kind']} for b in books],'matchingCount':sum(q['type']=='matching' for d in banks.values() for q in d['questions']),'clozeCount':sum(q['type']=='cloze' for d in banks.values() for q in d['questions'])})
 dump('books.json',books)
 if ERRORS:raise RuntimeError('Validation stopped publication: '+str(ERRORS))
 for book in books:
  id=book['id']
  with concurrent.futures.ProcessPoolExecutor(max_workers=4) as ex:imgs=list(ex.map(render,[(id,n) for n in range(1,book['pages']+1)]))
  manifests.append({'id':id,'pdfSha256':book['sha256'],'pages':imgs,'render':{'dpi':225,'format':'png','lossless':True,'firstGeneration':True}})
 dump('source-manifests.json',manifests)
 print('VALIDATED',sum(b['count'] for b in books),'new exercises',flush=True)
if __name__=='__main__':main()
