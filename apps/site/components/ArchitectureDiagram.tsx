/**
 * Inline SVG architecture diagram. Kept as one file (no external deps,
 * no image asset) so the marketing page has zero runtime image
 * requests and renders identically on any host.
 */
export function ArchitectureDiagram() {
  return (
    <svg
      viewBox="0 0 900 320"
      xmlns="http://www.w3.org/2000/svg"
      className="w-full h-auto max-w-4xl"
      role="img"
      aria-label="Winnow tiered architecture. Emails flow from Gmail into a local classifier. High-confidence decisions are final. Low-confidence cases escalate to an LLM."
    >
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#4b5563" />
        </marker>
        <marker id="arrow-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#34d399" />
        </marker>
        <marker id="arrow-amber" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#fbbf24" />
        </marker>
      </defs>

      {/* Gmail */}
      <g>
        <rect x="20" y="120" width="140" height="80" rx="8" fill="#1f2937" stroke="#374151" />
        <text x="90" y="150" textAnchor="middle" fill="#e5e7eb" fontSize="14" fontWeight="600">
          Gmail
        </text>
        <text x="90" y="170" textAnchor="middle" fill="#9ca3af" fontSize="11">
          incoming email
        </text>
        <text x="90" y="188" textAnchor="middle" fill="#9ca3af" fontSize="11">
          via Pub/Sub
        </text>
      </g>

      {/* Arrow to Tier 1 */}
      <line x1="160" y1="160" x2="290" y2="160" stroke="#4b5563" strokeWidth="2" markerEnd="url(#arrow)" />

      {/* Tier 1 — Local Classifier */}
      <g>
        <rect x="290" y="90" width="220" height="140" rx="8" fill="#0f172a" stroke="#34d399" strokeWidth="2" />
        <text x="400" y="118" textAnchor="middle" fill="#34d399" fontSize="12" fontWeight="600">
          TIER 1 — LOCAL, ~FREE
        </text>
        <text x="400" y="145" textAnchor="middle" fill="#e5e7eb" fontSize="15" fontWeight="600">
          scikit-learn + MiniLM
        </text>
        <text x="400" y="170" textAnchor="middle" fill="#9ca3af" fontSize="12">
          engineered features + 384-dim embeddings
        </text>
        <text x="400" y="188" textAnchor="middle" fill="#9ca3af" fontSize="12">
          ~5 ms per email, CPU-only
        </text>
        <text x="400" y="212" textAnchor="middle" fill="#34d399" fontSize="12" fontStyle="italic">
          handles 80%+ of routing
        </text>
      </g>

      {/* Confidence gate */}
      <g>
        <path
          d="M 510 160 L 590 100"
          stroke="#34d399"
          strokeWidth="2"
          fill="none"
          markerEnd="url(#arrow-green)"
        />
        <text x="530" y="110" fill="#34d399" fontSize="11" fontWeight="600">
          confident
        </text>

        <path
          d="M 510 160 L 590 240"
          stroke="#fbbf24"
          strokeWidth="2"
          fill="none"
          strokeDasharray="4 4"
          markerEnd="url(#arrow-amber)"
        />
        <text x="530" y="220" fill="#fbbf24" fontSize="11" fontWeight="600">
          uncertain
        </text>
      </g>

      {/* Decision — top branch */}
      <g>
        <rect x="590" y="60" width="290" height="80" rx="8" fill="#052e2b" stroke="#34d399" />
        <text x="735" y="88" textAnchor="middle" fill="#34d399" fontSize="12" fontWeight="600">
          DECISION FINAL
        </text>
        <text x="735" y="110" textAnchor="middle" fill="#e5e7eb" fontSize="13">
          route to lane, done
        </text>
        <text x="735" y="128" textAnchor="middle" fill="#9ca3af" fontSize="11">
          no network, no LLM cost
        </text>
      </g>

      {/* Tier 2 — LLM */}
      <g>
        <rect x="590" y="200" width="290" height="100" rx="8" fill="#1a1408" stroke="#fbbf24" strokeWidth="2" />
        <text x="735" y="228" textAnchor="middle" fill="#fbbf24" fontSize="12" fontWeight="600">
          TIER 2 — LLM, OPT-IN
        </text>
        <text x="735" y="252" textAnchor="middle" fill="#e5e7eb" fontSize="14" fontWeight="600">
          PydanticAI agent
        </text>
        <text x="735" y="270" textAnchor="middle" fill="#9ca3af" fontSize="11">
          Anthropic / OpenAI / Ollama
        </text>
        <text x="735" y="286" textAnchor="middle" fill="#9ca3af" fontSize="11">
          triage + draft, your key, your machine
        </text>
      </g>
    </svg>
  );
}
