'use client';
import {useEffect, useRef, useState} from 'react';
import {api, ApiError, readHealth, session as auth, type History, type Message, type Reply, type Runtime, type Ticket} from '@/lib/api';
import {LeopardMark} from '@/components/LeopardMark';
import {MessageCard} from './MessageCard';
import {TicketDraft} from './TicketDraft';
import {Composer} from './Composer';
import type {FeedbackKind} from './FeedbackRow';

const starters = ["Wi-Fi isn't working.", 'My Demo-Lab printer queue on Windows is stuck.', 'I want to talk to TechSpot staff.'];
const turnTimeout = 60000;

type Props = {
 runtime: Runtime | null; mode: string;
 onRuntime: (runtime: Runtime) => void; onModeRestored: (mode: string) => void;
 onSession: (id: string) => void; onBusy: (busy: boolean) => void; onTurn: () => void;
};

export function ChatWorkspace({runtime, mode, onRuntime, onModeRestored, onSession, onBusy, onTurn}: Props) {
 const [session, setSession] = useState('');
 const [messages, setMessages] = useState<Message[]>([]);
 const [text, setText] = useState('');
 const [working, setBusy] = useState(false);
 const [thinking, setThinking] = useState(false);
 const [slow, setSlow] = useState(false);
 const [restoring, setRestoring] = useState(true);
 const busy = working || restoring;
 const [error, setError] = useState('');
 const [notice, setNotice] = useState('');
 const [ticket, setTicket] = useState<Ticket | null>(null);
 const [draft, setDraft] = useState('');
 const [ratings, setRatings] = useState<Record<string, string>>({});
 const [pendingFix, setPendingFix] = useState<string | null>(null);
 const [confirmDelete, setConfirmDelete] = useState(false);
 const generation = useRef(0);
 const sending = useRef(false);
 const pendingSend = useRef<{value: string; requestId: string} | null>(null);
 const scroller = useRef<HTMLDivElement>(null);
 const pilot = runtime?.app_mode === 'pilot';
 const supportEmail = /^[^\s@]+@[^\s@]+$/.test(runtime?.support_contact ?? '') ? runtime!.support_contact! : process.env.NEXT_PUBLIC_SUPPORT_EMAIL ?? '';
 const latestAssistant = messages.filter(m => m.role === 'assistant').at(-1)?.id;

 useEffect(() => { onBusy(working); }, [working, onBusy]);

 useEffect(() => {
  const current = ++generation.current;
  const controller = new AbortController();
  const id = localStorage.getItem(auth.key);
  const restore = async () => {
   try {
    if (!id) return;
    const s = await api<History>(`/api/sessions/${id}`, {signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)])});
    if (generation.current !== current || controller.signal.aborted) return;
    setSession(s.id); onSession(s.id); onModeRestored(s.mode); setMessages(s.messages);
    setTicket(s.state.outcome === 'handoff' ? s.ticket : null); setDraft(s.ticket?.draft || '');
    setRatings(Object.fromEntries(s.feedback.map(f => [`${f.message_id}-${f.kind}`, f.value])));
    if (s.state.pending_failure) setPendingFix(s.messages.filter(m => m.role === 'assistant').at(-1)?.id ?? null);
   } catch (e) {
    if (generation.current !== current || controller.signal.aborted) return;
    // A conversation that belongs to another account, or no longer exists, simply starts fresh.
    if (e instanceof ApiError && e.status === 404) { localStorage.removeItem(auth.key); return; }
    setError(e instanceof Error ? e.message : 'Could not restore conversation.');
   } finally {
    if (generation.current === current && !controller.signal.aborted) setRestoring(false);
   }
  };
  void restore();
  return () => controller.abort();
  // Restores once per mounted conversation; the shell remounts this component to switch chats.
  // eslint-disable-next-line react-hooks/exhaustive-deps
 }, []);

 useEffect(() => {
  const container = scroller.current;
  const target = container?.querySelector<HTMLElement>(thinking ? '.typing' : '.message:last-of-type');
  if (container && target) container.scrollTo({top: container.scrollTop + target.getBoundingClientRect().top - container.getBoundingClientRect().top - 24, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
 }, [messages, thinking]);

 async function ensureSession() {
  if (session) return session;
  const s = await api<{id: string}>('/api/sessions', {method: 'POST', body: JSON.stringify({mode})});
  localStorage.setItem(auth.key, s.id); setSession(s.id); onSession(s.id); return s.id;
 }

 async function submitTurn(id: string, value: string, requestId: string, placeholder?: string) {
  setThinking(true); setSlow(false);
  const slowTimer = setTimeout(() => setSlow(true), 8000);
  try {
   const r = await api<Reply>(`/api/sessions/${id}/messages`, {
    method: 'POST', body: JSON.stringify({text: value, request_id: requestId}), timeout: turnTimeout,
   });
   // The mutation response contains the authoritative, redacted user message.
   // Rendering never depends on a second history request succeeding.
   setMessages(previous => {
    const rest = previous.filter(m => m.id !== placeholder);
    return rest.some(m => m.id === r.id) ? rest : [...rest, r.user_message, {id: r.id, role: 'assistant', text: r.text, response: r}];
   });
   if (r.ticket) { setTicket(r.ticket); setDraft(r.ticket.draft); }
   else if (r.state.outcome !== 'handoff') { setTicket(null); setDraft(''); }
   setPendingFix(null);
   onTurn();
   readHealth().then(onRuntime).catch(() => {});
  } finally {
   clearTimeout(slowTimer); setThinking(false); setSlow(false);
  }
 }

 async function send(value: string) {
  if (busy || sending.current || !value.trim()) return;
  sending.current = true; setBusy(true); setError(''); setNotice('');
  if (!pendingSend.current || pendingSend.current.value !== value) {
   // A new message replaces any earlier one that failed to send.
   setMessages(previous => previous.filter(m => !m.failed));
   pendingSend.current = {value, requestId: crypto.randomUUID()};
  }
  const pending = pendingSend.current;
  const placeholder = `local-${pending.requestId}`;
  setMessages(previous => [...previous.filter(m => m.id !== placeholder), {id: placeholder, role: 'user', text: value}]);
  setText('');
  try {
   await submitTurn(await ensureSession(), value, pending.requestId, placeholder);
   pendingSend.current = null;
  } catch (e) {
   setMessages(previous => previous.map(m => m.id === placeholder ? {...m, failed: true} : m));
   setError(e instanceof Error ? e.message : 'Could not send the message.');
  } finally { sending.current = false; setBusy(false); }
 }

 async function retryFix() {
  if (busy || !pendingFix) return;
  setBusy(true); setError('');
  try { await submitTurn(session, 'No, that did not fix it.', pendingFix); }
  catch { setError('Your feedback is saved. Retry the next step when the service is available.'); }
  finally { setBusy(false); }
 }

 async function feedback(r: Reply, kind: FeedbackKind, value: string, reason = '', comment = '') {
  if (busy) return;
  setBusy(true); setError('');
  try {
   const saved = await api<{duplicate: boolean; value: string}>('/api/feedback', {
    method: 'POST', body: JSON.stringify({session_id: session, message_id: r.id, snapshot_id: r.snapshot_id, kind, value, reason: reason.slice(0, 100), comment}),
   });
   setRatings(prev => ({...prev, [`${r.id}-${kind}`]: saved.value}));
   setNotice(saved.duplicate ? `Feedback already recorded: ${saved.value}.` : kind === 'fix' && saved.value === 'yes' ? 'Glad that worked. This issue is marked resolved.' : 'Feedback saved. Thank you.');
   if (kind === 'fix' && saved.value === 'no') {
    setPendingFix(r.id);
    await submitTurn(session, 'No, that did not fix it.', r.id);
   }
  } catch (e) { setError(e instanceof Error ? e.message : 'Could not save feedback.'); }
  finally { setBusy(false); }
 }

 async function saveTicket(then?: 'copy' | 'email') {
  setBusy(true); setError('');
  try {
   const t = await api<Ticket>(`/api/sessions/${session}/ticket`, {method: 'PUT', body: JSON.stringify({draft})});
   setTicket(t); setDraft(t.draft);
   if (then === 'copy') { await navigator.clipboard.writeText(t.draft); setNotice('Draft copied. Nothing was submitted.'); }
   else if (then === 'email') {
    window.location.href = `mailto:${supportEmail}?subject=${encodeURIComponent('IT support request')}&body=${encodeURIComponent(t.draft)}`;
    setNotice('Opening your email app. Nothing is sent until you press send there.');
   }
   else setNotice('Draft saved with privacy filtering.');
  } catch { setError('Could not save or copy. Try saving again, then select and copy the draft manually.'); }
  finally { setBusy(false); }
 }

 async function deleteConversation() {
  try { await api(`/api/sessions/${session}`, {method: 'DELETE'}); localStorage.removeItem(auth.key); window.location.reload(); }
  catch { setError('Could not delete the conversation. Please retry.'); }
 }

 const failed = messages.find(m => m.failed);
 const empty = !restoring && messages.length === 0;
 return <main className={`conversation${empty ? ' is-empty' : ''}`} id="main">
  <div className="scroller" ref={scroller}>
   <div className="column">
    {empty && <section className="welcome" aria-labelledby="welcome-title">
     <LeopardMark size={56} tile/>
     <h1 id="welcome-title">What’s getting in your way?</h1>
     <p>Describe the problem in your own words: what you see and on which device. I’ll find the right TechSpot guide, ask one quick question if something’s missing, or draft a ticket when you need a person.</p>
     <div className="starters" role="group" aria-label="Try one of these">
      {starters.map(s => <button type="button" key={s} onClick={() => send(s)} disabled={busy}>{s}</button>)}
     </div>
    </section>}
    <div className="messages" aria-live="polite" aria-relevant="additions">
     {messages.map(m => <MessageCard key={m.id} message={m} latest={m.id === latestAssistant} busy={busy} ratings={ratings} showProvider={!pilot && mode === 'baseline'}
      onReply={send} onRetry={() => send(m.text)} onFeedback={(kind, value, reason, comment) => feedback(m.response!, kind, value, reason, comment)}/>)}
     {(restoring || thinking) && <div className="typing" role="status">
      <span className="dots" aria-hidden="true"><i/><i/><i/></span>
      {restoring ? 'Restoring your conversation…' : slow ? 'Still working — the server may be waking up…' : 'Working through your request…'}
     </div>}
    </div>
    {ticket && <TicketDraft draft={draft} busy={busy} supportEmail={supportEmail} onChange={setDraft} onSave={saveTicket}/>}
    {pilot && session && <div className="pilot-delete">{confirmDelete
     ? <><span>Delete this conversation and its saved draft permanently?</span>
      <button type="button" className="danger small" disabled={busy} onClick={deleteConversation}>Delete</button>
      <button type="button" className="ghost small" onClick={() => setConfirmDelete(false)}>Cancel</button></>
     : <button type="button" className="ghost small" disabled={busy} onClick={() => setConfirmDelete(true)}>Delete conversation</button>}
    </div>}
   </div>
  </div>
  <div className="dock">
   <div className="column">
    <div className="status-area">
     {runtime?.status === 'degraded' && <p role="status" className="notice warn">Some answers may be unavailable right now. You can still describe your problem or ask for a person.</p>}
     {runtime?.ai_requests_remaining != null && runtime.ai_requests_remaining <= 5 && <p role="status" className="notice">Demo AI allowance: {runtime.ai_requests_remaining} requests remaining. More usage needs owner authorization.</p>}
     {pendingFix && <div className="pending-fix"><p>Your “No” is saved. Continue to the next step.</p><button type="button" disabled={busy} onClick={retryFix}>Retry next step</button></div>}
     {error && <p role="alert" className="error">{error}{failed && ' Use Retry on your message to send it again.'}</p>}
     {notice && <p role="status" className="notice">{notice}</p>}
    </div>
    <Composer text={text} busy={busy} onChange={setText} onSend={send}/>
    <p className="disclaimer">Uses sample troubleshooting guides — not official TechSpot advice. Never share passwords or personal details.</p>
   </div>
  </div>
 </main>;
}
