"""Use actual question/answer pairs to distinguish blue prompts from blue answers, including inverted statements."""
import collections,difflib,re
refs=[];indexes={}
def norm(t):return re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]','',t).lower()
def add(module,prompt,answer,source):
 l=norm(prompt);r=norm(answer)
 if len(l)>=3 and len(r)>=2:refs.append({'module':module,'prompt':prompt,'answer':answer,'l':l,'r':r,'source':source})
def prepare():
 for i,r in enumerate(refs):
  ix=indexes.setdefault(r['module'],collections.defaultdict(set))
  for g in {r['l'][j:j+3] for j in range(len(r['l'])-2)}:ix[g].add(i)
def find(module,text):
 e=norm(text);ix=indexes.get(module,{});scores=collections.Counter()
 for g in {e[i:i+3] for i in range(len(e)-2)}:scores.update(ix.get(g,()))
 best=None;value=0
 for i,n in scores.most_common(80):
  r=refs[i];ls=[b for b in difflib.SequenceMatcher(None,r['l'],e,autojunk=False).get_matching_blocks() if b.size>=3];rs=[b for b in difflib.SequenceMatcher(None,r['r'],e,autojunk=False).get_matching_blocks() if b.size>=2]
  ln=sum(b.size for b in ls);rn=sum(b.size for b in rs)
  if ln<min(6,len(r['l'])) or rn<min(3,len(r['r'])):continue
  lp={j for b in ls for j in range(b.b,b.b+b.size)};rp={j for b in rs for j in range(b.b,b.b+b.size)};coverage=len(lp|rp)/max(1,len(e))
  if coverage<.5:continue
  v=coverage+min(1,ln/len(r['l']))*.25+min(1,rn/len(r['r']))*.25+(.35 if r['source']=='matching' else 0)
  if v>value:value=v;best={**r,'leftPositions':lp,'rightPositions':rp,'coverage':coverage}
 return best
