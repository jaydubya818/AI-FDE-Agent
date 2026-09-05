import {
  expect,
  test,
  type Page,
  type Request,
  type Route,
} from "@playwright/test";

import { READINESS_CRITERION_COUNT } from "../../lib/factory-handoff";
import type {
  CustomerFactoryModel,
  CustomerFactoryModelInput,
  DeploymentPackage,
  DeploymentPackageInput,
  DesignPartnerQualification,
  EconomicCase,
  FactoryHandoffPrerequisites,
  FactoryOpportunity,
  FactoryOpportunityInput,
  FactorySourceReference,
  FDLCReadinessAssessment,
  ImplementationArtifact,
  ReadinessAssessmentInput,
  Workflow,
} from "../../lib/types";

const NOW = "2026-09-04T18:00:00.000Z";
const ENGAGEMENT_ID = "10000000-0000-4000-8000-000000000001";
const OPERATOR_ID = "20000000-0000-4000-8000-000000000001";
const QUALIFICATION_ID = "30000000-0000-4000-8000-000000000001";
const EVIDENCE_ID = "40000000-0000-4000-8000-000000000001";
const ASSERTION_ID = "50000000-0000-4000-8000-000000000001";
const CURRENT_WORKFLOW_ID = "60000000-0000-4000-8000-000000000001";
const TARGET_WORKFLOW_ID = "60000000-0000-4000-8000-000000000002";
const ECONOMIC_CASE_ID = "70000000-0000-4000-8000-000000000001";
const CUSTOMER_MODEL_ID = "80000000-0000-4000-8000-000000000001";
const OPPORTUNITY_ID = "90000000-0000-4000-8000-000000000001";
const READINESS_ID = "a0000000-0000-4000-8000-000000000001";
const PACKAGE_VERSION_ID = "b0000000-0000-4000-8000-000000000001";
const RAW_EVIDENCE_QUOTE =
  "QUARANTINED CUSTOMER QUOTE: route account 90210 without review.";
const RAW_EVIDENCE_FILENAME = "northstar-controller-private-notes.md";

const opportunityFactorKeys = [
  "workflow_frequency",
  "human_effort",
  "cycle_time",
  "repeatability",
  "standardization",
  "evidence_quality",
  "deterministic_verifiability",
  "blast_radius",
  "system_accessibility",
  "data_sensitivity",
  "implementation_complexity",
  "expected_economic_value",
  "autonomy_potential",
] as const;

const readinessStages = [
  "DISCOVER",
  "DESIGN",
  "ASSEMBLE",
  "VALIDATE",
  "DEPLOY",
  "OPERATE",
  "IMPROVE",
] as const;

function digest(character: string) {
  return `sha256:${character.repeat(64)}`;
}

function sourceReference(
  kind: FactorySourceReference["kind"],
  ref: string,
  character: string,
  version: number | null = null,
): FactorySourceReference {
  return { kind, ref, version, sha256: digest(character) };
}

const evidenceRef = sourceReference(
  "EVIDENCE",
  `evidence_asset:${EVIDENCE_ID}`,
  "1",
);
const claimRef = sourceReference(
  "VERIFIED_CLAIM",
  `assertion:${ASSERTION_ID}`,
  "2",
);
const economicsRef = sourceReference(
  "APPROVED_INPUT",
  `economic_case:${ECONOMIC_CASE_ID}`,
  "5",
  1,
);

const qualification: DesignPartnerQualification = {
  id: QUALIFICATION_ID,
  engagement_id: ENGAGEMENT_ID,
  partner_key: "northstar-design-partner",
  organization: "Northstar Components",
  status: "ACTIVE",
  qualification_state: "QUALIFIED",
  authorized_users: [
    {
      operator_id: OPERATOR_ID,
      display_name: "Avery Chen",
      role: "owner",
    },
  ],
  authorized_data_source_keys: ["invoice-exceptions-sanitized"],
  authorized_repository_refs: ["github.com/sellerfi/invoice-ops"],
  allowed_workflow_classes: ["bounded-software-change"],
  data_classification: "CONFIDENTIAL",
  retention_days: 30,
  authorization_basis_ref: "dp-contract-2026-09",
  created_at: NOW,
  updated_at: NOW,
};

const engagement = {
  id: ENGAGEMENT_ID,
  name: qualification.organization,
  slug: "northstar-components",
  workflow_name: "Invoice exception routing",
  primary_outcome:
    "Reduce exception cycle time while preserving controller approval authority.",
  lifecycle_stage: "specify" as const,
  data_classification: "sanitized" as const,
  data_lifecycle_status: "active" as const,
  retention_expires_at: "2026-10-04T18:00:00.000Z",
  created_at: NOW,
  updated_at: NOW,
};

