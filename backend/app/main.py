"""Phase 2A FastAPI endpoints for flood-aware routing."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
import os
from typing import Annotated, Any, Callable, Hashable, Literal

import networkx as nx
import osmnx as ox
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.db import PostgresReportStore
from app.flood import FloodReport, FloodReportService, GraphEdgeSnapper, PinHasNoNearbyRoad, RateLimitExceeded, VoteResult
from app.routing import (
    base_time_seconds,
    edge_cost,
    mark_edges_flooded,
    shortest_normal_route,
    shortest_safe_route,
)
from app.vehicles import VEHICLES

MALABON_PLACE = "Malabon, Metro Manila, Philippines"
GraphLoader = Callable[[], nx.MultiDiGraph]
NodeFinder = Callable[[nx.MultiDiGraph, float, float], Hashable]
ReportServiceFactory = Callable[[nx.MultiDiGraph], FloodReportService]


class Point(BaseModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]


class RouteRequest(BaseModel):
    origin: Point
    destination: Point
    safe_depth_cm: Annotated[float, Field(gt=0)]
    heavy_rain: bool = False


class RouteDetails(BaseModel):
    geometry: dict[str, Any]
    distance_m: float | None
    duration_s: float | None
    max_depth_cm: float | None
    status: str | None = None


class RouteResponse(BaseModel):
    safe_route: RouteDetails
    normal_route: RouteDetails
    warnings: list[str]


class CreateReportRequest(Point):
    depth_cm: Annotated[int, Field(ge=0, le=200)]
    note: str | None = Field(default=None, max_length=1_000)
    device_id: Annotated[str, Field(min_length=1, max_length=200)]


class VoteRequest(BaseModel):
    device_id: Annotated[str, Field(min_length=1, max_length=200)]
    vote: Literal["confirm", "clear"]


class ReportResponse(BaseModel):
    id: int
    lat: float
    lon: float
    depth_cm: int
    note: str | None
    created_at: datetime
    last_confirmed_at: datetime
    clear_votes: int


class VoteResponse(BaseModel):
    status: Literal["accepted"]


def load_malabon_graph() -> nx.MultiDiGraph:
    """Download/load the Malabon driving graph for the process lifetime."""
    return ox.graph_from_place(MALABON_PLACE, network_type="drive")


def find_nearest_node(graph: nx.MultiDiGraph, lon: float, lat: float) -> Hashable:
    """Snap a request coordinate to the closest graph node."""
    return ox.distance.nearest_nodes(graph, X=lon, Y=lat)


def report_response(report: FloodReport) -> ReportResponse:
    return ReportResponse(
        id=report.id,
        lat=report.lat,
        lon=report.lon,
        depth_cm=report.depth_cm,
        note=report.note,
        created_at=report.created_at,
        last_confirmed_at=report.last_confirmed_at,
        clear_votes=report.clear_votes,
    )


def default_report_service(graph: nx.MultiDiGraph) -> FloodReportService:
    return FloodReportService(PostgresReportStore(), GraphEdgeSnapper(graph))


def _route_edges(
    graph: nx.MultiDiGraph, path: list[Hashable], safe_depth_cm: float | None
) -> list[Mapping[str, Any]]:
    """Choose the edge that matches the routing weight for each path segment."""
    selected: list[Mapping[str, Any]] = []
    for u, v in zip(path, path[1:]):
        edge_bundle = graph.get_edge_data(u, v)
        if edge_bundle is None:
            raise ValueError(f"Route references missing edge {u!r} -> {v!r}")
        candidates = edge_bundle.values() if graph.is_multigraph() else [edge_bundle]
        chooser = base_time_seconds if safe_depth_cm is None else lambda edge: edge_cost(edge, safe_depth_cm)
        selected.append(min(candidates, key=chooser))
    return selected


def _route_details(
    graph: nx.MultiDiGraph,
    path: list[Hashable] | None,
    duration_s: float | None,
    status: str | None,
    safe_depth_cm: float | None,
) -> RouteDetails:
    if path is None:
        return RouteDetails(
            geometry={"type": "LineString", "coordinates": []},
            distance_m=None,
            duration_s=None,
            max_depth_cm=None,
            status=status,
        )

    edges = _route_edges(graph, path, safe_depth_cm)
    coordinates = [[graph.nodes[node]["x"], graph.nodes[node]["y"]] for node in path]
    return RouteDetails(
        geometry={"type": "LineString", "coordinates": coordinates},
        distance_m=sum(float(edge.get("length_m", edge.get("length", 0))) for edge in edges),
        duration_s=duration_s,
        max_depth_cm=max((float(edge.get("flood_depth_cm", 0)) for edge in edges), default=0),
        status=status,
    )


def create_app(
    graph_loader: GraphLoader = load_malabon_graph,
    node_finder: NodeFinder = find_nearest_node,
    report_service_factory: ReportServiceFactory = default_report_service,
) -> FastAPI:
    """Create an app; dependency injection keeps API tests offline."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        graph = graph_loader()
        app.state.graph = graph
        app.state.report_service = (
            report_service_factory(graph)
            if os.getenv("DATABASE_URL") or report_service_factory is not default_report_service
            else None
        )
        yield

    app = FastAPI(title="Flood-Aware Route Planner", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/vehicles")
    def vehicles() -> list[dict[str, float | str]]:
        return [
            {"id": vehicle_id, "safe_depth_cm": safe_depth_cm}
            for vehicle_id, safe_depth_cm in VEHICLES.items()
        ]

    @app.post("/route", response_model=RouteResponse, response_model_exclude_none=True)
    def route(route_request: RouteRequest, request: Request) -> RouteResponse:
        graph = request.app.state.graph
        try:
            origin = node_finder(graph, route_request.origin.lon, route_request.origin.lat)
            destination = node_finder(graph, route_request.destination.lon, route_request.destination.lat)
        except Exception as error:
            raise HTTPException(status_code=422, detail="Could not snap origin or destination to the road network") from error

        route_graph = graph.copy()
        report_service = request.app.state.report_service
        mark_edges_flooded(route_graph, report_service.edge_depths() if report_service else {})
        safe = shortest_safe_route(route_graph, origin, destination, route_request.safe_depth_cm)
        normal = shortest_normal_route(route_graph, origin, destination)
        warnings = list(safe.warnings)
        if route_request.heavy_rain:
            warnings.append("Heavy-rain hazard data is not available yet; flood depths may be unknown.")

        return RouteResponse(
            safe_route=_route_details(route_graph, safe.path, safe.duration_s, safe.status, route_request.safe_depth_cm),
            normal_route=_route_details(route_graph, normal.path, normal.duration_s, None, None),
            warnings=warnings,
        )

    @app.post("/reports", response_model=ReportResponse, status_code=201)
    def create_report(payload: CreateReportRequest, request: Request) -> ReportResponse:
        report_service = request.app.state.report_service
        if report_service is None:
            raise HTTPException(status_code=503, detail="Flood reports require DATABASE_URL to be configured")
        try:
            report = report_service.create(**payload.model_dump())
        except PinHasNoNearbyRoad as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RateLimitExceeded as error:
            raise HTTPException(status_code=429, detail=str(error)) from error
        return report_response(report)

    @app.get("/reports", response_model=list[ReportResponse])
    def get_reports(request: Request) -> list[ReportResponse]:
        report_service = request.app.state.report_service
        if report_service is None:
            raise HTTPException(status_code=503, detail="Flood reports require DATABASE_URL to be configured")
        return [report_response(report) for report in report_service.active()]

    @app.post("/reports/{report_id}/vote", response_model=VoteResponse)
    def vote(report_id: int, payload: VoteRequest, request: Request) -> VoteResponse:
        report_service = request.app.state.report_service
        if report_service is None:
            raise HTTPException(status_code=503, detail="Flood reports require DATABASE_URL to be configured")
        result = report_service.cast_vote(report_id, payload.device_id, payload.vote)
        if result is VoteResult.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Flood report not found")
        if result is VoteResult.DUPLICATE:
            raise HTTPException(status_code=409, detail="This device has already voted on this report")
        return VoteResponse(status="accepted")

    return app


app = create_app()
