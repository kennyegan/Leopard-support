'use client';
import {SendIcon} from '@/components/Icons';

type Props = {text: string; busy: boolean; onChange: (text: string) => void; onSend: (text: string) => void};

export function Composer({text, busy, onChange, onSend}: Props) {
 return <form className="composer" onSubmit={e => { e.preventDefault(); onSend(text); }}>
  <label htmlFor="message" className="sr-only">Your message</label>
  <div className="input-row">
   <textarea id="message" rows={2} maxLength={1000} placeholder="Describe your IT problem…" value={text} disabled={busy}
    aria-describedby="composer-hint" onChange={e => onChange(e.target.value)}
    onKeyDown={e => {
     if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSend(text); }
    }}/>
   <button disabled={busy || !text.trim()} type="submit" className="send">Send <SendIcon/></button>
  </div>
  <div className="composer-meta" id="composer-hint">
   <span>Enter to send · Shift + Enter for a new line · Don’t include passwords or personal information</span>
   <span aria-live="off">{text.length}/1000</span>
  </div>
 </form>;
}
