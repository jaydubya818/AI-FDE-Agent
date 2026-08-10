"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { AuthenticationRequired } from "@/components/authentication-required";
import { Brand } from "@/components/brand";
import { ArrowIcon, PlusIcon, ShieldIcon } from "@/components/icons";
import {
  ApiError,
  createEngagement,
  getAuthenticatedOperator,
  listEngagements,
  logoutOperator,
} from "@/lib/api";
import type { AuthenticatedOperator } from "@/lib/api";
import type { Engagement } from "@/lib/types";

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
  const [authenticationRequired, setAuthenticationRequired] = useState(false);

  useEffect(() => {
    getAuthenticatedOperator()
      .then(async (authenticatedOperator) => {
        setOperator(authenticatedOperator);
        setEngagements(await listEngagements());
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
    <main className="min-h-screen px-5 py-5 md:px-10 md:py-8">
      <header className="mx-auto flex max-w-[1240px] items-center justify-between">
        <Brand />
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-3 rounded-full border border-[var(--line)] bg-[var(--paper)] px-4 py-2 text-xs font-bold text-[var(--ink-soft)]">
            <span className="status-dot text-[var(--teal)]" />
            {operator
              ? `${operator.display_name} · ${operator.auth_mode === "oidc" ? "verified" : "development"}`
              : "Checking operator session"}
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
              className="inline-flex items-center gap-2 rounded-full bg-[var(--ink)] px-5 py-3 text-sm font-bold text-white transition hover:-translate-y-0.5"
              onClick={() => setShowForm(true)}
              type="button"
            >
              <PlusIcon /> New engagement
            </button>
          </div>
        </div>
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
        <section className="surface mx-auto mb-8 max-w-[1240px] rounded-2xl p-6 md:p-8">
          <div className="grid gap-8 lg:grid-cols-[0.55fr_1fr]">
            <div>
              <p className="eyebrow">New workspace</p>
              <h2 className="display-font mt-3 text-3xl font-medium">
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
                    onClick={() => setShowForm(false)}
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
                    {engagement.lifecycle_stage} ·{" "}
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
