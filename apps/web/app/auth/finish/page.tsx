'use client';
import {useEffect, useState} from 'react';
import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {signIn, signInError} from '@/lib/account';
import {LeopardMark} from '@/components/LeopardMark';

export default function FinishSignIn() {
 const router = useRouter();
 const [state, setState] = useState<'working' | 'needs-email' | 'error'>('working');
 const [email, setEmail] = useState('');
 const [error, setError] = useState('');

 async function finish(typed?: string) {
  setState('working'); setError('');
  try {
   const result = await signIn.finishEmailLink(typed);
   if (result === 'needs-email') return setState('needs-email');
   router.replace('/');
  } catch (e) { setError(signInError(e)); setState('error'); }
 }
 useEffect(() => {
  signIn.finishEmailLink().then(result => {
   if (result === 'needs-email') setState('needs-email'); else router.replace('/');
  }).catch(e => { setError(signInError(e)); setState('error'); });
 }, [router]);

 return <main className="gate" id="main"><div className="gate-card">
  <LeopardMark size={56} tile/>
  {state === 'working' && <><h1>Signing you in…</h1><p role="status"><span className="spinner" aria-hidden="true"/>One moment.</p></>}
  {state === 'needs-email' && <>
   <h1>Confirm your email</h1>
   <p className="muted">You opened the link on a different device or browser. Enter the email you used so we can finish signing you in.</p>
   <form className="stack" onSubmit={e => { e.preventDefault(); setState('working'); setError(''); void finish(email.trim()); }}>
    <label htmlFor="finish-email">Email</label>
    <input id="finish-email" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)}/>
    <button type="submit" className="primary wide">Finish signing in</button>
   </form>
  </>}
  {state === 'error' && <><h1>That link didn’t work</h1><p role="alert" className="error">{error}</p><Link className="button primary" href="/">Back to chat</Link></>}
 </div></main>;
}
