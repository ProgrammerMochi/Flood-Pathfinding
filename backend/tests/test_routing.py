import math

import networkx as nx
import pytest

from app.routing import edge_cost, mark_edges_flooded, shortest_safe_route


def graph_with_two_routes() -> nx.DiGraph:
    """A -> B -> D is short; A -> C -> D is a longer dry detour."""
    graph = nx.DiGraph()
    graph.add_edge("A", "B", length_m=100, speed_kph=30)
    graph.add_edge("B", "D", length_m=100, speed_kph=30)
    graph.add_edge("A", "C", length_m=200, speed_kph=30)
    graph.add_edge("C", "D", length_m=200, speed_kph=30)
    return graph


def test_sedan_avoids_30_cm_flood() -> None:
    graph = graph_with_two_routes()
    mark_edges_flooded(graph, {("A", "B"): 30})

    result = shortest_safe_route(graph, "A", "D", safe_depth_cm=15)

    assert result.path == ["A", "C", "D"]
    assert result.status == "SAFE"


def test_pickup_passes_20_cm_flood() -> None:
    graph = graph_with_two_routes()
    mark_edges_flooded(graph, {("A", "B"): 20})

    result = shortest_safe_route(graph, "A", "D", safe_depth_cm=30)

    assert result.path == ["A", "B", "D"]
    assert result.status == "RISKY"


def test_no_safe_route_returns_unsafe_alternative() -> None:
    graph = graph_with_two_routes()
    mark_edges_flooded(graph, {("A", "B"): 30, ("A", "C"): 30})

    result = shortest_safe_route(graph, "A", "D", safe_depth_cm=15)

    assert result.status == "NO_SAFE_ROUTE"
    assert result.path == ["A", "B", "D"]
    assert "unsafe" in result.warnings[-1].lower()


def test_near_limit_penalty_is_applied() -> None:
    edge = {"length_m": 1_000, "speed_kph": 50, "flood_depth_cm": 10}
    base_time = 72.0

    # 10 / 15 = 2/3, so the Section 6 multiplier is 1 + 4/3.
    assert edge_cost(edge, safe_depth_cm=15) == pytest.approx(base_time * (1 + 4 / 3))


def test_impassable_edge_cost_is_infinite() -> None:
    assert math.isinf(edge_cost({"length_m": 10, "speed_kph": 30, "flood_depth_cm": 15}, 15))


@pytest.mark.parametrize("safe_depth_cm", [None, 0, -1])
def test_invalid_safe_depth_is_rejected(safe_depth_cm: float | None) -> None:
    with pytest.raises(ValueError, match="safe_depth_cm"):
        edge_cost({"length_m": 10, "speed_kph": 30}, safe_depth_cm)
