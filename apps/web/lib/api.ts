/**
 * Thin fetch wrapper.
 *
 * `credentials: 'include'` is required so the browser sends the
 * `winnow_session` cookie the API set on the first `/api/demo/emails`
 * request. Without it, every request would look like a new visitor
 * and mint a fresh (empty) session.
 */
export type Lane = 'needs_you' | 'informational' | 'hidden';

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
