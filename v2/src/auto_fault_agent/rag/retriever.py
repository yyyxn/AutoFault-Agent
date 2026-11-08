import math,re,time
from collections import Counter
from ..data import knowledge
def tokens(text): return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]",text.lower())
class HybridRetriever:
    def __init__(self,documents=None):
        self.documents=documents or knowledge(); self.docs=[tokens(d.title+" "+d.content) for d in self.documents]
        self.df=Counter(t for doc in self.docs for t in set(doc)); self.avg=sum(map(len,self.docs))/max(len(self.docs),1)
    def search(self,query,top_k=5):
        start=time.perf_counter(); q=tokens(query); n=len(self.docs); ranked=[]
        for d,ts in zip(self.documents,self.docs):
            c=Counter(ts); score=sum(math.log(1+(n-self.df[t]+.5)/(self.df[t]+.5))*c[t]*2.5/(c[t]+1.5*(.25+.75*len(ts)/self.avg)) for t in q if c[t])
            if any(fid.lower() in query.lower() for fid in d.fault_ids): score+=10
            ranked.append((score,d))
        docs=[{"source_id":d.source_id,"title":d.title,"content":d.content,"score":round(s,5),"source":"synthetic_demo","fault_ids":d.fault_ids} for s,d in sorted(ranked,key=lambda x:x[0],reverse=True)[:top_k]]
        return {"documents":docs,"retrieval_latency_ms":round((time.perf_counter()-start)*1000,3)}