function workflow(
  id: string,
  workflowKind: "current" | "target",
  allocation: "human" | "ai_human",
): Workflow {
  return {
    id,
    workflow_kind: workflowKind,
    version_number: 1,
    name: `${engagement.workflow_name} — ${workflowKind} state`,
    objective: engagement.primary_outcome,
    status: "approved",
    source_workflow_id: workflowKind === "target" ? CURRENT_WORKFLOW_ID : null,
    source_assertion_ids: [ASSERTION_ID],
    generated_by: "system",
    approved_at: NOW,
    approval_reason: "Reviewed by the qualified design-partner operator.",
    created_at: NOW,
    updated_at: NOW,
    steps: [
      {
        id: `${id.slice(0, -1)}3`,
        step_key: "route-exception",
        position: 1,
        name: "Route invoice exception",
        description: "Classify the exception and preserve controller review.",
        step_type: "human_task",
        actor_label: "Accounts payable operator",
        system_label: "Invoice operations",
        allocation,
        rationale: "Material approvals remain human controlled.",
        controls: ["Controller approval required"],
        source_assertion_id: ASSERTION_ID,
      },
    ],
  };
}

const currentWorkflow = workflow(CURRENT_WORKFLOW_ID, "current", "human");
const targetWorkflow = workflow(TARGET_WORKFLOW_ID, "target", "ai_human");

const calculatedValue = (value: string | null, unit: string) => ({
  value,
  unit,
  classification: "calculated" as const,
  formula: "versioned deterministic formula",
});

const economicInputs = {
  annual_volume: {
    value: "12000",
    unit: "items / year",
    classification: "measured" as const,
  },
};
const economicOutputs = {
  annual_net_benefit: calculatedValue("84000", "USD / year"),
  payback_months: calculatedValue("6", "months"),
};

const economics: EconomicCase = {
  id: ECONOMIC_CASE_ID,
  version_number: 1,
  status: "approved",
  source_target_workflow_id: TARGET_WORKFLOW_ID,
  formula_version: "factory-economics/v1",
  inputs: economicInputs,
  outputs: economicOutputs,
  scenarios: {
    low: {
      label: "Low",
      description: "Conservative bounded case.",
      inputs: economicInputs,
      outputs: {
        annual_net_benefit: calculatedValue("42000", "USD / year"),
        payback_months: calculatedValue("12", "months"),
      },
    },
    base: {
      label: "Base",
      description: "Reviewed planning case.",
      inputs: economicInputs,
      outputs: economicOutputs,
    },
    high: {
      label: "High",
      description: "Upper sensitivity bound.",
      inputs: economicInputs,
      outputs: {
        annual_net_benefit: calculatedValue("126000", "USD / year"),
        payback_months: calculatedValue("4", "months"),
      },
    },
  },
  assumptions: ["Validated only for this design-partner workflow."],
  approved_at: NOW,
  created_at: NOW,
  updated_at: NOW,
};

const artifactTypes = [
  "prd",
  "architecture",
  "business_rules",
  "integration_requirements",
  "approval_controls",
  "evaluation_plan",
  "implementation_spec",
] as const;

const artifacts: ImplementationArtifact[] = artifactTypes.map(
  (artifactType, index) => ({
    id: `c0000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    artifact_type: artifactType,
    packet_version: 1,
    version_number: 1,
    status: "current",
    title: artifactType.replaceAll("_", " "),
    content:
      artifactType === "implementation_spec"
        ? `# Bounded implementation specification\n\nSource: ${RAW_EVIDENCE_FILENAME}\n\n${RAW_EVIDENCE_QUOTE}`
        : `# ${artifactType.replaceAll("_", " ")}\n\nReviewed design-partner artifact.`,
    content_hash: String(index + 3).repeat(64),
    source_current_workflow_id: CURRENT_WORKFLOW_ID,
    source_target_workflow_id: TARGET_WORKFLOW_ID,
    economic_case_id: ECONOMIC_CASE_ID,
    source_assertion_ids: [ASSERTION_ID],
    generated_at: NOW,
  }),
);

const prerequisites: FactoryHandoffPrerequisites = {
  engagement_id: ENGAGEMENT_ID,
  organization_key: "northstar-components",
  organization_label: engagement.name,
  workflow_name: engagement.workflow_name,
  primary_outcome: engagement.primary_outcome,
  evidence_refs: [evidenceRef],
  verified_claim_refs: [claimRef],
  current_workflow_ref: {
    id: CURRENT_WORKFLOW_ID,
    version: 1,
    digest: digest("6"),
  },
  target_workflow_ref: {
    id: TARGET_WORKFLOW_ID,
    version: 1,
    digest: digest("7"),
  },
  economic_case_ref: economicsRef,
  implementation_artifact_refs: artifacts.map((artifact, index) =>
    sourceReference(
      "APPROVED_INPUT",
      `implementation_artifact:${artifact.id}`,
      String((index + 3) % 10),
      artifact.version_number,
    ),
  ),
};

type MutationRecord = {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
};

