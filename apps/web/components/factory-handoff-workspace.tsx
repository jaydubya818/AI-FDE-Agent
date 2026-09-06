"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { CheckIcon } from "@/components/icons";
import {
  ApiError,
  approveDeploymentPackage,
  approveCustomerFactoryModel,
  approveReadiness,
  approveSyntheticCustomerModel,
  assessSyntheticFactoryOpportunity,
  assessSyntheticReadiness,
  createCustomerFactoryModel,
  createDeploymentPackage,
  createFactoryOpportunity,
  createReadinessAssessment,
  generateSyntheticDeploymentPackage,
  getDesignPartnerQualification,
  getEconomics,
  getFactoryHandoffWorkspace,
  getFactoryHandoffPrerequisites,
  getImplementationPacket,
  publishDeploymentPackage,
  selectFactoryOpportunity,
  simulateMissionControlRetrieval,
  submitDeploymentPackage,
} from "@/lib/api";
import {
  buildCustomerFactoryModelInput,
  buildDeploymentPackageInput,
  buildFactoryOpportunityInput,
  buildReadinessAssessmentInput,
  customerModelAuthorityReference,
  DEFAULT_OPPORTUNITY_FACTORS,
  humanize,
  READINESS_CRITERIA,
  READINESS_CRITERION_COUNT,
  READINESS_STAGES,
  readinessCriterionReviewKey,
} from "@/lib/factory-handoff";
import type {
  DesignPartnerQualification,
  DeploymentPackage,
  EconomicCase,
  FactoryHandoffPrerequisites,
  FactoryHandoffWorkspace as FactoryHandoffState,
  FactoryOpportunity,
  FactoryOpportunityFactors,
  FDLCReadinessStage,
  ImplementationArtifact,
} from "@/lib/types";

type Progress = {
  customerModel: boolean;
  opportunity: boolean;
  readiness: boolean;
  package: boolean;
  missionControlImport: boolean;
};

type Notice = { tone: "success" | "error"; text: string } | null;

type QualifiedContext = {
  qualification: DesignPartnerQualification | null;
  prerequisites: FactoryHandoffPrerequisites;
  economics: EconomicCase | null;
  artifacts: ImplementationArtifact[];
};

type Composer = "opportunity" | "readiness" | "package" | null;

const EMPTY_PROGRESS: Progress = {
  customerModel: false,
  opportunity: false,
  readiness: false,
  package: false,
  missionControlImport: false,
};

function statusTone(status: string) {
  if (
    ["READY", "APPROVED", "PUBLISHED", "SELECTED", "RETRIEVED"].includes(status)
  ) {
    return "bg-[var(--teal-soft)] text-[var(--teal)]";
  }
  if (
    ["STALE", "REVOKED", "REJECTED", "BLOCKED", "NOT_READY"].includes(status)
  ) {
    return "bg-[var(--red-soft)] text-[var(--red)]";
  }
  return "bg-[var(--amber-soft)] text-[var(--amber)]";
}

