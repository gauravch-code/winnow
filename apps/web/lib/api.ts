/**
 * API layer, mode-aware.
 *
 * The same dashboard talks to two backends:
 *  - demo mode  → /api/demo/emails  (session-cookie scoped, synthetic data)
 *  - real mode  → /api/emails       (owner-scoped, your Gmail)
 *
 * Set NEXT_PUBLIC_WINNOW_MODE=real to point at your self-hosted inbox.
 * It defaults to demo. The mode here MUST match the API's WINNOW_MODE —
 * a demo API only serves /demo/*, a real API only serves /emails.
 *
 * `credentials: 'include'` matters in demo mode (the API sets a
 * winnow_session cookie on first request); it's harmless in real mode.
 */
export type Lane = 'needs_you' | 'informational' | 'hidden';

export const MODE: 'demo' | 'real' =
  process.env.NEXT_PUBLIC_WINNOW_MODE === 'real' ? 'real' : 'demo';

const BASE = MODE === 'real' ? '/api/emails' : '/api/demo/emails';

export interface TopFeature {
  name: string;
  value: number;
  weight: number;
}

export interface EmailView {
  id: string;
  seed_email_id?: string | null; // demo only
  gmail_message_id?: string | null; // real only
  sender_email: string;
  sender_name: string | null;
  subject: string;
  snippet: string;
  received_at: string;
  lane: Lane;
  confidence: number;
  tier: number;
  classifier_version: string | null;
  reasoning: string | null;
  top_features: TopFeature[] | null;
}

export interface EscalateResult {
  email_id: string;
  route: string;
  tier_2_source: string;
  reason_unavailable?: string | null;
  lane?: Lane | null;
  confidence?: number | null;
  reasoning?: string | null;
  draft_included?: boolean | null;
  draft_subject?: string | null;
  draft_body_markdown?: string | null;
  draft_tone?: string | null;
  draft_assumptions?: string[] | null;
  signals?: { name: string; weight: number }[] | null;
}

const opts: RequestInit = { credentials: 'include', cache: 'no-store' };

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

export async function fetchEmails(): Promise<EmailView[]> {
  return j<EmailView[]>(await fetch(BASE, opts));
}

export async function moveEmail(id: string, to_lane: Lane): Promise<EmailView> {
  return j<EmailView>(
    await fetch(`${BASE}/${id}/lane`, {
      ...opts,
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_lane }),
    }),
  );
}

export async function escalateEmail(id: string): Promise<EscalateResult> {
  return j<EscalateResult>(
    await fetch(`${BASE}/${id}/escalate`, { ...opts, method: 'POST' }),
  );
}

// Real mode only — archive/star write training signal and re-lane.
export async function archiveEmail(id: string): Promise<EmailView> {
  return j<EmailView>(await fetch(`${BASE}/${id}/archive`, { ...opts, method: 'POST' }));
}

export async function starEmail(id: string): Promise<EmailView> {
  return j<EmailView>(await fetch(`${BASE}/${id}/star`, { ...opts, method: 'POST' }));
}
