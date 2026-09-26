"""Full-screen walking map for shorter and cooler Financial District walks."""

import gc
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import router

app = FastAPI()
PAGE = Path(__file__).resolve().parent / "web" / "index.html"
# The free host has little memory. Keep one hourly map, and only one search at a time.
_lock = threading.Lock()
_cached_key = None
_cached_graph = None


class RouteRequest(BaseModel):
    origin: str
    destination: str
    month: int = Field(ge=1, le=12)
    hour: int = Field(ge=0, le=23)


def _graphs():
    return router.list_graphs()


def _network(month, hour):
    global _cached_key, _cached_graph
    path = _graphs().get((month, hour))
    if path is None:
        raise router.RouteError(f"No heat model for month {month}, hour {hour}.")
    if _cached_key != path or _cached_graph is None:
        _cached_graph = None
        gc.collect()
        _cached_graph = router.load_network(path)
        _cached_key = path
    return _cached_graph


@app.get("/")
def index():
    return FileResponse(PAGE)


@app.get("/api/options")
def options():
    months: dict[str, list[int]] = {}
    for month, hour in sorted(_graphs()):
        months.setdefault(str(month), []).append(hour)
    return {"months": months}


@app.post("/api/routes")
def routes(body: RouteRequest):
    try:
        with _lock:
            start = router.geocode(body.origin)
            end = router.geocode(body.destination)
            found = router.routes_between(
                _network(body.month, body.hour),
                (start[0], start[1]),
                (end[0], end[1]),
            )
    except router.RouteError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"detail": "The walk search stopped. Wait a few seconds and press Find walks again."},
        )
    return {
        "origin_name": start[2],
        "destination_name": end[2],
        "selected": router.knee_index(found),
        "routes": found,
    }
