import { useEffect, useRef } from "react";
import type { FeatureCollection, LineString } from "geojson";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import type { FloodReport, Position, RouteDetails, ReportVote } from "../types";

interface MapViewProps {
  origin: Position | null;
  destination: Position | null;
  safeRoute: RouteDetails | null;
  normalRoute: RouteDetails | null;
  reports: FloodReport[];
  reportMode: boolean;
  reportPoint: Position | null;
  onMapPick: (position: Position) => void;
  onReportPick: (position: Position) => void;
  onOriginDrag: (position: Position) => void;
  onDestinationDrag: (position: Position) => void;
  onReportVote: (reportId: number, vote: ReportVote) => void;
}

const emptyLine: FeatureCollection<LineString> = { type: "FeatureCollection", features: [] };

function routeFeature(route: RouteDetails | null): FeatureCollection<LineString> {
  if (!route || route.geometry.coordinates.length < 2) return emptyLine;
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry: route.geometry }],
  };
}

export function MapView({
  origin,
  destination,
  safeRoute,
  normalRoute,
  reports,
  reportMode,
  reportPoint,
  onMapPick,
  onReportPick,
  onOriginDrag,
  onDestinationDrag,
  onReportVote,
}: MapViewProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const mapPickHandler = useRef(onMapPick);
  const originMarker = useRef<maplibregl.Marker | null>(null);
  const destinationMarker = useRef<maplibregl.Marker | null>(null);
  const reportMarkers = useRef<maplibregl.Marker[]>([]);
  const reportDraftMarker = useRef<maplibregl.Marker | null>(null);
  const reportPickHandler = useRef(onReportPick);
  const reportVoteHandler = useRef(onReportVote);
  const reportModeRef = useRef(reportMode);
  const safeRouteRef = useRef(safeRoute);
  const normalRouteRef = useRef(normalRoute);

  useEffect(() => { mapPickHandler.current = onMapPick; }, [onMapPick]);
  useEffect(() => { safeRouteRef.current = safeRoute; }, [safeRoute]);
  useEffect(() => { normalRouteRef.current = normalRoute; }, [normalRoute]);
  useEffect(() => { reportPickHandler.current = onReportPick; }, [onReportPick]);
  useEffect(() => { reportVoteHandler.current = onReportVote; }, [onReportVote]);
  useEffect(() => { reportModeRef.current = reportMode; }, [reportMode]);

  useEffect(() => {
    reportDraftMarker.current?.remove();
    reportDraftMarker.current = null;
    if (map.current && reportMode && reportPoint) {
      reportDraftMarker.current = new maplibregl.Marker({ color: "#7c3aed" })
        .setLngLat(reportPoint)
        .addTo(map.current);
    }
    return () => {
      reportDraftMarker.current?.remove();
      reportDraftMarker.current = null;
    };
  }, [reportMode, reportPoint]);

  useEffect(() => {
    if (!container.current || map.current) return;
    const instance = new maplibregl.Map({
      container: container.current,
      center: [120.956, 14.67],
      zoom: 13,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            maxzoom: 19,
            attribution: "© OpenStreetMap contributors",
          },
          "normal-route": { type: "geojson", data: emptyLine },
          "safe-route": { type: "geojson", data: emptyLine },
        },
        layers: [
          { id: "osm", type: "raster", source: "osm" },
          {
            id: "normal-route",
            type: "line",
            source: "normal-route",
            paint: { "line-color": "#6b7280", "line-width": 4, "line-dasharray": [2, 2], "line-opacity": 0.9 },
          },
          {
            id: "safe-route",
            type: "line",
            source: "safe-route",
            paint: { "line-color": "#007a5e", "line-width": 6, "line-opacity": 0.95 },
          },
        ],
      },
    });
    instance.addControl(new maplibregl.NavigationControl(), "bottom-right");
    instance.on("click", (event: maplibregl.MapMouseEvent) => {
      const position: Position = [event.lngLat.lng, event.lngLat.lat];
      if (reportModeRef.current) reportPickHandler.current(position);
      else mapPickHandler.current(position);
    });
    instance.once("load", () => {
      (instance.getSource("safe-route") as maplibregl.GeoJSONSource).setData(routeFeature(safeRouteRef.current));
      (instance.getSource("normal-route") as maplibregl.GeoJSONSource).setData(routeFeature(normalRouteRef.current));
    });
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    reportMarkers.current.forEach((marker) => marker.remove());
    reportMarkers.current = [];
    const mapInstance = map.current;
    if (!mapInstance) return;

    reports.forEach((report) => {
      const color = report.depth_cm <= 10 ? "#2563eb"
        : report.depth_cm <= 20 ? "#0891b2"
        : report.depth_cm <= 45 ? "#d97706"
        : "#dc2626";
      const popup = new maplibregl.Popup({ offset: 25, maxWidth: "260px" });
      const marker = new maplibregl.Marker({ color })
        .setLngLat([report.lon, report.lat])
        .setPopup(popup)
        .addTo(mapInstance);
      marker.getElement().addEventListener("click", () => {
        const content = document.createElement("div");
        content.className = "report-popup";
        content.innerHTML = `<strong>Flood report</strong><p>${report.depth_cm} cm · ${timeAgo(report.created_at)}</p>${report.note ? `<p>${escapeHtml(report.note)}</p>` : ""}`;
        const confirmButton = document.createElement("button");
        confirmButton.type = "button";
        confirmButton.textContent = "Still flooded";
        const clearButton = document.createElement("button");
        clearButton.type = "button";
        clearButton.textContent = "Cleared";
        confirmButton.addEventListener("click", () => reportVoteHandler.current(report.id, "confirm"));
        clearButton.addEventListener("click", () => reportVoteHandler.current(report.id, "clear"));
        content.append(confirmButton, clearButton);
        popup.setDOMContent(content).addTo(mapInstance);
      });
      reportMarkers.current.push(marker);
    });

    return () => {
      reportMarkers.current.forEach((marker) => marker.remove());
      reportMarkers.current = [];
    };
  }, [reports]);

  useEffect(() => {
    if (!map.current?.isStyleLoaded()) return;
    const source = map.current.getSource("safe-route") as maplibregl.GeoJSONSource | undefined;
    source?.setData(routeFeature(safeRoute));
  }, [safeRoute]);

  useEffect(() => {
    if (!map.current?.isStyleLoaded()) return;
    const source = map.current.getSource("normal-route") as maplibregl.GeoJSONSource | undefined;
    source?.setData(routeFeature(normalRoute));
  }, [normalRoute]);

  useEffect(() => {
    originMarker.current?.remove();
    originMarker.current = null;
    if (!map.current || !origin) return;
    const marker = new maplibregl.Marker({ color: "#047857", draggable: true }).setLngLat(origin).addTo(map.current);
    marker.on("dragend", () => {
      const point = marker.getLngLat();
      onOriginDrag([point.lng, point.lat]);
    });
    originMarker.current = marker;
  }, [origin, onOriginDrag]);

  useEffect(() => {
    destinationMarker.current?.remove();
    destinationMarker.current = null;
    if (!map.current || !destination) return;
    const marker = new maplibregl.Marker({ color: "#b91c1c", draggable: true }).setLngLat(destination).addTo(map.current);
    marker.on("dragend", () => {
      const point = marker.getLngLat();
      onDestinationDrag([point.lng, point.lat]);
    });
    destinationMarker.current = marker;
  }, [destination, onDestinationDrag]);

  return <div ref={container} className="map" aria-label="Map of Malabon" />;
}

function timeAgo(dateString: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(dateString)) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character] ?? character);
}
