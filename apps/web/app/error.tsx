"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center px-6">
      <section className="surface max-w-xl rounded-2xl p-10 text-center">
        <p className="eyebrow">Workspace unavailable</p>
        <h1 className="display-font mt-3 text-4xl font-medium">The cockpit could not load.</h1>
        <p className="mt-4 text-sm leading-6 text-[var(--ink-soft)]">Check that the local API and database are running, then try again.</p>
        <button className="mt-7 rounded-full bg-[var(--ink)] px-5 py-3 text-sm font-bold text-white" onClick={reset} type="button">
          Try again
        </button>
      </section>
    </main>
  );
}
