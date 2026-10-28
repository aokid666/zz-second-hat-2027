import re
CIRC="①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
DIG={c:str(i+1) for i,c in enumerate(CIRC)}
MODS=["马克思主义基本原理","思想道德与法治","中国近现代史纲要"]
norm=lambda t:re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]","",t).lower()
layouts={}
def heads(b,ls):return [l for l in ls if re.match(r"^连线题\s*[一二三四五六七八九十0-9]+",l["t"])]
def ref(p,lo=35,hi=None):return {'page':p['page'],'b':[20,round(max(0,lo),2),round(p['width']-40,2),round(min(p['height']-25,hi or p['height']-25)-max(0,lo),2)]}
def common(b,typ,n,module,chapter,stem):return {'id':f'pr-{b}-{typ}-{n:04}','bookId':b,'type':typ,'source':'p','moduleIdx':9,'module':module,'chapter':chapter,'chapterTitle':chapter,'section':'连线题' if typ=='matching' else '材料分析题' if typ=='written' else '选择题','no':n,'stem':stem,'options':{},'multi':False,'answer':'','kPages':[],'sPages':[],'mRefs':[],'aPages':[],'aCrops':[],'analysis':[],'qRefs':[],'keyRefs':[]}
def items(ls,side,pat,stop,threshold):
 chosen=[l for l in ls if l['b'][1]<stop and (l['b'][0]<threshold if side=='left' else l['b'][0]>=threshold)];chosen.sort(key=lambda l:(round(l['b'][1],1),l['b'][0]));out=[];cur=None
 for l in chosen:
  t=l['t']
  if re.match(r'^[A-Z1-9][.．]?\s*[—－–\-→]',t):continue
  m=re.match(pat,t)
  if m:
   if cur:out.append(cur)
   cur={'key':DIG.get(m[1],m[1]),'originalLabel':m[1],'text':m[2].strip()}
  elif cur and not re.search(r'^答案|^解析|《考点|乘风考点|^P\d|^第\d+\s*页|^左列|^右列|^连线|^请将|DAY',t):cur['text']+=t
 if cur:out.append(cur)
 return out

def matching(b):
 ps=layouts[b];segments=[];day='';chapter='';isAnswer=False
 for p in ps:
  ls=p['lines'];txt='\n'.join(l['t'] for l in ls);d=re.search(r'(?:腿)?DAY\s*(\d+)',txt,re.I)
  if d:day='DAY'+d[1];isAnswer=False
  if b in ['leg-marx','xu-marx'] and any(l['t']=='答案' and l['b'][1]<130 for l in ls):isAnswer=True
  cs=[l['t'] for l in ls if re.match(r'^(第[一二三四五六七八九十]+章|绪论)',l['t']) and l['b'][1]<150]
  if cs:chapter=''.join(cs)
  hs=heads(b,ls)
  for j,h in enumerate(hs):
   lo=h['b'][1];hi=hs[j+1]['b'][1]-3 if j+1<len(hs) else p['height']-30;sub=[l for l in ls if lo<=l['b'][1]<hi];refs=[ref(p,lo-4,hi)]
   if j==len(hs)-1 and p['page']<len(ps):
    nxt=ps[p['page']];lim=next((l['b'][1] for l in nxt['lines'] if l in heads(b,nxt['lines']) or re.search(r'^连线题答案|^(?:腿)?DAY|^第[一二三四五六七八九十]+章',l['t'])),nxt['height']-30);prefix=[l for l in nxt['lines'] if l['b'][1]<lim and l['b'][1]<nxt['height']-35]
    if prefix and not re.search('连线题|学成选择|DAY',prefix[0]['t']):
     for l in prefix:
      v=dict(l);v['b']=list(l['b']);v['b'][1]+=p['height'];v['b'][3]+=p['height'];sub.append(v)
     refs.append(ref(nxt,35,lim-3));hi=p['height']+lim-3
   subtext='\n'.join(l['t'] for l in sub);al=next((l for l in sub if re.match(r'^答案[：:]|^解析[：:]',l['t'])),None);stop=al['b'][1] if al else hi
   lp=r'^([1-9])\s*(.*)$' if b=='xu-ethics' else r'^([A-Z])[.．、]?\s*(.*)$';rp=r'^([A-Z])[.．、]?\s*(.*)$' if b=='xu-ethics' else r'^(['+CIRC+r'])\s*(.*)$';xs=[l['b'][0] for l in sub if re.match(rp,l['t']) and l['b'][1]>lo+15]
   if not xs:continue
   threshold=min(xs)-5;left=items(sub,'left',lp,stop,threshold);right=items(sub,'right',rp,stop,threshold)
   if b=='xu-ethics':
    for k,i in enumerate(right):i['key']=str(k+1)
   maps={}
   for a,raw in re.findall(r'([A-Z1-9])[.．]?\s*[—－–\-→]\s*(['+CIRC+r'A-Z]+)',subtext):
    if a not in maps:maps[a]=[str(ord(c)-64) if b=='xu-ethics' and c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' else DIG.get(c,c) for c in raw]
   if len(left)<2 or len(right)<2:continue
   segments.append({'page':p['page'],'title':h['t'],'chapter':day or chapter,'left':left,'right':right,'maps':maps,'answer':isAnswer or bool(maps) or (b in ['leg-round','xu-history'] and '答案' in h['t']),'refs':refs,'text':subtext,'ansY':al['b'][1] if al else None})
 
 qs=[];ans=[s for s in segments if s['answer']];module=MODS[1] if b in ['ethics-match','xu-ethics'] else MODS[2] if b in ['leg-round','xu-history','history-second'] else MODS[0]
 for seg in segments:
  same=b in ['ethics-match','history-second']
  if seg['answer'] and not same:continue
  q=common(b,'matching',len(qs)+1,module,seg['chapter'] or '专题连线',seg['title']);q.update(left=seg['left'],right=seg['right'],matchMap={},qRefs=[dict(r,b=r['b'][:]) for r in seg['refs']]);qs.append(q)
  a=seg if same else None
  if not a:
   sig=norm(''.join(i['text'] for i in seg['left']));cand=[a for a in ans if norm(''.join(i['text'] for i in a['left']))==sig]
   if not cand:cand=[a for a in ans if re.sub(r'答案|（.*?）|\s+','',a['title'])==re.sub(r'答案|（.*?）|\s+','',q['stem']) and a['page']>=seg['page']]
   if cand:a=min(cand,key=lambda a:abs(a['page']-seg['page']));ans.remove(a)
  if a:
   q['matchMap']=a['maps'];q['keyRefs']=a['refs'];q['analysis']=[{'k':'原书配对与讲解','t':a['text'][a['text'].find('答案'):] if '答案' in a['text'] else '原书配对：'+'；'.join(k+'—'+','.join(v) for k,v in a['maps'].items())}]
   if same and seg['ansY']:q['qRefs'][0]['b'][3]=seg['ansY']-q['qRefs'][0]['b'][1]-4
  q['multiMatch']=any(len(v)>1 for v in q['matchMap'].values())
 return qs

