"""PostgreSQL/PostGIS persistence for flood reports."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ModuleNotFoundError:  # Allows offline routing tests without a DB driver.
    psycopg2 = None
    RealDictCursor = None

from app.flood import FloodReport, VoteResult


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required to use flood reports")
    return value


@contextmanager
def connection() -> Iterator:
    if psycopg2 is None or RealDictCursor is None:
        raise RuntimeError("PostgreSQL support requires psycopg2-binary; install backend requirements")
    database = psycopg2.connect(database_url())
    try:
        yield database
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def _report(row: dict) -> FloodReport:
    return FloodReport(
        id=row["id"],
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        depth_cm=row["depth_cm"],
        note=row["note"],
        device_id=row["device_id"],
        created_at=row["created_at"],
        last_confirmed_at=row["last_confirmed_at"],
        clear_votes=row["clear_votes"],
        is_cleared=row["is_cleared"],
    )


class PostgresReportStore:
    """Each method opens a short transaction; psycopg commits on success."""

    def reports_created_by(self, device_id: str, since: datetime) -> int:
        with connection() as database, database.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT count(*) AS count FROM flood_reports WHERE device_id = %s AND created_at >= %s",
                (device_id, since),
            )
            return cursor.fetchone()["count"]

    def create_report(self, *, lat: float, lon: float, depth_cm: int, note: str | None, device_id: str, now: datetime) -> FloodReport:
        with connection() as database, database.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                INSERT INTO flood_reports (geom, depth_cm, note, device_id, created_at, last_confirmed_at)
                VALUES (ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s, %s, %s, %s)
                RETURNING id, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon,
                          depth_cm, note, device_id, created_at, last_confirmed_at, clear_votes, is_cleared
                """,
                (lon, lat, depth_cm, note, device_id, now, now),
            )
            return _report(cursor.fetchone())

    def active_reports(self, since: datetime) -> list[FloodReport]:
        with connection() as database, database.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT id, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon,
                       depth_cm, note, device_id, created_at, last_confirmed_at, clear_votes, is_cleared
                FROM flood_reports
                WHERE NOT is_cleared AND last_confirmed_at >= %s
                ORDER BY created_at DESC
                """,
                (since,),
            )
            return [_report(row) for row in cursor.fetchall()]

    def vote(self, report_id: int, device_id: str, vote: str, now: datetime) -> VoteResult:
        with connection() as database, database.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id FROM flood_reports WHERE id = %s FOR UPDATE", (report_id,))
            if cursor.fetchone() is None:
                return VoteResult.NOT_FOUND
            cursor.execute(
                """
                INSERT INTO report_votes (report_id, device_id, vote, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (report_id, device_id) DO NOTHING
                RETURNING report_id
                """,
                (report_id, device_id, vote, now),
            )
            if cursor.fetchone() is None:
                return VoteResult.DUPLICATE
            if vote == "confirm":
                cursor.execute("UPDATE flood_reports SET last_confirmed_at = %s WHERE id = %s", (now, report_id))
            else:
                cursor.execute(
                    """
                    UPDATE flood_reports
                    SET clear_votes = clear_votes + 1,
                        is_cleared = clear_votes + 1 >= 2
                    WHERE id = %s
                    """,
                    (report_id,),
                )
            return VoteResult.ACCEPTED
