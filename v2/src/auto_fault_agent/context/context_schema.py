from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any

@dataclass
class ContextBuildResult:
    task:dict[str,Any];authoritative_state:dict[str,Any];completion:dict[str,Any]
    actions:dict[str,list[dict[str,Any]]];evidence:list[dict[str,Any]];progress:dict[str,Any]
    messages:list[dict[str,Any]];compressed_summary:list[dict[str,Any]]=field(default_factory=list)
    compacted_observations:int=0;token_budget:dict[str,Any]=field(default_factory=dict);status:str="READY"
    def model_dump(self):return self.__dict__.copy()
