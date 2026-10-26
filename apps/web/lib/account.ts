'use client';
import {useEffect, useState} from 'react';
import type {Auth, ConfirmationResult, User} from 'firebase/auth';
import {setAccountTokenProvider} from './api';

const config = {
 apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
 authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
 projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
 appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};
export const accountsEnabled = Boolean(config.apiKey && config.authDomain && config.projectId);
// Phone codes are billed per SMS, so the option stays hidden until it is switched on.
export const phoneEnabled = accountsEnabled && process.env.NEXT_PUBLIC_ENABLE_PHONE_SIGN_IN === '1';
const emailKey = 'leopard.signin.email';

export type Account = {uid: string; name: string; detail: string; initial: string; photo: string | null};

let authPromise: Promise<Auth> | null = null;
function auth() {
 if (!accountsEnabled) return Promise.reject(new Error('Sign-in is not set up on this site yet.'));
 authPromise ??= (async () => {
  const [{initializeApp, getApps}, {getAuth}] = await Promise.all([import('firebase/app'), import('firebase/auth')]);
  const instance = getAuth(getApps()[0] ?? initializeApp(config));
  instance.useDeviceLanguage();
  setAccountTokenProvider(async () => instance.currentUser ? instance.currentUser.getIdToken() : '');
  return instance;
 })();
 return authPromise;
}

function describe(user: User): Account {
 const name = user.displayName || user.email?.split('@')[0] || user.phoneNumber || 'Your account';
 return {uid: user.uid, name, detail: user.email || user.phoneNumber || '', initial: name.trim().charAt(0).toUpperCase() || '·', photo: user.photoURL};
}

export function useAccount() {
 const [state, setState] = useState<{ready: boolean; account: Account | null}>({ready: !accountsEnabled, account: null});
 useEffect(() => {
  if (!accountsEnabled) return;
  let unsubscribe = () => {};
  let cancelled = false;
  void (async () => {
   try {
    const [instance, {onAuthStateChanged}] = await Promise.all([auth(), import('firebase/auth')]);
    if (cancelled) return;
    unsubscribe = onAuthStateChanged(instance, user => setState({ready: true, account: user ? describe(user) : null}));
   } catch { if (!cancelled) setState({ready: true, account: null}); }
  })();
  return () => { cancelled = true; unsubscribe(); };
 }, []);
 return state;
}

const messages: Record<string, string> = {
 'auth/invalid-email': 'That email address doesn’t look right.',
 'auth/missing-email': 'Enter your email address.',
 'auth/invalid-phone-number': 'Enter the full number with country code, like +1 617 555 0123.',
 'auth/missing-phone-number': 'Enter your phone number.',
 'auth/invalid-verification-code': 'That code isn’t right. Check the text message and try again.',
 'auth/code-expired': 'That code expired. Send a new one.',
 'auth/invalid-action-code': 'This sign-in link expired or was already used. Request a new one.',
 'auth/too-many-requests': 'Too many attempts. Wait a few minutes and try again.',
 'auth/network-request-failed': 'You seem to be offline. Check your connection and try again.',
 'auth/popup-blocked': 'Your browser blocked the Google window. Allow pop-ups for this site and try again.',
 'auth/unauthorized-domain': 'Sign-in isn’t allowed on this web address yet. Add it to Firebase’s authorized domains.',
 'auth/operation-not-allowed': 'This sign-in method isn’t turned on yet.',
 'auth/billing-not-enabled': 'Phone sign-in needs billing turned on in Firebase.',
};
export function signInError(error: unknown) {
 const code = (error as {code?: string})?.code ?? '';
 if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') return '';
 return messages[code] ?? 'Sign-in didn’t work. Please try again.';
}

export const signIn = {
 async google() {
  const [instance, {GoogleAuthProvider, signInWithPopup}] = await Promise.all([auth(), import('firebase/auth')]);
  await signInWithPopup(instance, new GoogleAuthProvider());
 },
 async sendEmailLink(email: string) {
  const [instance, {sendSignInLinkToEmail}] = await Promise.all([auth(), import('firebase/auth')]);
  await sendSignInLinkToEmail(instance, email, {url: `${window.location.origin}/auth/finish`, handleCodeInApp: true});
  localStorage.setItem(emailKey, email);
 },
 /** Completes an emailed link opened in this browser. */
 async finishEmailLink(typedEmail?: string): Promise<'done' | 'needs-email' | 'not-a-link'> {
  const [instance, {isSignInWithEmailLink, signInWithEmailLink}] = await Promise.all([auth(), import('firebase/auth')]);
  if (!isSignInWithEmailLink(instance, window.location.href)) return 'not-a-link';
  const email = typedEmail || localStorage.getItem(emailKey);
  if (!email) return 'needs-email';
  await signInWithEmailLink(instance, email, window.location.href);
  localStorage.removeItem(emailKey);
  return 'done';
 },
 async sendPhoneCode(phone: string, buttonId: string): Promise<ConfirmationResult> {
  const [instance, {RecaptchaVerifier, signInWithPhoneNumber}] = await Promise.all([auth(), import('firebase/auth')]);
  const verifier = new RecaptchaVerifier(instance, buttonId, {size: 'invisible'});
  try { return await signInWithPhoneNumber(instance, phone, verifier); }
  finally { verifier.clear(); }
 },
 async confirmPhoneCode(confirmation: ConfirmationResult, code: string) {
  await confirmation.confirm(code);
 },
 async signOut() {
  const [instance, {signOut}] = await Promise.all([auth(), import('firebase/auth')]);
  await signOut(instance);
 },
};
