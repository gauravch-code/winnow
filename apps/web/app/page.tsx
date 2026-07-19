'use client';

import { useEffect, useState } from 'react';
import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import {
  MODE,
  PAGE_SIZE,
  fetchEmails,
  moveEmail,
  retrain,
  syncNow,
  type EmailView,
  type Lane as LaneId,
} from '../lib/api';
import { Lane } from '../components/Lane';

const LANE_ORDER: LaneId[] = ['needs_you', 'informational', 'hidden'];

export default function DashboardPage() {
  const [emails, setEmails] = useState<EmailView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  // PointerSensor with an activation distance so a plain click on the
  // card body doesn't spuriously start a drag.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  useEffect(() => {
    fetchEmails(PAGE_SIZE, 0)
      .then((list) => {
        setEmails(list);
        setHasMore(list.length === PAGE_SIZE);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // Append the next page. A short final page means we've reached the end.
  async function loadMore() {
    if (!emails || loadingMore) return;
    setLoadingMore(true);
    try {
      const next = await fetchEmails(PAGE_SIZE, emails.length);
      setEmails((cur) => (cur ? [...cur, ...next] : next));
      setHasMore(next.length === PAGE_SIZE);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || !emails) return;
    const target = over.id as LaneId;
    const email = emails.find((e) => e.id === active.id);
    if (!email || email.lane === target) return;

    // Optimistic update — snap the card into the new lane immediately.
    const previous = emails;
    setEmails(emails.map((e) => (e.id === email.id ? { ...e, lane: target } : e)));

    try {
      const updated = await moveEmail(email.id, target);
      setEmails((cur) =>
        cur ? cur.map((e) => (e.id === updated.id ? updated : e)) : cur,
      );
    } catch (err) {
      setError(String(err));
      setEmails(previous);
    }
  }

  // Merge an updated email (from escalate lane-change / archive / star)
  // back into board state.
  function handleUpdate(updated: EmailView) {
    setEmails((cur) => (cur ? cur.map((e) => (e.id === updated.id ? updated : e)) : cur));
  }

  const [busy, setBusy] = useState<'sync' | 'retrain' | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  async function reloadFirstPage() {
    const list = await fetchEmails(PAGE_SIZE, 0);
    setEmails(list);
    setHasMore(list.length === PAGE_SIZE);
  }

  async function handleSync() {
    setBusy('sync');
    setStatus('Syncing Gmail…');
    try {
      const r = await syncNow();
      await reloadFirstPage();
      setStatus(`Synced — ${r.ingested} new email${r.ingested === 1 ? '' : 's'}.`);
    } catch (e) {
      setStatus(`Sync failed: ${e}`);
    } finally {
      setBusy(null);
    }
  }

  async function handleRetrain() {
    setBusy('retrain');
    setStatus('Retraining tier-1 on your corrections…');
    try {
      const r = await retrain();
      if (r.deployed) {
        const before = r.previous_active_accuracy;
        const after = r.holdout_accuracy;
        const delta =
          before != null && after != null
            ? ` (${(before * 100).toFixed(0)}% → ${(after * 100).toFixed(0)}% on holdout)`
            : '';
        await reloadFirstPage();
        setStatus(`Retrained and deployed a new model${delta}.`);
      } else {
        setStatus(r.rejection_reason ?? `Retrain: ${r.outcome}`);
      }
    } catch (e) {
      setStatus(`Retrain failed: ${e}`);
    } finally {
      setBusy(null);
    }
  }

  const byLane: Record<LaneId, EmailView[]> = {
    needs_you: [],
    informational: [],
    hidden: [],
  };
  for (const email of emails ?? []) byLane[email.lane].push(email);

  const isReal = MODE === 'real';

  return (
    <main className="min-h-screen p-6 max-w-[1600px] mx-auto">
      <header className="mb-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-semibold">Winnow</h1>
          <span className="text-sm text-white/50">
            {isReal ? 'your inbox · local-first' : 'demo · synthetic data'}
          </span>
          {isReal && (
            <div className="ml-auto flex items-center gap-2">
              {status && <span className="text-xs text-white/50 mr-1">{status}</span>}
              <button
                type="button"
                onClick={handleSync}
                disabled={busy !== null}
                className="rounded-md border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-white/80 hover:bg-white/10 disabled:opacity-50"
              >
                {busy === 'sync' ? 'Syncing…' : 'Sync now'}
              </button>
              <button
                type="button"
                onClick={handleRetrain}
                disabled={busy !== null}
                className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
              >
                {busy === 'retrain' ? 'Retraining…' : 'Retrain'}
              </button>
            </div>
          )}
        </div>
        <p className="text-sm text-white/60 mt-1">
          {isReal
            ? 'Your Gmail, triaged on your machine by the local classifier. Drag to correct a lane (it learns from every move), or click “ask LLM” to escalate an email to the tier-2 agent with your own key.'
            : 'Drag any email into a different lane — the classifier retrains on your edits. Click “ask LLM” to see the pre-recorded tier-2 response.'}
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {emails === null ? (
        <div className="text-white/50">Loading{isReal ? ' your inbox' : ' synthetic inbox'}…</div>
      ) : emails.length === 0 && isReal ? (
        <div className="text-white/50">
          No emails yet. Run <code className="text-emerald-300/80">winnow gmail sync --full</code>{' '}
          to pull and triage your inbox, then refresh.
        </div>
      ) : (
        <>
          <div className="mb-3 text-xs text-white/40">
            Showing {emails.length} email{emails.length === 1 ? '' : 's'}
            {isReal ? ' · newest first' : ''}
          </div>
          <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
            <div className="flex gap-4 items-start">
              {LANE_ORDER.map((id) => (
                <Lane key={id} id={id} emails={byLane[id]} onUpdate={handleUpdate} />
              ))}
            </div>
          </DndContext>
          {hasMore && (
            <div className="mt-6 flex justify-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-md border border-white/15 bg-white/5 px-5 py-2 text-sm text-white/80 hover:bg-white/10 disabled:opacity-50"
              >
                {loadingMore ? 'Loading…' : `Load ${PAGE_SIZE} more`}
              </button>
            </div>
          )}
        </>
      )}
    </main>
  );
}