type MockBackend = {
  mutations: MutationRecord[];
  unknownRequests: string[];
  state: {
    customerModel: () => CustomerFactoryModel | null;
    opportunity: () => FactoryOpportunity | null;
    readiness: () => FDLCReadinessAssessment | null;
    deploymentPackage: () => DeploymentPackage | null;
  };
};

function requestBody<T>(request: Request): T {
  const body = request.postData();
  if (!body) throw new Error(`Expected JSON body for ${request.url()}`);
  return JSON.parse(body) as T;
}

function corsHeaders(request: Request) {
  return {
    "access-control-allow-credentials": "true",
    "access-control-allow-headers":
      "Content-Type, X-AI-FDE-Intent, X-Correlation-ID",
    "access-control-allow-methods": "GET, POST, PUT, OPTIONS",
    "access-control-allow-origin":
      request.headers().origin ?? "http://localhost:3000",
    "content-type": "application/json",
    vary: "Origin",
  };
}

async function installDesignPartnerBackend(page: Page): Promise<MockBackend> {
  let customerModel: CustomerFactoryModel | null = null;
  let opportunity: FactoryOpportunity | null = null;
  let readiness: FDLCReadinessAssessment | null = null;
  let deploymentPackage: DeploymentPackage | null = null;
  const mutations: MutationRecord[] = [];
  const unknownRequests: string[] = [];
  const root = `/api/engagements/${ENGAGEMENT_ID}`;

  async function respond(route: Route, request: Request, json: unknown) {
    await route.fulfill({ headers: corsHeaders(request), json, status: 200 });
  }

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname;

    if (method === "OPTIONS") {
      await route.fulfill({ headers: corsHeaders(request), status: 204 });
      return;
    }

    const body = request.postData()
      ? (JSON.parse(request.postData()!) as unknown)
      : null;
    if (!["GET", "HEAD"].includes(method)) {
      mutations.push({ body, headers: request.headers(), method, path });
    }

    if (method === "GET" && path === "/api/auth/me") {
      await respond(route, request, {
        id: OPERATOR_ID,
        display_name: "Avery Chen",
        auth_mode: "oidc",
        sanitized_data_allowed: true,
      });
      return;
    }
    if (method === "GET" && path === root) {
      await respond(route, request, {
        engagement,
        counts: { evidence: 1, candidate_claims: 0, verified_assertions: 1 },
      });
      return;
    }
    if (method === "GET" && path === `${root}/design-partner-qualification`) {
      await respond(route, request, qualification);
      return;
    }
    if (method === "GET" && path === `${root}/evidence`) {
      await respond(route, request, [
        {
          id: EVIDENCE_ID,
          engagement_id: ENGAGEMENT_ID,
          file_name: "invoice-exceptions-sanitized.md",
          content_type: "text/markdown",
          content_hash: "1".repeat(64),
          byte_count: 512,
          source_type: "upload",
          source_timestamp: NOW,
          design_partner_qualification_id: QUALIFICATION_ID,
          authorized_source_key: "invoice-exceptions-sanitized",
          authorized_workflow_class: "bounded-software-change",
          data_classification: "CONFIDENTIAL",
          status: "complete",
          error_message: null,
          created_at: NOW,
        },
      ]);
      return;
    }
    if (method === "GET" && path === `${root}/claims`) {
      await respond(route, request, [
        {
          id: "d0000000-0000-4000-8000-000000000001",
          claim_kind: "rule",
          subject_text: "Invoice exceptions",
          predicate: "REQUIRES_APPROVAL",
          object_text: "Controller",
          summary: "Invoice exceptions require Controller approval.",
          normalized_payload: { authority: "Controller" },
          confidence: "0.98",
          materiality: "material",
          status: "accepted",
          created_at: NOW,
          provenance: [
            {
              claim_evidence_id: "d0000000-0000-4000-8000-000000000002",
              evidence_segment_id: "d0000000-0000-4000-8000-000000000003",
              evidence_asset_id: EVIDENCE_ID,
              file_name: "invoice-exceptions-sanitized.md",
              source_type: "upload",
              source_timestamp: NOW,
              locator: { line: 12 },
              quote: "Controller approval is required for invoice exceptions.",
              start_offset: 0,
              end_offset: 56,
            },
          ],
        },
      ]);
      return;
    }
    if (method === "GET" && path === `${root}/contradictions`) {
      await respond(route, request, []);
      return;
    }
    if (method === "GET" && path === `${root}/operating-model`) {
      await respond(route, request, {
        entities: [
          {
            id: "d0000000-0000-4000-8000-000000000004",
            entity_type: "process",
            canonical_key: "invoice-exception-routing",
            display_name: engagement.workflow_name,
            status: "active",
            created_at: NOW,
          },
        ],
        assertions: [
          {
            id: ASSERTION_ID,
            subject: "Invoice exceptions",
            subject_entity_id: "d0000000-0000-4000-8000-000000000004",
            predicate: "REQUIRES_APPROVAL",
            object: "Controller",
            object_entity_id: null,
            value: { authority: "Controller" },
            status: "verified",
            confidence: "0.98",
            recorded_at: NOW,
            evidence: {
              file_name: "invoice-exceptions-sanitized.md",
              source_type: "upload",
              source_timestamp: NOW,
              locator: { line: 12 },
              quote: "Controller approval is required for invoice exceptions.",
              segment_id: "d0000000-0000-4000-8000-000000000003",
            },
          },
        ],
      });
      return;
    }
    if (method === "GET" && path === `${root}/workflows`) {
      await respond(route, request, {
        current: currentWorkflow,
        target: targetWorkflow,
      });
      return;
    }
    if (method === "GET" && path === `${root}/economics`) {
      await respond(route, request, economics);
      return;
    }
    if (method === "GET" && path === `${root}/implementation-packet`) {
      await respond(route, request, artifacts);
      return;
    }
    if (method === "GET" && path === `${root}/factory-handoff/prerequisites`) {
      await respond(route, request, prerequisites);
      return;
    }
    if (method === "GET" && path === `${root}/factory-handoff`) {
      await respond(route, request, {
        customer_model: customerModel,
        opportunities: opportunity ? [opportunity] : [],
        readiness,
        packages: deploymentPackage ? [deploymentPackage] : [],
        latest_retrieval: null,
      });
      return;
    }
    if (method === "GET" && path === `${root}/delivery-scorecard`) {
      await respond(route, request, {
        engagement: {
          id: ENGAGEMENT_ID,
          name: engagement.name,
          slug: engagement.slug,
          workflow_name: engagement.workflow_name,
        },
        milestones: {
          engagement_created: true,
          evidence_ready: true,
          review_completed: true,
          workflows_approved: true,
          economics_approved: true,
          implementation_packet_completed: true,
        },
        claims: {
          total: 1,
          candidate: 0,
          accepted: 1,
          rejected: 0,
          deferred: 0,
          material_accepted: 1,
        },
        contradictions: { total: 0, resolved: 0, blocking_open: 0 },
        packet: {
          complete: true,
          artifact_count: 7,
          expected_artifact_count: 7,
          packet_version: 1,
          completed_at: NOW,
        },
        provider: {
          run_count: 1,
          providers: ["bedrock"],
          model_ids: ["qualified-extractor"],
          input_tokens: 100,
          output_tokens: 50,
          total_tokens: 150,
          latency_ms: 1200,
          tokens_per_accepted_material_claim: 150,
        },
        assessments: [],
      });
      return;
    }
    if (method === "GET" && path === `${root}/data-lifecycle`) {
      await respond(route, request, {
        status: "active",
        retention_expires_at: engagement.retention_expires_at,
        membership_role: "owner",
        latest_export: null,
        export_current: false,
        retention_blocked: false,
        can_delete: false,
      });
      return;
    }

    if (method === "POST" && path === `${root}/customer-factory-models`) {
      const input = requestBody<CustomerFactoryModelInput>(request);
      customerModel = {
        ...input,
        id: CUSTOMER_MODEL_ID,
        engagement_id: ENGAGEMENT_ID,
        version_number: 1,
        status: "DRAFT",
        content_digest: digest("8"),
        approved_at: null,
        stale_reason: null,
        created_at: NOW,
      };
      await respond(route, request, customerModel);
      return;
    }
    if (
      method === "POST" &&
      path === `${root}/customer-factory-models/${CUSTOMER_MODEL_ID}/approve`
    ) {
      if (!customerModel) throw new Error("Customer model was not created.");
      customerModel = {
        ...customerModel,
        approved_at: NOW,
        status: "APPROVED",
      };
      await respond(route, request, customerModel);
      return;
    }
    if (method === "POST" && path === `${root}/factory-opportunities`) {
      if (!customerModel) throw new Error("Customer model was not created.");
      const input = requestBody<FactoryOpportunityInput>(request);
      opportunity = {
        id: OPPORTUNITY_ID,
        engagement_id: ENGAGEMENT_ID,
        opportunity_key: input.opportunity.opportunity_key,
        version_number: 1,
        status: "RECOMMENDED",
        name: input.opportunity.name,
        description: input.opportunity.description,
        source_workflow_ref: input.opportunity.source_workflow_ref,
        customer_factory_model_id: customerModel.id,
        customer_factory_model_version: customerModel.version_number,
        value_score: 82,
        verifiability_score: 88,
        readiness_score: 80,
        risk_score: 74,
        autonomy_potential: input.opportunity.factors.autonomy_potential,
        priority_score: 84,
        factors: input.opportunity.factors,
        rubric: {},
        rubric_version: "factory-opportunity-rubric/v1",
        economics_ref: input.opportunity.economics_ref,
        evidence_refs: input.opportunity.evidence_refs,
        rationale: [
          "The workflow is frequent and bounded.",
          "Evidence and deterministic verification are available.",
          "Human approval authority remains explicit.",
        ],
        blockers: input.opportunity.blockers,
        recommendation: "RECOMMEND for a bounded factory line.",
        content_digest: digest("9"),
        selection_reason: null,
        selected_at: null,
        rejection_reason: null,
        rejected_at: null,
        stale_reason: null,
        created_at: NOW,
      };
      await respond(route, request, opportunity);
      return;
    }
    if (
      method === "POST" &&
      path === `${root}/factory-opportunities/${OPPORTUNITY_ID}/select`
    ) {
      if (!opportunity) throw new Error("Opportunity was not created.");
      const input = requestBody<{ reason: string }>(request);
      opportunity = {
        ...opportunity,
        selected_at: NOW,
        selection_reason: input.reason,
        status: "SELECTED",
      };
      await respond(route, request, opportunity);
      return;
    }
    if (method === "POST" && path === `${root}/fdlc-readiness`) {
      if (!customerModel || !opportunity) {
        throw new Error("Readiness prerequisites were not created.");
      }
      const input = requestBody<ReadinessAssessmentInput>(request);
      readiness = {
        id: READINESS_ID,
        engagement_id: ENGAGEMENT_ID,
        version_number: 1,
        status: "DRAFT",
        overall_status: "READY",
        customer_factory_model_id: customerModel.id,
        customer_factory_model_version: customerModel.version_number,
        selected_opportunity_id: opportunity.id,
        selected_opportunity_version: opportunity.version_number,
        current_workflow_ref: prerequisites.current_workflow_ref!,
        target_workflow_ref: prerequisites.target_workflow_ref!,
        stages: input.assessment.stages.map((stage) => ({
          stage: stage.stage,
          status: "READY",
          score: 100,
          evidence_refs: stage.criteria.flatMap((criterion) =>
            criterion.basis_refs.slice(0, 1),
          ),
          blockers: [],
          risks: stage.risks,
          decisions: stage.decisions,
          required_artifacts: stage.required_artifacts,
          owner: stage.owner,
          next_actions: [],
          criteria: stage.criteria,
          explanation:
            "Every blocking criterion was explicitly confirmed against immutable evidence.",
          updated_at: NOW,
        })),
        content_digest: digest("a"),
        approved_at: null,
        stale_reason: null,
        created_at: NOW,
      };
      await respond(route, request, readiness);
      return;
    }
    if (
      method === "POST" &&
      path === `${root}/fdlc-readiness/${READINESS_ID}/approve`
    ) {
      if (!readiness) throw new Error("Readiness was not created.");
      readiness = { ...readiness, approved_at: NOW, status: "APPROVED" };
      await respond(route, request, readiness);
      return;
    }
    if (method === "POST" && path === `${root}/deployment-packages`) {
      if (!customerModel || !opportunity || !readiness) {
        throw new Error("Package prerequisites were not created.");
      }
      const input = requestBody<DeploymentPackageInput>(request);
      deploymentPackage = {
        id: PACKAGE_VERSION_ID,
        engagement_id: ENGAGEMENT_ID,
        package_id: "pkg-northstar-invoice-v1",
        package_version: 1,
        schema_version: "fdlc.factory-deployment-package/v1",
        status: "DRAFT",
        issuer: {
          issuer_id: "factory-engineer",
          issuer_type: "FDLC_FACTORY_ENGINEER",
          environment: "design-partner",
          authority_scope: "DEPLOYMENT_PACKAGE_PUBLISH",
        },
        source: {
          customer_factory_model: {
            id: customerModel.id,
            version: customerModel.version_number,
            digest: customerModel.content_digest,
          },
          current_workflow: prerequisites.current_workflow_ref!,
          target_workflow: prerequisites.target_workflow_ref!,
          readiness_assessment: {
            id: readiness.id,
            version: readiness.version_number,
            digest: readiness.content_digest,
          },
          factory_opportunity: {
            id: opportunity.id,
            version: opportunity.version_number,
            digest: opportunity.content_digest,
          },
        },
        target: input.target,
        deployment_intent: input.deployment_intent,
        digest: null,
        approval: null,
        issued_at: null,
        approved_at: null,
        published_at: null,
        state_reason: "Draft prepared for explicit human review.",
        created_at: NOW,
      };
      await respond(route, request, deploymentPackage);
      return;
    }
    if (
      method === "POST" &&
      path === `${root}/deployment-packages/${PACKAGE_VERSION_ID}/review`
    ) {
      if (!deploymentPackage) throw new Error("Package was not created.");
      deploymentPackage = {
        ...deploymentPackage,
        state_reason: "Submitted by the human operator for review.",
        status: "READY_FOR_REVIEW",
      };
      await respond(route, request, deploymentPackage);
      return;
    }
    if (
      method === "POST" &&
      path === `${root}/deployment-packages/${PACKAGE_VERSION_ID}/approve`
    ) {
      if (!deploymentPackage) throw new Error("Package was not created.");
      const input = requestBody<{
        authority_basis_ref: FactorySourceReference;
      }>(request);
      deploymentPackage = {
        ...deploymentPackage,
        approval: {
          decision_ref: sourceReference(
            "APPROVED_INPUT",
            `deployment_package:${PACKAGE_VERSION_ID}`,
            "b",
            1,
          ),
          approved_by: OPERATOR_ID,
          authorized_by_ref: qualification.authorization_basis_ref,
          authority_basis_ref: input.authority_basis_ref,
          approved_at: NOW,
        },
        approved_at: NOW,
        digest: digest("b"),
        issued_at: NOW,
        state_reason: "Human approval bound to the immutable digest.",
        status: "APPROVED",
      };
      await respond(route, request, deploymentPackage);
      return;
    }
    if (
      method === "POST" &&
      path === `${root}/deployment-packages/${PACKAGE_VERSION_ID}/publish`
    ) {
      if (!deploymentPackage) throw new Error("Package was not created.");
      deploymentPackage = {
        ...deploymentPackage,
        published_at: NOW,
        state_reason: "Published for authenticated downstream retrieval.",
        status: "PUBLISHED",
      };
      await respond(route, request, deploymentPackage);
      return;
    }

    unknownRequests.push(`${method} ${path}`);
    await route.fulfill({
      headers: corsHeaders(request),
      json: { detail: `Unmocked request: ${method} ${path}` },
      status: 404,
    });
  });

  return {
    mutations,
    unknownRequests,
    state: {
      customerModel: () => customerModel,
      opportunity: () => opportunity,
      readiness: () => readiness,
      deploymentPackage: () => deploymentPackage,
    },
  };
}

