'use client';

import { useEffect, useState } from 'react';
import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { fetchEmails, moveEmail, type EmailView, type Lane as LaneId } from '../lib/api';
import { Lane } from '../components/Lane';

const LANE_ORDER: LaneId[] = ['needs_you', 'informational', 'hidden'];

export default function DemoPage() {
  const [emails, setEmails] = useState<EmailView[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // PointerSensor with an activation distance so a plain click on the
  // card body doesn't spuriously start a drag.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  useEffect(() => {
    fetchEmails()
      .then(setEmails)
      .catch((e) => setError(String(e)));
  }, []);

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

  const byLane: Record<LaneId, EmailView[]> = {
    needs_you: [],
    informational: [],
    hidden: [],
  };
  for (const email of emails ?? []) byLane[email.lane].push(email);

  return (
    <main className="min-h-screen p-6 max-w-[1600px] mx-auto">
      <header className="mb-6">
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-semibold">Winnow</h1>
          <span className="text-sm text-white/50">demo · synthetic data</span>
        </div>
        <p className="text-sm text-white/60 mt-1">
          Drag any email into a different lane. The classifier tier is not wired up yet — that
          lands in Step 4. Tier-2 LLM responses in this demo are pre-recorded to keep it free.
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {emails === null ? (
        <div className="text-white/50">Loading synthetic inbox…</div>
      ) : (
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <div className="flex gap-4 items-start">
            {LANE_ORDER.map((id) => (
              <Lane key={id} id={id} emails={byLane[id]} />
            ))}
          </div>
        </DndContext>
      )}
    </main>
  );
}
