export default function Loading() {
  return (
    <main className="grid min-h-screen place-items-center px-6">
      <div aria-live="polite" className="text-center">
        <span className="mx-auto mb-5 block h-10 w-10 animate-spin rounded-full border-2 border-[var(--line-strong)] border-t-[var(--teal)]" />
        <p className="text-sm font-bold text-[var(--ink-soft)]">Opening the operating workspace…</p>
      </div>
    </main>
  );
}
