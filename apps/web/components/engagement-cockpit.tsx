"use client";

import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";

import { AuthenticationRequired } from "@/components/authentication-required";
import { Brand } from "@/components/brand";
import { EcosystemLinks } from "@/components/ecosystem-links";
import { DataLifecycleWorkspace } from "@/components/data-lifecycle-workspace";
import { DeliveryEvaluationWorkspace } from "@/components/delivery-evaluation-workspace";
import {
  CheckIcon,
  FileIcon,
  ShieldIcon,
  UploadIcon,
} from "@/components/icons";
import { LifecycleWorkspace } from "@/components/lifecycle-workspace";
import {
  ApiError,
  createOperatorNote,
  getAuthenticatedOperator,
  getOperatingModel,
  getWorkspace,
  hostedDemoEnabled,
  listClaims,
  listContradictions,
  listEvidence,
  resolveContradiction,
  reviewClaim,
  uploadEvidence,
} from "@/lib/api";
import type { AuthenticatedOperator } from "@/lib/api";
import type {
  Claim,
  Contradiction,
  EngagementWorkspace,
  EngagementDeletionReceipt,
  Evidence,
  OperatingModel,
} from "@/lib/types";
import { GUIDE_LINKS, guideHref } from "@/lib/product";

type WorkspaceData = {
  operator: AuthenticatedOperator;
  workspace: EngagementWorkspace;
  evidence: Evidence[];
  claims: Claim[];
  contradictions: Contradiction[];
  operatingModel: OperatingModel;
};

type Notice = { tone: "success" | "error"; text: string } | null;

const stages = [
  {
    id: "evidence",
    number: "01",
    label: "Source evidence",
    detail: "Ingest & preserve",
  },
  {
    id: "review",
    number: "02",
    label: "Claim review",
    detail: "Human authority",
  },
  {
    id: "model",
    number: "03",
    label: "Verified model",
    detail: "Canonical state",
  },
  {
    id: "current-workflow",
    number: "04",
    label: "Current workflow",
    detail: "Approved reality",
  },
  {
    id: "target-workflow",
    number: "05",
    label: "Target workflow",
    detail: "Reviewed allocation",
  },
  {
    id: "economics",
    number: "06",
    label: "Economics",
    detail: "Deterministic case",
  },
  {
    id: "specification",
    number: "07",
    label: "Specification",
    detail: "Engineering handoff",
  },
  {
    id: "evaluation",
    number: "08",
    label: "Delivery proof",
    detail: "Outcomes & efficiency",
  },
  {
    id: "data-lifecycle",
    number: "09",
    label: "Data lifecycle",
    detail: "Export & deletion",
  },
] as const;

