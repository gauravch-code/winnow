import Link from 'next/link';

export default function EvalsPage() {
  return (
    <main className="min-h-screen">
      <div className="mx-auto max-w-4xl px-6 py-16">
        <Link href="/" className="text-sm text-white/50 hover:text-white/80">
          ← back
        </Link>
        <h1 className="mt-4 text-3xl font-semibold">Evaluations</h1>
        <p className="mt-3 text-white/60">
          Full harness comparing pure-LLM vs pure-classifier vs tiered on a held-out realistic
          set, with precision, recall, per-1000-email latency, and dollar cost per approach —
          lands with v1.0 (Step 10). Until then, tier-1 baseline numbers are on the landing page.
        </p>
      </div>
    </main>
  );
}
