"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { CheckIcon } from "@/components/icons";
import {
  approveDeploymentPackage,
  approveReadiness,
  approveSyntheticCustomerModel,
  assessSyntheticFactoryOpportunity,
  assessSyntheticReadiness,
  generateSyntheticDeploymentPackage,
  getFactoryHandoffWorkspace,
  publishDeploymentPackage,
  selectFactoryOpportunity,
  simulateMissionControlRetrieval,
  submitDeploymentPackage,
} from "@/lib/api";
import type {
  DeploymentPackage,
  FactoryHandoffWorkspace as FactoryHandoffState,
  FactoryOpportunity,
  FDLCReadinessStage,
} from "@/lib/types";

type Progress = {
  customerModel: boolean;
  opportunity: boolean;
  readiness: boolean;
  package: boolean;
  handoff: boolean;
};

type Notice = { tone: "success" | "error"; text: string } | null;

const EMPTY_PROGRESS: Progress = {
  customerModel: false,
  opportunity: false,
  readiness: false,
  package: false,
  handoff: false,
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

export function FactoryHandoffWorkspace({
  engagementId,
  lifecycleVersion,
  synthetic,
  onProgress,
}: {
  engagementId: string;
  lifecycleVersion: string;
  synthetic: boolean;
  onProgress: (progress: Progress) => void;
}) {
  const [data, setData] = useState<FactoryHandoffState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const load = useCallback(async () => {
    const next = await getFactoryHandoffWorkspace(engagementId);
    setData(next);
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
      handoff: next.latest_retrieval?.result === "RETRIEVED",
    });
  }, [engagementId, onProgress]);

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

      <section className="mt-14 scroll-mt-6" id="factory-opportunities">
        <HandoffHeading
          eyebrow="08 / Customer truth to candidate line"
          title="Factory opportunity portfolio"
          detail="Freeze the verified customer model, compare one explainable candidate for this workflow, and record the human selection before final readiness."
        />

        {!data.customer_model ? (
          <ActionState
            button="Approve customer model v1"
            detail="The version is built only from reviewed claims, approved workflow state, exact evidence references, and labeled assumptions."
            disabled={busy !== null || !synthetic}
            eyebrow="Customer Factory Model"
            onClick={() =>
              void runAction(
                "customer-model",
                () => approveSyntheticCustomerModel(engagementId),
                "Customer Factory Model v1 was approved with immutable provenance.",
              )
            }
            title={
              synthetic
                ? "Approve the verified synthetic model."
                : "Submit a traceable Customer Factory Model through the API."
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
            {data.opportunities.length === 0 && (
              <PrimaryButton
                busy={busy === "assess-opportunity"}
                disabled={busy !== null || !synthetic}
                label="Assess opportunity"
                onClick={() =>
                  void runAction(
                    "assess-opportunity",
                    () => assessSyntheticFactoryOpportunity(engagementId),
                    "The candidate was scored with the published deterministic rubric.",
                  )
                }
              />
            )}
          </div>
        )}

        {data.opportunities.length > 0 && (
          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            {data.opportunities.map((opportunity) => (
              <OpportunityCard
                busy={busy === `select-${opportunity.id}`}
                disabled={
                  busy !== null || !synthetic || Boolean(selectedOpportunity)
                }
                key={opportunity.id}
                onSelect={() =>
                  void runAction(
                    `select-${opportunity.id}`,
                    () =>
                      selectFactoryOpportunity(
                        engagementId,
                        opportunity.id,
                        "Selected after reviewing value, verifiability, readiness, risk, and authority boundaries.",
                      ),
                    `${opportunity.name} was selected. Final readiness now binds this exact version.`,
                  )
                }
                opportunity={opportunity}
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
            disabled={busy !== null || !synthetic || !selectedOpportunity}
            eyebrow="Readiness assessment"
            onClick={() =>
              void runAction(
                "assess-readiness",
                () => assessSyntheticReadiness(engagementId),
                "All seven FDLC stages were evaluated with explicit synthetic bases.",
              )
            }
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
                  disabled={busy !== null || !synthetic}
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
      </section>

      <section className="mt-14 scroll-mt-6" id="deployment-package">
        <HandoffHeading
          eyebrow="10 / Approved deployment intent"
          title="Factory Deployment Package"
          detail="Review exact source versions, approved intent, authority, verification, economics, risks, and provenance before publishing immutable bytes."
        />

        {!currentPackage ? (
          <ActionState
            button="Generate package draft"
            detail="Only approved current sources and final READY assessment may enter the package. Raw customer evidence stays in Factory Engineer."
            disabled={
              busy !== null ||
              !synthetic ||
              data.readiness?.status !== "APPROVED"
            }
            eyebrow="Package v1"
            onClick={() =>
              void runAction(
                "generate-package",
                () => generateSyntheticDeploymentPackage(engagementId),
                "A data-minimized package draft was generated from exact approved versions.",
              )
            }
            title="Prepare a governed proposal—not an executable payload."
          />
        ) : (
          <PackageReview
            busy={busy}
            deploymentPackage={currentPackage}
            onAction={(action) => {
              const actions = {
                review: () =>
                  submitDeploymentPackage(engagementId, currentPackage.id),
                approve: () =>
                  approveDeploymentPackage(engagementId, currentPackage.id),
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
            synthetic={synthetic}
          />
        )}
      </section>

      <section className="mt-14 scroll-mt-6" id="mission-control-handoff">
        <HandoffHeading
          eyebrow="11 / Governed downstream boundary"
          title="Mission Control handoff"
          detail="Mission Control independently authenticates, verifies, resolves local authority, and creates only Mission and Plan drafts."
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
                or deployment state crosses back as source truth. The hosted
                action below is a clearly labeled browser-local simulation.
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
            {!data.latest_retrieval ? (
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
                    "Mission Control retrieval and governed Plan-draft preview were simulated locally. No network request was made.",
                  )
                }
                type="button"
              >
                {busy === "simulate-retrieval"
                  ? "Simulating…"
                  : "Simulate safe retrieval"}
              </button>
            ) : (
              <div className="min-w-64 rounded-2xl border border-white/10 bg-white/5 p-5">
                <p className="flex items-center gap-2 text-xs font-extrabold text-[#9ed5cc]">
                  <CheckIcon className="h-4 w-4" /> Governed draft preview ready
                </p>
                <p className="mt-3 text-[0.68rem] leading-5 text-white/55">
                  {data.latest_retrieval.requester_system} ·{" "}
                  {formatTimestamp(data.latest_retrieval.created_at)}
                </p>
                <p className="mt-2 break-all font-mono text-[0.58rem] text-white/55">
                  Correlation {data.latest_retrieval.correlation_id}
                </p>
              </div>
            )}
          </div>
          <div className="border-t border-white/10 px-6 py-4 text-[0.64rem] font-bold text-white/55 lg:px-8">
            Synthetic demo: zero API requests · Real adapter: preconfigured
            HTTPS origin, scoped secret, issuer/digest/status validation,
            explicit operator confirmation
          </div>
        </div>
      </section>
    </>
  );
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
  onSelect,
}: {
  opportunity: FactoryOpportunity;
  busy: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
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
          <PrimaryButton
            busy={busy}
            disabled={disabled}
            label="Select factory line"
            onClick={onSelect}
          />
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
  synthetic,
  onAction,
}: {
  deploymentPackage: DeploymentPackage;
  busy: string | null;
  synthetic: boolean;
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
            disabled={busy !== null || !synthetic}
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
