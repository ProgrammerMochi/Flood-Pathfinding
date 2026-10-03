"""Print normal and flood-aware routes for a hard-coded example.

Run from the backend directory with:
    py demo_routing.py
"""

import networkx as nx

from app.routing import mark_edges_flooded, shortest_normal_route, shortest_safe_route


def build_demo_graph() -> nx.DiGraph:
    """Create a short main road and a longer dry detour."""
    graph = nx.DiGraph()
    graph.add_edge("Home", "Main Street", length_m=100, speed_kph=30)
    graph.add_edge("Main Street", "Office", length_m=100, speed_kph=30)
    graph.add_edge("Home", "Dry Detour", length_m=200, speed_kph=30)
    graph.add_edge("Dry Detour", "Office", length_m=200, speed_kph=30)
    return graph


def print_route(label: str, path: list[object] | None, duration_s: float | None, status: str) -> None:
    route = " -> ".join(map(str, path)) if path else "No route"
    duration = f"{duration_s:.0f} seconds" if duration_s is not None else "n/a"
    print(f"{label}: {route} ({duration}; {status})")


def main() -> None:
    graph = build_demo_graph()
    mark_edges_flooded(graph, {("Home", "Main Street"): 30})

    normal = shortest_normal_route(graph, "Home", "Office")
    safe = shortest_safe_route(graph, "Home", "Office", safe_depth_cm=15)

    print("30 cm flood reported on Home -> Main Street; vehicle clearance: 15 cm")
    print_route("Normal route", normal.path, normal.duration_s, normal.status)
    print_route("Safe route", safe.path, safe.duration_s, safe.status)
    for warning in safe.warnings:
        print(f"Warning: {warning}")


if __name__ == "__main__":
    main()