function formatTimestamp(value: string | null) {
  if (!value) return "Not recorded";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function missionControlDraftUrl(
  deploymentPackage: DeploymentPackage | undefined,
): string | null {
  const configuredOrigin = process.env.NEXT_PUBLIC_MISSION_CONTROL_URL;
  if (!configuredOrigin || deploymentPackage?.status !== "PUBLISHED") {
    return null;
  }
  try {
    const url = new URL("/v2/missions", configuredOrigin);
    if (!["https:", "http:"].includes(url.protocol)) return null;
    if (process.env.NODE_ENV === "production" && url.protocol !== "https:") {
      return null;
    }
    url.searchParams.set("factoryPackageId", deploymentPackage.package_id);
    url.searchParams.set(
      "factoryPackageVersion",
      String(deploymentPackage.package_version),
    );
    for (const codeScope of deploymentPackage.target.requested_code_scopes) {
      url.searchParams.append("factoryCodeScope", codeScope);
    }
    return url.toString();
  } catch {
    return null;
  }
}

export function FactoryHandoffWorkspace({
  engagementId,
  lifecycleVersion,
  operatorId,
  synthetic,
  onProgress,
}: {
  engagementId: string;
  lifecycleVersion: string;
  operatorId: string;
  synthetic: boolean;
  onProgress: (progress: Progress) => void;
}) {
  const [data, setData] = useState<FactoryHandoffState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [qualifiedContext, setQualifiedContext] =
    useState<QualifiedContext | null>(null);
  const [composer, setComposer] = useState<Composer>(null);

  const load = useCallback(async () => {
    const nextPromise = getFactoryHandoffWorkspace(engagementId);
    const contextPromise: Promise<QualifiedContext | null> = synthetic
      ? Promise.resolve(null)
      : Promise.all([
          getFactoryHandoffPrerequisites(engagementId),
          getEconomics(engagementId),
          getImplementationPacket(engagementId),
          getDesignPartnerQualification(engagementId).catch(
            (reason: unknown) => {
              if (reason instanceof ApiError && reason.status === 404) {
                return null;
              }
              throw reason;
            },
          ),
        ]).then(([prerequisites, economics, artifacts, qualification]) => ({
          qualification,
          prerequisites,
          economics,
          artifacts,
        }));
    const [next, context] = await Promise.all([nextPromise, contextPromise]);
    setData(next);
    setQualifiedContext(context);
    const selected = next.opportunities.some(
      (opportunity) => opportunity.status === "SELECTED",
    );
    const published = next.packages.some(
      (deploymentPackage) => deploymentPackage.status === "PUBLISHED",
    );
    onProgress({
      customerModel: next.customer_model?.status === "APPROVED",
      opportunity: selected,
      readiness: next.readiness?.status === "APPROVED",
      package: published,
      // Retrieval proves access to the package, not that Mission Control
      // created a Mission or Plan. This remains false until a future contract
      // carries an authenticated import receipt.
      missionControlImport: false,
    });
  }, [engagementId, onProgress, synthetic]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      load()
        .catch((reason: unknown) =>
          setNotice({
            tone: "error",
            text:
              reason instanceof Error
                ? reason.message
                : "The trusted handoff state could not be loaded.",
          }),
        )
        .finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [lifecycleVersion, load]);

  async function runAction(
    key: string,
    action: () => Promise<unknown>,
    success: string,
  ) {
    setBusy(key);
    setNotice(null);
    try {
      await action();
      await load();
      setComposer(null);
      setNotice({ tone: "success", text: success });
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The trusted handoff action could not be completed.",
      });
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!data && !loading) onProgress(EMPTY_PROGRESS);
  }, [data, loading, onProgress]);

  if (loading) {
    return (
      <div
        aria-live="polite"
        className="surface mt-8 rounded-2xl p-8 text-sm font-bold text-[var(--ink-soft)]"
        role="status"
      >
        Loading customer model, readiness, and handoff state…
      </div>
    );
  }

  if (!data) {
    return (
      <div
        className="mt-8 rounded-2xl border border-[var(--red)]/25 bg-[var(--red-soft)] p-6 text-sm font-bold text-[var(--red)]"
        role="alert"
      >
        Trusted handoff state is unavailable. Check the API and retry.
      </div>
    );
  }

  const selectedOpportunity = data.opportunities.find(
    (opportunity) => opportunity.status === "SELECTED",
  );
  const currentPackage = [...data.packages]
    .filter((deploymentPackage) => deploymentPackage.status !== "STALE")
    .sort((left, right) => right.package_version - left.package_version)[0];
  const governedDraftUrl = missionControlDraftUrl(currentPackage);
  const qualification = qualifiedContext?.qualification ?? null;
  const qualifiedPartner = Boolean(
    qualification &&
    qualification.status === "ACTIVE" &&
    qualification.qualification_state === "QUALIFIED" &&
    qualification.data_classification !== "RESTRICTED",
  );
  const partnerRole = qualification?.authorized_users.find(
    (user) => user.operator_id === operatorId,
  )?.role;
  const actionsEnabled =
    synthetic ||
    (qualifiedPartner && partnerRole !== undefined && partnerRole !== "viewer");
  const ownerActionsEnabled =
    synthetic || (qualifiedPartner && partnerRole === "owner");
  const prerequisites = qualifiedContext?.prerequisites ?? null;

  return (
    <>
      {notice && (
        <div
          className={`mt-8 rounded-xl border px-4 py-3 text-sm font-bold ${
            notice.tone === "success"
              ? "border-[var(--teal)]/25 bg-[var(--teal-soft)] text-[var(--teal)]"
              : "border-[var(--red)]/25 bg-[var(--red-soft)] text-[var(--red)]"
          }`}
          role={notice.tone === "error" ? "alert" : "status"}
        >
          {notice.text}
        </div>
      )}

      {!synthetic && (
        <QualifiedActionBoundary
          qualification={qualification}
          partnerRole={partnerRole}
          ready={qualifiedPartner}
        />
      )}

      <section className="mt-14 scroll-mt-6" id="factory-opportunities">
        <HandoffHeading
          eyebrow="08 / Customer truth to candidate line"
          title="Factory opportunity portfolio"
          detail="Freeze the verified customer model, compare one explainable candidate for this workflow, and record the human selection before final readiness."
        />

        {!data.customer_model ? (
          <ActionState
            button={
              synthetic ? "Approve customer model v1" : "Build model draft"
            }
            detail={
              synthetic
                ? "The version is built only from reviewed claims, approved workflow state, exact evidence references, and labeled assumptions."
                : "The server supplies exact evidence and verified-claim digests. Building creates a reviewable draft; it does not approve anything."
            }
            disabled={
              busy !== null ||
              !actionsEnabled ||
              (!synthetic &&
                (!prerequisites ||
                  prerequisites.evidence_refs.length === 0 ||
                  prerequisites.verified_claim_refs.length === 0))
            }
            eyebrow="Customer Factory Model"
            onClick={() => {
              if (synthetic) {
                void runAction(
                  "customer-model",
                  () => approveSyntheticCustomerModel(engagementId),
                  "Customer Factory Model v1 was approved with immutable provenance.",
                );
                return;
              }
              if (!prerequisites || !qualification) return;
              void runAction(
                "customer-model",
                () =>
                  createCustomerFactoryModel(
                    engagementId,
                    buildCustomerFactoryModelInput(
                      prerequisites,
                      qualification,
                    ),
                  ),
                "A traceable Customer Factory Model draft was built. Review and approve it separately.",
              );
            }}
            title={
              synthetic
                ? "Approve the verified synthetic model."
                : "Build customer truth from qualified, reviewed sources."
            }
          />
        ) : (
          <div className="surface mt-5 grid gap-5 rounded-2xl p-5 lg:grid-cols-[1fr_auto] lg:items-center">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <StatusPill status={data.customer_model.status} />
                <span className="text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                  Model v{data.customer_model.version_number}
                </span>
              </div>
              <h3 className="display-font mt-3 text-2xl font-medium">
                {data.customer_model.organization.label}
              </h3>
              <p className="mt-2 text-xs leading-5 text-[var(--ink-soft)]">
                {data.customer_model.verified_claim_refs.length} verified claim
                refs · {data.customer_model.evidence_refs.length} source
                evidence refs · approved{" "}
                {formatTimestamp(data.customer_model.approved_at)}
              </p>
              <Digest value={data.customer_model.content_digest} />
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              {data.customer_model.status === "DRAFT" && (
                <PrimaryButton
                  busy={busy === "approve-customer-model"}
                  disabled={busy !== null || !actionsEnabled}
                  label="Approve customer model"
                  onClick={() =>
                    void runAction(
                      "approve-customer-model",
                      () =>
                        approveCustomerFactoryModel(
                          engagementId,
                          data.customer_model!.id,
                        ),
                      "The human operator approved the Customer Factory Model and its immutable provenance.",
                    )
                  }
                />
              )}
              {data.customer_model.status === "APPROVED" &&
                data.opportunities.length === 0 && (
                  <PrimaryButton
                    busy={busy === "assess-opportunity"}
                    disabled={busy !== null || !actionsEnabled}
                    label="Assess opportunity"
                    onClick={() => {
                      if (!synthetic) {
                        setComposer("opportunity");
                        return;
                      }
                      void runAction(
                        "assess-opportunity",
                        () => assessSyntheticFactoryOpportunity(engagementId),
                        "The candidate was scored with the published deterministic rubric.",
                      );
                    }}
                  />
                )}
            </div>
          </div>
        )}

        {!synthetic &&
          composer === "opportunity" &&
          data.customer_model?.status === "APPROVED" &&
          prerequisites && (
            <OpportunityComposer
              busy={busy === "assess-opportunity"}
              defaultDescription={prerequisites.primary_outcome}
              defaultName={`${prerequisites.workflow_name} improvement`}
              onCancel={() => setComposer(null)}
              onSubmit={(name, description, factors) =>
                void runAction(
                  "assess-opportunity",
                  () =>
                    createFactoryOpportunity(
                      engagementId,
                      buildFactoryOpportunityInput({
                        model: data.customer_model!,
                        prerequisites,
                        name,
                        description,
                        factors,
                      }),
                    ),
                  "The candidate was scored with the published deterministic rubric. Selection remains a separate human decision.",
                )
              }
            />
          )}

        {data.opportunities.length > 0 && (
          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            {data.opportunities.map((opportunity) => (
              <OpportunityCard
                busy={busy === `select-${opportunity.id}`}
                disabled={
                  busy !== null ||
                  !actionsEnabled ||
                  Boolean(selectedOpportunity)
                }
                key={opportunity.id}
                onSelect={(reason) =>
                  void runAction(
                    `select-${opportunity.id}`,
                    () =>
                      selectFactoryOpportunity(
                        engagementId,
                        opportunity.id,
                        reason ||
                          "Selected after reviewing value, verifiability, readiness, risk, and authority boundaries.",
                      ),
                    `${opportunity.name} was selected. Final readiness now binds this exact version.`,
                  )
                }
                opportunity={opportunity}
                requiresReason={!synthetic}
              />
            ))}
          </div>
        )}
      </section>

      <section className="mt-14 scroll-mt-6" id="fdlc-readiness">
        <HandoffHeading
          eyebrow="09 / Explainable gates"
          title="FDLC readiness"
          detail="Seven lifecycle stages show their evidence, blockers, risks, and next actions. A score never overrides a blocking criterion."
        />

        {!data.readiness ? (
          <ActionState
            button="Assess seven stages"
            detail="Final readiness requires the selected line, approved target workflow and economics, plus the complete implementation packet."
            disabled={
              busy !== null ||
              !actionsEnabled ||
              !selectedOpportunity ||
              (!synthetic &&
                (!prerequisites?.current_workflow_ref ||
                  !prerequisites.target_workflow_ref ||
                  prerequisites.implementation_artifact_refs.length === 0))
            }
            eyebrow="Readiness assessment"
            onClick={() => {
              if (!synthetic) {
                setComposer("readiness");
                return;
              }
              void runAction(
                "assess-readiness",
                () => assessSyntheticReadiness(engagementId),
                "All seven FDLC stages were evaluated with explicit synthetic bases.",
              );
            }}
            title="Explain why the line is—or is not—ready."
          />
        ) : (
          <div className="mt-5">
            <div className="surface flex flex-wrap items-center justify-between gap-4 rounded-2xl p-5">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill status={data.readiness.overall_status} />
                  <span className="text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                    Assessment v{data.readiness.version_number} ·{" "}
                    {data.readiness.status}
                  </span>
                </div>
                <p className="mt-3 text-xs leading-5 text-[var(--ink-soft)]">
                  Bound to selected opportunity version{" "}
                  {data.readiness.selected_opportunity_version}. Every stage
                  remains independently inspectable.
                </p>
              </div>
              {data.readiness.status === "DRAFT" && (
                <PrimaryButton
                  busy={busy === "approve-readiness"}
                  disabled={
                    busy !== null ||
                    !actionsEnabled ||
                    data.readiness.overall_status !== "READY"
                  }
                  label="Approve readiness"
                  onClick={() =>
                    void runAction(
                      "approve-readiness",
                      () => approveReadiness(engagementId, data.readiness!.id),
                      "Final READY assessment was approved by the human operator.",
                    )
                  }
                />
              )}
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {data.readiness.stages.map((stage) => (
                <ReadinessCard key={stage.stage} stage={stage} />
              ))}
            </div>
          </div>
        )}

        {!synthetic &&
          composer === "readiness" &&
          data.customer_model?.status === "APPROVED" &&
          selectedOpportunity &&
          prerequisites && (
            <ReadinessComposer
              busy={busy === "assess-readiness"}
              onCancel={() => setComposer(null)}
              onSubmit={(reviewedCriteria) =>
                void runAction(
                  "assess-readiness",
                  () =>
                    createReadinessAssessment(
                      engagementId,
                      buildReadinessAssessmentInput({
                        model: data.customer_model!,
                        opportunity: selectedOpportunity,
                        prerequisites,
                        reviewedCriteria,
                        owner:
                          qualification?.organization ??
                          "Design-partner operator",
                      }),
                    ),
                  "Every FDLC criterion was recorded from an explicit human confirmation. Approval remains separate.",
                )
              }
            />
          )}
      </section>

      <section className="mt-14 scroll-mt-6" id="deployment-package">
        <HandoffHeading
          eyebrow="10 / Approved deployment intent"
          title="Factory Deployment Package"
          detail="Review exact source versions, approved intent, authority, verification, economics, risks, and provenance before publishing immutable bytes."
        />

        {!currentPackage ? (
          <>
            <ActionState
              button="Generate package draft"
              detail="Only approved current sources and final READY assessment may enter the package. Raw customer evidence stays in Factory Engineer."
              disabled={
                busy !== null ||
                !actionsEnabled ||
                data.readiness?.status !== "APPROVED" ||
                (!synthetic &&
                  (!qualification ||
                    !qualifiedContext?.economics ||
                    qualifiedContext.artifacts.length === 0))
              }
              eyebrow="Package v1"
              onClick={() => {
                if (!synthetic) {
                  setComposer("package");
                  return;
                }
                void runAction(
                  "generate-package",
                  () => generateSyntheticDeploymentPackage(engagementId),
                  "A data-minimized package draft was generated from exact approved versions.",
                );
              }}
              title="Prepare a governed proposal—not an executable payload."
            />
            {!synthetic &&
              composer === "package" &&
              data.customer_model?.status === "APPROVED" &&
              selectedOpportunity &&
              data.readiness?.status === "APPROVED" &&
              prerequisites &&
              qualification &&
              qualifiedContext?.economics && (
                <PackageComposer
                  busy={busy === "generate-package"}
                  defaultObjective={prerequisites.primary_outcome}
                  defaultTitle={`${selectedOpportunity.name} deployment proposal`}
                  qualification={qualification}
                  onCancel={() => setComposer(null)}
                  onSubmit={(submission) =>
                    void runAction(
                      "generate-package",
                      () =>
                        createDeploymentPackage(
                          engagementId,
                          buildDeploymentPackageInput({
                            model: data.customer_model!,
                            opportunity: selectedOpportunity,
                            readiness: data.readiness!,
                            prerequisites,
                            qualification,
                            economics: qualifiedContext.economics!,
                            artifacts: qualifiedContext.artifacts,
                            ...submission,
                          }),
                        ),
                      "A data-minimized package draft was generated from exact approved versions. Human review, approval, and publication remain separate.",
                    )
                  }
                />
              )}
          </>
        ) : (
          <PackageReview
            actionsEnabled={
              currentPackage.status === "DRAFT"
                ? actionsEnabled
                : ownerActionsEnabled
            }
            busy={busy}
            deploymentPackage={currentPackage}
            onAction={(action) => {
              const actions = {
                review: () =>
                  submitDeploymentPackage(engagementId, currentPackage.id),
                approve: () =>
                  approveDeploymentPackage(
                    engagementId,
                    currentPackage.id,
                    synthetic || !data.customer_model
                      ? undefined
                      : customerModelAuthorityReference(data.customer_model),
                  ),
                publish: () =>
                  publishDeploymentPackage(engagementId, currentPackage.id),
              };
              const messages = {
                review: "The package entered human review.",
                approve:
                  "The operator approval was bound to the immutable package digest.",
                publish:
                  "The immutable package version was published for authenticated retrieval.",
              };
              void runAction(action, actions[action], messages[action]);
            }}
          />
        )}
      </section>

      <section className="mt-14 scroll-mt-6" id="mission-control-handoff">
        <HandoffHeading
          eyebrow="11 / Governed downstream boundary"
          title="Mission Control import"
          detail="A separate Mission Control action must authenticate, verify, resolve local authority, and return a real import receipt before any Mission or Plan draft is claimed."
        />
        <div className="mt-5 overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--ink)] text-white">
          <div className="grid gap-6 p-6 lg:grid-cols-[1fr_auto] lg:items-center lg:p-8">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-white/10 px-2.5 py-1 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-white/75">
                  {currentPackage?.status === "PUBLISHED"
                    ? "Retrieval ready"
                    : "Waiting for publish"}
                </span>
                <span className="text-[0.64rem] font-bold text-white/55">
                  Authenticated retrieval · draft authority only
                </span>
              </div>
              <h3 className="display-font mt-4 text-3xl font-medium">
                Factory Engineer proposes. Mission Control governs.
              </h3>
              <p className="mt-3 max-w-3xl text-xs leading-5 text-white/60">
                No WorkOrder, Attempt, approval, verification, merge, release,
                or deployment state crosses back as source truth.{" "}
                {synthetic
                  ? "The hosted action below is a clearly labeled browser-local simulation."
                  : "Opening the importer is an explicit human action; Mission Control still validates scope, provenance, digest, and local authority before creating an unapproved draft."}
              </p>
              {currentPackage && (
                <dl className="mt-5 grid gap-3 text-xs sm:grid-cols-2">
                  <DarkField
                    label="Package"
                    value={`v${currentPackage.package_version} · ${currentPackage.package_id}`}
                  />
                  <DarkField
                    label="Target"
                    value={currentPackage.target.repository_ref}
                  />
                  <DarkField
                    label="Code scope"
                    value={currentPackage.target.requested_code_scopes.join(
                      ", ",
                    )}
                  />
                  <DarkField
                    label="Workflow requirement"
                    value={
                      currentPackage.target.semantic_execution_workflow_ref
                    }
                  />
                </dl>
              )}
            </div>
            {synthetic && !data.latest_retrieval ? (
              <button
                className="rounded-full bg-white px-5 py-3 text-xs font-extrabold text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-35"
                disabled={
                  busy !== null ||
                  !synthetic ||
                  currentPackage?.status !== "PUBLISHED"
                }
                onClick={() =>
                  currentPackage &&
                  void runAction(
                    "simulate-retrieval",
                    () =>
                      simulateMissionControlRetrieval(
                        engagementId,
                        currentPackage.id,
                      ),
                    "Package retrieval was simulated locally. No network request was made and no Mission or Plan draft was created.",
                  )
                }
                type="button"
              >
                {busy === "simulate-retrieval"
                  ? "Simulating…"
                  : "Simulate safe retrieval"}
              </button>
            ) : synthetic && data.latest_retrieval ? (
              <div className="min-w-64 rounded-2xl border border-white/10 bg-white/5 p-5">
                <p className="flex items-center gap-2 text-xs font-extrabold text-[#9ed5cc]">
                  <CheckIcon className="h-4 w-4" /> Package retrieval simulated
                </p>
                <p className="mt-3 text-[0.68rem] leading-5 text-white/55">
                  {data.latest_retrieval.requester_system} ·{" "}
                  {formatTimestamp(data.latest_retrieval.created_at)}
                </p>
                <p className="mt-2 text-[0.68rem] leading-5 text-white/55">
                  Retrieval is not an import receipt. No Mission or Plan draft
                  was created.
                </p>
                <p className="mt-2 break-all font-mono text-[0.58rem] text-white/55">
                  Correlation {data.latest_retrieval.correlation_id}
                </p>
              </div>
            ) : governedDraftUrl ? (
              <a
                className="inline-flex items-center justify-center rounded-full bg-white px-5 py-3 text-xs font-extrabold text-[var(--ink)] no-underline"
                href={governedDraftUrl}
                rel="noreferrer"
                target="_blank"
              >
                Open governed draft import
                <span aria-hidden="true">&nbsp;↗</span>
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : (
              <div className="max-w-72 rounded-2xl border border-white/10 bg-white/5 p-5 text-xs font-bold leading-5 text-white/60">
                {currentPackage?.status === "PUBLISHED"
                  ? "Mission Control handoff is blocked until its reviewed HTTPS origin is configured."
                  : "Publish an approved immutable package before opening Mission Control."}
              </div>
            )}
          </div>
          <div className="border-t border-white/10 px-6 py-4 text-[0.64rem] font-bold text-white/55 lg:px-8">
            {synthetic
              ? "Synthetic demo: zero API requests · retrieval only · no Mission Control import receipt"
              : "Real handoff: no secret in the browser link · scoped retrieval credential held by Mission Control · import remains pending until Mission Control returns an authenticated Mission/Plan draft receipt"}
          </div>
        </div>
      </section>
    </>
  );
}