function expectMutationHeaders(mutations: MutationRecord[]) {
  for (const mutation of mutations) {
    expect(mutation.headers["x-ai-fde-intent"]).toBe("browser-mutation");
    expect(mutation.headers["x-correlation-id"]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  }
}

test("a qualified sanitized partner publishes a governed package for human import", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ height: 960, width: 1440 });
  const backend = await installDesignPartnerBackend(page);
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(`/engagements/${ENGAGEMENT_ID}`);
  await expect(
    page.getByRole("heading", { level: 1, name: engagement.name }),
  ).toBeVisible();
  await expect(page.getByText("Qualified partner boundary")).toBeVisible();
  await expect(
    page.getByText("Customer-data access", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Qualified for this engagement", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Design-partner production", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Design-partner authority boundary" }),
  ).toContainText("Nothing here approves a Mission Control plan");

  await page.getByRole("button", { name: "Build model draft" }).click();
  await expect(
    page.getByRole("button", { name: "Approve customer model" }),
  ).toBeVisible();
  expect(backend.state.customerModel()?.status).toBe("DRAFT");
  expect(backend.mutations).toHaveLength(1);

  await page.getByRole("button", { name: "Approve customer model" }).click();
  await expect(
    page.getByRole("button", { name: "Assess opportunity" }),
  ).toBeVisible();
  expect(backend.state.customerModel()?.status).toBe("APPROVED");
  expect(backend.mutations).toHaveLength(2);

  await page.getByRole("button", { name: "Assess opportunity" }).click();
  const opportunityForm = page.getByRole("form", {
    name: "Assess a factory opportunity",
  });
  await opportunityForm
    .getByLabel("Candidate line name")
    .fill("Invoice exception triage");
  await opportunityForm
    .getByLabel("Bounded outcome")
    .fill("Route invoice exceptions faster without weakening human approval.");
  const factorInputs = opportunityForm.locator('input[type="number"]');
  await expect(factorInputs).toHaveCount(13);
  for (let index = 0; index < 13; index += 1) {
    await factorInputs.nth(index).fill(String((index % 3) + 3));
  }
  await opportunityForm
    .getByRole("button", { name: "Record assessment" })
    .click();

  const opportunityHeading = page.getByRole("heading", {
    level: 3,
    name: "Invoice exception triage",
  });
  const opportunityCard = page
    .getByRole("article")
    .filter({ has: opportunityHeading });
  await expect(opportunityHeading).toBeVisible();
  expect(backend.state.opportunity()?.status).toBe("RECOMMENDED");
  expect(backend.mutations).toHaveLength(3);
  const selectButton = opportunityCard.getByRole("button", {
    name: "Select factory line",
  });
  await expect(selectButton).toBeDisabled();
  const selectionRationale =
    "This bounded line has reviewed evidence, measurable value, and preserved Controller authority.";
  await opportunityCard
    .getByRole("textbox", {
      name: "Selection rationale for Invoice exception triage",
    })
    .fill(selectionRationale);
  await selectButton.click();
  await expect(opportunityCard.getByText(/Human-selected/)).toContainText(
    selectionRationale,
  );
  expect(backend.state.opportunity()?.status).toBe("SELECTED");
  expect(backend.mutations).toHaveLength(4);

  await page.getByRole("button", { name: "Assess seven stages" }).click();
  const readinessForm = page.getByRole("form", {
    name: "Review FDLC readiness",
  });
  const criterionConfirmations = readinessForm.getByRole("checkbox");
  await expect(criterionConfirmations).toHaveCount(READINESS_CRITERION_COUNT);
  await expect(
    readinessForm.getByRole("button", {
      name: `Record readiness draft (0/${READINESS_CRITERION_COUNT} criteria)`,
    }),
  ).toBeDisabled();
  await criterionConfirmations.first().check();
  await expect(
    readinessForm.getByRole("button", {
      name: `Record readiness draft (1/${READINESS_CRITERION_COUNT} criteria)`,
    }),
  ).toBeDisabled();
  for (let index = 1; index < READINESS_CRITERION_COUNT - 1; index += 1) {
    await criterionConfirmations.nth(index).check();
  }
  await expect(
    readinessForm.getByRole("button", {
      name: `Record readiness draft (${READINESS_CRITERION_COUNT - 1}/${READINESS_CRITERION_COUNT} criteria)`,
    }),
  ).toBeDisabled();
  await criterionConfirmations.last().check();
  await readinessForm
    .getByRole("button", {
      name: `Record readiness draft (${READINESS_CRITERION_COUNT}/${READINESS_CRITERION_COUNT} criteria)`,
    })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve readiness" }),
  ).toBeVisible();
  expect(backend.state.readiness()?.status).toBe("DRAFT");
  expect(backend.state.readiness()?.overall_status).toBe("READY");
  expect(backend.mutations).toHaveLength(5);

  await page.getByRole("button", { name: "Approve readiness" }).click();
  await expect(
    page.getByText("Final READY assessment was approved"),
  ).toBeVisible();
  expect(backend.state.readiness()?.status).toBe("APPROVED");
  expect(backend.mutations).toHaveLength(6);

  await page.getByRole("button", { name: "Generate package draft" }).click();
  const packageForm = page.getByRole("form", {
    name: "Prepare a deployment package draft",
  });
  await packageForm
    .getByLabel("Authorized repository")
    .selectOption("github.com/sellerfi/invoice-ops");
  await packageForm
    .getByLabel("Authorized workflow class")
    .selectOption("bounded-software-change");
  await packageForm
    .getByLabel(/Bounded code scopes/)
    .fill("apps/web/components/invoice-exceptions/**");
  await packageForm
    .getByLabel("Mission draft title")
    .fill("Invoice exception triage implementation draft");
  await packageForm
    .getByLabel("Objective")
    .fill("Prepare a bounded, independently verified invoice-routing change.");
  await packageForm
    .getByRole("button", { name: "Create package draft" })
    .click();

  const packageHeading = page.getByRole("heading", {
    level: 3,
    name: "Invoice exception triage implementation draft",
  });
  const packageReview = page
    .getByRole("article")
    .filter({ has: packageHeading });
  await expect(packageHeading).toBeVisible();
  await expect(packageReview.getByText("DRAFT", { exact: true })).toBeVisible();
  expect(backend.state.deploymentPackage()?.status).toBe("DRAFT");
  expect(backend.mutations).toHaveLength(7);

  await packageReview.getByRole("button", { name: "Send to review" }).click();
  await expect(
    packageReview.getByRole("button", { name: "Approve & bind digest" }),
  ).toBeVisible();
  expect(backend.state.deploymentPackage()?.status).toBe("READY_FOR_REVIEW");
  expect(backend.mutations).toHaveLength(8);

  await packageReview
    .getByRole("button", { name: "Approve & bind digest" })
    .click();
  await expect(
    packageReview.getByRole("button", { name: "Publish immutable v1" }),
  ).toBeVisible();
  await expect(packageReview.getByText(/^sha256:[a-f0-9]{64}$/)).toBeVisible();
  expect(backend.state.deploymentPackage()?.status).toBe("APPROVED");
  expect(backend.mutations).toHaveLength(9);

  await packageReview
    .getByRole("button", { name: "Publish immutable v1" })
    .click();
  await expect(
    packageReview.getByText("PUBLISHED", { exact: true }),
  ).toBeVisible();
  expect(backend.state.deploymentPackage()?.status).toBe("PUBLISHED");
  expect(backend.mutations).toHaveLength(10);

  const handoffLink = page.getByRole("link", {
    name: /Open governed draft import/,
  });
  await expect(handoffLink).toHaveAttribute(
    "href",
    /https:\/\/mission-control\.example\/v2\/missions\?.*factoryPackageId=pkg-northstar-invoice-v1/,
  );
  await expect(handoffLink).toHaveAttribute("href", /factoryPackageVersion=1/);
  await expect(handoffLink).toHaveAttribute(
    "href",
    /factoryCodeScope=apps%2Fweb%2Fcomponents%2Finvoice-exceptions%2F\*\*/,
  );
  const handoffHref = await handoffLink.getAttribute("href");
  await expect(
    page.getByRole("link", {
      name: /11\. Mission Control: External import, incomplete/,
    }),
  ).toBeVisible();
  await expect(
    page.getByText(/import remains pending until Mission Control returns/),
  ).toBeVisible();

  expect(backend.unknownRequests).toEqual([]);
  expectMutationHeaders(backend.mutations);
  expect(backend.mutations.map((mutation) => mutation.path)).toEqual([
    `${rootPath()}/customer-factory-models`,
    `${rootPath()}/customer-factory-models/${CUSTOMER_MODEL_ID}/approve`,
    `${rootPath()}/factory-opportunities`,
    `${rootPath()}/factory-opportunities/${OPPORTUNITY_ID}/select`,
    `${rootPath()}/fdlc-readiness`,
    `${rootPath()}/fdlc-readiness/${READINESS_ID}/approve`,
    `${rootPath()}/deployment-packages`,
    `${rootPath()}/deployment-packages/${PACKAGE_VERSION_ID}/review`,
    `${rootPath()}/deployment-packages/${PACKAGE_VERSION_ID}/approve`,
    `${rootPath()}/deployment-packages/${PACKAGE_VERSION_ID}/publish`,
  ]);
  expect(
    backend.mutations.some((mutation) =>
      /\/(bootstrap|simulate-retrieval|deployments|promotions|work-orders|attempts)(?:\/|$)/u.test(
        mutation.path,
      ),
    ),
  ).toBe(false);

  const opportunityMutation = backend.mutations[2]
    .body as FactoryOpportunityInput;
  expect(Object.keys(opportunityMutation.opportunity.factors).sort()).toEqual(
    [...opportunityFactorKeys].sort(),
  );
  expect((backend.mutations[3].body as { reason: string }).reason).toBe(
    selectionRationale,
  );
  const readinessMutation = backend.mutations[4]
    .body as ReadinessAssessmentInput;
  expect(
    readinessMutation.assessment.stages.map((stage) => stage.stage),
  ).toEqual(readinessStages);
  expect(
    readinessMutation.assessment.stages.every((stage) =>
      stage.criteria.every(
        (criterion) => criterion.satisfied && criterion.basis_refs.length > 0,
      ),
    ),
  ).toBe(true);
  expect(
    readinessMutation.assessment.stages.reduce(
      (total, stage) => total + stage.criteria.length,
      0,
    ),
  ).toBe(READINESS_CRITERION_COUNT);
  const packageMutation = backend.mutations[6].body as DeploymentPackageInput;
  const mcBoundPayload = JSON.stringify(packageMutation);
  const storedPackage = JSON.stringify(backend.state.deploymentPackage());
  for (const customerEvidenceValue of [
    RAW_EVIDENCE_QUOTE,
    RAW_EVIDENCE_FILENAME,
  ]) {
    expect(packageMutation.deployment_intent.specification).not.toContain(
      customerEvidenceValue,
    );
    expect(mcBoundPayload).not.toContain(customerEvidenceValue);
    expect(storedPackage).not.toContain(customerEvidenceValue);
    expect(handoffHref).not.toContain(customerEvidenceValue);
    expect(handoffHref).not.toContain(
      encodeURIComponent(customerEvidenceValue),
    );
  }
  expect(
    JSON.parse(packageMutation.deployment_intent.specification),
  ).toMatchObject({
    schema_version: "fdlc.data-minimized-implementation-specification/v1",
    target: {
      environment_class: "ISOLATED_NON_PRODUCTION",
      repository_ref: "github.com/sellerfi/invoice-ops",
      requested_code_scopes: ["apps/web/components/invoice-exceptions/**"],
      semantic_execution_workflow_ref: "bounded-software-change",
    },
    data_boundary: {
      customer_content_embedded: false,
      evidence_quotes_embedded: false,
      implementation_artifact_content_embedded: false,
      source_filenames_embedded: false,
    },
  });
  expect(packageMutation.target).toMatchObject({
    environment_class: "ISOLATED_NON_PRODUCTION",
    repository_ref: "github.com/sellerfi/invoice-ops",
    requested_code_scopes: ["apps/web/components/invoice-exceptions/**"],
    semantic_execution_workflow_ref: "bounded-software-change",
  });
  expect(
    packageMutation.deployment_intent.authority_boundaries[0]
      .prohibited_actions,
  ).toEqual(
    expect.arrayContaining(["approve a Plan", "merge", "release", "deploy"]),
  );
  expect(backend.mutations[8].body).toEqual({
    authority_basis_ref: {
      kind: "APPROVED_INPUT",
      ref: `customer_factory_model:${CUSTOMER_MODEL_ID}`,
      version: 1,
      sha256: digest("8"),
    },
  });
  expect(consoleErrors).toEqual([]);
});

function rootPath() {
  return `/api/engagements/${ENGAGEMENT_ID}`;
}
