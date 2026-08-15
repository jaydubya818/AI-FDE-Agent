import type {
  Claim,
  Contradiction,
  DeliveryScorecard,
  Engagement,
  EngagementAssessment,
  EngagementDataLifecycle,
  EngagementDeletionReceipt,
  EngagementWorkspace,
  EconomicCase,
  Evidence,
  EvidenceClassification,
  ImplementationArtifact,
  InternalAlphaScorecard,
  OperatingModel,
  Workflow,
  WorkflowStep,
  WorkflowWorkspace,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_AI_FDE_API_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export type AuthenticatedOperator = {
  id: string;
  display_name: string;
  auth_mode: "development" | "oidc";
  sanitized_data_allowed: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
    credentials: "include",
  });

  if (!response.ok) throw await responseError(response);

  if (response.status === 204) return undefined as T;

  return response.json() as Promise<T>;
}

async function responseError(response: Response): Promise<ApiError> {
  const payload = (await response.json().catch(() => null)) as {
    detail?: string;
  } | null;
  return new ApiError(
    payload?.detail ?? "The operator service could not complete the request.",
    response.status,
  );
}

export function getAuthenticatedOperator(): Promise<AuthenticatedOperator> {
  return request("/auth/me");
}

export function getAuthLoginUrl(returnTo: string): string {
  const url = new URL(`${API_URL}/auth/login`);
  url.searchParams.set("return_to", returnTo);
  return url.toString();
}

export function logoutOperator(): Promise<void> {
  return request("/auth/logout", { method: "POST" });
}

export function listEngagements(): Promise<Engagement[]> {
  return request("/engagements");
}

export function createEngagement(payload: {
  name: string;
  workflow_name: string;
  primary_outcome: string;
  data_classification: "synthetic" | "sanitized";
}): Promise<Engagement> {
  return request("/engagements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getWorkspace(
  engagementId: string,
): Promise<EngagementWorkspace> {
  return request(`/engagements/${engagementId}`);
}

export function getInternalAlphaScorecard(): Promise<InternalAlphaScorecard> {
  return request("/internal-alpha/scorecard");
}

export function getDeliveryScorecard(
  engagementId: string,
): Promise<DeliveryScorecard> {
  return request(`/engagements/${engagementId}/delivery-scorecard`);
}

export function recordEngagementAssessment(
  engagementId: string,
  payload: Omit<
    EngagementAssessment,
    "id" | "engagement_id" | "evaluator_id" | "created_at" | "updated_at"
  >,
): Promise<EngagementAssessment> {
  return request(`/engagements/${engagementId}/assessments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getEngagementDataLifecycle(
  engagementId: string,
): Promise<EngagementDataLifecycle> {
  return request(`/engagements/${engagementId}/data-lifecycle`);
}

export function updateEngagementRetention(
  engagementId: string,
  retainUntil: string,
): Promise<Engagement> {
  return request(`/engagements/${engagementId}/data-lifecycle/retention`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ retain_until: retainUntil }),
  });
}

export async function downloadEngagementExport(
  engagementId: string,
): Promise<{ blob: Blob; exportId: string; filename: string }> {
  const response = await fetch(
    `${API_URL}/engagements/${engagementId}/data-lifecycle/exports`,
    {
      method: "POST",
      credentials: "include",
    },
  );
  if (!response.ok) throw await responseError(response);
  const exportId = response.headers.get("x-ai-fde-export-id");
  if (!exportId) throw new ApiError("The export response was incomplete.", 502);
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename =
    disposition.match(/filename="([^"]+)"/)?.[1] ??
    `ai-fde-engagement-${exportId}.zip`;
  return { blob: await response.blob(), exportId, filename };
}

export function deleteEngagementData(
  engagementId: string,
  payload: { export_id: string; confirmation_name: string },
): Promise<EngagementDeletionReceipt> {
  return request(`/engagements/${engagementId}/data-lifecycle/deletion`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listEvidence(engagementId: string): Promise<Evidence[]> {
  return request(`/engagements/${engagementId}/evidence`);
}

export function listClaims(engagementId: string): Promise<Claim[]> {
  return request(`/engagements/${engagementId}/claims`);
}

export function listContradictions(
  engagementId: string,
): Promise<Contradiction[]> {
  return request(`/engagements/${engagementId}/contradictions`);
}

export function getOperatingModel(
  engagementId: string,
): Promise<OperatingModel> {
  return request(`/engagements/${engagementId}/operating-model`);
}

export function uploadEvidence(
  engagementId: string,
  file: File,
): Promise<Evidence> {
  const body = new FormData();
  body.set("file", file);
  return request(`/engagements/${engagementId}/evidence`, {
    method: "POST",
    body,
  });
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
): Promise<{
  claim_id: string;
  decision: string;
  assertion_id: string | null;
}> {
  return request(`/engagements/${engagementId}/claims/${claimId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reason: reason || null }),
  });
}