function QualifiedActionBoundary({
  qualification,
  partnerRole,
  ready,
}: {
  qualification: DesignPartnerQualification | null;
  partnerRole: "owner" | "operator" | "viewer" | undefined;
  ready: boolean;
}) {
  return (
    <section
      className={`mt-8 rounded-2xl border p-5 ${
        ready
          ? "border-[var(--teal)]/25 bg-[var(--teal-soft)]"
          : "border-[var(--amber)]/25 bg-[var(--amber-soft)]"
      }`}
      aria-label="Design-partner authority boundary"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[0.62rem] font-extrabold uppercase tracking-[0.11em] text-[var(--ink-soft)]">
            Qualified customer path
          </p>
          <p className="mt-2 text-sm font-extrabold">
            {ready
              ? `${qualification?.organization} is qualified for controlled handoff work.`
              : "Customer-data actions remain locked."}
          </p>
        </div>
        <StatusPill
          status={
            ready
              ? "QUALIFIED"
              : (qualification?.status ??
                qualification?.qualification_state ??
                "NOT CONFIGURED")
          }
        />
      </div>
      <p className="mt-3 max-w-4xl text-xs leading-5 text-[var(--ink-soft)]">
        {ready
          ? `Your qualification role is ${partnerRole ?? "not authorized"}. Operators may prepare and review drafts; package approval and publication require the engagement owner. Nothing here approves a Mission Control plan, dispatches work, merges, releases, promotes, or deploys.`
          : qualification
            ? `Qualification is ${qualification.status.toLowerCase()} and ${qualification.qualification_state.toLowerCase().replaceAll("_", " ")}. An owner must restore an active, qualified boundary before operators can proceed.`
            : "An owner must provision and qualify this design-partner engagement before customer-derived models or packages can be created."}
      </p>
    </section>
  );
}

