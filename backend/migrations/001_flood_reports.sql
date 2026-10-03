CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS flood_reports (
  id                SERIAL PRIMARY KEY,
  geom              GEOGRAPHY(Point, 4326) NOT NULL,
  depth_cm          INTEGER NOT NULL CHECK (depth_cm BETWEEN 0 AND 200),
  note              TEXT,
  device_id         TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  clear_votes       INTEGER NOT NULL DEFAULT 0,
  is_cleared        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS flood_reports_geom_idx ON flood_reports USING GIST (geom);

CREATE TABLE IF NOT EXISTS report_votes (
  report_id  INTEGER REFERENCES flood_reports(id) ON DELETE CASCADE,
  device_id  TEXT NOT NULL,
  vote       TEXT NOT NULL CHECK (vote IN ('confirm', 'clear')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (report_id, device_id)
);
