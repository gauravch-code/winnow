'use client';

import { useDroppable } from '@dnd-kit/core';
import type { EmailView, Lane as LaneId } from '../lib/api';
import { EmailCard } from './EmailCard';

const LANE_META: Record<LaneId, { title: string; accent: string; description: string }> = {
  needs_you: {
    title: 'Needs You',
    accent: 'bg-lane-needs',
    description: 'Direct asks, replies expected, deadlines.',
  },
  informational: {
    title: 'Informational',
    accent: 'bg-lane-info',
    description: 'Newsletters, digests, FYIs.',
  },
  hidden: {
    title: 'Hidden',
    accent: 'bg-lane-hidden',
    description: 'Receipts, notifications, noise.',
  },
};

export function Lane({
  id,
  emails,
  onUpdate,
}: {
  id: LaneId;
  emails: EmailView[];
  onUpdate?: (e: EmailView) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id });
  const meta = LANE_META[id];

  return (
    <div
      ref={setNodeRef}
      className={`flex-1 min-w-0 rounded-lg border border-white/10 bg-black/30 transition-colors ${
        isOver ? 'bg-white/5 border-white/30' : ''
      }`}
    >
      <div className="p-4 border-b border-white/10">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${meta.accent}`} />
          <h2 className="font-semibold text-white/90">{meta.title}</h2>
          <span className="text-xs text-white/40 ml-auto tabular-nums">{emails.length}</span>
        </div>
        <p className="text-xs text-white/40 mt-1">{meta.description}</p>
      </div>
      <div className="p-3 space-y-2 min-h-[300px]">
        {emails.map((email) => (
          <EmailCard key={email.id} email={email} onUpdate={onUpdate} />
        ))}
      </div>
    </div>
  );
}
