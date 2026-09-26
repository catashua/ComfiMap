"""Full-screen walking map. Shadows come from leaflet-shadow-simulator."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import router

app = FastAPI()
PAGE = Path(__file__).resolve().parent / "web" / "index.html"
_networks = {}


class RouteRequest(BaseModel):
    origin: str
    destination: str
    month: int = Field(ge=1, le=12)
    hour: int = Field(ge=0, le=23)


def _graphs():
    return router.list_graphs()


def _network(month, hour):
    path = _graphs().get((month, hour))
    if path is None:
        raise HTTPException(
            status_code=400,
            detail=f"No heat model for month {month}, hour {hour}.",
        )
    cached = _networks.get(path)
    if cached is None:
        cached = router.load_network(path)
        _networks[path] = cached
    return cached


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
        start = router.geocode(body.origin)
        end = router.geocode(body.destination)
        found = router.routes_between(
            _network(body.month, body.hour),
            (start[0], start[1]),
            (end[0], end[1]),
        )
    except router.RouteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "origin_name": start[2],
        "destination_name": end[2],
        "selected": router.knee_index(found),
        "routes": found,
    }
