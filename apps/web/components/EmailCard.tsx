'use client';

import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';
import type { EmailView } from '../lib/api';

export function EmailCard({ email }: { email: EmailView }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: email.id,
    data: { email },
  });

  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.4 : 1,
  };

  const displayName = email.sender_name ?? email.sender_email;
  const received = new Date(email.received_at);
  const timeLabel = received.toLocaleDateString(undefined, {
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
    </div>
  );
}
