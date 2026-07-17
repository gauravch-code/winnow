'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { DemoBanner } from '../../components/DemoBanner';
import { Lane } from '../../components/Lane';
import { fetchEmails, moveEmail, type EmailView, type Lane as LaneId } from '../../lib/api';

const LANE_ORDER: LaneId[] = ['needs_you', 'informational', 'hidden'];

export default function DemoPage() {
  const [emails, setEmails] = useState<EmailView[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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

    const previous = emails;
    setEmails(emails.map((e) => (e.id === email.id ? { ...e, lane: target } : e)));

    try {
      const updated = await moveEmail(email.id, target);
      setEmails((cur) => (cur ? cur.map((e) => (e.id === updated.id ? updated : e)) : cur));
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
    <main className="min-h-screen">
      <DemoBanner />

      <div className="px-6 py-6 max-w-[1600px] mx-auto">
        <header className="mb-6 flex items-baseline justify-between flex-wrap gap-3">
          <div>
            <Link href="/" className="text-2xl font-semibold hover:text-emerald-300 transition-colors">
              Winnow
            </Link>
            <span className="ml-3 text-sm text-white/50">
              drag between lanes · click "ask LLM" to escalate any card
            </span>
          </div>
          <div className="flex gap-3 text-xs">
            <span className="rounded border border-white/10 bg-white/5 px-2 py-1 text-white/60">
              tier 1: live
            </span>
            <span className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-amber-200">
              tier 2: pre-recorded
            </span>
          </div>
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
      </div>
    </main>
  );
}