function OpportunityComposer({
  busy,
  defaultName,
  defaultDescription,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  defaultName: string;
  defaultDescription: string;
  onCancel: () => void;
  onSubmit: (
    name: string,
    description: string,
    factors: FactoryOpportunityFactors,
  ) => void;
}) {
  const [name, setName] = useState(defaultName);
  const [description, setDescription] = useState(defaultDescription);
  const [factors, setFactors] = useState<FactoryOpportunityFactors>({
    ...DEFAULT_OPPORTUNITY_FACTORS,
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !description.trim()) return;
    onSubmit(name, description, factors);
  }

  return (
    <form
      className="surface mt-5 rounded-2xl p-6"
      aria-label="Assess a factory opportunity"
      onSubmit={submit}
    >
      <div className="grid gap-5 lg:grid-cols-2">
        <label className="text-xs font-extrabold">
          Candidate line name
          <input
            className="mt-2 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-sm font-medium"
            maxLength={512}
            minLength={3}
            onChange={(event) => setName(event.target.value)}
            required
            value={name}
          />
        </label>
        <label className="text-xs font-extrabold">
          Bounded outcome
          <textarea
            className="mt-2 min-h-24 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-sm font-medium"
            maxLength={4000}
            minLength={5}
            onChange={(event) => setDescription(event.target.value)}
            required
            value={description}
          />
        </label>
      </div>
      <fieldset className="mt-6">
        <legend className="text-xs font-extrabold">
          Deterministic rubric factors · 0–5
        </legend>
        <p className="mt-2 text-[0.68rem] leading-5 text-[var(--ink-soft)]">
          These inputs produce an explainable score. They do not select the
          line.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(Object.keys(factors) as Array<keyof FactoryOpportunityFactors>).map(
            (key) => (
              <label
                className="flex items-center justify-between gap-3 rounded-xl border border-[var(--line)] px-3 py-2"
                key={key}
              >
                <span className="text-[0.68rem] font-bold">
                  {humanize(key)}
                </span>
                <input
                  aria-label={`${humanize(key)} score`}
                  className="w-16 rounded-lg border border-[var(--line-strong)] bg-white px-2 py-1.5 text-center text-xs font-extrabold"
                  max={5}
                  min={0}
                  onChange={(event) =>
                    setFactors((current) => ({
                      ...current,
                      [key]: Number(event.target.value),
                    }))
                  }
                  required
                  type="number"
                  value={factors[key]}
                />
              </label>
            ),
          )}
        </div>
      </fieldset>
      <ComposerActions
        busy={busy}
        onCancel={onCancel}
        submitLabel="Record assessment"
      />
    </form>
  );
}

