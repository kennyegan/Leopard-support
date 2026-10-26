'use client';
import Link from 'next/link';
import {useEffect, useRef, useState} from 'react';
import type {Account} from '@/lib/account';
import type {Runtime} from '@/lib/api';
import {ChartIcon, LogOutIcon, MoreIcon, PlusIcon, SidebarIcon} from '@/components/Icons';
import {LeopardMark} from '@/components/LeopardMark';

type Props = {
 runtime: Runtime | null; historyOpen: boolean; accountsOn: boolean; account: Account | null; accountReady: boolean;
 mode: string; modeLocked: boolean; busy: boolean;
 onToggleHistory: () => void; onNew: () => void; onSignIn: () => void; onSignOut: () => void; onMode: (mode: string) => void;
};

function usePopover() {
 const [open, setOpen] = useState(false);
 const ref = useRef<HTMLDivElement>(null);
 useEffect(() => {
  if (!open) return;
  const close = (e: MouseEvent | KeyboardEvent) => {
   if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false);
  };
  document.addEventListener('mousedown', close); document.addEventListener('keydown', close);
  return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close); };
 }, [open]);
 return {open, setOpen, ref};
}

export function TopBar(p: Props) {
 const {open: menuOpen, setOpen: setMenuOpen, ref: menuRef} = usePopover();
 const pilot = p.runtime?.app_mode === 'pilot';
 const degraded = p.runtime?.status === 'degraded';
 return <header className="topbar">
  <div className="topbar-start">
   {p.accountsOn && <button type="button" className="icon-button" aria-label={p.historyOpen ? 'Hide conversations' : 'Show conversations'}
    aria-expanded={p.historyOpen} onClick={p.onToggleHistory}><SidebarIcon/></button>}
   <Link href="/" className="wordmark" aria-label="Leopard Support home"><LeopardMark size={28} tile/><span>Leopard Support</span></Link>
   {degraded && <span className="status-chip" role="status">Limited service</span>}
  </div>
  <div className="topbar-end">
   <button type="button" className="ghost new-chat" onClick={p.onNew} disabled={p.busy}><PlusIcon/><span>New conversation</span></button>
   <div className="popover-anchor" ref={menuRef}>
    {p.account
     ? <button type="button" className="avatar-button" aria-label={`Account and options for ${p.account.name}`} aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>
      {p.account.photo ? <span className="avatar-photo" style={{backgroundImage: `url(${JSON.stringify(p.account.photo)})`}}/> : <span>{p.account.initial}</span>}
     </button>
     : <button type="button" className="icon-button" aria-label="Options" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}><MoreIcon/></button>}
    {menuOpen && <div className="popover" role="dialog" aria-label="Options">
     {p.account && <div className="popover-account"><strong>{p.account.name}</strong>{p.account.detail && <span>{p.account.detail}</span>}</div>}
     {!pilot && <div className="popover-section">
      <h3>Research settings</h3>
      <label htmlFor="mode">Research mode</label>
      <select id="mode" value={p.mode} disabled={p.modeLocked} onChange={e => p.onMode(e.target.value)}>
       <option value="policy">Assist · answer, ask, hand off</option>
       <option value="baseline">Baseline · always answer</option>
      </select>
      <small>{p.modeLocked ? 'Applies to new conversations.' : p.mode === 'policy' ? 'Checks whether a guide fits before answering.' : 'Uses the closest guide even when details are missing. For comparison only.'}</small>
      {p.runtime && <small className="status-line"><span className={`status-dot ${p.runtime.status ?? ''}`}/>
       {p.runtime.provider === 'scripted' ? 'Offline scripted interpreter' : `Interpreter: ${p.runtime.provider}`}</small>}
     </div>}
     <Link className="popover-link" href="/team" onClick={() => setMenuOpen(false)}><ChartIcon/> Team results</Link>
     {p.account && <button type="button" className="popover-link" onClick={() => { setMenuOpen(false); p.onSignOut(); }}><LogOutIcon/> Sign out</button>}
    </div>}
   </div>
   {p.accountsOn && p.accountReady && !p.account && <button type="button" className="primary sign-in-button" onClick={p.onSignIn}>Sign in</button>}
  </div>
 </header>;
}
