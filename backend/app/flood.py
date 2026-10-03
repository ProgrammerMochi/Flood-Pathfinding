"""Flood-report policy: snapping, expiry, voting, and edge-depth aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Callable, Hashable, Protocol

import geopandas as gpd
import osmnx as ox
from pyproj import Transformer
from shapely.geometry import Point

ACTIVE_FOR = timedelta(hours=2)
MAX_REPORTS_PER_HOUR = 10
EdgeKey = tuple[Hashable, Hashable, Hashable]
EdgeSnapper = Callable[[float, float], list[EdgeKey]]


@dataclass(frozen=True)
class FloodReport:
    id: int
    lat: float
    lon: float
    depth_cm: int
    note: str | None
    device_id: str
    created_at: datetime
    last_confirmed_at: datetime
    clear_votes: int
    is_cleared: bool


class VoteResult(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    NOT_FOUND = "not_found"


class ReportStore(Protocol):
    def reports_created_by(self, device_id: str, since: datetime) -> int: ...
    def create_report(self, *, lat: float, lon: float, depth_cm: int, note: str | None, device_id: str, now: datetime) -> FloodReport: ...
    def active_reports(self, since: datetime) -> list[FloodReport]: ...
    def vote(self, report_id: int, device_id: str, vote: str, now: datetime) -> VoteResult: ...


class PinHasNoNearbyRoad(ValueError):
    pass


class RateLimitExceeded(ValueError):
    pass


class GraphEdgeSnapper:
    """Find every road edge within 30 m of a WGS84 report coordinate."""

    radius_m = 30

    def __init__(self, graph):
        self.graph = ox.project_graph(graph)
        source_crs = graph.graph["crs"]
        self.transformer = Transformer.from_crs(source_crs, self.graph.graph["crs"], always_xy=True)
        self.edges: gpd.GeoDataFrame = ox.graph_to_gdfs(self.graph, nodes=False, fill_edge_geometry=True)

    def __call__(self, lat: float, lon: float) -> list[EdgeKey]:
        x, y = self.transformer.transform(lon, lat)
        _, nearest_distance = ox.distance.nearest_edges(self.graph, X=x, Y=y, return_dist=True)
        if nearest_distance > self.radius_m:
            return []
        point = Point(x, y)
        nearby = self.edges[self.edges.geometry.distance(point) <= self.radius_m]
        return [(u, v, key) for u, v, key in nearby.index]


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_active(report: FloodReport, now: datetime) -> bool:
    return not report.is_cleared and report.last_confirmed_at >= now - ACTIVE_FOR


class FloodReportService:
    def __init__(self, store: ReportStore, snapper: EdgeSnapper, now: Callable[[], datetime] = utc_now):
        self.store = store
        self.snapper = snapper
        self.now = now

    def create(self, *, lat: float, lon: float, depth_cm: int, note: str | None, device_id: str) -> FloodReport:
        if not self.snapper(lat, lon):
            raise PinHasNoNearbyRoad("No road is within 30 m of this pin")
        current_time = self.now()
        if self.store.reports_created_by(device_id, current_time - timedelta(hours=1)) >= MAX_REPORTS_PER_HOUR:
            raise RateLimitExceeded("A device may create at most 10 reports per hour")
        return self.store.create_report(lat=lat, lon=lon, depth_cm=depth_cm, note=note, device_id=device_id, now=current_time)

    def active(self) -> list[FloodReport]:
        return self.store.active_reports(self.now() - ACTIVE_FOR)

    def cast_vote(self, report_id: int, device_id: str, vote: str) -> VoteResult:
        return self.store.vote(report_id, device_id, vote, self.now())

    def edge_depths(self) -> dict[EdgeKey, int]:
        depths: dict[EdgeKey, int] = {}
        for report in self.active():
            for edge in self.snapper(report.lat, report.lon):
                depths[edge] = max(depths.get(edge, 0), report.depth_cm)
        return depths
