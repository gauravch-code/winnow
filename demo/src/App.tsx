import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  BarChart3,
  BrainCircuit,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  Cpu,
  FileText,
  FlaskConical,
  Github,
  GripVertical,
  Inbox,
  Info,
  Lock,
  Mail,
  MoreHorizontal,
  RefreshCcw,
  Reply,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Star,
  Target,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react';

type Lane = 'needs_you' | 'informational' | 'hidden';
type View = 'inbox' | 'learning' | 'evals';

type Feature = { label: string; weight: number };
type Email = {
  id: string;
  sender: string;
  address: string;
  initials: string;
  color: string;
  subject: string;
  snippet: string;
  body: string;
  time: string;
  lane: Lane;
  confidence: number;
  tier: 1 | 2;
  unread?: boolean;
  starred?: boolean;
  features: Feature[];
};

const initialEmails: Email[] = [
  {
    id: 'mail_7c21', sender: 'Maya Chen', address: 'maya@northstar.dev', initials: 'MC', color: '#67c7b0',
    subject: 'Can you review the launch brief today?', snippet: 'I incorporated the positioning notes. Could you give the final pass before 3 PM?',
    body: 'Hey Gaurav,\n\nI incorporated the positioning notes from yesterday. Could you give the launch brief a final pass before 3 PM? I am especially unsure about the enterprise section.\n\nThanks,\nMaya',
    time: '9:42 AM', lane: 'needs_you', confidence: 0.96, tier: 1, unread: true,
    features: [{ label: 'Direct question', weight: .88 }, { label: 'Deadline language', weight: .72 }, { label: 'Known collaborator', weight: .51 }],
  },
  {
    id: 'mail_1a04', sender: 'Daniel Ortiz', address: 'daniel@contoso.com', initials: 'DO', color: '#8a9cdf',
    subject: 'Re: API migration decision', snippet: 'One follow-up: should we keep the compatibility layer through October?',
    body: 'One follow-up from the migration review: should we keep the compatibility layer through October, or remove it after the September release? I need your decision for the implementation plan.',
    time: '8:16 AM', lane: 'needs_you', confidence: 0.89, tier: 1,
    features: [{ label: 'Reply in active thread', weight: .81 }, { label: 'Decision requested', weight: .76 }, { label: 'Work sender', weight: .38 }],
  },
  {
    id: 'mail_82bd', sender: 'Priya Shah', address: 'priya@atlaslabs.ai', initials: 'PS', color: '#d9a45b',
    subject: 'Coffee next week?', snippet: 'I will be near your office Tuesday and would love to catch up if you are free.',
    body: 'Hi Gaurav,\n\nI will be near your office Tuesday afternoon and would love to catch up if you are free. Does 2:30 work?\n\nPriya',
    time: 'Yesterday', lane: 'needs_you', confidence: 0.78, tier: 1,
    features: [{ label: 'Personal sender', weight: .62 }, { label: 'Question in body', weight: .55 }, { label: 'Calendar language', weight: .33 }],
  },
  {
    id: 'mail_5e20', sender: 'Linear', address: 'updates@linear.app', initials: 'LI', color: '#7279d8',
    subject: 'ENG-482 moved to In Review', snippet: 'Nora moved “Improve OAuth retry handling” from In Progress to In Review.',
    body: 'Nora moved ENG-482 “Improve OAuth retry handling” from In Progress to In Review. No action is required.',
    time: '10:03 AM', lane: 'informational', confidence: 0.98, tier: 1, unread: true,
    features: [{ label: 'Notification domain', weight: .93 }, { label: 'No action language', weight: .71 }, { label: 'Automated sender', weight: .58 }],
  },
  {
    id: 'mail_29f6', sender: 'Marcus Bell', address: 'marcus@contoso.com', initials: 'MB', color: '#70a9bd',
    subject: 'Q3 planning: meeting notes', snippet: 'Notes from the Q3 planning sync are attached. No action items for you.',
    body: 'Notes from the Q3 planning sync are attached. No action items for you - sharing for visibility.',
    time: 'Yesterday', lane: 'informational', confidence: 0.94, tier: 1,
    features: [{ label: 'No action language', weight: .84 }, { label: 'FYI pattern', weight: .64 }, { label: 'Known collaborator', weight: .29 }],
  },
  {
    id: 'mail_74ab', sender: 'GitHub', address: 'notifications@github.com', initials: 'GH', color: '#89928c',
    subject: '[winnow] CI passed on main', snippet: 'All 166 checks completed successfully for cf93467.',
    body: 'Workflow complete. All 166 checks passed on main for commit cf93467. Duration: 3m 14s.',
    time: 'Mon', lane: 'informational', confidence: 0.91, tier: 1,
    features: [{ label: 'Notification domain', weight: .87 }, { label: 'Status update', weight: .59 }, { label: 'No question', weight: .31 }],
  },
  {
    id: 'mail_33de', sender: 'Stripe', address: 'receipts@stripe.com', initials: 'ST', color: '#8f82da',
    subject: 'Receipt from Acme Co #69799', snippet: 'Amount charged: $67.92. Card ending 4242.',
    body: 'Payment receipt\n\nAmount charged: $67.92\nCard ending 4242.\n\nThank you for your payment.',
    time: '7:14 AM', lane: 'hidden', confidence: 0.99, tier: 1,
    features: [{ label: 'Receipt domain', weight: .96 }, { label: 'Transaction pattern', weight: .79 }, { label: 'Unsubscribe footer', weight: .24 }],
  },
  {
    id: 'mail_a921', sender: 'Product Weekly', address: 'digest@productweekly.co', initials: 'PW', color: '#d16e7c',
    subject: 'The quiet shift in AI interfaces', snippet: 'Issue 214: invisible agents, adaptive workflows, and five products worth studying.',
    body: 'This week: invisible agents, adaptive workflows, and five products worth studying. You are receiving this because you subscribed to Product Weekly.',
    time: '6:30 AM', lane: 'hidden', confidence: 0.97, tier: 1,
    features: [{ label: 'Newsletter domain', weight: .91 }, { label: 'Unsubscribe footer', weight: .82 }, { label: 'Bulk sender', weight: .45 }],
  },
  {
    id: 'mail_c018', sender: 'Amazon', address: 'auto-confirm@amazon.com', initials: 'AZ', color: '#cc935d',
    subject: 'Your order is arriving Friday', snippet: 'Order total: $147.10. Track your package.',
    body: 'Your order has shipped and is arriving Friday. Order total: $147.10. Track your package from your orders page.',
    time: 'Sun', lane: 'hidden', confidence: 0.96, tier: 1,
    features: [{ label: 'Receipt domain', weight: .86 }, { label: 'Order pattern', weight: .74 }, { label: 'Automated sender', weight: .57 }],
  },
];

