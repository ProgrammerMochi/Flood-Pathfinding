import type {
  CreateReportRequest,
  FloodReport,
  ReportVote,
  RouteRequest,
  RouteResponse,
  Vehicle,
} from "./types";

const apiUrl = import.meta.env.VITE_API_URL?.replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  if (!apiUrl) {
    throw new Error("VITE_API_URL is missing. Copy .env.example to .env and set the backend URL.");
  }

  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(response.status, body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function getVehicles(): Promise<Vehicle[]> {
  return request<Vehicle[]>("/vehicles");
}

export function findRoute(payload: RouteRequest): Promise<RouteResponse> {
  return request<RouteResponse>("/route", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getReports(): Promise<FloodReport[]> {
  return request<FloodReport[]>("/reports");
}

export function createReport(payload: CreateReportRequest): Promise<FloodReport> {
  return request<FloodReport>("/reports", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function voteOnReport(reportId: number, deviceId: string, vote: ReportVote): Promise<{ status: "accepted" }> {
  return request<{ status: "accepted" }>(`/reports/${reportId}/vote`, {
    method: "POST",
    body: JSON.stringify({ device_id: deviceId, vote }),
  });
}

export function getDeviceId(): string {
  const storageKey = "flood-router-device-id";
  try {
    const existing = localStorage.getItem(storageKey);
    if (existing) return existing;
    const generated = globalThis.crypto?.randomUUID?.() ?? `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(storageKey, generated);
    return generated;
  } catch {
    return `session-device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}
