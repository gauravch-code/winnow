'use client';

import { useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import type { EmailView, TopFeature } from '../lib/api';

// Friendly labels for the engineered feature names emitted by the API.
// Anything not in this map falls through to a lightly-humanized version
// of the raw name.
const FEATURE_LABELS: Record<string, string> = {
  email_content_signal: 'email content (embedding)',
  sender_is_notification_domain: 'sender: notification service',
  sender_is_receipt_domain: 'sender: receipt service',
  sender_is_personal_domain: 'sender: personal email',
  sender_is_suspicious_tld: 'sender: suspicious TLD',
  has_unsubscribe: 'has unsubscribe link',
  is_reply: 'is a reply in a thread',
  thread_depth_capped: 'thread depth',
  log_subject_length: 'subject length',
  log_body_length: 'body length',
  subject_question_marks: 'question marks in subject',
  body_question_marks: 'question marks in body',
  urgency_word_count: 'urgency words',
  recipient_count: 'total recipients',
  cc_count: 'people cc’d',
  hour_sin: 'time of day',
  hour_cos: 'time of day',
  dow_sin: 'day of week',
  dow_cos: 'day of week',
};

function label(name: string): string {
  return FEATURE_LABELS[name] ?? name.replaceAll('_', ' ');
}

export function EmailCard({ email }: { email: EmailView }) {
  const [expanded, setExpanded] = useState(false);
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: email.id,
    data: { email },
  });

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.4 : 1,
  };

  const displayName = email.sender_name ?? email.sender_email;
  const timeLabel = new Date(email.received_at).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className="cursor-grab active:cursor-grabbing rounded-md border border-white/10 bg-white/5 p-3 text-sm shadow-sm hover:bg-white/10 transition-colors"
    >
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="font-medium truncate">{displayName}</span>
        <span className="text-xs text-white/40 shrink-0">{timeLabel}</span>
      </div>
      <div className="font-medium text-white/90 truncate">{email.subject}</div>
      <div className="text-white/60 mt-1 line-clamp-2">{email.snippet}</div>

      <div className="flex items-center gap-2 mt-2">
        <ConfidenceBadge tier={email.tier} confidence={email.confidence} />
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => setExpanded((v) => !v)}
          className="ml-auto text-[11px] text-white/50 hover:text-white/80 underline underline-offset-2"
        >
          {expanded ? 'hide why' : 'why?'}
        </button>
      </div>

      {expanded && <Explanation email={email} />}
    </div>
  );
}

function ConfidenceBadge({ tier, confidence }: { tier: number; confidence: number }) {
  const pct = Math.round(confidence * 100);
  const bar = Math.max(4, Math.round(confidence * 40));
  return (
    <div className="flex items-center gap-2 text-[11px] text-white/50">
      <span className="rounded bg-white/10 px-1.5 py-0.5">T{tier}</span>
      <div className="h-1 w-10 rounded bg-white/10 overflow-hidden">
        <div className="h-full bg-emerald-400/70" style={{ width: `${bar}px` }} />
      </div>
      <span className="tabular-nums">{pct}%</span>
    </div>
  );
}

function Explanation({ email }: { email: EmailView }) {
  const top: TopFeature[] = email.top_features ?? [];
  const maxAbs = top.reduce((m, f) => Math.max(m, Math.abs(f.weight)), 1);
  return (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      className="mt-3 pt-3 border-t border-white/10 space-y-2 cursor-default"
    >
      {email.reasoning && (
        <div className="text-xs text-white/60">{email.reasoning}</div>
      )}
      <ul className="space-y-1">
        {top.map((f) => {
          const pct = Math.round((Math.abs(f.weight) / maxAbs) * 100);
          const positive = f.weight >= 0;
          return (
            <li key={f.name} className="text-[11px] flex items-center gap-2">
              <span className="w-32 truncate text-white/60">{label(f.name)}</span>
              <div className="flex-1 h-1 rounded bg-white/5 overflow-hidden">
                <div
                  className={`h-full ${positive ? 'bg-emerald-400/70' : 'bg-rose-400/70'}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span
                className={`w-12 text-right tabular-nums ${
                  positive ? 'text-emerald-300/80' : 'text-rose-300/80'
                }`}
              >
                {f.weight >= 0 ? '+' : ''}
                {f.weight.toFixed(2)}
              </span>
            </li>
          );
        })}
      </ul>
      {email.classifier_version && (
        <div className="text-[10px] text-white/30">
          classifier {email.classifier_version}
        </div>
      )}
    </div>
  );
}