const laneMeta: Record<Lane, { title: string; eyebrow: string; icon: typeof Target; tone: string }> = {
  needs_you: { title: 'Needs you', eyebrow: 'Respond or decide', icon: Target, tone: 'mint' },
  informational: { title: 'Informational', eyebrow: 'Read when useful', icon: Info, tone: 'blue' },
  hidden: { title: 'Auto-hidden', eyebrow: 'Cleared from focus', icon: Archive, tone: 'coral' },
};

function BrandMark() {
  return <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>;
}

function App() {
  const [emails, setEmails] = useState(initialEmails);
  const [view, setView] = useState<View>('inbox');
  const [filter, setFilter] = useState<Lane | 'all'>('all');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState(initialEmails[0].id);
  const [guideOpen, setGuideOpen] = useState(true);
  const [tourStep, setTourStep] = useState<number | null>(null);
  const [trainingCount, setTrainingCount] = useState(18);
  const [draftState, setDraftState] = useState<'idle' | 'loading' | 'ready'>('idle');
  const [retrainState, setRetrainState] = useState<'idle' | 'running' | 'done'>('idle');
  const [toast, setToast] = useState<string | null>(null);
  const selected = emails.find((email) => email.id === selectedId) ?? null;

  const filteredEmails = useMemo(() => emails.filter((email) => {
    const inLane = filter === 'all' || email.lane === filter;
    const term = search.trim().toLowerCase();
    return inLane && (!term || `${email.sender} ${email.subject} ${email.snippet}`.toLowerCase().includes(term));
  }), [emails, filter, search]);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 2400);
  }

  function moveEmail(id: string, lane: Lane) {
    const email = emails.find((item) => item.id === id);
    if (!email || email.lane === lane) return;
    setEmails((current) => current.map((item) => item.id === id ? { ...item, lane, confidence: .99 } : item));
    setTrainingCount((count) => count + 1);
    notify(`Correction saved. ${email.sender} will teach the next local model.`);
  }

  function toggleStar(id: string) {
    setEmails((current) => current.map((email) => email.id === id ? { ...email, starred: !email.starred } : email));
    notify('Preference captured as a learning signal.');
  }

  function archiveSelected() {
    if (!selected) return;
    moveEmail(selected.id, 'hidden');
  }

  function askAi() {
    setDraftState('loading');
    window.setTimeout(() => setDraftState('ready'), 1100);
  }

  function runRetrain() {
    setRetrainState('running');
    window.setTimeout(() => {
      setRetrainState('done');
      notify('v1.9 passed the guardrail and is now active.');
    }, 1500);
  }

  function startTour() {
    setGuideOpen(false);
    setView('inbox');
    setFilter('all');
    setTourStep(0);
  }

  const tour = [
    { view: 'inbox' as View, label: 'The local pass', title: 'Start with a calm inbox', copy: 'Tier 1 sorted these synthetic emails locally in milliseconds. Open any message to inspect the decision.' },
    { view: 'inbox' as View, label: 'Explainability', title: 'No mystery labels', copy: 'The reading pane shows the signed signals behind every route. Correct a lane and that action becomes training data.' },
    { view: 'learning' as View, label: 'Learning loop', title: 'Your actions improve the model', copy: 'Moves, stars, archives, and draft edits are labeled examples. Retraining deploys only when the holdout score does not regress.' },
    { view: 'evals' as View, label: 'Measured tradeoff', title: 'Use the LLM like a scalpel', copy: 'Winnow escalates only uncertain cases. The evaluation view makes accuracy, latency, and cost visible.' },
  ];

  function advanceTour() {
    if (tourStep === null) return;
    if (tourStep === tour.length - 1) {
      setTourStep(null);
      setView('inbox');
      notify('Tour complete. Try correcting an email or asking Tier 2.');
      return;
    }
    const next = tourStep + 1;
    setTourStep(next);
    setView(tour[next].view);
  }

  return <div className="app-shell">
    <Sidebar view={view} setView={setView} emails={emails} filter={filter} setFilter={setFilter} />
    <main className="workspace">
      <Topbar search={search} setSearch={setSearch} openGuide={() => setGuideOpen(true)} notify={notify} />
      {view === 'inbox' && <InboxView emails={filteredEmails} allEmails={emails} selected={selected} setSelected={setSelectedId} filter={filter} setFilter={setFilter} moveEmail={moveEmail} toggleStar={toggleStar} archiveSelected={archiveSelected} draftState={draftState} askAi={askAi} />}
      {view === 'learning' && <LearningView trainingCount={trainingCount} state={retrainState} run={runRetrain} />}
      {view === 'evals' && <EvalsView />}
    </main>
    {guideOpen && <Welcome close={() => setGuideOpen(false)} start={startTour} />}
    {tourStep !== null && <TourCoach step={tourStep} tour={tour} next={advanceTour} close={() => setTourStep(null)} />}
    {toast && <div className="toast"><CheckCircle2 size={16} />{toast}</div>}
  </div>;
}

