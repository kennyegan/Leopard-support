'use client';
import {useEffect, useState} from 'react';

type Row = {n: number; [key: string]: string | number | null};
type Stats = {sessions: number; questions: number; decisions: Row[]; outcomes: Row[]; feedback: Row[]};

function Table({caption, rows, columns}: {caption: string; rows: Row[]; columns: string[]}) {
 return <table><caption className="sr-only">{caption}</caption>
  <thead><tr>{columns.map(c => <th key={c} scope="col">{c}</th>)}<th scope="col" className="num">Count</th></tr></thead>
  <tbody>{rows.length ? rows.map((r, i) => <tr key={i}>{columns.map(c => <td key={c}>{String(r[c.toLowerCase()] ?? '—')}</td>)}<td className="num">{r.n}</td></tr>)
   : <tr><td colSpan={columns.length + 1}>No data yet.</td></tr>}</tbody>
 </table>;
}

export default function Team() {
 const [pilot, setPilot] = useState(false);
 useEffect(() => { fetch('/api/health').then(r => r.json()).then(h => setPilot(h.app_mode === 'pilot')).catch(() => {}); }, []);
 const [token, setToken] = useState('');
 const [stats, setStats] = useState<Stats | null>(null);
 const [error, setError] = useState('');
 const [loading, setLoading] = useState(false);
 const count = (rows: Row[], key: string, value: string) => rows.find(r => r[key] === value)?.n ?? 0;
 return <main className="document" id="main">
  <div className="eyebrow">Team only</div>
  <h1>Demo results</h1>
  <p>{pilot ? 'Aggregate counts only. Your invited account must have the administrator role.' : 'Aggregate counts only. The team token stays in this page’s memory.'}</p>
  <form onSubmit={async e => {
   e.preventDefault(); setError(''); setLoading(true);
   try {
    const r = await fetch('/api/admin/stats', {headers: {Authorization: `Bearer ${token}`}});
    if (!r.ok) throw Error('Team access denied or service unavailable.');
    setStats(await r.json());
   } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }}>
   {!pilot && <><label htmlFor="token">Team access token</label><input id="token" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)}/></>}
   <button disabled={loading}>{loading ? 'Loading…' : 'View aggregate results'}</button>
  </form>
  {error && <p role="alert" className="error">{error}</p>}
  {stats && <>
   <div className="stats">
    <div className="stat"><b>{stats.sessions}</b><span>Conversations</span></div>
    <div className="stat"><b>{stats.questions}</b><span>Follow-up questions</span></div>
    <div className="stat"><b>{count(stats.outcomes, 'outcome', 'resolved')}</b><span>Resolved</span></div>
    <div className="stat"><b>{count(stats.outcomes, 'outcome', 'handoff')}</b><span>Handed to a person</span></div>
   </div>
   <h2>Decisions</h2><Table caption="Decisions by action" rows={stats.decisions} columns={['Action']}/>
   <h2>Outcomes</h2><Table caption="Conversation outcomes" rows={stats.outcomes} columns={['Outcome']}/>
   <h2>Feedback</h2><Table caption="Feedback by kind and value" rows={stats.feedback} columns={['Kind', 'Value']}/>
  </>}
 </main>;
}
