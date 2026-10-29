from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import audio
from app.bands import GAIN_LIMIT
from app.controller import StreamConflict, StreamController
from app.discovery import AirPlayDiscovery

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
controller = StreamController()
discovery = AirPlayDiscovery()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await run_in_threadpool(discovery.start)
    except Exception:
        logger.exception("AirPlay discovery could not start")
    try:
        yield
    finally:
        await run_in_threadpool(discovery.stop)


app = FastAPI(title="Vinyl Streamer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ConnectRequest(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=512)
    sink: str = Field(min_length=1, max_length=512)
    latency_ms: int = Field(default=80, ge=40, le=500)


class VolumeRequest(BaseModel):
    sink: str | None = Field(default=None, min_length=1, max_length=512)
    volume: int = Field(ge=0, le=150)


class MuteRequest(BaseModel):
    sink: str | None = Field(default=None, min_length=1, max_length=512)
    muted: bool


class EqualizerRequest(BaseModel):
    enabled: bool
    preset: Literal["custom", "neutral", "warm", "bass", "clear", "voices"] = "neutral"
    bands: list[Annotated[float, Field(ge=-GAIN_LIMIT, le=GAIN_LIMIT, allow_inf_nan=False)]] | None = Field(default=None, min_length=6, max_length=6)


class EqualizerPreset(BaseModel):
    id: str
    name: str
    description: str


class EqualizerStatus(BaseModel):
    enabled: bool = False
    preset: str = "neutral"
    active: bool = False
    available: bool = False
    preamp_db: float = 0
    bands: list[float] = Field(default_factory=lambda: [0] * 6)
    custom_bands: list[float] = Field(default_factory=lambda: [0] * 6)
    presets: list[EqualizerPreset] = Field(default_factory=list)


class StatusResponse(BaseModel):
    source: str | None = None
    sink: str | None = None
    loopback_module: str | None = None
    raop_module: str | None = None
    latency_ms: int = 80
    running: bool = False
    volume: int | None = None
    muted: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    eq_unit: str | None = None
    eq_sink: str | None = None
    eq_preset: str | None = None
    eq_bands: list[float] | None = None
    eq_cleanup: list[str] = Field(default_factory=list)
    equalizer: EqualizerStatus = Field(default_factory=EqualizerStatus)


@app.exception_handler(RuntimeError)
async def audio_error(request: Request, exc: RuntimeError):
    logger.warning("Audio request failed (%s): %s", request.url.path, exc)
    return JSONResponse(status_code=409 if isinstance(exc, StreamConflict) else 503, content={"detail": str(exc)})


@app.get("/api/status", response_model=StatusResponse)
def get_status() -> dict:
    return controller.status()


@app.get("/api/devices")
def get_devices() -> dict:
    warnings = []
    if discovery.error:
        try:
            discovery.start()
        except Exception:
            logger.warning("AirPlay discovery is still unavailable", exc_info=True)
    with controller.lock:
        try:
            audio.ensure_raop_module()
        except RuntimeError as exc:
            warnings.append(f"AirPlay-uitgangen konden niet worden ingeschakeld: {exc}")
        sinks = sorted((item for item in audio.list_sinks() if audio.is_airplay_sink(item)), key=lambda item: item.name)
        sources = sorted((item for item in audio.list_sources() if not item.name.endswith(".monitor") and not item.name.startswith("auto_null")), key=lambda item: item.name)
    if discovery.error:
        warnings.append(discovery.error)
    return {"sources": sources, "sinks": sinks, "airplay": discovery.snapshot(),
            "warnings": warnings, "discovering": discovery.discovering}


@app.post("/api/connect", response_model=StatusResponse)
def connect(req: ConnectRequest) -> dict:
    try:
        return controller.connect(req.source, req.sink, req.latency_ms)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/disconnect", response_model=StatusResponse)
def disconnect() -> dict:
    return controller.disconnect()


@app.post("/api/equalizer", response_model=StatusResponse)
def set_equalizer(req: EqualizerRequest) -> dict:
    return controller.configure_equalizer(req.enabled, req.preset, req.bands)


@app.post("/api/volume")
def set_volume(req: VolumeRequest) -> dict:
    controller.set_volume(volume=req.volume, sink=req.sink)
    return {"ok": True}


@app.post("/api/mute")
def set_mute(req: MuteRequest) -> dict:
    controller.set_volume(muted=req.muted, sink=req.sink)
    return {"ok": True}


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(
        STATIC / "manifest.webmanifest", media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon() -> FileResponse:
    return FileResponse(STATIC / "icons" / "apple-touch-icon.png", media_type="image/png")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC / "icons" / "favicon.ico", media_type="image/vnd.microsoft.icon")