function Sidebar({ view, setView, emails, filter, setFilter }: { view: View; setView: (view: View) => void; emails: Email[]; filter: Lane | 'all'; setFilter: (lane: Lane | 'all') => void }) {
  const unread = emails.filter((email) => email.unread).length;
  const nav = [
    { id: 'inbox' as View, label: 'Inbox', icon: Inbox, count: unread },
    { id: 'learning' as View, label: 'Learning', icon: BrainCircuit },
    { id: 'evals' as View, label: 'Evals', icon: FlaskConical },
  ];
  return <aside className="sidebar">
    <div className="brand"><BrandMark /><div><strong>Winnow</strong><span>Local-first triage</span></div></div>
    <nav className="primary-nav" aria-label="Workspace">
      {nav.map(({ id, label, icon: Icon, count }) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}><Icon size={17} /><span>{label}</span>{count ? <b>{count}</b> : null}</button>)}
    </nav>
    <div className="sidebar-rule" />
    <p className="nav-label">Lanes</p>
    <nav className="lane-nav" aria-label="Email lanes">
      <button className={view === 'inbox' && filter === 'all' ? 'active' : ''} onClick={() => { setView('inbox'); setFilter('all'); }}><Mail size={15} /><span>All mail</span><b>{emails.length}</b></button>
      {(Object.keys(laneMeta) as Lane[]).map((lane) => {
        const meta = laneMeta[lane]; const Icon = meta.icon;
        return <button key={lane} className={view === 'inbox' && filter === lane ? `active ${meta.tone}` : meta.tone} onClick={() => { setView('inbox'); setFilter(lane); }}><Icon size={15} /><span>{meta.title}</span><b>{emails.filter((email) => email.lane === lane).length}</b></button>;
      })}
    </nav>
    <div className="privacy-card"><Lock size={15} /><div><strong>Private by default</strong><span>92% handled locally</span></div></div>
    <a className="repo-link" href="https://github.com/gauravch-code/winnow" target="_blank" rel="noreferrer"><Github size={15} /><span>View source</span><ArrowRight size={13} /></a>
  </aside>;
}