export function resolveContradiction(
  engagementId: string,
  contradictionId: string,
  resolutionType:
    "accepted_exception" | "not_a_conflict" | "superseded" | "override",
  reason: string,
): Promise<Contradiction> {
  return request(
    `/engagements/${engagementId}/contradictions/${contradictionId}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution_type: resolutionType, reason }),
    },
  );
}

export function getWorkflows(engagementId: string): Promise<WorkflowWorkspace> {
  return request(`/engagements/${engagementId}/workflows`);
}

export function generateCurrentWorkflow(
  engagementId: string,
): Promise<Workflow> {
  return request(`/engagements/${engagementId}/workflows/current/generate`, {
    method: "POST",
  });
}

export function generateTargetWorkflow(
  engagementId: string,
): Promise<Workflow> {
  return request(`/engagements/${engagementId}/workflows/target/generate`, {
    method: "POST",
  });
}

export function updateWorkflowStep(
  engagementId: string,
  workflowId: string,
  stepId: string,
  payload: Partial<
    Pick<
      WorkflowStep,
      | "name"
      | "description"
      | "actor_label"
      | "allocation"
      | "rationale"
      | "controls"
    >
  >,
): Promise<WorkflowStep> {
  return request(
    `/engagements/${engagementId}/workflows/${workflowId}/steps/${stepId}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function approveWorkflow(
  engagementId: string,
  workflowId: string,
  reason: string | null = null,
): Promise<Workflow> {
  return request(
    `/engagements/${engagementId}/workflows/${workflowId}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    },
  );
}

export function getEconomics(
  engagementId: string,
): Promise<EconomicCase | null> {
  return request(`/engagements/${engagementId}/economics`);
}

type EconomicInput = { value: string; classification: EvidenceClassification };

export function calculateEconomics(
  engagementId: string,
  payload: {
    annual_volume: EconomicInput;
    current_minutes_per_item: EconomicInput;
    target_minutes_per_item: EconomicInput;
    loaded_hourly_cost: EconomicInput;
    implementation_cost: EconomicInput;
    annual_operating_cost: EconomicInput;
    assumptions: string[];
  },
): Promise<EconomicCase> {
  return request(`/engagements/${engagementId}/economics/calculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function approveEconomics(
  engagementId: string,
  economicCaseId: string,
): Promise<EconomicCase> {
  return request(
    `/engagements/${engagementId}/economics/${economicCaseId}/approve`,
    {
      method: "POST",
    },
  );
}

export function getImplementationSpecification(
  engagementId: string,
): Promise<ImplementationArtifact | null> {
  return request(`/engagements/${engagementId}/implementation-specifications`);
}

export function generateImplementationSpecification(
  engagementId: string,
): Promise<ImplementationArtifact> {
  return request(
    `/engagements/${engagementId}/implementation-specifications/generate`,
    {
      method: "POST",
    },
  );
}

export function getImplementationPacket(
  engagementId: string,
): Promise<ImplementationArtifact[]> {
  return request(`/engagements/${engagementId}/implementation-packet`);
}

export function generateImplementationPacket(
  engagementId: string,
): Promise<ImplementationArtifact[]> {
  return request(
    `/engagements/${engagementId}/implementation-packet/generate`,
    {
      method: "POST",
    },
  );
}
