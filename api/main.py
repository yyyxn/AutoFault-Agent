from __future__ import annotations
import asyncio,os,time
from collections import defaultdict,deque
from fastapi import Depends,FastAPI,Header,HTTPException,Request
from fastapi.middleware.cors import CORSMiddleware
from autofault_agent.data import scenarios
from autofault_agent.engine import run_live
from autofault_agent.live import LiveUnavailable,live_preflight
from autofault_agent.models import RunRequest,RunResult
from autofault_agent.replay import run_replay

app=FastAPI(title="AutoFault-Agent Demo API",version="0.1.0",docs_url="/docs",redoc_url=None)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:8501","http://127.0.0.1:8501"],allow_methods=["GET","POST"],allow_headers=["Authorization","Content-Type"])
semaphore=asyncio.Semaphore(max(1,int(os.getenv("AUTOFAULT_MAX_CONCURRENCY","1"))))
requests=defaultdict(deque)

def _auth(authorization:str|None=Header(default=None)):
    expected=os.getenv("AUTOFAULT_API_TOKEN","")
    if not expected:raise HTTPException(503,"Live authentication is not configured")
    if authorization!=f"Bearer {expected}":raise HTTPException(401,"Invalid API token")

def _limit(request:Request):
    key=request.client.host if request.client else "unknown";now=time.monotonic();q=requests[key]
    while q and q[0]<now-60:q.popleft()
    if len(q)>=30:raise HTTPException(429,"Rate limit exceeded")
    q.append(now)

@app.get("/health")
def health():return {"status":"ok","default_mode":"replay","live_enabled":os.getenv("AUTOFAULT_LIVE_ENABLED","false").lower()=="true"}

@app.get("/api/v1/scenarios",dependencies=[Depends(_limit)])
def list_scenarios():return [{"id":x.id,"title":x.title,"description":x.description,"component":x.component,"scenario":x.scenario} for x in scenarios()]

@app.get("/api/v1/live/preflight",dependencies=[Depends(_auth),Depends(_limit)])
def preflight(model:str="base"):
    try:return live_preflight(model)
    except LiveUnavailable as exc:raise HTTPException(503,str(exc)) from exc

@app.post("/api/v1/run",response_model=RunResult,dependencies=[Depends(_limit)])
async def run(req:RunRequest,authorization:str|None=Header(default=None)):
    if req.mode=="replay":
        try:return run_replay(req)
        except KeyError as exc:raise HTTPException(404,"Unknown public scenario") from exc
    _auth(authorization)
    timeout=float(os.getenv("AUTOFAULT_TIMEOUT_SECONDS","120"))
    try:
        async with semaphore:return await asyncio.wait_for(run_live(req),timeout=timeout)
    except LiveUnavailable as exc:raise HTTPException(503,str(exc)) from exc
    except TimeoutError as exc:raise HTTPException(504,"Live execution timed out") from exc