function Topbar({ search, setSearch, openGuide, notify }: { search: string; setSearch: (value: string) => void; openGuide: () => void; notify: (value: string) => void }) {
  return <header className="topbar">
    <div className="search"><Search size={16} /><input aria-label="Search synthetic inbox" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search synthetic inbox" /><kbd>⌘ K</kbd></div>
    <div className="top-actions">
      <span className="demo-pill"><ShieldCheck size={14} />Demo · no keys</span>
      <button className="quiet-action" onClick={openGuide}><CircleHelp size={16} /><span>How it works</span></button>
      <button className="sync-button" onClick={() => notify('Inbox synced. 3 new messages classified locally.')}><RefreshCcw size={15} /><span>Sync inbox</span></button>
      <span className="avatar">GC</span>
    </div>
  </header>;
}

function InboxView({ emails, allEmails, selected, setSelected, filter, setFilter, moveEmail, toggleStar, archiveSelected, draftState, askAi }: { emails: Email[]; allEmails: Email[]; selected: Email | null; setSelected: (id: string) => void; filter: Lane | 'all'; setFilter: (lane: Lane | 'all') => void; moveEmail: (id: string, lane: Lane) => void; toggleStar: (id: string) => void; archiveSelected: () => void; draftState: 'idle' | 'loading' | 'ready'; askAi: () => void }) {
  return <div className="inbox-view">
    <section className="mail-list">
      <div className="section-head">
        <div><p>FOCUS INBOX</p><h1>{filter === 'all' ? 'Today' : laneMeta[filter].title}</h1><span>{emails.length} synthetic messages · newest first</span></div>
        <button className="icon-button" aria-label="Filter messages" title="Filter messages"><SlidersHorizontal size={17} /></button>
      </div>
      <div className="lane-tabs">
        <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>All <b>{allEmails.length}</b></button>
        {(Object.keys(laneMeta) as Lane[]).map((lane) => <button key={lane} className={filter === lane ? 'active' : ''} onClick={() => setFilter(lane)}>{laneMeta[lane].title} <b>{allEmails.filter((email) => email.lane === lane).length}</b></button>)}
      </div>
      <div className="messages">
        {emails.map((email) => <EmailRow key={email.id} email={email} active={selected?.id === email.id} onClick={() => setSelected(email.id)} onStar={() => toggleStar(email.id)} />)}
        {emails.length === 0 && <div className="empty"><Search size={22} /><strong>No matching messages</strong><span>Try a different search or lane.</span></div>}
      </div>
    </section>
    <ReadingPane email={selected} moveEmail={moveEmail} toggleStar={toggleStar} archive={archiveSelected} draftState={draftState} askAi={askAi} />
  </div>;
}

