import type {
  Claim,
  Contradiction,
  Engagement,
  EngagementWorkspace,
  Evidence,
  OperatingModel,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_AI_FDE_API_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? "The operator service could not complete the request.", response.status);
  }

  return response.json() as Promise<T>;
}

export function listEngagements(): Promise<Engagement[]> {
  return request("/engagements");
}

export function createEngagement(payload: {
  name: string;
  primary_outcome: string;
  data_classification: "synthetic" | "sanitized";
}): Promise<Engagement> {
  return request("/engagements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getWorkspace(engagementId: string): Promise<EngagementWorkspace> {
  return request(`/engagements/${engagementId}`);
}

export function listEvidence(engagementId: string): Promise<Evidence[]> {
  return request(`/engagements/${engagementId}/evidence`);
}

export function listClaims(engagementId: string): Promise<Claim[]> {
  return request(`/engagements/${engagementId}/claims`);
}

export function listContradictions(engagementId: string): Promise<Contradiction[]> {
  return request(`/engagements/${engagementId}/contradictions`);
}

export function getOperatingModel(engagementId: string): Promise<OperatingModel> {
  return request(`/engagements/${engagementId}/operating-model`);
}

export function uploadEvidence(engagementId: string, file: File): Promise<Evidence> {
  const body = new FormData();
  body.set("file", file);
  return request(`/engagements/${engagementId}/evidence`, { method: "POST", body });
}

export function createOperatorNote(
  engagementId: string,
  payload: { title: string; content: string },
): Promise<Evidence> {
  return request(`/engagements/${engagementId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function reviewClaim(
  engagementId: string,
  claimId: string,
  decision: "accepted" | "rejected" | "deferred",
  reason: string | null,
): Promise<{ claim_id: string; decision: string; assertion_id: string | null }> {
  return request(`/engagements/${engagementId}/claims/${claimId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reason: reason || null }),
  });
}
