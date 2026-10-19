from __future__ import annotations
import json,os,re,time
from pathlib import Path
from .models import ToolCall
from .tools import TOOL_SCHEMAS

CALL=re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>",re.S)
class LiveUnavailable(RuntimeError):pass

def live_preflight(model:str):
    if os.getenv("AUTOFAULT_LIVE_ENABLED","false").lower()!="true":raise LiveUnavailable("Live mode is disabled by default")
    base=Path(os.getenv("AUTOFAULT_MODEL_PATH",""));adapter=Path(os.getenv("AUTOFAULT_SFT_ADAPTER_PATH",""))
    if not base.is_dir() or not (base/'config.json').is_file():raise LiveUnavailable("Base model path is unavailable")
    if model=="sft-b" and (not adapter.is_dir() or not (adapter/'adapter_config.json').is_file()):raise LiveUnavailable("SFT-B adapter path is unavailable")
    try:
        import torch
        if not torch.cuda.is_available() or torch.cuda.device_count()!=1:raise LiveUnavailable("Live mode requires exactly one visible CUDA device")
        free,total=torch.cuda.mem_get_info(0)
        if free//2**20<18000:raise LiveUnavailable("Less than 18000 MiB free CUDA memory")
    except ImportError as exc:raise LiveUnavailable("Live dependencies are not installed") from exc
    return {"ready":True,"logical_device":"cuda:0","free_mib":free//2**20,"total_mib":total//2**20}

def parse_action(text:str):
    m=CALL.search(text)
    if not m:return None
    obj=json.loads(m.group(1));return ToolCall(name=obj["name"],arguments=obj.get("arguments",{}))

class ModelToolPolicy:
    """Lazy local Qwen policy. It never imports or loads model libraries in Replay mode."""
    def __init__(self,variant:str):
        live_preflight(variant)
        from transformers import AutoModelForCausalLM,AutoTokenizer
        from peft import PeftModel
        base=os.environ["AUTOFAULT_MODEL_PATH"]
        self.tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True)
        model=AutoModelForCausalLM.from_pretrained(base,torch_dtype="auto",device_map={"":"cuda:0"},local_files_only=True)
        if variant=="sft-b":model=PeftModel.from_pretrained(model,os.environ["AUTOFAULT_SFT_ADAPTER_PATH"],local_files_only=True)
        self.model=model.eval();self.variant=variant
    def generate(self,messages,max_new_tokens=160):
        rendered=self.tokenizer.apply_chat_template(messages,tools=TOOL_SCHEMAS,tokenize=False,add_generation_prompt=True)
        inputs=self.tokenizer(rendered,return_tensors="pt").to("cuda:0");started=time.perf_counter()
        out=self.model.generate(**inputs,max_new_tokens=max_new_tokens,do_sample=False)
        text=self.tokenizer.decode(out[0,inputs.input_ids.shape[1]:],skip_special_tokens=True)
        return text,(time.perf_counter()-started)*1000