function EmailRow({ email, active, onClick, onStar }: { email: Email; active: boolean; onClick: () => void; onStar: () => void }) {
  const meta = laneMeta[email.lane];
  return <article className={`email-row ${active ? 'active' : ''}`} onClick={onClick} draggable onDragStart={(event) => event.dataTransfer.setData('text/plain', email.id)}>
    <GripVertical className="drag-grip" size={14} />
    <span className="sender-avatar" style={{ '--avatar-color': email.color } as React.CSSProperties}>{email.initials}</span>
    <div className="email-copy"><div><strong>{email.sender}</strong>{email.unread && <i className="unread-dot" />}</div><h2>{email.subject}</h2><p>{email.snippet}</p><span className={`lane-chip ${meta.tone}`}>{meta.title}</span></div>
    <div className="email-side"><time>{email.time}</time><button aria-label={email.starred ? 'Unstar email' : 'Star email'} onClick={(event) => { event.stopPropagation(); onStar(); }} className={email.starred ? 'starred' : ''}><Star size={15} fill={email.starred ? 'currentColor' : 'none'} /></button><span>T{email.tier} · {Math.round(email.confidence * 100)}%</span></div>
  </article>;
}

function ReadingPane({ email, moveEmail, toggleStar, archive, draftState, askAi }: { email: Email | null; moveEmail: (id: string, lane: Lane) => void; toggleStar: (id: string) => void; archive: () => void; draftState: 'idle' | 'loading' | 'ready'; askAi: () => void }) {
  if (!email) return <section className="reading-pane empty-reading"><Mail size={28} /><strong>Select a message</strong></section>;
  return <section className="reading-pane">
    <div className="reading-toolbar">
      <button aria-label="Archive" title="Archive" onClick={archive}><Archive size={17} /></button>
      <button aria-label="Star" title="Star" className={email.starred ? 'starred' : ''} onClick={() => toggleStar(email.id)}><Star size={17} fill={email.starred ? 'currentColor' : 'none'} /></button>
      <button aria-label="More actions" title="More actions"><MoreHorizontal size={18} /></button>
      <span />
      <small>{email.time}</small>
    </div>
    <div className="message-body">
      <span className={`decision-label ${laneMeta[email.lane].tone}`}><Cpu size={13} />Tier 1 · {laneMeta[email.lane].title} · {Math.round(email.confidence * 100)}%</span>
      <h1>{email.subject}</h1>
      <div className="sender-line"><span className="sender-avatar large" style={{ '--avatar-color': email.color } as React.CSSProperties}>{email.initials}</span><div><strong>{email.sender}</strong><span>{email.address} · to me</span></div><ChevronRight size={14} /></div>
      <div className="email-content">{email.body.split('\n').map((line, index) => <p key={index}>{line || <br />}</p>)}</div>
      <div className="message-actions"><button><Reply size={15} />Reply</button><button onClick={askAi} className="ai-action"><Sparkles size={15} />Ask Tier 2</button></div>
    </div>
    <DecisionPanel email={email} moveEmail={moveEmail} draftState={draftState} askAi={askAi} />
  </section>;
}

function DecisionPanel({ email, moveEmail, draftState, askAi }: { email: Email; moveEmail: (id: string, lane: Lane) => void; draftState: 'idle' | 'loading' | 'ready'; askAi: () => void }) {
  return <aside className="decision-panel">
    <div className="decision-head"><div><p>WHY THIS LANE</p><h2>Local decision</h2></div><span><Zap size={13} />4.8 ms</span></div>
    <p className="decision-summary">The local classifier saw a direct request and a time constraint. No email content left this browser.</p>
    <div className="feature-list">{email.features.map((feature) => <div key={feature.label}><span>{feature.label}</span><i><b style={{ width: `${Math.abs(feature.weight) * 100}%` }} /></i><strong>+{feature.weight.toFixed(2)}</strong></div>)}</div>
    <div className="move-block"><span>Was this right? Correct the lane:</span><div>{(Object.keys(laneMeta) as Lane[]).map((lane) => { const Icon = laneMeta[lane].icon; return <button key={lane} className={email.lane === lane ? 'active' : ''} onClick={() => moveEmail(email.id, lane)}><Icon size={14} />{laneMeta[lane].title}</button>; })}</div><small><BrainCircuit size={12} />Every correction becomes a labeled training example.</small></div>
    {draftState === 'idle' && <button className="tier-two-button" onClick={askAi}><Sparkles size={15} /><span><strong>Ask Tier 2</strong><small>Use the prerecorded LLM response</small></span><ArrowRight size={15} /></button>}
    {draftState === 'loading' && <div className="llm-loading"><i /><div><strong>Tier 2 is reasoning</strong><span>Simulating a structured LLM response...</span></div></div>}
    {draftState === 'ready' && <div className="draft-panel"><div className="draft-head"><span><Sparkles size={13} />TIER 2 · PRERECORDED</span><strong>Draft ready</strong></div><p>Hi Maya,</p><p>I’ll review the enterprise section and send final comments before 3 PM today.</p><p>Best,<br />Gaurav</p><div className="assumption"><AlertTriangle size={13} /><span>Assumes you can complete the review before the stated deadline.</span></div><div className="draft-actions"><button><FileText size={14} />Edit draft</button><button><Send size={14} />Copy to Gmail</button></div><small>Draft only. Winnow never sends on your behalf.</small></div>}
  </aside>;
}

