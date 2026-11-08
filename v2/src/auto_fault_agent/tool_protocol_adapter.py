from __future__ import annotations
import json,re
from dataclasses import dataclass,asdict
from typing import Any
from auto_fault_agent.sft_pipeline import validate_arguments

NATIVE_BLOCK=re.compile(r'<tool_call>(.*?)</tool_call>',re.S)
FUNC_RE=re.compile(r'^\s*<function=([A-Za-z_][A-Za-z0-9_]*)>(.*?)</function>\s*$',re.S)
PARAM_RE=re.compile(r'<parameter=([A-Za-z_][A-Za-z0-9_]*)>(.*?)</parameter>',re.S)
KNOWN={'search_fault_knowledge','get_test_case','inject_fault','read_dtc','judge_test_result','recover_fault'}
@dataclass
class ParseResult:
 status:str
 calls:list[dict[str,Any]]
 raw:str
 source_format:str|None=None
 error:str|None=None
 diagnostics:dict[str,Any]|None=None
 def to_dict(self): return asdict(self)
def _typed(v:str):
 s=v.strip()
 try:return json.loads(s)
 except Exception:return s
def _validate(name,args):
 if name not in KNOWN:return 'unknown_tool'
 errors=validate_arguments(name,args)
 return '; '.join(errors) if errors else None
def parse_tool_output(raw:str)->ParseResult:
 blocks=list(NATIVE_BLOCK.finditer(raw))
 json_blocks=[]
 # JSON format: each block must contain exactly one JSON object and no nonspace text outside blocks.
 for b in blocks:
  body=b.group(1).strip()
  if body.startswith('{'):
   json_blocks.append((b,body))
 if json_blocks:
  if len(blocks)!=len(json_blocks): return ParseResult('PROTOCOL_ERROR',[],raw,'json', 'mixed native/JSON or malformed tool blocks')
  outside=NATIVE_BLOCK.sub('',raw).replace('<|im_end|>','').strip()
  if outside:return ParseResult('PROTOCOL_ERROR',[],raw,'json','ordinary text around tool call')
  calls=[]
  for _,body in json_blocks:
   try:v=json.loads(body)
   except Exception as e:return ParseResult('PROTOCOL_ERROR',[],raw,'json',f'invalid JSON: {e}')
   if not isinstance(v,dict) or not isinstance(v.get('name'),str) or not isinstance(v.get('arguments'),dict):return ParseResult('PROTOCOL_ERROR',[],raw,'json','required name/arguments object missing')
   err=_validate(v['name'],v['arguments'])
   if err:return ParseResult('PROTOCOL_ERROR',[],raw,'json',err)
   calls.append({'name':v['name'],'arguments':v['arguments']})
  if len(calls)!=1:return ParseResult('PROTOCOL_ERROR',calls,raw,'json','multiple tool calls are unsupported by frozen single-call protocol')
  return ParseResult('TOOL_CALL',calls,raw,'json',None,{'call_count':1})
 if not blocks:
  cleaned=raw.replace('<|im_end|>','').strip()
  if any(x in cleaned for x in ('<function=','<parameter=','</function>','<parameter>')):
   return ParseResult('PROTOCOL_ERROR',[],raw,'native','incomplete or malformed native tags')
  return ParseResult('FINAL',[],raw,None,None,{'content':cleaned})
 calls=[]
 for b in blocks:
  fm=FUNC_RE.match(b.group(1))
  if not fm:return ParseResult('PROTOCOL_ERROR',[],raw,'native','invalid function boundary')
  name,body=fm.group(1),fm.group(2)
  matches=list(PARAM_RE.finditer(body)); residue=PARAM_RE.sub('',body).strip()
  if residue:return ParseResult('PROTOCOL_ERROR',[],raw,'native','text outside parameter tags')
  args={}
  for m in matches:
   key=m.group(1)
   if key in args:return ParseResult('PROTOCOL_ERROR',[],raw,'native',f'duplicate parameter: {key}')
   args[key]=_typed(m.group(2))
  err=_validate(name,args)
  if err:return ParseResult('PROTOCOL_ERROR',[],raw,'native',err)
  calls.append({'name':name,'arguments':args})
 if len(calls)!=1:return ParseResult('PROTOCOL_ERROR',calls,raw,'native','multiple tool calls are unsupported by frozen single-call protocol')
 outside=NATIVE_BLOCK.sub('',raw).replace('<|im_end|>','').strip()
 if outside:return ParseResult('PROTOCOL_ERROR',calls,raw,'native','ordinary text around tool call')
 return ParseResult('TOOL_CALL',calls,raw,'native',None,{'call_count':1})