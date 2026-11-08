class RecoveryManager:
    TRANSIENT_MARKERS=("transient", "temporary_tool_failure", "temporarily unavailable")
    def retryable(self,error):
        if not error: return False
        kind=str(error.get("type","")).lower(); message=str(error.get("message","")).lower()
        return kind in {"timeouterror","harnesstimeouterror"} or any(x in message for x in self.TRANSIENT_MARKERS)