function LearningView({ trainingCount, state, run }: { trainingCount: number; state: 'idle' | 'running' | 'done'; run: () => void }) {
  return <div className="page-view">
    <div className="page-title"><p>CONTINUOUS LEARNING</p><h1>Your inbox teaches the model.</h1><span>Every correction becomes local training data. New models ship only after passing a holdout guardrail.</span></div>
    <div className="learning-grid">
      <section className="learning-hero"><div><p>ACTIVE MODEL</p><h2>{state === 'done' ? 'v1.9' : 'v1.8'}</h2><span>Logistic regression + MiniLM embeddings</span></div><div className="model-score"><strong>{state === 'done' ? '90.1' : '88.3'}%</strong><span>holdout accuracy</span><small className={state === 'done' ? 'positive' : ''}><TrendingUp size={13} />{state === 'done' ? '+1.8% accepted' : 'No regression'}</small></div></section>
      <section className="signal-panel"><div className="panel-head"><div><p>LEARNING SIGNALS</p><h2>{trainingCount} corrections ready</h2></div><BrainCircuit size={22} /></div><div className="signal-bars"><div><span>Lane moves</span><i><b style={{ width: '72%' }} /></i><strong>{trainingCount - 7}</strong></div><div><span>Stars</span><i><b style={{ width: '38%' }} /></i><strong>4</strong></div><div><span>Archives</span><i><b style={{ width: '54%' }} /></i><strong>7</strong></div><div><span>Draft edits</span><i><b style={{ width: '22%' }} /></i><strong>2</strong></div></div></section>
      <section className="retrain-panel"><div className="panel-head"><div><p>NIGHTLY RETRAIN</p><h2>Candidate pipeline</h2></div><Clock3 size={21} /></div><div className="pipeline"><PipelineStep state="done" label="Collect labels" value={`${trainingCount} examples`} /><PipelineStep state={state === 'idle' ? 'waiting' : 'done'} label="Train candidate" value={state === 'idle' ? 'Not started' : 'v1.9 ready'} /><PipelineStep state={state === 'done' ? 'done' : state === 'running' ? 'running' : 'waiting'} label="Evaluate holdout" value={state === 'done' ? '90.1% · passed' : state === 'running' ? 'Comparing...' : 'Guardrail pending'} /><PipelineStep state={state === 'done' ? 'done' : 'waiting'} label="Deploy or reject" value={state === 'done' ? 'Deployed safely' : 'Awaiting result'} /></div><button onClick={run} disabled={state !== 'idle'} className="retrain-button"><RefreshCcw size={15} className={state === 'running' ? 'spin' : ''} />{state === 'idle' ? 'Run retraining demo' : state === 'running' ? 'Training candidate...' : 'v1.9 deployed'}</button></section>
      <section className="guardrail-panel"><ShieldCheck size={23} /><div><p>REGRESSION GUARDRAIL</p><h2>The old model stays one command away.</h2><span>A candidate must match or beat the active holdout score. Failed candidates are rejected; successful ones preserve v1.8 for instant rollback.</span></div></section>
    </div>
  </div>;
}

function PipelineStep({ state, label, value }: { state: 'done' | 'running' | 'waiting'; label: string; value: string }) {
  return <div className={`pipeline-step ${state}`}><span>{state === 'done' ? <Check size={13} /> : state === 'running' ? <RefreshCcw size={13} /> : null}</span><div><strong>{label}</strong><small>{value}</small></div></div>;
}