function ReadinessComposer({
  busy,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (reviewedCriteria: ReadonlySet<string>) => void;
}) {
  const [reviewedCriteria, setReviewedCriteria] = useState<Set<string>>(
    new Set(),
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reviewedCriteria.size !== READINESS_CRITERION_COUNT) return;
    onSubmit(reviewedCriteria);
  }

  return (
    <form
      className="surface mt-5 rounded-2xl p-6"
      aria-label="Review FDLC readiness"
      onSubmit={submit}
    >
      <h3 className="display-font text-2xl font-medium">
        Confirm every criterion against its immutable basis
      </h3>
      <p className="mt-2 max-w-3xl text-xs leading-5 text-[var(--ink-soft)]">
        This records a DRAFT readiness assessment. A separate approval is still
        required, and no downstream execution authority is granted.
      </p>
      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {READINESS_STAGES.map((stage) => {
          return (
            <fieldset
              className="rounded-xl border border-[var(--line)] bg-white p-4"
              key={stage}
            >
              <legend className="px-1 text-xs font-extrabold">
                {humanize(stage)}
              </legend>
              <div className="mt-2 grid gap-2.5">
                {READINESS_CRITERIA[stage].map((criterion) => {
                  const reviewKey = readinessCriterionReviewKey(
                    stage,
                    criterion,
                  );
                  const checked = reviewedCriteria.has(reviewKey);
                  return (
                    <label
                      className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 text-[0.66rem] font-bold leading-4 ${
                        checked
                          ? "border-[var(--teal)]/35 bg-[var(--teal-soft)]"
                          : "border-[var(--line)] bg-[var(--canvas)]"
                      }`}
                      key={criterion}
                    >
                      <input
                        aria-label={`Confirm ${humanize(stage)} criterion: ${humanize(criterion)}`}
                        checked={checked}
                        className="mt-0.5"
                        onChange={(event) =>
                          setReviewedCriteria((current) => {
                            const next = new Set(current);
                            if (event.target.checked) next.add(reviewKey);
                            else next.delete(reviewKey);
                            return next;
                          })
                        }
                        type="checkbox"
                      />
                      <span>{humanize(criterion)}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          );
        })}
      </div>
      <ComposerActions
        busy={busy}
        disabled={reviewedCriteria.size !== READINESS_CRITERION_COUNT}
        onCancel={onCancel}
        submitLabel={`Record readiness draft (${reviewedCriteria.size}/${READINESS_CRITERION_COUNT} criteria)`}
      />
    </form>
  );
}

type PackageComposerSubmission = {
  repositoryRef: string;
  workflowClass: string;
  requestedCodeScopes: string[];
  missionTitle: string;
  objective: string;
};

function PackageComposer({
  busy,
  defaultTitle,
  defaultObjective,
  qualification,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  defaultTitle: string;
  defaultObjective: string;
  qualification: DesignPartnerQualification;
  onCancel: () => void;
  onSubmit: (submission: PackageComposerSubmission) => void;
}) {
  const [repositoryRef, setRepositoryRef] = useState(
    qualification.authorized_repository_refs[0] ?? "",
  );
  const [workflowClass, setWorkflowClass] = useState(
    qualification.allowed_workflow_classes[0] ?? "",
  );
  const [scopeText, setScopeText] = useState("");
  const [missionTitle, setMissionTitle] = useState(defaultTitle);
  const [objective, setObjective] = useState(defaultObjective);
  const [validationError, setValidationError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const requestedCodeScopes = parseBoundedCodeScopes(scopeText);
      setValidationError(null);
      onSubmit({
        repositoryRef,
        workflowClass,
        requestedCodeScopes,
        missionTitle,
        objective,
      });
    } catch (reason) {
      setValidationError(
        reason instanceof Error ? reason.message : "The code scope is invalid.",
      );
    }
  }

  return (
    <form
      className="surface mt-5 rounded-2xl p-6"
      aria-label="Prepare a deployment package draft"
      onSubmit={submit}
    >
      <h3 className="display-font text-2xl font-medium">
        Bound the proposal before it enters review
      </h3>
      <p className="mt-2 max-w-3xl text-xs leading-5 text-[var(--ink-soft)]">
        Repository and workflow choices come only from the active qualification.
        The workspace reference is server-derived; this form never accepts a
        credential, retrieval token, or arbitrary destination URL.
      </p>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <label className="text-xs font-extrabold">
          Authorized repository
          <select
            className="mt-2 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-sm"
            onChange={(event) => setRepositoryRef(event.target.value)}
            required
            value={repositoryRef}
          >
            {qualification.authorized_repository_refs.map((repository) => (
              <option key={repository} value={repository}>
                {repository}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-extrabold">
          Authorized workflow class
          <select
            className="mt-2 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-sm"
            onChange={(event) => setWorkflowClass(event.target.value)}
            required
            value={workflowClass}
          >
            {qualification.allowed_workflow_classes.map((workflow) => (
              <option key={workflow} value={workflow}>
                {workflow}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-extrabold lg:col-span-2">
          Bounded code scopes · one relative path or glob per line
          <textarea
            className="mt-2 min-h-24 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 font-mono text-xs"
            maxLength={8000}
            onChange={(event) => setScopeText(event.target.value)}
            placeholder="apps/web/components/qualified-flow/**"
            required
            value={scopeText}
          />
        </label>
        <label className="text-xs font-extrabold">
          Mission draft title
          <input
            className="mt-2 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-sm"
            maxLength={512}
            minLength={3}
            onChange={(event) => setMissionTitle(event.target.value)}
            required
            value={missionTitle}
          />
        </label>
        <label className="text-xs font-extrabold">
          Objective
          <textarea
            className="mt-2 min-h-24 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-sm"
            maxLength={4000}
            minLength={5}
            onChange={(event) => setObjective(event.target.value)}
            required
            value={objective}
          />
        </label>
      </div>
      {validationError && (
        <p className="mt-4 text-xs font-bold text-[var(--red)]" role="alert">
          {validationError}
        </p>
      )}
      <ComposerActions
        busy={busy}
        disabled={!repositoryRef || !workflowClass}
        onCancel={onCancel}
        submitLabel="Create package draft"
      />
    </form>
  );
}

function ComposerActions({
  busy,
  disabled = false,
  onCancel,
  submitLabel,
}: {
  busy: boolean;
  disabled?: boolean;
  onCancel: () => void;
  submitLabel: string;
}) {
  return (
    <div className="mt-6 flex flex-wrap justify-end gap-2">
      <button
        className="rounded-full border border-[var(--line-strong)] bg-white px-5 py-3 text-xs font-extrabold disabled:opacity-40"
        disabled={busy}
        onClick={onCancel}
        type="button"
      >
        Cancel
      </button>
      <button
        className="rounded-full bg-[var(--ink)] px-5 py-3 text-xs font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-40"
        disabled={busy || disabled}
        type="submit"
      >
        {busy ? "Working…" : submitLabel}
      </button>
    </div>
  );
}

function parseBoundedCodeScopes(value: string): string[] {
  const scopes = Array.from(
    new Set(
      value
        .split("\n")
        .map((scope) => scope.trim())
        .filter(Boolean),
    ),
  );
  if (scopes.length === 0 || scopes.length > 50) {
    throw new Error("Record between 1 and 50 bounded code scopes.");
  }
  if (
    scopes.some(
      (scope) =>
        scope.length > 1024 ||
        scope.startsWith("/") ||
        scope.includes("..") ||
        scope.includes("://") ||
        scope.includes("\\") ||
        /[\r\n\0]/u.test(scope),
    )
  ) {
    throw new Error(
      "Use relative repository paths or globs only; URLs, parent traversal, and absolute paths are not allowed.",
    );
  }
  return scopes;
}

function HandoffHeading({
  eyebrow,
  title,
  detail,
}: {
  eyebrow: string;
  title: string;
  detail: string;
}) {
  return (
    <div className="grid gap-3 border-t border-[var(--line-strong)] pt-5 lg:grid-cols-[0.75fr_1fr] lg:items-end">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="display-font mt-2 text-3xl font-medium tracking-[-0.025em] md:text-4xl">
          {title}
        </h2>
      </div>
      <p className="max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">
        {detail}
      </p>
    </div>
  );
}

function ActionState({
  eyebrow,
  title,
  detail,
  button,
  disabled,
  onClick,
}: {
  eyebrow: string;
  title: string;
  detail: string;
  button: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <div className="surface mt-5 grid gap-5 rounded-2xl p-6 lg:grid-cols-[1fr_auto] lg:items-center">
      <div>
        <p className="text-[0.64rem] font-extrabold uppercase tracking-[0.12em] text-[var(--teal)]">
          {eyebrow}
        </p>
        <h3 className="display-font mt-2 text-2xl font-medium">{title}</h3>
        <p className="mt-2 max-w-3xl text-xs leading-5 text-[var(--ink-soft)]">
          {detail}
        </p>
      </div>
      <PrimaryButton disabled={disabled} label={button} onClick={onClick} />
    </div>
  );
}

function PrimaryButton({
  label,
  disabled,
  busy = false,
  onClick,
}: {
  label: string;
  disabled: boolean;
  busy?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className="rounded-full bg-[var(--ink)] px-5 py-3 text-xs font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-40"
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      {busy ? "Working…" : label}
    </button>
  );
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-[0.6rem] font-extrabold uppercase tracking-[0.09em] ${statusTone(status)}`}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}

function Digest({ value }: { value: string | null }) {
  if (!value) return null;
  return (
    <p className="mt-3 break-all font-mono text-[0.62rem] leading-5 text-[var(--ink-soft)]">
      {value}
    </p>
  );
}

function OpportunityCard({
  opportunity,
  busy,
  disabled,
  requiresReason,
  onSelect,
}: {
  opportunity: FactoryOpportunity;
  busy: boolean;
  disabled: boolean;
  requiresReason: boolean;
  onSelect: (reason: string) => void;
}) {
  const [selectionReason, setSelectionReason] = useState("");
  const scores = [
    ["Value", opportunity.value_score],
    ["Verify", opportunity.verifiability_score],
    ["Ready", opportunity.readiness_score],
    ["Risk", opportunity.risk_score],
    ["Priority", opportunity.priority_score],
  ] as const;
  return (
    <article className="surface overflow-hidden rounded-2xl">
      <div className="border-b border-[var(--line)] p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <StatusPill status={opportunity.status} />
          <span className="text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
            {opportunity.rubric_version}
          </span>
        </div>
        <h3 className="display-font mt-4 text-3xl font-medium">
          {opportunity.name}
        </h3>
        <p className="mt-3 text-xs leading-5 text-[var(--ink-soft)]">
          {opportunity.description}
        </p>
      </div>
      <div className="grid grid-cols-5 divide-x divide-[var(--line)] border-b border-[var(--line)]">
        {scores.map(([label, score]) => (
          <div className="px-2 py-4 text-center" key={label}>
            <p className="display-font text-xl font-medium">{score}</p>
            <p className="mt-1 text-[0.54rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
              {label}
            </p>
          </div>
        ))}
      </div>
      <div className="p-5">
        <p className="text-xs font-extrabold">{opportunity.recommendation}</p>
        <ul className="mt-3 grid gap-2 text-[0.68rem] leading-5 text-[var(--ink-soft)]">
          {opportunity.rationale.slice(0, 3).map((reason) => (
            <li className="flex gap-2" key={reason}>
              <span aria-hidden="true" className="text-[var(--teal)]">
                —
              </span>
              {reason}
            </li>
          ))}
        </ul>
        {opportunity.status === "SELECTED" ? (
          <p className="mt-5 rounded-xl bg-[var(--teal-soft)] px-4 py-3 text-xs font-bold text-[var(--teal)]">
            Human-selected · {opportunity.selection_reason}
          </p>
        ) : (
          <div className="mt-5">
            {requiresReason && (
              <label className="mb-3 block text-xs font-extrabold">
                Selection rationale
                <textarea
                  aria-label={`Selection rationale for ${opportunity.name}`}
                  className="mt-2 min-h-20 w-full rounded-xl border border-[var(--line-strong)] bg-white px-3 py-2.5 text-xs font-medium"
                  maxLength={4000}
                  minLength={5}
                  onChange={(event) => setSelectionReason(event.target.value)}
                  placeholder="Why this line should advance after reviewing value, evidence, risk, and authority."
                  required
                  value={selectionReason}
                />
              </label>
            )}
            <PrimaryButton
              busy={busy}
              disabled={
                disabled ||
                (requiresReason && selectionReason.trim().length < 5)
              }
              label="Select factory line"
              onClick={() => onSelect(selectionReason.trim())}
            />
          </div>
        )}
      </div>
    </article>
  );
}

function ReadinessCard({ stage }: { stage: FDLCReadinessStage }) {
  return (
    <article className="surface rounded-2xl p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
            {stage.stage}
          </p>
          <p className="display-font mt-2 text-3xl font-medium">
            {stage.score}
          </p>
        </div>
        <StatusPill status={stage.status} />
      </div>
      <p className="mt-4 text-[0.68rem] leading-5 text-[var(--ink-soft)]">
        {stage.explanation}
      </p>
      {stage.blockers.length > 0 && (
        <ul className="mt-3 text-[0.66rem] leading-5 text-[var(--red)]">
          {stage.blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[0.6rem] font-bold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
        {stage.evidence_refs.length} basis ref · {stage.next_actions.length}{" "}
        next actions
      </p>
    </article>
  );
}

function PackageReview({
  deploymentPackage,
  busy,
  actionsEnabled,
  onAction,
}: {
  deploymentPackage: DeploymentPackage;
  busy: string | null;
  actionsEnabled: boolean;
  onAction: (action: "review" | "approve" | "publish") => void;
}) {
  const nextAction = useMemo(() => {
    if (deploymentPackage.status === "DRAFT")
      return { key: "review" as const, label: "Send to review" };
    if (deploymentPackage.status === "READY_FOR_REVIEW")
      return { key: "approve" as const, label: "Approve & bind digest" };
    if (deploymentPackage.status === "APPROVED")
      return { key: "publish" as const, label: "Publish immutable v1" };
    return null;
  }, [deploymentPackage.status]);

  return (
    <article className="surface mt-5 overflow-hidden rounded-2xl">
      <div className="grid gap-6 border-b border-[var(--line)] p-6 lg:grid-cols-[1fr_auto] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={deploymentPackage.status} />
            <span className="text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
              Package v{deploymentPackage.package_version} ·{" "}
              {deploymentPackage.schema_version}
            </span>
          </div>
          <h3 className="display-font mt-4 text-3xl font-medium">
            {deploymentPackage.deployment_intent.mission_title}
          </h3>
          <p className="mt-3 max-w-4xl text-xs leading-5 text-[var(--ink-soft)]">
            {deploymentPackage.deployment_intent.plan_summary}
          </p>
          <p className="mt-3 max-w-4xl text-xs font-bold leading-5">
            Objective: {deploymentPackage.deployment_intent.objective}
          </p>
          {deploymentPackage.digest ? (
            <Digest value={deploymentPackage.digest} />
          ) : (
            <p className="mt-3 text-[0.62rem] font-bold text-[var(--ink-soft)]">
              Digest pending · created from the approved immutable projection
            </p>
          )}
        </div>
        {nextAction && (
          <PrimaryButton
            busy={busy === nextAction.key}
            disabled={busy !== null || !actionsEnabled}
            label={nextAction.label}
            onClick={() => onAction(nextAction.key)}
          />
        )}
      </div>
      <div className="grid divide-y divide-[var(--line)] lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        <PackageColumn title="Exact source versions">
          <CompactField
            label="Customer model"
            value={`v${deploymentPackage.source.customer_factory_model.version}`}
          />
          <CompactField
            label="Current workflow"
            value={`v${deploymentPackage.source.current_workflow.version}`}
          />
          <CompactField
            label="Target workflow"
            value={`v${deploymentPackage.source.target_workflow.version}`}
          />
          <CompactField
            label="Readiness"
            value={`v${deploymentPackage.source.readiness_assessment.version}`}
          />
          <CompactField
            label="Selected line"
            value={`v${deploymentPackage.source.factory_opportunity.version}`}
          />
        </PackageColumn>
        <PackageColumn title="Authority & verification">
          {deploymentPackage.deployment_intent.authority_boundaries.map(
            (boundary) => (
              <CompactField
                key={boundary.key}
                label={boundary.subject}
                value={boundary.maximum_authority}
              />
            ),
          )}
          {deploymentPackage.deployment_intent.verification_contract.map(
            (requirement) => (
              <CompactField
                key={requirement.key}
                label={requirement.independent ? "Independent" : "Verification"}
                value={requirement.statement}
              />
            ),
          )}
        </PackageColumn>
        <PackageColumn title="Acceptance, risk & provenance">
          <CompactField
            label="Factory design"
            value={deploymentPackage.deployment_intent.intent}
          />
          {deploymentPackage.deployment_intent.acceptance_criteria.map(
            (criterion) => (
              <CompactField
                key={criterion.key}
                label={criterion.verification_method}
                value={criterion.statement}
              />
            ),
          )}
          <CompactField
            label="Risk"
            value={
              deploymentPackage.deployment_intent.risk_summary[0]?.statement ??
              "No risk statement"
            }
          />
          <CompactField
            label="Provenance"
            value={`${deploymentPackage.deployment_intent.provenance.length} immutable refs`}
          />
        </PackageColumn>
      </div>
      <dl className="grid gap-4 border-t border-[var(--line)] bg-[var(--canvas)] px-6 py-5 text-xs md:grid-cols-3">
        <CompactField
          label="Issuer"
          value={`${deploymentPackage.issuer.issuer_id} · ${deploymentPackage.issuer.environment}`}
        />
        <CompactField
          label="Repository target"
          value={deploymentPackage.target.repository_ref}
        />
        <CompactField
          label="Economics"
          value={`${Object.keys(deploymentPackage.deployment_intent.economics_baseline).length} labeled outputs`}
        />
      </dl>
    </article>
  );
}

function PackageColumn({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="p-6">
      <p className="mb-4 text-[0.62rem] font-extrabold uppercase tracking-[0.11em] text-[var(--ink-soft)]">
        {title}
      </p>
      <dl className="grid gap-4">{children}</dl>
    </div>
  );
}

function CompactField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.58rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
        {label}
      </dt>
      <dd className="mt-1 text-[0.68rem] font-bold leading-5">{value}</dd>
    </div>
  );
}

function DarkField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[0.56rem] font-extrabold uppercase tracking-[0.09em] text-white/55">
        {label}
      </dt>
      <dd className="mt-1 break-all font-mono text-[0.64rem] leading-5 text-white/70">
        {value}
      </dd>
    </div>
  );
}
