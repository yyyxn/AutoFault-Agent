from __future__ import annotations
import hashlib,json

class ContextCompactor:
    def __init__(self,recent_turns=8,recent_observations=6):self.recent_turns=recent_turns;self.recent_observations=recent_observations
    @staticmethod
    def _digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    def compact_messages(self,messages):
        pinned=[];pairs=[];plain=[];i=0
        while i<len(messages):
            m=messages[i]
            if m.get("role") in {"system","user"} and not plain: pinned.append(m);i+=1;continue
            if m.get("role")=="assistant" and m.get("tool_calls"):
                group=[m];j=i+1
                while j<len(messages) and messages[j].get("role")=="tool":group.append(messages[j]);j+=1
                if len(group)>1:pairs.append(group);i=j;continue
            plain.append(m);i+=1
        seen=set();kept_pairs=[];summary=[]
        for group in reversed(pairs):
            key=self._digest([{"name":x.get("name"),"content":x.get("content")} for x in group[1:]])
            if key in seen:summary.append({"type":"duplicate_tool_observation","digest":key,"count":1});continue
            seen.add(key);kept_pairs.append(group)
            if len(kept_pairs)>=self.recent_observations:
                for older in pairs[:max(0,len(pairs)-len(kept_pairs))]:summary.append({"type":"older_tool_pair","digest":self._digest(older),"count":1})
                break
        result=list(pinned)
        for group in reversed(kept_pairs):result.extend(group)
        result.extend(plain[-self.recent_turns:])
        return result,summary,max(0,len(pairs)-len(kept_pairs))
