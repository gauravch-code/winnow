/**
 * Fetch wrapper. Same shape as apps/web/lib/api.ts but adds the
 * escalate endpoint (which the local app also has server-side; the
 * public demo is where visitors actually click it).
 *
 * All requests go through Next.js /api/* rewrites so the browser sees
 * one origin and cookies stay SameSite=Lax.
 */
export type Lane = 'needs_you' | 'informational' | 'hidden';

export interface TopFeature {
  name: string;
  value: number;
  weight: number;
}

export interface EmailView {
  id: string;
  seed_email_id: string | null;
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

export interface EscalateResponse {
  email_id: string;
  route: 'tier_1_only' | 'escalated_to_tier_2' | 'tier_2_unavailable';
  tier_2_source: 'live' | 'prerecorded' | 'unavailable';
  reason_unavailable: string | null;
  lane: Lane | null;
  confidence: number | null;
  reasoning: string | null;
  draft_included: boolean | null;
  draft_subject: string | null;
  draft_body_markdown: string | null;
  draft_tone: string | null;
  draft_assumptions: string[] | null;
  signals: { name: string; weight: number }[] | null;
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  return (await res.json()) as T;
}

export async function fetchEmails(): Promise<EmailView[]> {
  return j<EmailView[]>(
    await fetch('/api/demo/emails', { credentials: 'include', cache: 'no-store' }),
  );
}

export async function moveEmail(id: string, to_lane: Lane): Promise<EmailView> {
  return j<EmailView>(
    await fetch(`/api/demo/emails/${id}/lane`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_lane }),
    }),
  );
}

export async function escalateEmail(id: string): Promise<EscalateResponse> {
  return j<EscalateResponse>(
    await fetch(`/api/demo/emails/${id}/escalate`, {
      method: 'POST',
      credentials: 'include',
    }),
  );
}
