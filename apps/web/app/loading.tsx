export default function Loading() {
  return (
    <main
      className="grid min-h-screen place-items-center px-6"
      id="main-content"
      tabIndex={-1}
    >
      <div aria-live="polite" className="text-center" role="status">
        <span
          aria-hidden="true"
          className="mx-auto mb-5 block h-10 w-10 animate-spin rounded-full border-2 border-[var(--line-strong)] border-t-[var(--teal)]"
        />
        <p className="text-sm font-bold text-[var(--ink-soft)]">
          Opening the operating workspace…
        </p>
      </div>
    </main>
  );
}
