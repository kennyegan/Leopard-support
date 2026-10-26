'use client';
import {useState} from 'react';
import type {SavedSession} from '@/lib/api';
import {CloseIcon, TrashIcon} from '@/components/Icons';

type Props = {
 open: boolean; signedIn: boolean; sessions: SavedSession[] | null; current: string; error: string;
 onClose: () => void; onSelect: (id: string) => void; onDelete: (id: string) => void; onSignIn: () => void;
};

function group(sessions: SavedSession[]) {
 const day = 86400000;
 const today = new Date(); today.setHours(0, 0, 0, 0);
 const buckets: [string, SavedSession[]][] = [['Today', []], ['Previous 7 days', []], ['Earlier', []]];
 for (const s of sessions) {
  const t = new Date(s.updated_at).getTime();
  buckets[t >= today.getTime() ? 0 : t >= today.getTime() - 7 * day ? 1 : 2][1].push(s);
 }
 return buckets.filter(([, items]) => items.length);
}

export function HistoryRail({open, signedIn, sessions, current, error, onClose, onSelect, onDelete, onSignIn}: Props) {
 const [confirming, setConfirming] = useState('');
 return <>
  <div className={`scrim${open ? ' open' : ''}`} onClick={onClose} aria-hidden="true"/>
  <nav className={`history${open ? ' open' : ''}`} aria-label="Conversation history" inert={!open}>
   <div className="history-head">
    <h2>Conversations</h2>
    <button type="button" className="icon-button history-close" aria-label="Close history" onClick={onClose}><CloseIcon/></button>
   </div>
   {!signedIn && <div className="history-empty">
    <p>Sign in to save your conversations and come back to them later.</p>
    <button type="button" className="secondary" onClick={onSignIn}>Sign in</button>
   </div>}
   {signedIn && sessions === null && !error && <ul className="history-list" aria-busy="true">{[0, 1, 2].map(i => <li key={i}><span className="skeleton"/></li>)}</ul>}
   {signedIn && error && <p className="history-empty error-text">{error}</p>}
   {signedIn && sessions?.length === 0 && <p className="history-empty">Your saved conversations will appear here.</p>}
   {signedIn && sessions && group(sessions).map(([label, items]) => <section key={label} className="history-group">
    <h3>{label}</h3>
    <ul className="history-list">{items.map(s => <li key={s.id} className={s.id === current ? 'current' : ''}>
     {confirming === s.id
      ? <div className="history-confirm" role="group" aria-label="Delete conversation">
       <span>Delete for good?</span>
       <button type="button" className="danger small" onClick={() => { setConfirming(''); onDelete(s.id); }}>Delete</button>
       <button type="button" className="ghost small" onClick={() => setConfirming('')}>Keep</button>
      </div>
      : <>
       <button type="button" className="history-item" aria-current={s.id === current ? 'page' : undefined} onClick={() => onSelect(s.id)}>
        <span className="history-title">{s.title}</span>
        {s.outcome === 'resolved' && <span className="history-tag">Resolved</span>}
        {s.outcome === 'handoff' && <span className="history-tag handoff">Ticket</span>}
       </button>
       <button type="button" className="icon-button history-delete" aria-label={`Delete “${s.title}”`} onClick={() => setConfirming(s.id)}><TrashIcon/></button>
      </>}
    </li>)}</ul>
   </section>)}
  </nav>
 </>;
}
