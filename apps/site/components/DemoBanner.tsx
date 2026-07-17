export function DemoBanner() {
  return (
    <div className="border-b border-emerald-500/20 bg-emerald-500/5 px-4 py-2 text-xs text-emerald-100/80">
      <div className="mx-auto max-w-[1600px] flex items-center gap-3 flex-wrap">
        <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-emerald-200">
          demo
        </span>
        <span>
          Synthetic data — no real inbox is touched. Tier 1 classifier is running{' '}
          <span className="text-emerald-300">live</span> in your session. Tier 2 LLM responses are{' '}
          <span className="text-amber-300">pre-recorded</span> to keep the demo free and abuse-proof.
        </span>
        <a
          href="/"
          className="ml-auto rounded border border-white/10 px-2 py-0.5 text-white/70 hover:bg-white/10"
        >
          about this demo
        </a>
      </div>
    </div>
  );
}
