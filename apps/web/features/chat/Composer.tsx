'use client';
import {useLayoutEffect, useRef} from 'react';
import {SendIcon} from '@/components/Icons';

type Props = {text: string; busy: boolean; onChange: (text: string) => void; onSend: (text: string) => void};

export function Composer({text, busy, onChange, onSend}: Props) {
 const field = useRef<HTMLTextAreaElement>(null);
 // Grow with the message up to a few lines, then scroll.
 useLayoutEffect(() => {
  const el = field.current;
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
 }, [text]);
 return <form className="composer" onSubmit={e => { e.preventDefault(); onSend(text); }}>
  <label htmlFor="message" className="sr-only">Your message</label>
  <textarea id="message" ref={field} rows={1} maxLength={1000} placeholder="Describe your IT problem…" value={text} disabled={busy}
   aria-describedby="composer-hint" onChange={e => onChange(e.target.value)}
   onKeyDown={e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSend(text); }
   }}/>
  <div className="composer-row">
   <span id="composer-hint" className="composer-hint">Enter to send · Shift + Enter for a new line{text.length > 800 && ` · ${1000 - text.length} characters left`}</span>
   <button disabled={busy || !text.trim()} type="submit" className="send" aria-label="Send"><SendIcon size={18}/></button>
  </div>
 </form>;
}
