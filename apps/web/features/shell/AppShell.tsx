'use client';
import {useCallback, useEffect, useRef, useState} from 'react';
import {accountApi, session as storage, type Runtime, type SavedSession} from '@/lib/api';
import {accountsEnabled, signIn, useAccount} from '@/lib/account';
import {ChatWorkspace} from '@/features/chat/ChatWorkspace';
import {HistoryRail} from './HistoryRail';
import {SignInDialog} from './SignInDialog';
import {TopBar} from './TopBar';

const wide = '(min-width: 1100px)';

export function AppShell({initialRuntime}: {initialRuntime: Runtime | null}) {
 const {ready, account} = useAccount();
 const [runtime, setRuntime] = useState(initialRuntime);
 const [historyOpen, setHistoryOpen] = useState(false);
 const [signInOpen, setSignInOpen] = useState(false);
 const [sessions, setSessions] = useState<SavedSession[] | null>(null);
 const [historyError, setHistoryError] = useState('');
 const [current, setCurrent] = useState('');
 const [chatKey, setChatKey] = useState(0);
 const [mode, setMode] = useState('policy');
 const [busy, setBusy] = useState(false);
 const previousAccount = useRef<string | null>(null);

 const refresh = useCallback(async () => {
  try { setSessions(await accountApi.sessions()); setHistoryError(''); }
  catch { setHistoryError('Couldn’t load your conversations. Try again in a moment.'); }
 }, []);

 const openChat = useCallback((id: string) => {
  if (id) localStorage.setItem(storage.key, id); else localStorage.removeItem(storage.key);
  setCurrent(id); setChatKey(k => k + 1);
  if (!window.matchMedia(wide).matches) setHistoryOpen(false);
 }, []);

 // React to sign-in and sign-out: keep the open guest chat, then load saved history.
 useEffect(() => {
  if (!ready) return;
  const uid = account?.uid ?? null;
  if (uid === previousAccount.current) return;
  const wasSignedIn = previousAccount.current !== null;
  previousAccount.current = uid;
  if (uid) {
   void (async () => {
    const open = localStorage.getItem(storage.key);
    if (open) { try { await accountApi.claim(open); } catch { /* owned elsewhere or gone */ } }
    await refresh();
    if (window.matchMedia(wide).matches) setHistoryOpen(true);
   })();
  } else if (wasSignedIn) {
   setSessions(null); setHistoryOpen(false); openChat('');
  }
 }, [ready, account, refresh, openChat]);

 async function remove(id: string) {
  try {
   await accountApi.remove(id);
   if (id === current || id === localStorage.getItem(storage.key)) openChat('');
   await refresh();
  } catch { setHistoryError('Couldn’t delete that conversation. Try again.'); }
 }

 return <div className={`shell${historyOpen ? ' history-open' : ''}`}>
  {accountsEnabled && <HistoryRail open={historyOpen} signedIn={!!account} sessions={sessions} current={current} error={historyError}
   onClose={() => setHistoryOpen(false)} onSelect={openChat} onDelete={remove} onSignIn={() => setSignInOpen(true)}/>}
  <div className="stage">
   <TopBar runtime={runtime} historyOpen={historyOpen} accountsOn={accountsEnabled} account={account} accountReady={ready}
    mode={mode} modeLocked={!!current} busy={busy}
    onToggleHistory={() => setHistoryOpen(o => !o)} onNew={() => openChat('')} onSignIn={() => setSignInOpen(true)}
    onSignOut={() => void signIn.signOut()} onMode={setMode}/>
   <ChatWorkspace key={chatKey} runtime={runtime} onRuntime={setRuntime} mode={mode} onModeRestored={setMode}
    onSession={setCurrent} onBusy={setBusy} onTurn={() => { if (account) void refresh(); }}/>
  </div>
  {accountsEnabled && <SignInDialog open={signInOpen} onClose={() => setSignInOpen(false)}/>}
 </div>;
}
