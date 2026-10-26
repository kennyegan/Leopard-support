'use client';
import {useEffect, useState} from 'react';
import {api, readHealth, session, type Runtime} from '@/lib/api';
import {LeopardMark} from '@/components/Icons';
import {ChatWorkspace} from './ChatWorkspace';

type Status = 'loading' | 'waking' | 'ready' | 'login' | 'error';
const wakeLimit = 120000;

// The free API host sleeps when idle and takes up to a minute to start again.
async function waitForApi(cancelled: () => boolean, onSlow: () => void) {
 const started = Date.now();
 while (!cancelled()) {
  try {
   const r = await fetch('/api/live', {cache: 'no-store', signal: AbortSignal.timeout(10000)});
   if (r.ok) return true;
  } catch {}
  if (Date.now() - started > wakeLimit) return false;
  onSlow();
  await new Promise(resolve => setTimeout(resolve, 2000));
 }
 return false;
}

export default function AccessGate() {
 const [status, setStatus] = useState<Status>('loading');
 const [runtime, setRuntime] = useState<Runtime | null>(null);
 const [attempt, setAttempt] = useState(0);
 useEffect(() => {
  let cancelled = false;
  const isCancelled = () => cancelled;
  async function load() {
   if (!await waitForApi(isCancelled, () => { if (!cancelled) setStatus('waking'); })) {
    if (!cancelled) setStatus('error');
    return;
   }
   try {
    const health = await readHealth();
    if (cancelled) return;
    setRuntime(health);
    if (health.app_mode === 'pilot') {
     try {
      const identity = await api<{csrf_token: string; user_id: string}>('/api/auth/me');
      if (cancelled) return;
      session.signIn(identity.csrf_token, identity.user_id);
     } catch { if (!cancelled) setStatus('login'); return; }
    }
    if (!cancelled) setStatus('ready');
   } catch { if (!cancelled) setStatus('error'); }
  }
  void load();
  return () => { cancelled = true; };
 }, [attempt]);

 if (status === 'ready') return <>
  {runtime?.app_mode === 'pilot' && <div className="pilot-access">
   <span>Private pilot · {runtime.qualification_only ? 'Local qualification' : 'Invited testers'}</span>
   <button type="button" className="ghost small" onClick={async () => {
    const r = await fetch('/api/auth/logout', {method: 'POST', headers: {'X-CSRF-Token': session.csrf}});
    if (r.ok) { localStorage.removeItem(session.key); window.location.reload(); }
   }}>Sign out</button>
  </div>}
  <ChatWorkspace initialRuntime={runtime}/>
 </>;

 return <main className="gate" id="main">
  <div className="gate-card">
   <LeopardMark size={48}/>
   <h1>{runtime?.app_mode === 'pilot' ? 'Leopard Support private pilot' : 'Leopard Support'}</h1>
   {status === 'loading' && <p role="status"><span className="spinner" aria-hidden="true"/>Checking access…</p>}
   {status === 'waking' && <div role="status">
    <p><span className="spinner" aria-hidden="true"/>Waking up the support server…</p>
    <small>Our free hosting sleeps when nobody is using it. This usually takes under a minute.</small>
   </div>}
   {status === 'login' && <>
    <p>Sign in with your invited account. Use sample issues only; do not enter passwords or personal information.</p>
    <a className="button" href="/api/auth/login">Sign in</a>
    {runtime?.support_contact && <small>Access help: {runtime.support_contact}</small>}
   </>}
   {status === 'error' && <>
    <p role="alert">The support service is unavailable right now.</p>
    <button type="button" onClick={() => { setStatus('loading'); setAttempt(a => a + 1); }}>Try again</button>
   </>}
  </div>
 </main>;
}
