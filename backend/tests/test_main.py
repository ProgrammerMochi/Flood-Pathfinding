import networkx as nx
from fastapi.testclient import TestClient

from app.main import create_app


class FloodedEdgeService:
    def edge_depths(self) -> dict[tuple[str, str, int], int]:
        return {("A", "B", 0): 30}


def synthetic_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node("A", x=120.970, y=14.650)
    graph.add_node("B", x=120.971, y=14.650)
    graph.add_node("C", x=120.970, y=14.651)
    graph.add_node("D", x=120.972, y=14.650)
    graph.add_edge("A", "B", key=0, length_m=100, speed_kph=30)
    graph.add_edge("B", "D", key=0, length_m=100, speed_kph=30)
    graph.add_edge("A", "C", key=0, length_m=200, speed_kph=30)
    graph.add_edge("C", "D", key=0, length_m=200, speed_kph=30)
    return graph


def client_for_test() -> TestClient:
    def node_finder(_: nx.MultiDiGraph, lon: float, lat: float) -> str:
        return "A" if (lon, lat) == (120.970, 14.650) else "D"

    app = create_app(
        graph_loader=synthetic_graph,
        node_finder=node_finder,
        report_service_factory=lambda _graph: FloodedEdgeService(),
    )
    return TestClient(app)


def test_health() -> None:
    with client_for_test() as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_vehicles_returns_presets() -> None:
    with client_for_test() as client:
        response = client.get("/vehicles")

    assert response.status_code == 200
    assert {vehicle["id"] for vehicle in response.json()} == {
        "motorcycle",
        "sedan_hatchback",
        "crossover_small_suv",
        "suv_pickup",
    }


def test_route_returns_safe_and_normal_routes() -> None:
    with client_for_test() as client:
        response = client.post(
            "/route",
            json={
                "origin": {"lat": 14.650, "lon": 120.970},
                "destination": {"lat": 14.650, "lon": 120.972},
                "safe_depth_cm": 15,
                "heavy_rain": False,
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["normal_route"]["distance_m"] == 200
    assert body["safe_route"]["distance_m"] == 400
    assert body["safe_route"]["status"] == "SAFE"
    assert body["safe_route"]["geometry"]["coordinates"][0] == [120.970, 14.650]


def test_route_rejects_missing_or_zero_safe_depth() -> None:
    request = {
        "origin": {"lat": 14.650, "lon": 120.970},
        "destination": {"lat": 14.650, "lon": 120.972},
    }
    with client_for_test() as client:
        missing = client.post("/route", json=request)
        zero = client.post("/route", json={**request, "safe_depth_cm": 0})

    assert missing.status_code == 422
    assert zero.status_code == 422
