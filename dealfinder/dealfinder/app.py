import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, pipeline
from .llm import interview_turn
from .models import SearchSpec
from .ratelimit import Limiter

STATIC = Path(__file__).parent / "static"


class Msg(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    messages: list[Msg] = Field(min_length=1, max_length=config.MAX_CHAT_TURNS)


def create_app(client=None, limiter: Limiter | None = None) -> FastAPI:
    app = FastAPI(title="dealfinder")
    app.state.client = client
    app.state.limiter = limiter or Limiter(config.PER_IP_PER_HOUR, config.DAILY_LLM_CALLS)

    def get_client():
        if app.state.client is None:
            import anthropic
            app.state.client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
        return app.state.client

    def guard(request: Request, cost: int = 1):
        if config.ACCESS_CODE and not hmac.compare_digest(request.headers.get("x-access-code", ""), config.ACCESS_CODE):
            raise HTTPException(401, "Access code required")
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
        if not app.state.limiter.allow(ip, cost):
            raise HTTPException(429, "Too many requests right now; try again later")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https:; style-src 'self'; script-src 'self'"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.get("/api/health")
    def health():
        return {"ok": True, "needs_code": bool(config.ACCESS_CODE)}

    @app.post("/api/chat")
    def chat(body: ChatIn, request: Request):
        guard(request)
        if body.messages[-1].role != "user":
            raise HTTPException(400, "Last message must be from the user")
        msgs = [m.model_dump() for m in body.messages]
        text, spec = interview_turn(get_client(), msgs)
        return {"reply": text, "spec": spec.model_dump() if spec else None}

    @app.post("/api/search")
    async def search(spec: SearchSpec, request: Request):
        guard(request, cost=3)
        return await pipeline.run(get_client(), spec)

    @app.exception_handler(Exception)
    async def boom(request: Request, exc: Exception):
        return JSONResponse({"detail": "Something went wrong talking to Claude or the marketplace."}, status_code=502)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app() if os.environ.get("DEALFINDER_NO_AUTOAPP") != "1" else None
