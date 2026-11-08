import json
import os
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from .context import ExecutionContext
from .progress import ProgressCorruptError,RecoveryStatus

def now():return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class RecoveryResult:
    status:RecoveryStatus
    safe_to_resume:bool
    checkpoint_payload:dict|None=None
    progress_state:object|None=None
    diagnostic:str|None=None

class CheckpointStore:
    def __init__(self,root): self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
    def _next_version(self,session_id):
        latest=self.latest(session_id)
        if not latest:return 1
        try:return int((self.read(latest).get("consistency") or {}).get("checkpoint_version",0))+1
        except Exception:return 1
    def save(self,context,dut,ledger_entry=None,*,progress_version=0,last_committed_sequence=0,recovery_status=RecoveryStatus.CONSISTENT.value):
        path=self.root/f"{context.session_id}_{context.task_id}_step_{context.step_count:03}.json"
        checkpoint_version=self._next_version(context.session_id)
        payload={"context":context.model_dump(),"dut":dut.snapshot(),"ledger":{"logical_action":ledger_entry},"consistency":{"task_id":context.task_id,"checkpoint_version":checkpoint_version,"progress_version":int(progress_version),"last_committed_sequence":int(last_committed_sequence),"updated_at":now(),"recovery_status":str(recovery_status)}}
        temporary=path.with_suffix(path.suffix+f".tmp.{os.getpid()}")
        with temporary.open("w",encoding="utf-8") as handle:
            handle.write(json.dumps(payload,ensure_ascii=False,indent=2,default=str));handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
        return path
    def read(self,path):
        return json.loads(Path(path).read_text(encoding="utf-8"))
    def latest(self,session_id):
        files=sorted(self.root.glob(f"{session_id}_*_step_*.json"))
        return files[-1] if files else None
    def load(self,path,dut):
        payload=self.read(path); dut.restore(payload["dut"])
        return ExecutionContext.model_validate(payload["context"])
    def arbitrate(self,path,progress_store,*,session_id=None,task_id=None):
        payload=None
        if path is not None:
            try:payload=self.read(path);session_id=session_id or payload["context"]["session_id"];task_id=task_id or payload["context"]["task_id"]
            except Exception as exc:return RecoveryResult(RecoveryStatus.CHECKPOINT_CORRUPT,False,diagnostic=str(exc))
        if session_id is None or task_id is None:return RecoveryResult(RecoveryStatus.BOTH_MISSING,False,diagnostic="session_id/task_id unavailable")
        try:progress=progress_store.load(session_id,task_id)
        except ProgressCorruptError as exc:return RecoveryResult(RecoveryStatus.PROGRESS_CORRUPT,False,payload,diagnostic=str(exc))
        if payload is None and progress is None:return RecoveryResult(RecoveryStatus.BOTH_MISSING,False)
        if payload is None:return RecoveryResult(RecoveryStatus.PROGRESS_AHEAD,True,None,progress,"checkpoint missing; resume from committed progress and rebuild task context explicitly")
        consistency=payload.get("consistency") or {}
        checkpoint_progress=int(consistency.get("progress_version",0))
        if progress is None:return RecoveryResult(RecoveryStatus.PROGRESS_MISSING,False,payload,None,"checkpoint references unavailable progress state")
        if progress.version>checkpoint_progress:return RecoveryResult(RecoveryStatus.PROGRESS_AHEAD,True,payload,progress,"progress commit is authoritative; checkpoint is stale")
        if progress.version<checkpoint_progress:return RecoveryResult(RecoveryStatus.CHECKPOINT_AHEAD,False,payload,progress,"checkpoint references an uncommitted or missing progress version")
        checkpoint_fingerprint=(payload.get("context") or {}).get("progress_fingerprint")
        if checkpoint_fingerprint!=progress.progress_fingerprint:return RecoveryResult(RecoveryStatus.CONFLICT,False,payload,progress,"equal versions contain different progress fingerprints")
        return RecoveryResult(RecoveryStatus.CONSISTENT,True,payload,progress)
