export type Position = [longitude: number, latitude: number];

export interface Vehicle {
  id: string;
  safe_depth_cm: number;
}

export interface RouteRequest {
  origin: { lat: number; lon: number };
  destination: { lat: number; lon: number };
  safe_depth_cm: number;
  heavy_rain: boolean;
}

export type RouteStatus = "SAFE" | "RISKY" | "NO_SAFE_ROUTE";

export interface RouteDetails {
  geometry: {
    type: "LineString";
    coordinates: Position[];
  };
  distance_m: number | null;
  duration_s: number | null;
  max_depth_cm: number | null;
  status?: RouteStatus;
}

export interface RouteResponse {
  safe_route: RouteDetails;
  normal_route: RouteDetails;
  warnings: string[];
}

export type FloodDepthLevel = "ankle" | "half_tire" | "knee" | "waist";

export interface FloodReport {
  id: number;
  lat: number;
  lon: number;
  depth_cm: number;
  note: string | null;
  created_at: string;
  last_confirmed_at: string;
  clear_votes: number;
}

export interface CreateReportRequest {
  lat: number;
  lon: number;
  depth_cm: number;
  note?: string;
  device_id: string;
}

export type ReportVote = "confirm" | "clear";