function formatDate(value: string | null) {
  if (!value) return "Timestamp not supplied";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function humanBytes(value: number) {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}

function confidenceLabel(value: string) {
  return `${Math.round(Number(value) * 100)}% extraction confidence`;
}

function sourceOffset(provenance: Claim["provenance"][number]) {
  const segmentStart = provenance.locator.start;
  const base = typeof segmentStart === "number" ? segmentStart : 0;
  return `${base + provenance.start_offset}–${base + provenance.end_offset}`;
}

function statusStyle(status: Evidence["status"]) {
  if (status === "failed") return "bg-[var(--red-soft)] text-[var(--red)]";
  if (status === "queued" || status === "processing")
    return "bg-[var(--amber-soft)] text-[var(--amber)]";
  return "bg-[var(--teal-soft)] text-[var(--teal)]";
}

function LoadingWorkspace() {
  return (
    <main
      className="grid min-h-screen place-items-center"
      id="main-content"
      tabIndex={-1}
    >
      <div aria-live="polite" className="text-center" role="status">
        <span
          aria-hidden="true"
          className="mx-auto mb-4 block h-10 w-10 animate-spin rounded-full border-2 border-[var(--line-strong)] border-t-[var(--teal)]"
        />
        <p className="text-sm font-bold text-[var(--ink-soft)]">
          Loading verified workspace…
        </p>
      </div>
    </main>
  );
}

export function EngagementCockpit({ engagementId }: { engagementId: string }) {
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [authenticationRequired, setAuthenticationRequired] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [uploading, setUploading] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [dataLifecycleReady, setDataLifecycleReady] = useState(false);
  const [assessmentReady, setAssessmentReady] = useState(false);
  const [deletedReceipt, setDeletedReceipt] =
    useState<EngagementDeletionReceipt | null>(null);
  const [lifecycleProgress, setLifecycleProgress] = useState({
    current: false,
    target: false,
    economics: false,
    specification: false,
  });
  const fileInput = useRef<HTMLInputElement>(null);
  const noteToggle = useRef<HTMLButtonElement>(null);
  const noteTitle = useRef<HTMLInputElement>(null);
  const handleLifecycleProgress = useCallback(
    (progress: typeof lifecycleProgress) => setLifecycleProgress(progress),
    [],
  );
  const handleDataLifecycleReady = useCallback(
    (ready: boolean) => setDataLifecycleReady(ready),
    [],
  );
  const handleAssessmentReady = useCallback(
    (ready: boolean) => setAssessmentReady(ready),
    [],
  );

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      try {
        const [
          operator,
          workspace,
          evidence,
          claims,
          contradictions,
          operatingModel,
        ] = await Promise.all([
          getAuthenticatedOperator(),
          getWorkspace(engagementId),
          listEvidence(engagementId),
          listClaims(engagementId),
          listContradictions(engagementId),
          getOperatingModel(engagementId),
        ]);
        setData({
          operator,
          workspace,
          evidence,
          claims,
          contradictions,
          operatingModel,
        });
        setAuthenticationRequired(false);
        setFatalError(null);
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 401) {
          setAuthenticationRequired(true);
          setFatalError(null);
          return;
        }
        if (!quiet) {
          setFatalError(
            reason instanceof Error
              ? reason.message
              : "The engagement could not be loaded.",
          );
        }
      } finally {
        if (!quiet) setLoading(false);
      }
    },
    [engagementId],
  );

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  useEffect(() => {
    if (noteOpen) noteTitle.current?.focus();
  }, [noteOpen]);

  const processingEvidence =
    data?.evidence.some(
      (item) => item.status === "queued" || item.status === "processing",
    ) ?? false;
  useEffect(() => {
    if (!processingEvidence) return;
    const interval = window.setInterval(() => void load(true), 2500);
    return () => window.clearInterval(interval);
  }, [load, processingEvidence]);

  const candidateClaims = useMemo(
    () => data?.claims.filter((claim) => claim.status === "candidate") ?? [],
    [data?.claims],
  );
  const reviewedClaims = useMemo(
    () => data?.claims.filter((claim) => claim.status !== "candidate") ?? [],
    [data?.claims],
  );

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setNotice(null);
    try {
      await uploadEvidence(engagementId, file);
      setNotice({
        tone: "success",
        text: `${file.name} was preserved and queued for extraction.`,
      });
      await load(true);
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof ApiError
            ? reason.message
            : "The source evidence could not be uploaded.",
      });
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function handleNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setUploading(true);
    setNotice(null);
    const form = new FormData(event.currentTarget);
    try {
      await createOperatorNote(engagementId, {
        title: String(form.get("title")),
        content: String(form.get("content")),
      });
      event.currentTarget.reset();
      setNoteOpen(false);
      window.setTimeout(() => noteToggle.current?.focus(), 0);
      setNotice({
        tone: "success",
        text: "The operator note was preserved as source evidence and queued for extraction.",
      });
      await load(true);
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The note could not be preserved.",
      });
    } finally {
      setUploading(false);
    }
  }

  async function handleReview(
    claimId: string,
    decision: "accepted" | "rejected" | "deferred",
    reason: string,
  ) {
    setReviewingId(claimId);
    setNotice(null);
    try {
      await reviewClaim(engagementId, claimId, decision, reason);
      const verb =
        decision === "accepted" ? "accepted into the verified model" : decision;
      setNotice({
        tone: "success",
        text: `Claim ${verb}. The decision and actor were recorded.`,
      });
      await load(true);
    } catch (reviewError) {
      setNotice({
        tone: "error",
        text:
          reviewError instanceof Error
            ? reviewError.message
            : "The review could not be recorded.",
      });
    } finally {
      setReviewingId(null);
    }
  }

  async function handleContradictionResolution(
    contradictionId: string,
    resolutionType:
      "accepted_exception" | "not_a_conflict" | "superseded" | "override",
    reason: string,
  ) {
    setResolvingId(contradictionId);
    setNotice(null);
    try {
      await resolveContradiction(
        engagementId,
        contradictionId,
        resolutionType,
        reason,
      );
      setNotice({
        tone: "success",
        text: "The contradiction resolution and operator reason were recorded.",
      });
      await load(true);
    } catch (reasonCaught) {
      setNotice({
        tone: "error",
        text:
          reasonCaught instanceof Error
            ? reasonCaught.message
            : "The contradiction could not be resolved.",
      });
    } finally {
      setResolvingId(null);
    }
  }

  if (loading) return <LoadingWorkspace />;

  if (authenticationRequired) {
    return <AuthenticationRequired returnTo={`/engagements/${engagementId}`} />;
  }

  if (deletedReceipt) {
    return <DeletedWorkspace receipt={deletedReceipt} />;
  }

  if (fatalError || !data) {
    return (
      <main
        className="grid min-h-screen place-items-center px-5"
        id="main-content"
        tabIndex={-1}
      >
        <section className="surface max-w-xl rounded-2xl p-9 text-center">
          <p className="eyebrow">Unable to open engagement</p>
          <h1 className="display-font mt-3 text-4xl font-medium">
            The workspace is unavailable.
          </h1>
          <p className="mt-4 text-sm leading-6 text-[var(--ink-soft)]">
            {fatalError}
          </p>
          <button
            className="mt-6 rounded-full bg-[var(--ink)] px-5 py-3 text-sm font-bold text-white"
            onClick={() => void load()}
            type="button"
          >
            Try again
          </button>
        </section>
      </main>
    );
  }

  const { operator } = data;
  const { engagement, counts } = data.workspace;

  return (
    <div className="cockpit-shell grid min-h-screen grid-cols-[248px_1fr]">
      <aside
        aria-label="Engagement navigation"
        className="cockpit-rail sticky top-0 flex h-screen w-[248px] flex-col border-r border-[var(--line)] bg-[var(--paper)] px-5 py-6"
      >
        <Brand />
        <div className="mt-4 border-b border-[var(--line)] pb-4">
          <EcosystemLinks compact />
        </div>
        <div className="cockpit-engagement-context mt-10 border-y border-[var(--line)] py-5">
          <p className="text-[0.65rem] font-extrabold uppercase tracking-[0.13em] text-[var(--ink-soft)]">
            Active engagement
          </p>
          <p className="mt-2 text-sm font-extrabold leading-5">
            {engagement.name}
          </p>
          <p className="mt-1 text-xs font-semibold text-[var(--ink-soft)]">
            {engagement.workflow_name}
          </p>
          <span className="mt-3 inline-flex rounded-full bg-[var(--amber-soft)] px-2.5 py-1 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--amber)]">
            Synthetic workspace
          </span>
        </div>

        <nav aria-label="Engagement stages" className="mt-7 grid gap-1">
          {stages.map((stage, index) => {
            const complete =
              index === 0
                ? counts.evidence > 0
                : index === 1
                  ? candidateClaims.length === 0 && reviewedClaims.length > 0
                  : index === 2
                    ? counts.verified_assertions > 0
                    : stage.id === "current-workflow"
                      ? lifecycleProgress.current
                      : stage.id === "target-workflow"
                        ? lifecycleProgress.target
                        : stage.id === "economics"
                          ? lifecycleProgress.economics
                          : stage.id === "specification"
                            ? lifecycleProgress.specification
                            : stage.id === "evaluation"
                              ? assessmentReady
                              : dataLifecycleReady;
            return (
              <a
                aria-label={`${stage.number}. ${stage.label}: ${stage.detail}, ${complete ? "complete" : "incomplete"}`}
                className="group grid grid-cols-[28px_1fr] gap-3 rounded-xl px-2 py-3 text-[var(--ink)] no-underline hover:bg-[var(--canvas)]"
                href={`#${stage.id}`}
                key={stage.id}
              >
                <span
                  className={`grid h-7 w-7 place-items-center rounded-full border text-[0.62rem] font-extrabold ${complete ? "border-[var(--teal)] bg-[var(--teal)] text-white" : "border-[var(--line-strong)] text-[var(--ink-soft)]"}`}
                >
                  {complete ? <CheckIcon className="h-4 w-4" /> : stage.number}
                </span>
                <span>
                  <span className="block text-xs font-extrabold">
                    {stage.label}
                  </span>
                  <span className="mt-1 block text-[0.66rem] font-semibold text-[var(--ink-soft)]">
                    {stage.detail}
                  </span>
                </span>
              </a>
            );
          })}
        </nav>

        <div className="cockpit-isolation mt-auto rounded-xl border border-[var(--line)] bg-[var(--canvas)] p-3.5">
          <p className="flex items-center gap-2 text-[0.68rem] font-extrabold uppercase tracking-[0.1em]">
            <ShieldIcon className="h-4 w-4 text-[var(--teal)]" /> Isolation
            active
          </p>
          <p className="mt-2 text-[0.66rem] leading-5 text-[var(--ink-soft)]">
            {hostedDemoEnabled
              ? "Browser-local synthetic state. Customer data and production authority are disabled."
              : "Application authorization plus PostgreSQL row policies. "}
            {!hostedDemoEnabled && operator.auth_mode === "oidc"
              ? "Verified production identity."
              : !hostedDemoEnabled
                ? "Local development identity."
                : null}
          </p>
        </div>
      </aside>

      <main className="min-w-0" id="main-content" tabIndex={-1}>
        <header className="border-b border-[var(--line)] bg-[rgba(243,240,232,0.78)] px-5 py-4 backdrop-blur md:px-8">
          <div className="mx-auto flex max-w-[1320px] items-center justify-between gap-5">
            <div className="min-w-0 flex-1">
              <p className="text-[0.63rem] font-extrabold uppercase tracking-[0.13em] text-[var(--ink-soft)]">
                FDE workspace / {engagement.lifecycle_stage}
              </p>
              <p className="mt-1 max-w-3xl truncate text-xs font-bold text-[var(--ink-soft)]">
                {engagement.primary_outcome}
              </p>
            </div>
            <div className="operator-session-indicator flex shrink-0 items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--paper)] px-3 py-2 text-[0.66rem] font-extrabold text-[var(--ink-soft)]">
              <span className="status-dot text-[var(--teal)]" /> Operator
              session · {operator.display_name}
            </div>
          </div>
        </header>

        <div className="mx-auto max-w-[1320px] px-5 py-8 md:px-8 md:py-11">
          <section className="grid gap-8 lg:grid-cols-[1fr_auto] lg:items-end">
            <div>
              <p className="eyebrow">Verified operating state</p>
              <h1 className="display-font mt-3 text-4xl font-medium tracking-[-0.035em] md:text-6xl">
                {engagement.name}
              </h1>
              <p className="mt-4 max-w-3xl text-sm leading-6 text-[var(--ink-soft)]">
                The canonical model contains only human-accepted assertions.
                Source documents remain source evidence—not truth.
              </p>
            </div>
            <div className="grid grid-cols-3 divide-x divide-[var(--line)] rounded-2xl border border-[var(--line)] bg-[var(--paper)]">
              <Metric value={counts.evidence} label="Source evidence" />
              <Metric
                value={candidateClaims.length}
                label="To review"
                emphasis={candidateClaims.length > 0}
              />
              <Metric value={counts.verified_assertions} label="Verified" />
            </div>
          </section>

          <div className="mt-8 rounded-xl border border-[var(--amber)]/25 bg-[var(--amber-soft)] px-4 py-3 text-xs font-semibold leading-5 text-[var(--amber)]">
            <strong className="font-extrabold">V1 capability boundary:</strong>{" "}
            PDF, DOCX, CSV, email, image, Markdown, and text source formats are
            supported. Local development uses transparent deterministic fixture
            patterns across three synthetic workflows; production requires
            fail-closed Bedrock extraction. Coding-agent execution and
            autonomous remediation are not included.
          </div>

          {notice && (
            <div
              className={`mt-5 rounded-xl border px-4 py-3 text-sm font-bold ${notice.tone === "success" ? "border-[var(--teal)]/25 bg-[var(--teal-soft)] text-[var(--teal)]" : "border-[var(--red)]/25 bg-[var(--red-soft)] text-[var(--red)]"}`}
              role={notice.tone === "error" ? "alert" : "status"}
            >
              {notice.text}
            </div>
          )}

          <section className="mt-10 scroll-mt-6" id="evidence">
            <SectionHeading
              eyebrow="01 / Source record"
              title="Source evidence ledger"
              detail="Files are hashed, stored immutably, and processed asynchronously. Exact locations survive into every downstream assertion."
            />
            <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_0.55fr]">
              <div className="surface overflow-hidden rounded-2xl">
                {data.evidence.length === 0 ? (
                  <div className="p-9 text-center">
                    <FileIcon className="mx-auto h-8 w-8 text-[var(--ink-soft)]" />
                    <p className="display-font mt-4 text-2xl">
                      No source evidence preserved yet.
                    </p>
                    <p className="mt-2 text-sm text-[var(--ink-soft)]">
                      Add a Markdown or text file to start this engagement.
                    </p>
                  </div>
                ) : (
                  <div className="divide-y divide-[var(--line)]">
                    {data.evidence.map((asset) => (
                      <div
                        className="grid gap-4 p-5 md:grid-cols-[1fr_auto] md:items-center"
                        key={asset.id}
                      >
                        <div className="flex min-w-0 items-start gap-3">
                          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--canvas)] text-[var(--ink-soft)]">
                            <FileIcon />
                          </span>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-extrabold">
                              {asset.file_name}
                            </p>
                            <p className="mt-1 text-[0.68rem] font-semibold text-[var(--ink-soft)]">
                              {asset.source_type.replace("_", " ")} ·{" "}
                              {humanBytes(asset.byte_count)} · SHA-256{" "}
                              {asset.content_hash.slice(0, 10)}…
                            </p>
                            {asset.error_message && (
                              <p className="mt-2 text-xs text-[var(--red)]">
                                {asset.error_message}
                              </p>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <span
                            className={`rounded-full px-2.5 py-1 text-[0.62rem] font-extrabold uppercase tracking-[0.08em] ${statusStyle(asset.status)}`}
                          >
                            {asset.status.replace("_", " ")}
                          </span>
                          <time className="text-[0.65rem] font-semibold text-[var(--ink-soft)]">
                            {formatDate(asset.created_at)}
                          </time>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="grid content-start gap-4">
                <div className="rounded-2xl border border-dashed border-[var(--line-strong)] bg-[rgba(251,250,246,0.65)] p-6 text-center">
                  <UploadIcon className="mx-auto h-7 w-7 text-[var(--teal)]" />
                  <p className="mt-3 text-sm font-extrabold">
                    Preserve source evidence
                  </p>
                  <p className="mt-2 text-xs leading-5 text-[var(--ink-soft)]">
                    PDF, DOCX, CSV, email, image, Markdown, or text · 5 MB
                    maximum
                  </p>
                  <input
                    accept=".pdf,.docx,.csv,.eml,.png,.jpg,.jpeg,.md,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/csv,message/rfc822,image/png,image/jpeg,text/markdown,text/plain"
                    disabled={uploading}
                    hidden
                    onChange={(event) =>
                      void handleFile(event.target.files?.[0])
                    }
                    ref={fileInput}
                    tabIndex={-1}
                    type="file"
                  />
                  <button
                    className="mt-4 rounded-full bg-[var(--ink)] px-4 py-2.5 text-xs font-extrabold text-white disabled:cursor-wait disabled:opacity-60"
                    disabled={uploading}
                    onClick={() => fileInput.current?.click()}
                    type="button"
                  >
                    {uploading ? "Preserving…" : "Choose file"}
                  </button>
                </div>
                <button
                  aria-controls="operator-note-form"
                  aria-expanded={noteOpen}
                  className="rounded-xl border border-[var(--line)] bg-[var(--paper)] px-4 py-3 text-xs font-extrabold text-[var(--ink)]"
                  onClick={() => setNoteOpen((value) => !value)}
                  ref={noteToggle}
                  type="button"
                >
                  {noteOpen
                    ? "Close operator note"
                    : "Add operator note as source evidence"}
                </button>
                {noteOpen && (
                  <form
                    className="surface grid gap-3 rounded-2xl p-5"
                    id="operator-note-form"
                    onSubmit={handleNote}
                  >
                    <label className="grid gap-1.5 text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                      Title
                      <input
                        className="rounded-lg border border-[var(--line)] bg-white px-3 py-2.5 text-xs font-semibold normal-case tracking-normal text-[var(--ink)]"
                        minLength={2}
                        name="title"
                        ref={noteTitle}
                        required
                      />
                    </label>
                    <label className="grid gap-1.5 text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                      Observation
                      <textarea
                        className="min-h-28 resize-y rounded-lg border border-[var(--line)] bg-white px-3 py-2.5 text-xs font-semibold leading-5 normal-case tracking-normal text-[var(--ink)]"
                        name="content"
                        required
                      />
                    </label>
                    <button
                      className="rounded-full bg-[var(--teal)] px-4 py-2.5 text-xs font-extrabold text-white disabled:opacity-60"
                      disabled={uploading}
                      type="submit"
                    >
                      Preserve & extract
                    </button>
                  </form>
                )}
              </div>
            </div>
          </section>

          <section className="mt-14 scroll-mt-6" id="review">
            <SectionHeading
              eyebrow="02 / Human authority"
              title="Candidate claim review"
              detail="Extraction proposes. The FDE decides. Accepting a claim creates a verified assertion and preserves its exact evidence chain."
            />
            <p className="mt-3 text-xs font-bold text-[var(--ink-soft)]">
              FDLC Guide:{" "}
              <a
                className="text-[var(--teal)] underline decoration-[var(--teal)]/35 underline-offset-4"
                href={guideHref("trust.evidence-record")}
                rel="noreferrer"
                target="_blank"
              >
                {GUIDE_LINKS["trust.evidence-record"].title}
                <span aria-hidden="true"> ↗</span>
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </p>

            {data.contradictions.length > 0 && (
              <div className="mt-5 grid gap-3">
                {data.contradictions.map((contradiction) => (
                  <ContradictionCard
                    busy={resolvingId === contradiction.id}
                    contradiction={contradiction}
                    key={contradiction.id}
                    onResolve={handleContradictionResolution}
                  />
                ))}
              </div>
            )}

            {candidateClaims.length === 0 ? (
              <div className="surface mt-5 rounded-2xl p-9 text-center">
                <CheckIcon className="mx-auto h-8 w-8 text-[var(--teal)]" />
                <p className="display-font mt-4 text-2xl">
                  Review queue is clear.
                </p>
                <p className="mt-2 text-sm text-[var(--ink-soft)]">
                  Newly extracted claims will appear here before they can affect
                  the model.
                </p>
              </div>
            ) : (
              <div className="mt-5 grid gap-5 xl:grid-cols-2">
                {candidateClaims.map((claim) => (
                  <ClaimCard
                    busy={reviewingId === claim.id}
                    claim={claim}
                    key={claim.id}
                    onReview={handleReview}
                  />
                ))}
              </div>
            )}

            {reviewedClaims.length > 0 && (
              <details className="surface mt-5 rounded-2xl">
                <summary className="cursor-pointer px-5 py-4 text-xs font-extrabold">
                  Decision history · {reviewedClaims.length} claims
                </summary>
                <div className="divide-y divide-[var(--line)] border-t border-[var(--line)]">
                  {reviewedClaims.map((claim) => (
                    <div
                      className="flex items-start justify-between gap-5 px-5 py-4"
                      key={claim.id}
                    >
                      <p className="text-xs font-bold leading-5">
                        {claim.summary}
                      </p>
                      <span
                        className={`shrink-0 rounded-full px-2.5 py-1 text-[0.6rem] font-extrabold uppercase ${claim.status === "accepted" ? "bg-[var(--teal-soft)] text-[var(--teal)]" : claim.status === "rejected" ? "bg-[var(--red-soft)] text-[var(--red)]" : "bg-[var(--amber-soft)] text-[var(--amber)]"}`}
                      >
                        {claim.status}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </section>

          <section className="mt-14 scroll-mt-6" id="model">
            <SectionHeading
              eyebrow="03 / Canonical state"
              title="Company Operating Model"
              detail="This verified view—not the source documents—is the state agents and downstream workflows will reason over."
            />
            <div className="mt-5 grid gap-5 xl:grid-cols-[0.4fr_1fr]">
              <div className="surface rounded-2xl p-5">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                    Entities
                  </p>
                  <span className="text-xs font-extrabold text-[var(--teal)]">
                    {data.operatingModel.entities.length}
                  </span>
                </div>
                {data.operatingModel.entities.length === 0 ? (
                  <p className="mt-7 text-sm leading-6 text-[var(--ink-soft)]">
                    No verified entities yet. Accept an entity or relationship
                    claim to begin the model.
                  </p>
                ) : (
                  <div className="mt-4 grid gap-2">
                    {data.operatingModel.entities.map((entity) => (
                      <div
                        className="rounded-xl border border-[var(--line)] bg-white p-3.5"
                        key={entity.id}
                      >
                        <p className="text-xs font-extrabold">
                          {entity.display_name}
                        </p>
                        <p className="mt-1 text-[0.62rem] font-bold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                          {entity.entity_type} · {entity.status}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="surface overflow-hidden rounded-2xl">
                <div className="flex items-center justify-between border-b border-[var(--line)] px-5 py-4">
                  <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                    Verified assertions
                  </p>
                  <span className="text-xs font-extrabold text-[var(--teal)]">
                    {data.operatingModel.assertions.length}
                  </span>
                </div>
                {data.operatingModel.assertions.length === 0 ? (
                  <div className="p-9 text-center">
                    <ShieldIcon className="mx-auto h-8 w-8 text-[var(--ink-soft)]" />
                    <p className="display-font mt-4 text-2xl">
                      The model is intentionally empty.
                    </p>
                    <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-[var(--ink-soft)]">
                      Nothing becomes canonical until a human FDE accepts an
                      evidence-backed claim.
                    </p>
                  </div>
                ) : (
                  <div className="divide-y divide-[var(--line)]">
                    {data.operatingModel.assertions.map((assertion) => (
                      <article className="p-5" key={assertion.id}>
                        <div className="flex flex-wrap items-center gap-2 text-sm font-extrabold">
                          <span>{assertion.subject}</span>
                          <span className="rounded-full bg-[var(--teal-soft)] px-2 py-1 text-[0.62rem] uppercase tracking-[0.08em] text-[var(--teal)]">
                            {assertion.predicate.replaceAll("_", " ")}
                          </span>
                          {assertion.object && <span>{assertion.object}</span>}
                        </div>
                        <blockquote className="mt-4 border-l-2 border-[var(--teal)] pl-4 text-xs leading-5 text-[var(--ink-soft)]">
                          “{assertion.evidence.quote}”
                        </blockquote>
                        <p className="mt-3 text-[0.63rem] font-bold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
                          {assertion.evidence.file_name} · exact segment
                          retained · verified{" "}
                          {formatDate(assertion.recorded_at)}
                        </p>
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>

          <LifecycleWorkspace
            blockingContradictions={
              data.contradictions.filter((item) => item.blocking).length
            }
            engagementId={engagementId}
            modelVersion={`${counts.verified_assertions}:${data.contradictions.map((item) => `${item.id}:${item.status}`).join("|")}`}
            onProgress={handleLifecycleProgress}
          />

          <DeliveryEvaluationWorkspace
            engagementId={engagementId}
            lifecycleVersion={JSON.stringify(lifecycleProgress)}
            onReady={handleAssessmentReady}
          />

          <DataLifecycleWorkspace
            engagement={engagement}
            onDeleted={setDeletedReceipt}
            onReady={handleDataLifecycleReady}
          />

          <section className="mt-14 rounded-2xl border border-[var(--line)] bg-[var(--ink)] p-6 text-white md:p-8">
            <p className="text-[0.64rem] font-extrabold uppercase tracking-[0.13em] text-[#9dc8c2]">
              V1 boundary
            </p>
            <p className="display-font mt-3 text-2xl font-medium">
              The lifecycle stops at an implementation-ready artifact packet.
            </p>
            <p className="mt-3 max-w-3xl text-xs leading-5 text-white/60">
              Coding-agent dispatch and autonomous remediation remain post-V1.
              Production and sanitized data remain gated until live tenant and
              deployment validation succeeds.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}

function DeletedWorkspace({ receipt }: { receipt: EngagementDeletionReceipt }) {
  return (
    <main
      className="grid min-h-screen place-items-center px-5 py-12"
      id="main-content"
      tabIndex={-1}
    >
      <section className="surface w-full max-w-3xl overflow-hidden rounded-[1.75rem]">
        <div className="border-b border-[var(--teal)]/20 bg-[var(--teal-soft)] px-7 py-7 md:px-10">
          <CheckIcon className="h-8 w-8 text-[var(--teal)]" />
          <p className="eyebrow mt-5">Deletion verified</p>
          <h1 className="display-font mt-2 text-4xl font-medium md:text-5xl">
            Engagement data was permanently removed.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">
            Customer content is no longer available in Factory Engineer. This
            page shows only the content-free receipt retained for operational
            proof.
          </p>
        </div>
        <div className="grid gap-6 px-7 py-7 md:grid-cols-2 md:px-10">
          <ReceiptField label="Receipt ID" value={receipt.id} />
          <ReceiptField label="Export ID" value={receipt.export_id} />
          <ReceiptField
            label="Database rows removed"
            value={String(receipt.database_row_count)}
          />
          <ReceiptField
            label="Source-evidence objects removed"
            value={String(receipt.evidence_object_count)}
          />
          <div className="md:col-span-2">
            <ReceiptField label="Export SHA-256" value={receipt.archive_hash} />
          </div>
        </div>
        <div className="border-t border-[var(--line)] px-7 py-6 md:px-10">
          <Link
            className="inline-flex rounded-full bg-[var(--ink)] px-5 py-3 text-sm font-extrabold text-white no-underline"
            href="/"
          >
            Return to engagements
          </Link>
        </div>
      </section>
    </main>
  );
}

function ReceiptField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.62rem] font-extrabold uppercase tracking-[0.11em] text-[var(--ink-soft)]">
        {label}
      </p>
      <p className="mt-2 break-all font-mono text-xs font-bold text-[var(--ink)]">
        {value}
      </p>
    </div>
  );
}

function Metric({
  value,
  label,
  emphasis = false,
}: {
  value: number;
  label: string;
  emphasis?: boolean;
}) {
  return (
    <div className="min-w-24 px-4 py-4 text-center">
      <p
        className={`display-font text-3xl font-medium ${emphasis ? "text-[var(--amber)]" : "text-[var(--ink)]"}`}
      >
        {value}
      </p>
      <p className="mt-1 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
        {label}
      </p>
    </div>
  );
}

function SectionHeading({
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

function ClaimCard({
  claim,
  busy,
  onReview,
}: {
  claim: Claim;
  busy: boolean;
  onReview: (
    claimId: string,
    decision: "accepted" | "rejected" | "deferred",
    reason: string,
  ) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const provenance = claim.provenance[0];

  return (
    <article className="surface flex flex-col rounded-2xl p-5">
      <div className="flex items-center justify-between gap-3">
        <span className="rounded-full bg-[var(--canvas)] px-2.5 py-1 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
          {claim.claim_kind}
        </span>
        <span className="text-[0.64rem] font-bold text-[var(--ink-soft)]">
          {confidenceLabel(claim.confidence)}
        </span>
      </div>
      <h3 className="display-font mt-5 text-2xl font-medium leading-7">
        {claim.summary}
      </h3>

      {provenance ? (
        <div className="mt-5 rounded-xl border border-[var(--line)] bg-white p-4">
          <p className="text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--teal)]">
            Exact source evidence
          </p>
          <blockquote className="mt-2 text-xs font-semibold leading-5 text-[var(--ink)]">
            “{provenance.quote}”
          </blockquote>
          <div className="mt-3 border-t border-[var(--line)] pt-3 text-[0.62rem] font-bold leading-5 text-[var(--ink-soft)]">
            <p>{provenance.file_name}</p>
            <p>
              Source offsets {sourceOffset(provenance)} ·{" "}
              {formatDate(provenance.source_timestamp)}
            </p>
          </div>
        </div>
      ) : (
        <div className="mt-5 rounded-xl bg-[var(--red-soft)] p-4 text-xs font-bold text-[var(--red)]">
          No provenance is attached. This claim cannot be safely accepted.
        </div>
      )}

      <label className="mt-5 grid gap-2 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
        Decision note{" "}
        <span className="normal-case tracking-normal">
          (recommended for rejection)
        </span>
        <textarea
          aria-label={`Decision note for: ${claim.summary}`}
          className="min-h-20 resize-y rounded-xl border border-[var(--line)] bg-white px-3 py-2.5 text-xs font-semibold leading-5 normal-case tracking-normal text-[var(--ink)]"
          disabled={busy}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Record why this decision is appropriate…"
          value={reason}
        />
      </label>
      <div className="mt-auto grid grid-cols-2 gap-2 pt-4">
        <button
          className="rounded-full border border-[var(--red)]/35 px-3 py-2.5 text-[0.66rem] font-extrabold text-[var(--red)] disabled:opacity-50"
          disabled={busy}
          onClick={() => void onReview(claim.id, "rejected", reason)}
          type="button"
        >
          Reject
        </button>
        <button
          className="rounded-full bg-[var(--teal)] px-3 py-2.5 text-[0.66rem] font-extrabold text-white disabled:cursor-wait disabled:opacity-50"
          disabled={busy || !provenance}
          onClick={() => void onReview(claim.id, "accepted", reason)}
          type="button"
        >
          {busy ? "Saving…" : "Accept"}
        </button>
      </div>
    </article>
  );
}

function ContradictionCard({
  contradiction,
  busy,
  onResolve,
}: {
  contradiction: Contradiction;
  busy: boolean;
  onResolve: (
    contradictionId: string,
    resolutionType:
      "accepted_exception" | "not_a_conflict" | "superseded" | "override",
    reason: string,
  ) => Promise<void>;
}) {
  const [resolutionType, setResolutionType] = useState<
    "accepted_exception" | "not_a_conflict" | "superseded" | "override"
  >("accepted_exception");
  const [reason, setReason] = useState("");

  return (
    <div
      className={`rounded-2xl border p-5 ${contradiction.blocking ? "border-[var(--red)]/25 bg-[var(--red-soft)]" : "border-[var(--teal)]/25 bg-[var(--teal-soft)]"}`}
    >
      <div className="flex items-center justify-between gap-4">
        <p
          className={`text-[0.65rem] font-extrabold uppercase tracking-[0.12em] ${contradiction.blocking ? "text-[var(--red)]" : "text-[var(--teal)]"}`}
        >
          {contradiction.blocking
            ? "Blocking contradiction"
            : "Resolved contradiction"}
        </p>
        <span
          className={`rounded-full border px-2.5 py-1 text-[0.6rem] font-extrabold uppercase ${contradiction.blocking ? "border-[var(--red)]/25 text-[var(--red)]" : "border-[var(--teal)]/25 text-[var(--teal)]"}`}
        >
          {contradiction.status.replaceAll("_", " ")}
        </span>
      </div>
      <p className="mt-2 text-sm font-bold leading-6 text-[var(--ink)]">
        {contradiction.summary}
      </p>
      {contradiction.blocking ? (
        <div className="mt-4 grid gap-3 border-t border-[var(--red)]/15 pt-4 md:grid-cols-[0.55fr_1fr_auto] md:items-end">
          <label className="grid gap-1.5 text-[0.62rem] font-extrabold uppercase tracking-[0.08em] text-[var(--red)]">
            Classification
            <select
              aria-label={`Classification for contradiction: ${contradiction.summary}`}
              className="rounded-lg border border-[var(--red)]/20 bg-white px-3 py-2.5 text-xs font-bold normal-case tracking-normal text-[var(--ink)]"
              disabled={busy}
              onChange={(event) =>
                setResolutionType(event.target.value as typeof resolutionType)
              }
              value={resolutionType}
            >
              <option value="accepted_exception">Accepted exception</option>
              <option value="not_a_conflict">Not a conflict</option>
              <option value="superseded">Superseded source evidence</option>
              <option value="override">Operator override</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-[0.62rem] font-extrabold uppercase tracking-[0.08em] text-[var(--red)]">
            Operator reason
            <input
              aria-label={`Operator reason for contradiction: ${contradiction.summary}`}
              className="rounded-lg border border-[var(--red)]/20 bg-white px-3 py-2.5 text-xs font-semibold normal-case tracking-normal text-[var(--ink)]"
              disabled={busy}
              minLength={5}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why can this blocker be closed?"
              value={reason}
            />
          </label>
          <button
            className="rounded-full bg-[var(--red)] px-4 py-2.5 text-xs font-extrabold text-white disabled:opacity-50"
            disabled={busy || reason.trim().length < 5}
            onClick={() =>
              void onResolve(contradiction.id, resolutionType, reason)
            }
            type="button"
          >
            {busy ? "Recording…" : "Resolve blocker"}
          </button>
        </div>
      ) : (
        <p className="mt-3 text-xs leading-5 text-[var(--ink-soft)]">
          <strong className="font-extrabold">
            {contradiction.resolution_type?.replaceAll("_", " ")}:
          </strong>{" "}
          {contradiction.resolution_reason}
        </p>
      )}
    </div>
  );
}
