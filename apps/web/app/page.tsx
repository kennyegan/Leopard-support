'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';

let csrfToken = '';
let storageKey = 'techspot.demo.session';
type Runtime = {provider: string; external_ai_enabled: boolean; ai_requests_remaining?: number | null; app_mode?: string; support_contact?: string; qualification_only?: boolean};

type Source = {id: string; title: string; href: string; corpus_version: string; score: number};
type Ticket = {id: string; draft: string; edited: boolean};
type Reply = {
 id: string; snapshot_id: string; action: 'ANSWER' | 'ASK' | 'HANDOFF'; text: string;
 steps: string[]; sources: Source[]; options: string[]; provider: string; ticket?: Ticket;
 user_message: Message;
 response_kind?: string; request_type?: string;
 progress?: {current: number; total: number; kind: string; prompt: string} | null;
 references?: {title: string; url: string; checked_at: string}[];
 state: {outcome: string; problem_id: string; details?: {system_or_app?: string; vendor?: string; os?: string}};
};
type Message = {id: string; role: string; text: string; response?: Reply};
type History = {
 id: string; mode: string; messages: Message[]; ticket: Ticket | null;
 state: {pending_failure: boolean; outcome: string};
 feedback: {message_id: string; kind: string; value: string}[];
};
async function api<T>(path: string, init?: RequestInit): Promise<T> {
 const response = await fetch(path, {
  ...init, headers: {'Content-Type': 'application/json', ...(csrfToken ? {'X-CSRF-Token': csrfToken} : {}), ...init?.headers},
  signal: init?.signal ?? AbortSignal.timeout(20000),
 });
 if (!response.ok) throw new Error(response.status === 401 ? 'Your sign-in has expired. Refresh this page to sign in again.' : response.status === 429 ? 'Your request allowance is temporarily reached. Please wait before trying again.' : response.status === 409 ? 'This turn is running or its outcome is uncertain. Retry the same message later; start a new conversation if it remains uncertain.' : response.status === 404
  ? 'That conversation is unavailable. Start a new chat.'
  : 'The support service is unavailable. Please try again.');
 return response.json();
}
function canReportFix(r: Reply) {
 return r.response_kind !== 'check' && (!r.progress || r.progress.current === r.progress.total);
}
function outcomeLabel(r: Reply) {
 if (r.response_kind === 'check') return 'Let’s check one thing';
 if (r.response_kind === 'service_error') return 'Assistant unavailable';
 if (r.response_kind === 'status') return r.state.outcome === 'resolved' ? 'Resolved' : 'Progress update';
 if (r.response_kind === 'explanation') return 'Let’s clarify';
 if (r.action === 'ASK') return 'A quick question';
 if (r.action === 'HANDOFF') return 'Let’s bring in a person';
 return r.request_type === 'install' ? 'Download and setup' : 'Guide-backed steps';
}
export default function PilotBoundary() {
 const [status, setStatus] = useState<'loading'|'ready'|'login'|'error'>('loading');
 const [runtime, setRuntime] = useState<Runtime | null>(null);
 useEffect(() => {
  let cancelled = false;
  async function load() {
   try {
    const health = await api<Runtime>('/api/health');
    if (cancelled) return;
    setRuntime(health);
    if (health.app_mode === 'pilot') {
     try {
      const identity = await api<{csrf_token: string; user_id: string}>('/api/auth/me');
      if (cancelled) return;
      csrfToken = identity.csrf_token;
      storageKey = `techspot.pilot.session.${identity.user_id}`;
     } catch {if (!cancelled) setStatus('login'); return;}
    }
    if (!cancelled) setStatus('ready');
   } catch {if (!cancelled) setStatus('error');}
  }
  void load();
  return () => {cancelled = true;};
 }, []);
 if (status === 'ready') return <><div className="pilot-access">{runtime?.app_mode === 'pilot' && <><span>Private pilot · {runtime.qualification_only ? 'Local qualification' : 'Invited testers'}</span><button onClick={async () => {const r = await fetch('/api/auth/logout', {method:'POST',headers:{'X-CSRF-Token':csrfToken}}); if(r.ok){localStorage.removeItem(storageKey);window.location.reload();}}}>Sign out</button></>}</div><Chat/></>;
 return <main className="document"><h1>TechSpot Assist private pilot</h1>{status === 'loading' ? <p role="status">Checking access…</p> : status === 'login' ? <><p>Sign in with your invited account. Use synthetic issues only; do not enter passwords or personal information.</p><a href="/api/auth/login">Sign in</a>{runtime?.support_contact && <p>Access help: {runtime.support_contact}</p>}</> : <><p role="alert">The support service is unavailable.</p><button onClick={()=>window.location.reload()}>Try again</button></>}</main>;
}
function Chat() {
 const [runtime, setRuntime] = useState<Runtime | null>(null);
 const [session, setSession] = useState('');
 const [mode, setMode] = useState('policy');
 const [messages, setMessages] = useState<Message[]>([]);
 const [text, setText] = useState('');
 const [working, setBusy] = useState(false);
 const [restoring, setRestoring] = useState(true);
 const busy = working || restoring;
 const [error, setError] = useState('');
 const [notice, setNotice] = useState('');
 const [ticket, setTicket] = useState<Ticket | null>(null);
 const [draft, setDraft] = useState('');
 const [reason, setReason] = useState('');
 const [ratings, setRatings] = useState<Record<string, string>>({});
 const [pendingFix, setPendingFix] = useState<string | null>(null);
 const generation = useRef(0);
 const sending = useRef(false);
 const pendingSend = useRef<{value: string; requestId: string} | null>(null);
 const messageList = useRef<HTMLDivElement>(null);
 useEffect(() => {
  const current = ++generation.current;
  const controller = new AbortController();
  api<Runtime>('/api/health').then(setRuntime).catch(() => {});
  const id = localStorage.getItem(storageKey);
  const restore = async () => {
   try {
    if (!id) return;
    const s = await api<History>(`/api/sessions/${id}`, {signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)])});
    if (generation.current !== current || controller.signal.aborted) return;
    setSession(s.id); setMode(s.mode); setMessages(s.messages);
    setTicket(s.state.outcome === 'handoff' ? s.ticket : null); setDraft(s.ticket?.draft || '');
    setRatings(Object.fromEntries(s.feedback.map(f => [`${f.message_id}-${f.kind}`, f.value])));
    if (s.state.pending_failure) setPendingFix(s.messages.filter(m => m.role === 'assistant').at(-1)?.id ?? null);
   } catch (e) {
    if (generation.current === current && !controller.signal.aborted) setError(e instanceof Error ? e.message : 'Could not restore conversation.');
   } finally {
    if (generation.current === current && !controller.signal.aborted) setRestoring(false);
   }
  };
  void restore();
  return () => controller.abort();
 }, []);
 useEffect(() => {
  const container = messageList.current;
  const newest = container?.querySelector<HTMLElement>('.message:last-of-type');
  if (container && newest) container.scrollTo({top: container.scrollTop + newest.getBoundingClientRect().top - container.getBoundingClientRect().top - 16, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
 }, [messages]);
 async function ensureSession() {
  if (session) return session;
  const s = await api<{id: string}>('/api/sessions', {method: 'POST', body: JSON.stringify({mode})});
  localStorage.setItem(storageKey, s.id); setSession(s.id); return s.id;
 }
 function newChat() {
  generation.current++;
  localStorage.removeItem(storageKey);
  pendingSend.current = null;
  setRestoring(false); setSession(''); setMessages([]); setText(''); setReason('');
  setTicket(null); setDraft(''); setError(''); setNotice(''); setRatings({}); setPendingFix(null);
 }
 async function submitTurn(id: string, value: string, requestId: string) {
  const r = await api<Reply>(`/api/sessions/${id}/messages`, {
   method: 'POST', body: JSON.stringify({text: value, request_id: requestId}),
  });
  // The mutation response contains the authoritative, redacted user message.
  // Rendering never depends on a second history request succeeding.
  setMessages(previous => previous.some(m => m.id === r.id) ? previous : [
   ...previous, r.user_message, {id: r.id, role: 'assistant', text: r.text, response: r},
  ]);
  if (r.ticket) { setTicket(r.ticket); setDraft(r.ticket.draft); }
  else if (r.state.outcome !== 'handoff') { setTicket(null); setDraft(''); }
  setPendingFix(null);
  api<Runtime>('/api/health').then(setRuntime).catch(() => {});
 }
 async function send(value: string) {
  if (busy || sending.current || !value.trim()) return;
  sending.current = true; setBusy(true); setError(''); setNotice('');
  if (!pendingSend.current || pendingSend.current.value !== value) {
   pendingSend.current = {value, requestId: crypto.randomUUID()};
  }
  try {
   await submitTurn(await ensureSession(), value, pendingSend.current.requestId);
   pendingSend.current = null; setText('');
  } catch (e) { setError(e instanceof Error ? e.message : 'Could not send the message.'); }
  finally { sending.current = false; setBusy(false); }
 }
 async function retryFix() {
  if (busy || !pendingFix) return;
  setBusy(true); setError('');
  try { await submitTurn(session, 'No, that did not fix it.', pendingFix); }
  catch { setError('Your feedback is saved. Retry the next step when the service is available.'); }
  finally { setBusy(false); }
 }
 async function feedback(r: Reply, kind: string, value: string) {
  if (busy) return;
  setBusy(true); setError('');
  try {
   const saved = await api<{duplicate: boolean; value: string}>('/api/feedback', {
    method: 'POST', body: JSON.stringify({session_id: session, message_id: r.id, snapshot_id: r.snapshot_id, kind, value, reason: reason.slice(0, 100), comment: reason}),
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
 async function saveTicket(copy = false) {
  setBusy(true); setError('');
  try {
   const t = await api<Ticket>(`/api/sessions/${session}/ticket`, {method: 'PUT', body: JSON.stringify({draft})});
   setTicket(t); setDraft(t.draft);
   if (copy) { await navigator.clipboard.writeText(t.draft); setNotice('Draft copied. Nothing was submitted.'); }
   else setNotice('Draft saved with privacy filtering.');
  } catch { setError('Could not save or copy. Try saving again, then select and copy the draft manually.'); }
  finally { setBusy(false); }
 }
 return <main className="workspace"><aside><div className="eyebrow">SUPPORT, WITH CONTEXT</div><h1>Let’s work<br/> through it.</h1><p>Find a useful next step, clarify what’s missing, or prepare a draft for a person.</p>{runtime?.app_mode !== 'pilot' && <div className="mode-box"><label htmlFor="mode">Research mode</label><select id="mode" value={mode} disabled={!!session||busy} onChange={e=>setMode(e.target.value)}><option value="policy">Assist · answer, ask, handoff</option><option value="baseline">Baseline · always answer</option></select><small>{mode==='policy'?'Checks whether a guide fits your situation.':'Uses the closest guide even when details are missing. For comparison only.'}</small></div>}{runtime?.app_mode === 'pilot' && session && <button className="secondary" disabled={busy} onClick={async()=>{if(!window.confirm('Delete this conversation and its saved draft permanently?'))return;try{await api(`/api/sessions/${session}`,{method:'DELETE'});newChat();}catch{setError('Could not delete the conversation. Please retry.');}}}>Delete conversation</button>}<button className="secondary" onClick={newChat} disabled={working}>＋ New conversation</button><div className="demo-note"><span className="status-dot"/> {runtime?.app_mode === 'pilot' ? 'Private synthetic pilot' : 'Local demonstration'}<p>{runtime?.app_mode === 'pilot' ? <>Synthetic guides may not fit your setup.<br/>Ask for a person at any time.<br/>{runtime.support_contact}</> : <>Real semantic retrieval.<br/>{runtime?.provider==='scripted'?'Scripted offline interpreter.':runtime?'External interpreter configured.':'Checking interpreter…'}<br/>{runtime?.external_ai_enabled?'External AI enabled by configuration.':'External AI disabled in demo mode.'}</>}</p></div></aside>
 <section className={`chat${ticket ? " has-ticket" : ""}`} aria-label="Support conversation"><div className="chat-heading"><div><strong>Your support conversation</strong><p>No passwords, student IDs, or personal information.</p></div><span className="pill">Synthetic guides</span></div><div className="messages" aria-live="polite" ref={messageList}>
 {!restoring&&messages.length===0&&<div className="welcome"><div className="welcome-icon">↗</div><h2>What’s getting in your way?</h2><p>Describe what is happening in your own words. You can ask what a step means or say when you aren’t sure.</p><div className="starters">{["Wi-Fi isn't working.",'My Demo-Lab printer queue on Windows is stuck.','I want to talk to TechSpot staff.'].map(s=><button key={s} onClick={()=>send(s)} disabled={busy}>{s}<span>↗</span></button>)}</div><small>All guides are synthetic. Checks help narrow down the issue; some problems need a person.</small></div>}
 {messages.map(m=><article key={m.id} className={`message ${m.role}`}><div className="message-label">{m.role==='user'?'You':'TechSpot Assist'}{m.response&&<span className={`outcome ${m.response.action.toLowerCase()}`}>{outcomeLabel(m.response)}</span>}</div><p>{m.text}</p>{m.response&&<><ol>{m.response.steps.map((step,i)=><li key={i}>{step}</li>)}</ol>{m.response.progress&&['guide','check'].includes(m.response.response_kind || '')&&<div className="next-check"><small>Step {m.response.progress.current} of {m.response.progress.total}</small><p>{m.response.progress.prompt}</p></div>}{m.response.sources.map(s=><Link className="source" key={s.id} href={s.href} target="_blank">↗ {s.title}<small>Synthetic source · {s.id}</small></Link>)}{m.response.references?.map(ref=><a className="official-reference" key={ref.url} href={ref.url} target="_blank" rel="noopener noreferrer">↗ {ref.title}<small>Official vendor site · opens in a new tab</small></a>)}<div className="quick-replies">{m.response.options.map(o=><button disabled={busy||m.id!==messages.filter(item=>item.role==='assistant').at(-1)?.id} onClick={()=>send(o)} key={o}>{o}</button>)}</div>{m.response.action!=='HANDOFF'&&!['status','explanation','service_error'].includes(m.response.response_kind || '')&&<div className="feedback">{m.response.action==='ANSWER'?<><div className="feedback-group" role="group" aria-label="Answer usefulness"><span>Was this useful?</span>{['yes','no'].map(v=><button key={v} disabled={busy||!!ratings[`${m.id}-rating`]} aria-pressed={ratings[`${m.id}-rating`]===v} aria-label={v==='yes'?'Thumbs up':'Thumbs down'} onClick={()=>feedback(m.response!,'rating',v)}>{v==='yes'?'↑':'↓'}</button>)}</div><>{canReportFix(m.response)&&<div className="feedback-group" role="group" aria-label="Problem resolution"><span>{m.response.request_type==='install'?'Is your software ready to use?':'Did this fix it?'}</span>{['yes','no'].map(v=><button key={v} disabled={busy||!!ratings[`${m.id}-fix`]||m.id!==messages.filter(item=>item.role==='assistant').at(-1)?.id} aria-pressed={ratings[`${m.id}-fix`]===v} onClick={()=>feedback(m.response!,'fix',v)}>{v==='yes'?'Yes':'No'}</button>)}</div>}</></>:<><span>Was this question helpful?</span>{['yes','no'].map(v=><button key={v} disabled={busy||!!ratings[`${m.id}-question`]} aria-pressed={ratings[`${m.id}-question`]===v} onClick={()=>feedback(m.response!,'question',v)}>{v==='yes'?'Yes':'No'}</button>)}</>}</div>}{runtime?.app_mode !== 'pilot' && <small className="provider-label">{m.response.provider}</small>}</>}</article>)}
 {busy&&<p role="status" className="working">{restoring ? "Restoring your conversation…" : "Working through your request…"}</p>}</div>
 {ticket&&<section className="ticket"><div className="eyebrow">REVIEW BEFORE SHARING</div><h2>Your editable ticket draft</h2><p>Nothing has been submitted. Privacy filtering is best-effort; remove any remaining personal information.</p><label htmlFor="draft" className="sr-only">Ticket draft</label><textarea id="draft" value={draft} maxLength={5000} onChange={e=>setDraft(e.target.value)}/><div className="actions"><button disabled={busy} onClick={()=>saveTicket()}>Save draft</button><button className="secondary" disabled={busy} onClick={()=>saveTicket(true)}>Copy draft</button></div></section>}
 {runtime?.ai_requests_remaining!=null&&runtime.ai_requests_remaining<=5&&<p role="status" className="notice">Demo AI allowance: {runtime.ai_requests_remaining} requests remaining. More usage needs owner authorization.</p>}{pendingFix&&<div className="pending-fix"><p>Your No feedback is saved. Continue to the next step.</p><button disabled={busy} onClick={retryFix}>Retry next step</button></div>}{error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status" className="notice">{notice}</p>}<form className="composer" onSubmit={e=>{e.preventDefault();send(text);}}><label htmlFor="message" className="sr-only">Your message</label><div className="input-row"><textarea id="message" rows={2} maxLength={1000} placeholder="Describe your IT problem…" value={text} onChange={e=>setText(e.target.value)} disabled={busy}/><button disabled={busy||!text.trim()} type="submit">Send ↗</button></div><div className="composer-meta"><span>{text.length}/1000 · Don’t include personal information</span><details><summary>Optional feedback note</summary><label htmlFor="reason">Reason or comment for your next rating</label><input id="reason" value={reason} maxLength={500} onChange={e=>setReason(e.target.value)}/></details></div></form></section></main>;
}
