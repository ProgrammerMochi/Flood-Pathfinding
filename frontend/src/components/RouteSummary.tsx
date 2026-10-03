import type { RouteResponse, RouteStatus } from "../types";

interface RouteSummaryProps {
  route: RouteResponse | null;
}

function duration(seconds: number | null): string {
  if (seconds === null) return "No route";
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} hr ${minutes % 60} min`;
}

function distance(meters: number | null): string {
  if (meters === null) return "—";
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
}

export function RouteSummary({ route }: RouteSummaryProps) {
  if (!route) return null;
  const safe = route.safe_route;
  const status = safe.status ?? "NO_SAFE_ROUTE";
  return (
    <section className="route-summary" aria-live="polite">
      <div className="summary-heading">
        <h2>Flood-aware route</h2>
        <span className={`status status-${status.toLowerCase()}`}>{status}</span>
      </div>
      <dl>
        <div><dt>Duration</dt><dd>{duration(safe.duration_s)}</dd></div>
        <div><dt>Distance</dt><dd>{distance(safe.distance_m)}</dd></div>
        <div><dt>Max flood depth</dt><dd>{safe.max_depth_cm === null ? "—" : `${safe.max_depth_cm} cm`}</dd></div>
      </dl>
      <p className="normal-route">Normal route: {duration(route.normal_route.duration_s)} · {distance(route.normal_route.distance_m)}</p>
      {route.warnings.length > 0 && (
        <ul className="warnings">{route.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
      )}
    </section>
  );
}
