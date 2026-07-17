'use client';

import { useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import type { EmailView, EscalateResponse, TopFeature } from '../lib/api';
import { escalateEmail } from '../lib/api';

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
  const [escalating, setEscalating] = useState(false);
  const [tier2, setTier2] = useState<EscalateResponse | null>(null);
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

  async function runEscalate(e: React.MouseEvent) {
    e.stopPropagation();
    if (escalating) return;
    setEscalating(true);
    setExpanded(true);
    try {
      const res = await escalateEmail(email.id);
      setTier2(res);
    } catch (err) {
      setTier2({
        email_id: email.id,
        route: 'tier_2_unavailable',
        tier_2_source: 'unavailable',
        reason_unavailable: String(err),
        lane: null,
        confidence: null,
        reasoning: null,
        draft_included: null,
        draft_subject: null,
        draft_body_markdown: null,
        draft_tone: null,
        draft_assumptions: null,
        signals: null,
      });
    } finally {
      setEscalating(false);
    }
  }

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
          onClick={runEscalate}
          disabled={escalating}
          className="text-[11px] text-emerald-300/80 hover:text-emerald-200 disabled:opacity-50"
        >
          {escalating ? 'thinking…' : 'ask LLM'}
        </button>
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => setExpanded((v) => !v)}
          className="ml-auto text-[11px] text-white/50 hover:text-white/80 underline underline-offset-2"
        >
          {expanded ? 'hide' : 'why?'}
        </button>
      </div>

      {expanded && (
        <ExplanationPanel email={email} tier2={tier2} />
      )}
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

function ExplanationPanel({
  email,
  tier2,
}: {
  email: EmailView;
  tier2: EscalateResponse | null;
}) {
  const top: TopFeature[] = email.top_features ?? [];
  const maxAbs = top.reduce((m, f) => Math.max(m, Math.abs(f.weight)), 1);
  return (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      className="mt-3 pt-3 border-t border-white/10 space-y-2 cursor-default"
    >
      <div className="text-[10px] uppercase tracking-wider text-white/40">tier 1 · classifier</div>
      {email.reasoning && <div className="text-xs text-white/70">{email.reasoning}</div>}
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

      {tier2 && <Tier2Panel res={tier2} />}
    </div>
  );
}

function Tier2Panel({ res }: { res: EscalateResponse }) {
  if (res.tier_2_source === 'unavailable') {
    return (
      <div className="mt-3 pt-3 border-t border-white/10">
        <div className="text-[10px] uppercase tracking-wider text-white/40 mb-1">tier 2 · LLM</div>
        <div className="text-xs text-amber-200/80">
          {res.reason_unavailable ?? 'Tier 2 unavailable for this email.'}
        </div>
      </div>
    );
  }
  return (
    <div className="mt-3 pt-3 border-t border-white/10 space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-white/40">
        tier 2 · LLM{' '}
        <span className="ml-1 rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-200 text-[9px]">
          {res.tier_2_source}
        </span>
      </div>
      <div className="text-xs text-white/70">
        <span className="font-medium">{res.lane}</span> at{' '}
        {res.confidence != null ? Math.round(res.confidence * 100) : '?'}%
      </div>
      {res.reasoning && <div className="text-xs text-white/60 italic">"{res.reasoning}"</div>}
      {res.draft_included && (
        <div className="mt-2 rounded border border-white/10 bg-black/40 p-2 text-[11px]">
          <div className="text-white/40 mb-1">draft · {res.draft_tone ?? 'neutral'}</div>
          <div className="text-white/70 mb-1 font-medium">{res.draft_subject}</div>
          <pre className="whitespace-pre-wrap text-white/80 font-sans text-[11px]">
            {res.draft_body_markdown}
          </pre>
          {res.draft_assumptions && res.draft_assumptions.length > 0 && (
            <div className="mt-2 text-white/40 text-[10px]">
              assumes: {res.draft_assumptions.join('; ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