function EvalsView() {
  const rows = [
    { name: 'Pure classifier', note: 'Every email stays local', accuracy: '86.7%', latency: '3.7 ms', cost: '$0.00', escalated: '0%', tone: 'neutral' },
    { name: 'Winnow tiered', note: 'Local first, LLM when uncertain', accuracy: '88.3%', latency: '104 ms', cost: '$0.41', escalated: '8.3%', tone: 'winner' },
    { name: 'Pure LLM', note: 'Every email calls the model', accuracy: '100%*', latency: '1.20 s', cost: '$5.30', escalated: '100%', tone: 'costly' },
  ];
  return <div className="page-view eval-view">
    <div className="page-title"><p>EVALUATION HARNESS</p><h1>Most of the accuracy. A fraction of the cost.</h1><span>Held-out comparison across the local classifier, the tiered system, and the prerecorded LLM ceiling.</span></div>
    <div className="eval-summary"><div><Cpu /><span>Local coverage</span><strong>91.7%</strong><small>of emails avoid an LLM</small></div><div><Zap /><span>Cost reduction</span><strong>92.3%</strong><small>vs. pure LLM routing</small></div><div><BarChart3 /><span>Accuracy lift</span><strong>+1.6 pt</strong><small>vs. local-only baseline</small></div></div>
    <section className="eval-table"><div className="eval-header"><span>Strategy</span><span>Accuracy</span><span>Mean latency</span><span>Cost / 1,000</span><span>LLM calls</span></div>{rows.map((row) => <div className={`eval-row ${row.tone}`} key={row.name}><div><strong>{row.name}</strong><small>{row.note}</small></div><span>{row.accuracy}</span><span>{row.latency}</span><span>{row.cost}</span><span>{row.escalated}</span></div>)}</section>
    <section className="threshold-panel"><div><p>CONFIDENCE THRESHOLD</p><h2>The dial is the product.</h2><span>Raise the threshold to buy more LLM accuracy. Lower it to maximize local privacy, speed, and zero-cost routing.</span></div><div className="threshold-track"><span>More local</span><i><b /><em /></i><span>More accurate</span><small>0.82 · current</small></div></section>
    <p className="eval-caveat">* Pure LLM uses deterministic prerecorded fixtures, so treat 100% as a ceiling rather than measured live-model accuracy. Winnow’s classifier, escalation rate, latency, and cost figures are measured on the held-out synthetic set.</p>
  </div>;
}

function Welcome({ close, start }: { close: () => void; start: () => void }) {
  return <div className="welcome-layer" role="dialog" aria-modal="true" aria-labelledby="welcome-title"><div className="welcome-backdrop" /><section className="welcome-card">
    <img src={`${import.meta.env.BASE_URL}inbox-ritual.png`} alt="A chaotic stack of envelopes becoming three ordered inbox lanes" />
    <div className="welcome-shade" />
    <div className="welcome-brand"><BrandMark /><span>Winnow</span><small>INTERACTIVE DEMO</small></div>
    <div className="welcome-copy"><span className="welcome-kicker"><Lock size={13} />Your inbox stays yours</span><h1 id="welcome-title">Turn inbox noise into three clear decisions.</h1><p>Winnow sorts most mail locally, explains every route, learns from your corrections, and calls an LLM only when confidence is low.</p><div className="welcome-stats"><div><strong>~5 ms</strong><span>local decision</span></div><div><strong>92%</strong><span>no LLM needed</span></div><div><strong>$0</strong><span>demo cost</span></div></div><div className="welcome-actions"><button onClick={start}>Start the 90-second tour <ArrowRight size={16} /></button><button onClick={close}>Explore inbox</button></div><small>Synthetic email · prerecorded Tier 2 · no signup · no API key</small></div>
  </section></div>;
}

function TourCoach({ step, tour, next, close }: { step: number; tour: { view: View; label: string; title: string; copy: string }[]; next: () => void; close: () => void }) {
  const item = tour[step];
  return <aside className="tour-coach"><div className="tour-progress"><span>GUIDED TOUR</span><div>{tour.map((_, index) => <i key={index} className={index <= step ? 'active' : ''} />)}</div><button onClick={close} aria-label="Close tour"><X size={14} /></button></div><p>{step + 1} OF {tour.length} · {item.label}</p><h2>{item.title}</h2><span>{item.copy}</span><div className="tour-actions"><button onClick={close}>Exit tour</button><button onClick={next}>{step === tour.length - 1 ? 'Finish' : 'Next'}<ArrowRight size={14} /></button></div></aside>;
}

export default App;
