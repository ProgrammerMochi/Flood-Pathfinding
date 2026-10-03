"""Flood-aware edge costs and route selection.

All route durations are in seconds.  The functions work with NetworkX Graph,
DiGraph, MultiGraph, and MultiDiGraph instances; OSMnx normally supplies a
MultiDiGraph.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Any, Hashable, Mapping

import networkx as nx

DEFAULT_SPEED_KPH = 30.0


@dataclass(frozen=True)
class RouteResult:
    """A route outcome, including an unsafe fallback where required."""

    path: list[Hashable] | None
    duration_s: float | None
    status: str
    warnings: list[str]


def _positive_safe_depth(safe_depth_cm: float | int | None) -> float:
    if safe_depth_cm is None or safe_depth_cm <= 0:
        raise ValueError("safe_depth_cm must be greater than zero")
    return float(safe_depth_cm)


def base_time_seconds(edge: Mapping[str, Any]) -> float:
    """Calculate the unflooded traversal time for one edge in seconds."""
    length_m = float(edge.get("length_m", edge.get("length", 0)))
    speed_kph = float(edge.get("speed_kph", DEFAULT_SPEED_KPH))
    if length_m < 0:
        raise ValueError("edge length must not be negative")
    if speed_kph <= 0:
        raise ValueError("edge speed_kph must be greater than zero")
    return length_m / (speed_kph * 1000 / 3600)


def edge_cost(edge: Mapping[str, Any], safe_depth_cm: float | int | None) -> float:
    """Return Section 6's flood-aware cost for one edge.

    ``math.inf`` means the edge is impassable and therefore excluded by the
    safe-route Dijkstra search.
    """
    safe_depth = _positive_safe_depth(safe_depth_cm)
    base_time = base_time_seconds(edge)
    flood_depth = float(edge.get("flood_depth_cm", 0))
    ratio = flood_depth / safe_depth

    if ratio >= 1.0:
        return inf
    if ratio >= 0.5:
        return base_time * (1 + 4 * (ratio - 0.5) / 0.5)
    return base_time


def mark_edges_flooded(
    graph: nx.Graph,
    flooded_edges: Mapping[tuple[Hashable, ...], float | int],
) -> None:
    """Set ``flood_depth_cm`` on graph edges from ``{edge: depth_cm}``.

    MultiGraph keys are ``(u, v, key)``; ordinary Graph/DiGraph keys are
    ``(u, v)``.  Invalid edge keys are left to NetworkX to report clearly.
    """
    for edge_key, depth_cm in flooded_edges.items():
        if depth_cm < 0:
            raise ValueError("flood depth must not be negative")
        if graph.is_multigraph():
            if len(edge_key) != 3:
                raise ValueError("multigraph flood keys must be (u, v, key)")
            u, v, key = edge_key
            graph[u][v][key]["flood_depth_cm"] = depth_cm
        else:
            if len(edge_key) != 2:
                raise ValueError("graph flood keys must be (u, v)")
            u, v = edge_key
            graph[u][v]["flood_depth_cm"] = depth_cm


def _incident_flood_warning(
    graph: nx.Graph, node: Hashable, label: str, safe_depth_cm: float
) -> str | None:
    """Warn when an endpoint touches an impassable flooded edge."""
    edges = graph.edges(node, keys=True, data=True) if graph.is_multigraph() else graph.edges(node, data=True)
    for item in edges:
        data = item[-1]
        if float(data.get("flood_depth_cm", 0)) >= safe_depth_cm:
            return f"{label} is connected to an impassable flooded edge."
    return None


def shortest_safe_route(
    graph: nx.Graph,
    origin: Hashable,
    destination: Hashable,
    safe_depth_cm: float | int | None,
) -> RouteResult:
    """Find the fastest passable route, or return an explicitly unsafe fallback.

    When every route has an impassable edge, the fallback minimizes the
    highest flood-to-clearance ratio, then travel time. It is always labelled
    ``NO_SAFE_ROUTE`` and must never be presented as driveable.
    """
    safe_depth = _positive_safe_depth(safe_depth_cm)
    warnings = [
        warning
        for warning in (
            _incident_flood_warning(graph, origin, "Origin", safe_depth),
            _incident_flood_warning(graph, destination, "Destination", safe_depth),
        )
        if warning is not None
    ]

    def weight(_: Hashable, __: Hashable, data: Mapping[str, Any]) -> float | None:
        # For multigraphs NetworkX supplies {key: edge-data}; select the least
        # costly parallel edge, just as its built-in string weights do.  NetworkX
        # hides an edge when a callable weight returns None; infinity alone is
        # still a valid (albeit unusable) Dijkstra path cost.
        if graph.is_multigraph():
            cost = min(edge_cost(edge, safe_depth) for edge in data.values())
        else:
            cost = edge_cost(data, safe_depth)
        return None if cost == inf else cost

    try:
        path = nx.dijkstra_path(graph, origin, destination, weight=weight)
        duration = nx.dijkstra_path_length(graph, origin, destination, weight=weight)
        status = "RISKY" if _route_uses_near_limit_edge(graph, path, safe_depth) else "SAFE"
        return RouteResult(path, duration, status, warnings)
    except nx.NetworkXNoPath:
        fallback = _least_risky_route(graph, origin, destination, safe_depth)
        warnings.append("No safe route exists; the alternative route is unsafe.")
        return RouteResult(fallback.path, fallback.duration_s, "NO_SAFE_ROUTE", warnings)


def shortest_normal_route(
    graph: nx.Graph, origin: Hashable, destination: Hashable
) -> RouteResult:
    """Find the fastest route while deliberately ignoring flood depth."""
    def weight(_: Hashable, __: Hashable, data: Mapping[str, Any]) -> float:
        if graph.is_multigraph():
            return min(base_time_seconds(edge) for edge in data.values())
        return base_time_seconds(data)

    try:
        return RouteResult(
            nx.dijkstra_path(graph, origin, destination, weight=weight),
            nx.dijkstra_path_length(graph, origin, destination, weight=weight),
            "NORMAL",
            [],
        )
    except nx.NetworkXNoPath:
        return RouteResult(None, None, "NO_ROUTE", [])


def _least_risky_route(
    graph: nx.Graph, origin: Hashable, destination: Hashable, safe_depth_cm: float
) -> RouteResult:
    """Find an unsafe fallback by minimizing (maximum ratio, travel time)."""
    import heapq

    # A tuple provides lexicographic ordering: a lower worst flood ratio always
    # beats a faster route with a worse flood ratio.
    best: dict[Hashable, tuple[float, float]] = {origin: (0.0, 0.0)}
    previous: dict[Hashable, Hashable] = {}
    queue: list[tuple[float, float, int, Hashable]] = [(0.0, 0.0, 0, origin)]
    sequence = 1

    while queue:
        worst_ratio, duration, _, node = heapq.heappop(queue)
        if (worst_ratio, duration) != best[node]:
            continue
        if node == destination:
            path = [node]
            while path[-1] != origin:
                path.append(previous[path[-1]])
            path.reverse()
            return RouteResult(path, duration, "UNSAFE", [])

        for neighbour in graph.neighbors(node):
            edge_data = graph.get_edge_data(node, neighbour)
            candidates = edge_data.values() if graph.is_multigraph() else [edge_data]
            for edge in candidates:
                candidate = (
                    max(worst_ratio, float(edge.get("flood_depth_cm", 0)) / safe_depth_cm),
                    duration + base_time_seconds(edge),
                )
                if candidate < best.get(neighbour, (inf, inf)):
                    best[neighbour] = candidate
                    previous[neighbour] = node
                    heapq.heappush(queue, (*candidate, sequence, neighbour))
                    sequence += 1

    return RouteResult(None, None, "NO_ROUTE", [])


def _route_uses_near_limit_edge(
    graph: nx.Graph, path: list[Hashable], safe_depth_cm: float
) -> bool:
    for u, v in zip(path, path[1:]):
        edge_data = graph.get_edge_data(u, v)
        candidates = edge_data.values() if graph.is_multigraph() else [edge_data]
        chosen_edge = min(candidates, key=lambda edge: edge_cost(edge, safe_depth_cm))
        if 0.5 <= float(chosen_edge.get("flood_depth_cm", 0)) / safe_depth_cm < 1:
            return True
    return False
