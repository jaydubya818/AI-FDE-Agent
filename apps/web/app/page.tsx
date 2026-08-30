"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import { AuthenticationRequired } from "@/components/authentication-required";
import { Brand } from "@/components/brand";
import { ArrowIcon, PlusIcon, ShieldIcon } from "@/components/icons";
import {
  ApiError,
  createEngagement,
  getAuthenticatedOperator,
  getInternalAlphaScorecard,
  listEngagements,
  logoutOperator,
} from "@/lib/api";
import type { AuthenticatedOperator } from "@/lib/api";
import type { Engagement, InternalAlphaScorecard } from "@/lib/types";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

export default function EngagementsPage() {
  const router = useRouter();
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [operator, setOperator] = useState<AuthenticatedOperator | null>(null);
  const [alphaScorecard, setAlphaScorecard] =
    useState<InternalAlphaScorecard | null>(null);
  const [authenticationRequired, setAuthenticationRequired] = useState(false);
  const createButton = useRef<HTMLButtonElement>(null);
  const nameInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getAuthenticatedOperator()
      .then(async (authenticatedOperator) => {
        setOperator(authenticatedOperator);
        const [currentEngagements, currentScorecard] = await Promise.all([
          listEngagements(),
          getInternalAlphaScorecard(),
        ]);
        setEngagements(currentEngagements);
        setAlphaScorecard(currentScorecard);
      })
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 401) {
          setAuthenticationRequired(true);
          return;
        }
        setError(
          reason instanceof Error
            ? reason.message
            : "Unable to load engagements.",
        );
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (showForm) nameInput.current?.focus();
  }, [showForm]);

  function closeCreateForm() {
    setShowForm(false);
    window.setTimeout(() => createButton.current?.focus(), 0);
  }

  async function handleLogout() {
    try {
      await logoutOperator();
      setOperator(null);
      setEngagements([]);
      setAuthenticationRequired(true);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The operator session could not be closed.",
      );
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    const form = new FormData(event.currentTarget);

    try {
      const engagement = await createEngagement({
        name: String(form.get("name")),
        workflow_name: String(form.get("workflow_name")),
        primary_outcome: String(form.get("primary_outcome")),
        data_classification: "synthetic",
      });
      router.push(`/engagements/${engagement.id}`);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "The engagement could not be created.",
      );
      setCreating(false);
    }
  }

  if (!loading && authenticationRequired) {
    return <AuthenticationRequired returnTo="/" />;
  }

  return (
    <main
      className="min-h-screen px-5 py-5 md:px-10 md:py-8"
      id="main-content"
      tabIndex={-1}
    >
      <header className="mx-auto flex max-w-[1240px] items-center justify-between">
        <Brand />
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-3 rounded-full border border-[var(--line)] bg-[var(--paper)] px-4 py-2 text-xs font-bold text-[var(--ink-soft)]">
            <span className="status-dot text-[var(--teal)]" />
            {operator
              ? `${operator.display_name} · ${operator.auth_mode === "oidc" ? "verified" : "development"}`
              : loading
                ? "Checking operator session"
                : "Operator service unavailable"}
          </div>
          {operator?.auth_mode === "oidc" && (
            <button
              className="rounded-full border border-[var(--line-strong)] px-4 py-2 text-xs font-bold text-[var(--ink-soft)] transition hover:border-[var(--ink)] hover:text-[var(--ink)]"
              onClick={() => void handleLogout()}
              type="button"
            >
              Sign out
            </button>
          )}
        </div>
      </header>

      <section className="mx-auto grid max-w-[1240px] gap-14 pb-16 pt-20 lg:grid-cols-[1fr_0.78fr] lg:items-end lg:pt-28">
        <div>
          <p className="eyebrow">Evidence-backed delivery</p>
          <h1 className="display-font mt-5 max-w-3xl text-5xl font-medium leading-[0.95] tracking-[-0.04em] md:text-7xl">
            Turn company context into a verified operating model.
          </h1>
        </div>
        <div className="max-w-xl lg:pb-2">
          <p className="text-base leading-7 text-[var(--ink-soft)]">
            A stateful workspace for Forward Deployed Engineers to ingest
            evidence, verify claims, and build an implementation-ready view of
            how a company actually operates.
          </p>
          <div className="mt-7 flex gap-3">
            <button
              aria-controls="new-engagement-form"
              aria-expanded={showForm}
              className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-3 text-sm font-bold text-white transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
              disabled={!operator}
              onClick={() => setShowForm(true)}
              ref={createButton}
              type="button"
            >
              <PlusIcon /> New engagement
            </button>
          </div>
        </div>
      </section>

      <section
        aria-labelledby="alpha-scorecard-heading"
        className="surface mx-auto mb-12 max-w-[1240px] overflow-hidden rounded-2xl"
      >
        <div className="grid gap-6 border-b border-[var(--line)] bg-[var(--ink)] px-6 py-7 text-white md:px-8 lg:grid-cols-[1fr_0.9fr] lg:items-end">
          <div>
            <p className="text-[0.68rem] font-extrabold uppercase tracking-[0.15em] text-[#9dc8c2]">
              Internal alpha evidence
            </p>
            <h2
              className="display-font mt-3 text-3xl font-medium md:text-4xl"
              id="alpha-scorecard-heading"
            >
              Delivery proof before production claims.
            </h2>
          </div>
          <p className="text-sm leading-6 text-white/65">
            Three distinct workflow shapes, objective stage gates, and
            structured evaluator observations. Time and token economics remain
            absolute until a complete conventional baseline exists.
          </p>
        </div>

        {loading ? (
          <div
            aria-live="polite"
            className="p-8 text-sm font-bold text-[var(--ink-soft)]"
            role="status"
          >
            Loading internal alpha scorecard…
          </div>
        ) : !alphaScorecard ? (
          <div
            aria-live="polite"
            className="p-8 text-sm font-bold text-[var(--ink-soft)]"
            role="status"
          >
            Internal alpha scorecard unavailable until the operator service
            connects.
          </div>
        ) : (
          <div className="p-6 md:p-8">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <AlphaMetric
                label="Workflow profiles"
                value={alphaScorecard.profile_count}
              />
              <AlphaMetric
                label="Complete packets"
                value={
                  String(alphaScorecard.packet_complete_count) +
                  "/" +
                  String(alphaScorecard.profile_count)
                }
              />
              <AlphaMetric
                label="Accepted material claims"
                value={alphaScorecard.accepted_material_claim_count}
              />
              <AlphaMetric
                label="Measured provider tokens"
                value={alphaScorecard.total_provider_tokens.toLocaleString()}
              />
            </div>

            <div className="mt-6 grid gap-3 lg:grid-cols-3">
              {alphaScorecard.engagements.map((card) => (
                <Link
                  className="rounded-xl border border-[var(--line)] bg-white p-4 text-[var(--ink)] no-underline transition hover:-translate-y-0.5 hover:border-[var(--line-strong)]"
                  href={"/engagements/" + card.engagement.id + "#evaluation"}
                  key={card.engagement.id}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="status-dot text-[var(--teal)]" />
                    <span className="text-[0.6rem] font-extrabold uppercase tracking-[0.09em] text-[var(--ink-soft)]">
                      {card.packet.artifact_count}/7 artifacts
                    </span>
                  </div>
                  <p className="mt-4 text-sm font-extrabold">
                    {card.engagement.workflow_name}
                  </p>
                  <p className="mt-1 text-xs font-semibold text-[var(--ink-soft)]">
                    {card.engagement.name} · {card.claims.material_accepted}{" "}
                    material claims
                  </p>
                </Link>
              ))}
            </div>

            <div
              className={
                "mt-6 rounded-xl border px-4 py-4 text-sm font-bold " +
                (alphaScorecard.comparison.ready
                  ? "border-[var(--teal)]/25 bg-[var(--teal-soft)] text-[var(--teal)]"
                  : "border-[var(--amber)]/25 bg-[var(--amber-soft)] text-[var(--amber)]")
              }
            >
              <p>
                {alphaScorecard.comparison.ready
                  ? "Comparison cohort complete. Absolute method differences are available for internal review."
                  : alphaScorecard.comparison.reason}
              </p>
              <p className="mt-2 text-xs font-extrabold uppercase tracking-[0.08em]">
                AI-FDE completed operator cohort:{" "}
                {
                  alphaScorecard.comparison.methods.ai_fde
                    .completed_operator_assessment_count
                }
                /3
                {" · "}Conventional baseline:{" "}
                {
                  alphaScorecard.comparison.methods.conventional
                    .completed_operator_assessment_count
                }
                /3
              </p>
            </div>
          </div>
        )}
      </section>

      {error && (
        <div
          className="mx-auto mb-6 max-w-[1240px] rounded-xl border border-[var(--red)]/25 bg-[var(--red-soft)] px-5 py-4 text-sm text-[var(--red)]"
          role="alert"
        >
          {error}
        </div>
      )}

      {showForm && (
        <section
          aria-labelledby="new-engagement-heading"
          className="surface mx-auto mb-8 max-w-[1240px] rounded-2xl p-6 md:p-8"
          id="new-engagement-form"
        >
          <div className="grid gap-8 lg:grid-cols-[0.55fr_1fr]">
            <div>
              <p className="eyebrow">New workspace</p>
              <h2
                className="display-font mt-3 text-3xl font-medium"
                id="new-engagement-heading"
              >
                Frame the engagement.
              </h2>
              <p className="mt-3 text-sm leading-6 text-[var(--ink-soft)]">
                V1 workspaces are synthetic or sanitized. Customer production
                data is intentionally out of scope.
              </p>
            </div>
            <form className="grid gap-5" onSubmit={handleCreate}>
              <label className="grid gap-2 text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                Company name
                <input
                  className="rounded-xl border border-[var(--line)] bg-white px-4 py-3.5 text-sm font-medium normal-case tracking-normal text-[var(--ink)]"
                  maxLength={255}
                  minLength={2}
                  name="name"
                  placeholder="e.g. Acme Manufacturing"
                  ref={nameInput}
                  required
                />
              </label>
              <label className="grid gap-2 text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                Primary workflow
                <input
                  className="rounded-xl border border-[var(--line)] bg-white px-4 py-3.5 text-sm font-medium normal-case tracking-normal text-[var(--ink)]"
                  maxLength={255}
                  minLength={2}
                  name="workflow_name"
                  placeholder="e.g. Vendor onboarding"
                  required
                />
              </label>
              <label className="grid gap-2 text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                Primary business outcome
                <textarea
                  className="min-h-28 resize-y rounded-xl border border-[var(--line)] bg-white px-4 py-3.5 text-sm font-medium normal-case leading-6 tracking-normal text-[var(--ink)]"
                  maxLength={2000}
                  minLength={10}
                  name="primary_outcome"
                  placeholder="What measurable business outcome should this engagement deliver?"
                  required
                />
              </label>
              <div className="flex items-center justify-between gap-4">
                <p className="inline-flex items-center gap-2 text-xs font-bold text-[var(--ink-soft)]">
                  <ShieldIcon /> Synthetic classification
                </p>
                <div className="flex gap-3">
                  <button
                    className="rounded-full border border-[var(--line-strong)] px-5 py-3 text-sm font-bold"
                    onClick={closeCreateForm}
                    type="button"
                  >
                    Cancel
                  </button>
                  <button
                    className="rounded-full bg-[var(--teal)] px-5 py-3 text-sm font-bold text-white disabled:cursor-wait disabled:opacity-60"
                    disabled={creating}
                    type="submit"
                  >
                    {creating ? "Creating…" : "Create workspace"}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </section>
      )}

      <section className="mx-auto max-w-[1240px] border-t border-[var(--line-strong)] pt-6">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <p className="eyebrow">Active work</p>
            <h2 className="display-font mt-2 text-3xl font-medium">
              Engagements
            </h2>
          </div>
          <span className="text-xs font-bold text-[var(--ink-soft)]">
            {engagements.length} total
          </span>
        </div>

        {loading ? (
          <div className="surface rounded-2xl p-8 text-sm font-bold text-[var(--ink-soft)]">
            Loading engagements…
          </div>
        ) : engagements.length === 0 ? (
          <div className="surface rounded-2xl p-10 text-center">
            <p className="display-font text-2xl">No engagements yet.</p>
            <p className="mt-2 text-sm text-[var(--ink-soft)]">
              Create a synthetic workspace to begin the evidence lifecycle.
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {engagements.map((engagement) => (
              <Link
                className="group grid gap-4 rounded-2xl border border-[var(--line)] bg-[var(--paper)] p-5 text-[var(--ink)] no-underline transition hover:-translate-y-0.5 hover:border-[var(--line-strong)] hover:shadow-[var(--shadow)] md:grid-cols-[1fr_2fr_auto] md:items-center md:p-6"
                href={`/engagements/${engagement.id}`}
                key={engagement.id}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="status-dot text-[var(--teal)]" />
                    <p className="font-extrabold tracking-[-0.02em]">
                      {engagement.name}
                    </p>
                  </div>
                  <p className="mt-2 text-xs font-bold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                    {engagement.workflow_name} · {engagement.lifecycle_stage} ·{" "}
                    {engagement.data_classification}
                  </p>
                </div>
                <p className="text-sm leading-6 text-[var(--ink-soft)]">
                  {engagement.primary_outcome}
                </p>
                <div className="flex items-center gap-4 text-xs font-bold text-[var(--ink-soft)]">
                  {formatDate(engagement.updated_at)}
                  <span className="grid h-9 w-9 place-items-center rounded-full border border-[var(--line)] text-[var(--ink)] transition group-hover:bg-[var(--ink)] group-hover:text-white">
                    <ArrowIcon />
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

function AlphaMetric({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-xl border border-[var(--line)] bg-white p-4">
      <p className="display-font text-3xl font-medium">{value}</p>
      <p className="mt-1 text-[0.62rem] font-extrabold uppercase tracking-[0.09em] text-[var(--ink-soft)]">
        {label}
      </p>
    </div>
  );
}
