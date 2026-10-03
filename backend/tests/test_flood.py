from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.flood import (
    FloodReport,
    FloodReportService,
    PinHasNoNearbyRoad,
    RateLimitExceeded,
    VoteResult,
)


class MemoryReportStore:
    def __init__(self) -> None:
        self.reports: dict[int, FloodReport] = {}
        self.votes: set[tuple[int, str]] = set()
        self.next_id = 1

    def reports_created_by(self, device_id: str, since: datetime) -> int:
        return sum(report.device_id == device_id and report.created_at >= since for report in self.reports.values())

    def create_report(self, *, lat: float, lon: float, depth_cm: int, note: str | None, device_id: str, now: datetime) -> FloodReport:
        report = FloodReport(self.next_id, lat, lon, depth_cm, note, device_id, now, now, 0, False)
        self.reports[report.id] = report
        self.next_id += 1
        return report

    def active_reports(self, since: datetime) -> list[FloodReport]:
        return [report for report in self.reports.values() if not report.is_cleared and report.last_confirmed_at >= since]

    def vote(self, report_id: int, device_id: str, vote: str, now: datetime) -> VoteResult:
        report = self.reports.get(report_id)
        if report is None:
            return VoteResult.NOT_FOUND
        if (report_id, device_id) in self.votes:
            return VoteResult.DUPLICATE
        self.votes.add((report_id, device_id))
        if vote == "confirm":
            self.reports[report_id] = replace(report, last_confirmed_at=now)
        else:
            votes = report.clear_votes + 1
            self.reports[report_id] = replace(report, clear_votes=votes, is_cleared=votes >= 2)
        return VoteResult.ACCEPTED


def service_at(now: datetime, snapper=lambda _lat, _lon: [("a", "b", 0)]):
    clock = [now]
    service = FloodReportService(MemoryReportStore(), snapper, now=lambda: clock[0])
    return service, clock


def test_snapping_rejects_pin_without_a_road_within_30_m() -> None:
    service, _ = service_at(datetime(2026, 1, 1, tzinfo=UTC), snapper=lambda _lat, _lon: [])

    with pytest.raises(PinHasNoNearbyRoad, match="within 30 m"):
        service.create(lat=14.65, lon=120.97, depth_cm=20, note=None, device_id="device-1")


def test_expiry_uses_created_or_latest_confirmation_time() -> None:
    service, clock = service_at(datetime(2026, 1, 1, 12, tzinfo=UTC))
    report = service.create(lat=14.65, lon=120.97, depth_cm=20, note=None, device_id="device-1")

    clock[0] += timedelta(hours=1, minutes=59)
    assert [item.id for item in service.active()] == [report.id]
    assert service.cast_vote(report.id, "device-2", "confirm") is VoteResult.ACCEPTED
    clock[0] += timedelta(hours=1, minutes=59)
    assert [item.id for item in service.active()] == [report.id]
    clock[0] += timedelta(minutes=2)
    assert service.active() == []


def test_votes_are_unique_and_two_clears_deactivate_a_report() -> None:
    service, _ = service_at(datetime(2026, 1, 1, tzinfo=UTC))
    report = service.create(lat=14.65, lon=120.97, depth_cm=20, note=None, device_id="reporter")

    assert service.cast_vote(report.id, "device-1", "clear") is VoteResult.ACCEPTED
    assert service.cast_vote(report.id, "device-1", "confirm") is VoteResult.DUPLICATE
    assert service.cast_vote(report.id, "device-2", "clear") is VoteResult.ACCEPTED
    assert service.active() == []


def test_rate_limit_allows_ten_reports_per_device_per_hour() -> None:
    service, _ = service_at(datetime(2026, 1, 1, tzinfo=UTC))
    for _ in range(10):
        service.create(lat=14.65, lon=120.97, depth_cm=10, note=None, device_id="device-1")

    with pytest.raises(RateLimitExceeded):
        service.create(lat=14.65, lon=120.97, depth_cm=10, note=None, device_id="device-1")


def test_overlapping_active_reports_use_the_maximum_edge_depth() -> None:
    service, _ = service_at(datetime(2026, 1, 1, tzinfo=UTC))
    service.create(lat=14.65, lon=120.97, depth_cm=10, note=None, device_id="device-1")
    service.create(lat=14.65, lon=120.97, depth_cm=45, note=None, device_id="device-2")

    assert service.edge_depths() == {("a", "b", 0): 45}
