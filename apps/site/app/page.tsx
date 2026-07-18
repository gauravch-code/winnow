import Link from 'next/link';
import { ArchitectureDiagram } from '../components/ArchitectureDiagram';

const GITHUB_URL = 'https://github.com/gauravch-code/winnow';
const LINKEDIN_URL = 'https://www.linkedin.com/in/gaurav-pvt/';

export default function LandingPage() {
  return (
    <main className="min-h-screen">
      {/* ---------- Hero ---------- */}
      <section className="hero-grid border-b border-white/5">
        <div className="mx-auto max-w-6xl px-6 pt-16 pb-24 sm:pt-24 sm:pb-32">
          <div className="flex items-center gap-2 text-xs text-emerald-300/80 mb-6">
            <span className="rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5">
              v0.7-learning
            </span>
            <span className="text-white/40">·</span>
            <span className="text-white/60">local-first · MIT · Python + TypeScript</span>
          </div>

          <h1 className="text-4xl sm:text-6xl font-semibold tracking-tight leading-[1.05]">
            Your inbox, triaged
            <br />
            <span className="text-winnow-accent">on your machine.</span>
          </h1>

          <p className="mt-6 max-w-2xl text-lg text-white/70 leading-relaxed">
            Winnow is a self-hosted Gmail triage agent. A small classifier on your laptop handles
            80%+ of routing in milliseconds. An LLM sees only the cases the classifier isn't sure
            about — and only if you opt in with your own API key.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/demo"
              className="inline-flex items-center gap-2 rounded-md bg-winnow-accent px-5 py-2.5 text-sm font-semibold text-black hover:bg-emerald-300 transition-colors"
            >
              Try the demo →
            </Link>
            <a
              href={GITHUB_URL}
              className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-5 py-2.5 text-sm font-semibold text-white/80 hover:bg-white/10 transition-colors"
            >
              View source
            </a>
          </div>

          <div className="mt-10 flex flex-wrap gap-x-6 gap-y-2 text-sm text-white/50">
            <span>200 synthetic emails</span>
            <span>·</span>
            <span>real live classifier in your browser session</span>
            <span>·</span>
            <span>pre-recorded LLM responses</span>
            <span>·</span>
            <span>zero visitor cost</span>
          </div>
        </div>
      </section>

      {/* ---------- Architecture ---------- */}
      <section className="border-b border-white/5 py-20">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mb-10">
            <div className="text-xs uppercase tracking-wider text-emerald-400/70 mb-2">
              architecture
            </div>
            <h2 className="text-3xl font-semibold">Two tiers. One decision per email.</h2>
            <p className="mt-3 max-w-2xl text-white/60">
              Existing "AI inbox" tools are either hosted SaaS that see all your email, or thin
              wrappers that call an LLM on every message. Winnow does neither.
            </p>
          </div>
          <div className="rounded-lg border border-white/10 bg-black/40 p-6 sm:p-10 overflow-x-auto">
            <ArchitectureDiagram />
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-3 text-sm">
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <div className="text-xs text-emerald-300/80 mb-1">tier 1 · local · ~free</div>
              <div className="text-white/80">
                scikit-learn LogReg over engineered features + MiniLM subject embeddings. Retrains
                nightly on your own drag actions.
              </div>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <div className="text-xs text-amber-300/80 mb-1">tier 2 · LLM · opt-in</div>
              <div className="text-white/80">
                PydanticAI agent with structured output. Escalated only when tier 1's confidence
                falls below your threshold. Your key, your provider, your machine.
              </div>
            </div>
            <div className="rounded border border-white/10 bg-white/5 p-4">
              <div className="text-xs text-white/50 mb-1">learning loop</div>
              <div className="text-white/80">
                Every action — archive, star, drag between lanes, edit draft — becomes a labeled
                training example the classifier will see tomorrow.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- Evals ---------- */}
      <section className="border-b border-white/5 py-20">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mb-8">
            <div className="text-xs uppercase tracking-wider text-emerald-400/70 mb-2">evals</div>
            <h2 className="text-3xl font-semibold">Numbers, not vibes.</h2>
            <p className="mt-3 max-w-2xl text-white/60">
              Tier 1 baseline, measured by 5-fold cross-validation on the current 200-email
              synthetic corpus. The full harness (pure-LLM vs pure-classifier vs tiered on a
              held-out realistic set with per-1000-email cost + latency) lands with v1.0.
            </p>
          </div>

          <div className="overflow-x-auto rounded-lg border border-white/10">
            <table className="w-full text-sm">
              <thead className="bg-white/5 text-white/60">
                <tr>
                  <th className="text-left px-4 py-3 font-medium">lane</th>
                  <th className="text-right px-4 py-3 font-medium">precision</th>
                  <th className="text-right px-4 py-3 font-medium">recall</th>
                  <th className="text-right px-4 py-3 font-medium">latency (p50)</th>
                  <th className="text-right px-4 py-3 font-medium">cost / 1k emails</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-white/10">
                  <td className="px-4 py-3 text-emerald-300/90">needs_you</td>
                  <td className="px-4 py-3 text-right tabular-nums">1.00</td>
                  <td className="px-4 py-3 text-right tabular-nums">1.00</td>
                  <td className="px-4 py-3 text-right tabular-nums">~5 ms</td>
                  <td className="px-4 py-3 text-right tabular-nums">$0.00</td>
                </tr>
                <tr className="border-t border-white/10">
                  <td className="px-4 py-3 text-blue-300/90">informational</td>
                  <td className="px-4 py-3 text-right tabular-nums">1.00</td>
                  <td className="px-4 py-3 text-right tabular-nums">1.00</td>
                  <td className="px-4 py-3 text-right tabular-nums">~5 ms</td>
                  <td className="px-4 py-3 text-right tabular-nums">$0.00</td>
                </tr>
                <tr className="border-t border-white/10">
                  <td className="px-4 py-3 text-white/50">hidden</td>
                  <td className="px-4 py-3 text-right tabular-nums">1.00</td>
                  <td className="px-4 py-3 text-right tabular-nums">1.00</td>
                  <td className="px-4 py-3 text-right tabular-nums">~5 ms</td>
                  <td className="px-4 py-3 text-right tabular-nums">$0.00</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-xs text-white/40 max-w-2xl">
            <strong className="text-white/60">honest caveat:</strong> 100% on synthetic data is a
            plumbing check, not a quality claim. The synthetic ground truth is deterministic from
            category, and the sender-domain features leak that signal. The v1.0 eval uses noised
            labels + held-out real Gmail categories.
          </p>
        </div>
      </section>

      {/* ---------- How the demo works ---------- */}
      <section className="border-b border-white/5 py-20 bg-black/20">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mb-8">
            <div className="text-xs uppercase tracking-wider text-emerald-400/70 mb-2">
              how the demo works
            </div>
            <h2 className="text-3xl font-semibold">$0, guaranteed. Honest about it.</h2>
          </div>

          <div className="grid gap-6 sm:grid-cols-2">
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-6">
              <div className="text-xs text-emerald-300/80 uppercase tracking-wider mb-2">
                live in your browser
              </div>
              <div className="text-lg font-semibold mb-2">Tier 1 classifier</div>
              <p className="text-sm text-white/70">
                Runs genuine inference on every card. Retrains on your drags within your session.
                Session state is namespaced by cookie; nothing bleeds between visitors.
              </p>
            </div>

            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-6">
              <div className="text-xs text-amber-300/80 uppercase tracking-wider mb-2">
                pre-recorded
              </div>
              <div className="text-lg font-semibold mb-2">Tier 2 LLM responses</div>
              <p className="text-sm text-white/70">
                Every "ask LLM" click resolves to a committed fixture, generated once against a
                real Anthropic call. The demo simulates the real latency (~1.2 s) and streams the
                response. Zero API calls happen when you click.
              </p>
            </div>
          </div>

          <div className="mt-6 rounded-lg border border-white/10 bg-black/40 p-5 text-sm text-white/70">
            <div className="text-white/50 mb-1">why the split matters</div>
            <p>
              The classifier is free to run for real — CPU only, no API. The LLM tier is where the
              money would go, so the demo hard-codes it: every tier-2 response is a{' '}
              <code className="rounded bg-white/10 px-1 py-0.5 text-emerald-300/90 text-xs">
                packages/seed-data/llm-responses/{'{seed_id}'}.json
              </code>{' '}
              file committed to the repo. Novel emails you add during the session return a graceful{' '}
              <em>"run locally with your own key"</em> card instead. This is the whole point of the
              two-tier architecture in one sentence.
            </p>
          </div>
        </div>
      </section>

      {/* ---------- Out of scope ---------- */}
      <section className="border-b border-white/5 py-16">
        <div className="mx-auto max-w-6xl px-6">
          <div className="mb-6">
            <div className="text-xs uppercase tracking-wider text-emerald-400/70 mb-2">
              explicitly out of scope
            </div>
            <h2 className="text-2xl font-semibold">What Winnow won't do</h2>
          </div>
          <ul className="grid gap-2 sm:grid-cols-2 text-sm text-white/70">
            <li>· Multi-account support (one Gmail, one owner)</li>
            <li>· Non-Gmail providers (Fastmail, Outlook, etc.)</li>
            <li>· Team or shared inboxes</li>
            <li>· Mobile app</li>
            <li>· Calendar integration</li>
            <li>· Auto-sending replies (drafts only)</li>
            <li>· Live LLM calls in this public demo</li>
            <li>· Hosting Winnow-as-a-service for other people's inboxes</li>
          </ul>
        </div>
      </section>

      {/* ---------- Footer ---------- */}
      <footer className="py-12">
        <div className="mx-auto max-w-6xl px-6 flex flex-wrap items-center justify-between gap-4 text-sm text-white/50">
          <div>Winnow — a portfolio project by Gaurav.</div>
          <div className="flex gap-4">
            <a href={GITHUB_URL} className="hover:text-white/80">
              GitHub
            </a>
            <a href={LINKEDIN_URL} className="hover:text-white/80">
              LinkedIn
            </a>
            <Link href="/demo" className="hover:text-white/80">
              Demo
            </Link>
          </div>
        </div>
      </footer>
    </main>
  );
}
