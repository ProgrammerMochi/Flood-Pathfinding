import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, createReport, findRoute, getDeviceId, getReports, getVehicles, voteOnReport } from "./api";
import { MapView } from "./components/MapView";
import { RouteSummary } from "./components/RouteSummary";
import { VehicleSelector } from "./components/VehicleSelector";
import type { FloodDepthLevel, FloodReport, Position, ReportVote, RouteResponse, Vehicle } from "./types";

const depthOptions: { value: FloodDepthLevel; label: string; cm: number }[] = [
  { value: "ankle", label: "Ankle-deep", cm: 10 },
  { value: "half_tire", label: "Half-tire / shin", cm: 20 },
  { value: "knee", label: "Knee-deep", cm: 45 },
  { value: "waist", label: "Waist-deep", cm: 90 },
];

function friendlyApiError(error: unknown, fallback: string): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : fallback;
  if (error.status === 422 && error.message.toLowerCase().includes("road")) return "No road was found within 30 m of that pin. Try placing it closer to a road.";
  if (error.status === 429) return "You have reached the report limit. Please try again later.";
  if (error.status === 409) return "You have already voted on this flood report.";
  if (error.status === 503) return "Flood reports are not available until the backend database is configured.";
  return error.message || fallback;
}

export default function App() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [selectedVehicle, setSelectedVehicle] = useState("");
  const [customDepth, setCustomDepth] = useState("");
  const [origin, setOrigin] = useState<Position | null>(null);
  const [destination, setDestination] = useState<Position | null>(null);
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [loadingVehicles, setLoadingVehicles] = useState(true);
  const [vehiclesError, setVehiclesError] = useState<string | null>(null);
  const [loadingRoute, setLoadingRoute] = useState(false);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [reports, setReports] = useState<FloodReport[]>([]);
  const [loadingReports, setLoadingReports] = useState(true);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const [reportMode, setReportMode] = useState(false);
  const [reportPoint, setReportPoint] = useState<Position | null>(null);
  const [reportDepth, setReportDepth] = useState<FloodDepthLevel>("ankle");
  const [reportNote, setReportNote] = useState("");
  const [reportError, setReportError] = useState<string | null>(null);
  const [loadingReportSubmit, setLoadingReportSubmit] = useState(false);
  const [votingReportId, setVotingReportId] = useState<number | null>(null);
  const [voteError, setVoteError] = useState<string | null>(null);
  const [recomputeNotice, setRecomputeNotice] = useState(false);
  const deviceId = useMemo(() => getDeviceId(), []);

  const loadVehicles = useCallback(async () => {
    setLoadingVehicles(true);
    setVehiclesError(null);
    try {
      const presets = await getVehicles();
      setVehicles(presets);
      setSelectedVehicle((current) => current || presets[0]?.id || "custom");
    } catch (error) {
      setVehiclesError(error instanceof Error ? error.message : "Could not load vehicle presets.");
    } finally {
      setLoadingVehicles(false);
    }
  }, []);

  useEffect(() => { void loadVehicles(); }, [loadVehicles]);

  const loadReports = useCallback(async () => {
    setLoadingReports(true);
    setReportsError(null);
    try {
      setReports(await getReports());
    } catch (error) {
      setReportsError(friendlyApiError(error, "Could not load active flood reports."));
    } finally {
      setLoadingReports(false);
    }
  }, []);

  useEffect(() => { void loadReports(); }, [loadReports]);

  const safeDepth = useMemo(() => {
    if (selectedVehicle === "custom") return Number(customDepth);
    return vehicles.find((vehicle) => vehicle.id === selectedVehicle)?.safe_depth_cm ?? 0;
  }, [customDepth, selectedVehicle, vehicles]);

  const pickPoint = useCallback((position: Position) => {
    if (!origin) setOrigin(position);
    else if (!destination) setDestination(position);
  }, [destination, origin]);

  const reset = useCallback(() => {
    setOrigin(null);
    setDestination(null);
    setRoute(null);
    setRouteError(null);
  }, []);

  const startReport = () => {
    setReportMode(true);
    setReportPoint(null);
    setReportError(null);
    setVoteError(null);
  };

  const cancelReport = () => {
    setReportMode(false);
    setReportPoint(null);
    setReportError(null);
  };

  const submitReport = async () => {
    if (!reportPoint) {
      setReportError("Tap the map to place the flood report pin first.");
      return;
    }
    setLoadingReportSubmit(true);
    setReportError(null);
    try {
      await createReport({
        lat: reportPoint[1],
        lon: reportPoint[0],
        depth_cm: depthOptions.find((option) => option.value === reportDepth)?.cm ?? 10,
        note: reportNote.trim() || undefined,
        device_id: deviceId,
      });
      await loadReports();
      cancelReport();
      setReportNote("");
      setRecomputeNotice(Boolean(origin && destination));
    } catch (error) {
      setReportError(friendlyApiError(error, "Could not submit this flood report."));
    } finally {
      setLoadingReportSubmit(false);
    }
  };

  const handleVote = async (reportId: number, vote: ReportVote) => {
    setVotingReportId(reportId);
    setVoteError(null);
    try {
      await voteOnReport(reportId, deviceId, vote);
      await loadReports();
      setRecomputeNotice(Boolean(origin && destination));
    } catch (error) {
      setVoteError(friendlyApiError(error, "Could not submit your vote."));
    } finally {
      setVotingReportId(null);
    }
  };

  const submitRoute = async () => {
    if (!origin || !destination || !Number.isFinite(safeDepth) || safeDepth <= 0) {
      setRouteError("Set both map points and choose a safe wading depth greater than 0 cm.");
      return;
    }
    setLoadingRoute(true);
    setRouteError(null);
    try {
      setRoute(await findRoute({
        origin: { lon: origin[0], lat: origin[1] },
        destination: { lon: destination[0], lat: destination[1] },
        safe_depth_cm: safeDepth,
        heavy_rain: false,
      }));
    } catch (error) {
      setRouteError(error instanceof Error ? error.message : "Could not find a route.");
    } finally {
      setLoadingRoute(false);
    }
  };

  return (
    <main className="app-shell">
      <MapView
        origin={origin}
        destination={destination}
        safeRoute={route?.safe_route ?? null}
        normalRoute={route?.normal_route ?? null}
        reports={reports}
        reportMode={reportMode}
        reportPoint={reportPoint}
        onMapPick={pickPoint}
        onReportPick={setReportPoint}
        onOriginDrag={(position) => { setOrigin(position); setRoute(null); }}
        onDestinationDrag={(position) => { setDestination(position); setRoute(null); }}
        onReportVote={(reportId, vote) => void handleVote(reportId, vote)}
      />

      <section className="control-panel" aria-label="Route planner">
        <div className="panel-heading">
          <div><p className="eyebrow">Malabon, Metro Manila</p><h1>Flood-aware routes</h1></div>
          <button className="secondary" type="button" onClick={reset}>Reset</button>
        </div>
        <p className="instruction">
          {reportMode ? (reportPoint ? "Choose the flood depth and submit the report." : "Tap the map to place a flood report pin.") : !origin ? "Tap the map to set your origin." : !destination ? "Tap the map again to set your destination." : "Drag either marker to adjust your trip."}
        </p>

        <div className="report-actions">
          <button className="secondary report-button" type="button" onClick={reportMode ? cancelReport : startReport}>
            {reportMode ? "Cancel report" : "Report flood"}
          </button>
          {loadingReports && <span className="loading">Loading pins…</span>}
          {!loadingReports && <button className="text-button" type="button" onClick={() => void loadReports()}>Refresh pins</button>}
        </div>
        {reportsError && <div className="error"><span>{reportsError}</span><button type="button" onClick={() => void loadReports()}>Retry</button></div>}
        {reportMode && (
          <div className="report-form">
            <label htmlFor="report-depth">Flood depth</label>
            <select id="report-depth" value={reportDepth} onChange={(event) => setReportDepth(event.target.value as FloodDepthLevel)}>
              {depthOptions.map((option) => <option key={option.value} value={option.value}>{option.label} ({option.cm} cm)</option>)}
            </select>
            <label htmlFor="report-note">Note (optional)</label>
            <textarea id="report-note" rows={2} maxLength={1000} value={reportNote} onChange={(event) => setReportNote(event.target.value)} placeholder="What did you observe?" />
            <button className="primary" type="button" disabled={!reportPoint || loadingReportSubmit} onClick={() => void submitReport()}>
              {loadingReportSubmit ? "Submitting…" : "Submit flood report"}
            </button>
            {reportError && <p className="error route-error" role="alert">{reportError}</p>}
          </div>
        )}
        {voteError && <p className="error route-error" role="alert">{voteError}</p>}
        {votingReportId !== null && <p className="loading">Submitting vote…</p>}

        {loadingVehicles && <p className="loading">Loading vehicle presets…</p>}
        {vehiclesError && <div className="error"><span>{vehiclesError}</span><button type="button" onClick={() => void loadVehicles()}>Retry</button></div>}
        {!loadingVehicles && !vehiclesError && (
          <VehicleSelector
            vehicles={vehicles}
            value={selectedVehicle}
            customDepth={customDepth}
            disabled={vehicles.length === 0}
            onVehicleChange={setSelectedVehicle}
            onCustomDepthChange={setCustomDepth}
          />
        )}
        <button
          className="primary"
          type="button"
          disabled={loadingRoute || loadingVehicles || Boolean(vehiclesError)}
          onClick={() => void submitRoute()}
        >
          {loadingRoute ? "Finding route…" : "Find route"}
        </button>
        {routeError && <p className="error route-error" role="alert">{routeError}</p>}
        {recomputeNotice && (
          <div className="recompute-notice">
            <span>Flood data changed. Recompute your current route?</span>
            <button type="button" onClick={() => { setRecomputeNotice(false); void submitRoute(); }}>Recompute</button>
            <button type="button" onClick={() => setRecomputeNotice(false)}>Dismiss</button>
          </div>
        )}
        <RouteSummary route={route} />
      </section>

      <p className="disclaimer">Flood data is crowdsourced and estimated. Routes are suggestions, not guarantees of safety. Do not drive into floodwater you cannot see the bottom of.</p>
    </main>
  );
}
