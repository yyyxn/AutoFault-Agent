import os
from dataclasses import dataclass

@dataclass
class HarnessConfig:
    timeout_seconds: float = float(os.getenv("HARNESS_TIMEOUT_SECONDS", "3"))
    max_retries: int = 2
    max_steps: int = 8
    enable_retry: bool = True
    enable_timeout: bool = True
    enable_step_limit: bool = True
    enable_checkpoint: bool = True
    ledger_filename: str = "action_ledger.sqlite3"
