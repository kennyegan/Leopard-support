'use client';
import {useEffect,useState} from 'react';
export default function Team(){
 const [pilot,setPilot]=useState(false);
 useEffect(()=>{fetch('/api/health').then(r=>r.json()).then(h=>setPilot(h.app_mode==='pilot')).catch(()=>{});},[]);
 const [token,setToken]=useState('');const [result,setResult]=useState('');const [error,setError]=useState('');
 return <main className="document"><div className="eyebrow">TEAM ONLY</div><h1>Demo results</h1><p>{pilot?'Aggregate counts only. Your invited account must have the administrator role.':'Aggregate counts only. The local team token stays in this page’s memory.'}</p><form onSubmit={async e=>{e.preventDefault();setError('');try{const r=await fetch('/api/admin/stats',{headers:{Authorization:`Bearer ${token}`}});if(!r.ok)throw Error('Team access denied or service unavailable.');setResult(JSON.stringify(await r.json(),null,2));}catch(e){setError((e as Error).message);}}}>{!pilot&&<><label htmlFor="token">Team access token</label><input id="token" type="password" autoComplete="off" value={token} onChange={e=>setToken(e.target.value)}/></>}<button>View aggregate results</button></form>{error&&<p role="alert">{error}</p>}{result&&<pre>{result}</pre>}</main>;
}
