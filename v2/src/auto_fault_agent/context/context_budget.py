from __future__ import annotations
import json,math

class ContextBudgetExceeded(RuntimeError):pass

class ContextBudgetController:
    def __init__(self,max_context_tokens,reserved_output_tokens=512,tokenizer=None):
        if max_context_tokens<=reserved_output_tokens:raise ValueError("reserved output must be smaller than context limit")
        self.max_context_tokens=max_context_tokens;self.reserved_output_tokens=reserved_output_tokens;self.tokenizer=tokenizer
        self.token_count_mode="exact" if tokenizer is not None else "estimated";self.token_count_scope="serialized_payload_without_chat_template"
    def count_text(self,value):
        text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True,default=str)
        if self.tokenizer is not None:
            encoded=self.tokenizer(text,add_special_tokens=False);ids=encoded["input_ids"] if isinstance(encoded,dict) else encoded.input_ids
            return len(ids)
        return max(1,math.ceil(len(text.encode("utf-8"))/3))
    def measure(self,system_prompt,task_context,observations,conversation):
        parts={"system_prompt_tokens":self.count_text(system_prompt),"task_context_tokens":self.count_text(task_context),"observation_tokens":self.count_text(observations),"conversation_tokens":self.count_text(conversation)}
        current=sum(parts.values());return {"max_context_tokens":self.max_context_tokens,"reserved_output_tokens":self.reserved_output_tokens,**parts,"current_context_tokens":current,"available_context_tokens":self.max_context_tokens-self.reserved_output_tokens-current,"token_count_mode":self.token_count_mode,"token_count_scope":self.token_count_scope}
    def ensure(self,budget):
        if budget["available_context_tokens"]<0:raise ContextBudgetExceeded("CONTEXT_BUDGET_EXCEEDED")
