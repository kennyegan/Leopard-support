'use client';
import {useEffect, useRef, useState} from 'react';
import type {ConfirmationResult} from 'firebase/auth';
import {phoneEnabled, signIn, signInError} from '@/lib/account';
import {ArrowLeftIcon, CloseIcon, GoogleIcon, MailIcon, PhoneIcon} from '@/components/Icons';
import {LeopardMark} from '@/components/LeopardMark';

type Step = 'choose' | 'email-sent' | 'phone' | 'phone-code';

export function SignInDialog({open, onClose}: {open: boolean; onClose: () => void}) {
 const dialog = useRef<HTMLDialogElement>(null);
 const [step, setStep] = useState<Step>('choose');
 const [email, setEmail] = useState('');
 const [phone, setPhone] = useState('');
 const [code, setCode] = useState('');
 const [busy, setBusy] = useState(false);
 const [error, setError] = useState('');
 const confirmation = useRef<ConfirmationResult | null>(null);

 useEffect(() => {
  const el = dialog.current;
  if (!el) return;
  if (open && !el.open) { setStep('choose'); setError(''); setCode(''); el.showModal(); }
  if (!open && el.open) el.close();
 }, [open]);

 async function run(action: () => Promise<void>) {
  setBusy(true); setError('');
  try { await action(); }
  catch (e) { setError(signInError(e)); }
  finally { setBusy(false); }
 }

 return <dialog ref={dialog} className="sign-in" aria-labelledby="sign-in-title" onClose={onClose}
  onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
  <div className="sign-in-body">
   <button type="button" className="icon-button close" aria-label="Close" onClick={onClose}><CloseIcon/></button>
   <LeopardMark size={40} tile/>
   {step === 'choose' && <>
    <h2 id="sign-in-title">Sign in to keep your chats</h2>
    <p className="muted">Pick up where you left off on any device. You can keep chatting as a guest without signing in.</p>
    <button type="button" className="provider" disabled={busy} onClick={() => run(async () => { await signIn.google(); onClose(); })}>
     <GoogleIcon/> Continue with Google
    </button>
    <div className="divider"><span>or</span></div>
    <form onSubmit={e => { e.preventDefault(); void run(async () => { await signIn.sendEmailLink(email.trim()); setStep('email-sent'); }); }}>
     <label htmlFor="sign-in-email">Email</label>
     <input id="sign-in-email" type="email" autoComplete="email" required placeholder="you@wit.edu" value={email} onChange={e => setEmail(e.target.value)}/>
     <button type="submit" className="primary wide" disabled={busy || !email.trim()}><MailIcon/> Email me a sign-in link</button>
    </form>
    {phoneEnabled && <button type="button" className="text-button" onClick={() => { setError(''); setStep('phone'); }}><PhoneIcon/> Use a phone number instead</button>}
   </>}
   {step === 'email-sent' && <>
    <h2 id="sign-in-title">Check your inbox</h2>
    <p className="muted">We sent a sign-in link to <strong>{email}</strong>. Open it on this device to finish signing in. It can take a minute to arrive; check spam if you don’t see it.</p>
    <button type="button" className="secondary wide" onClick={() => setStep('choose')}><ArrowLeftIcon/> Use a different method</button>
   </>}
   {step === 'phone' && <>
    <h2 id="sign-in-title">Sign in with your phone</h2>
    <p className="muted">We’ll text you a 6-digit code. Message and data rates may apply.</p>
    <form onSubmit={e => { e.preventDefault(); void run(async () => { confirmation.current = await signIn.sendPhoneCode(phone.trim(), 'send-code'); setStep('phone-code'); }); }}>
     <label htmlFor="sign-in-phone">Mobile number</label>
     <input id="sign-in-phone" type="tel" autoComplete="tel" inputMode="tel" required placeholder="+1 617 555 0123" value={phone} onChange={e => setPhone(e.target.value)}/>
     <button id="send-code" type="submit" className="primary wide" disabled={busy || !phone.trim()}>Text me a code</button>
    </form>
    <button type="button" className="text-button" onClick={() => setStep('choose')}><ArrowLeftIcon/> Other ways to sign in</button>
   </>}
   {step === 'phone-code' && <>
    <h2 id="sign-in-title">Enter your code</h2>
    <p className="muted">Sent to <strong>{phone}</strong>.</p>
    <form onSubmit={e => { e.preventDefault(); void run(async () => { await signIn.confirmPhoneCode(confirmation.current!, code.trim()); onClose(); }); }}>
     <label htmlFor="sign-in-code">6-digit code</label>
     <input id="sign-in-code" className="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))}/>
     <button type="submit" className="primary wide" disabled={busy || code.length !== 6}>Verify and sign in</button>
    </form>
    <button type="button" className="text-button" onClick={() => setStep('phone')}><ArrowLeftIcon/> Change number</button>
   </>}
   {error && <p role="alert" className="error">{error}</p>}
   <p className="fine-print">Your sign-in is only used to save your conversations.</p>
  </div>
 </dialog>;
}
