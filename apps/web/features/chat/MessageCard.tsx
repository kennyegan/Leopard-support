'use client';
import Link from 'next/link';
import {outcomeLabel, type Message} from '@/lib/api';
import {RichText} from '@/components/RichText';
import {BookIcon, ExternalIcon, RetryIcon} from '@/components/Icons';
import {LeopardMark} from '@/components/LeopardMark';
import {FeedbackRow, type FeedbackKind} from './FeedbackRow';

type Props = {
 message: Message; latest: boolean; busy: boolean; ratings: Record<string, string>; showProvider: boolean;
 onReply: (text: string) => void; onRetry: () => void;
 onFeedback: (kind: FeedbackKind, value: string, reason?: string, comment?: string) => void;
};

const quiet = ['status', 'explanation', 'service_error'];

export function MessageCard({message: m, latest, busy, ratings, showProvider, onReply, onRetry, onFeedback}: Props) {
 const r = m.response;
 if (m.role === 'user') {
  return <article className={`message user${m.failed ? ' failed' : ''}`}>
   <div className="message-label">You</div>
   <p><RichText text={m.text}/></p>
   {m.failed && <div className="send-failed"><span>Not sent.</span>
    <button type="button" className="ghost small" disabled={busy} onClick={onRetry}><RetryIcon/> Retry</button></div>}
  </article>;
 }
 return <article className="message assistant">
  <div className="message-label"><LeopardMark size={22} tile className="avatar"/>Leopard Support
   {r && <span className={`outcome ${r.action.toLowerCase()}`}>{outcomeLabel(r)}</span>}</div>
  <p><RichText text={m.text}/></p>
  {r && <>
   {r.steps.length > 0 && <ol className="steps">{r.steps.map((step, i) => <li key={i}><RichText text={step}/></li>)}</ol>}
   {r.progress && ['guide', 'check'].includes(r.response_kind || '') && <div className="next-check">
    <small>Step {r.progress.current} of {r.progress.total}</small>
    <div className="progress" aria-hidden="true"><span style={{width: `${Math.min(100, r.progress.current / r.progress.total * 100)}%`}}/></div>
    <p>{r.progress.prompt}</p>
   </div>}
   {(r.sources.length > 0 || !!r.references?.length) && <div className="sources">
    {r.sources.map(s => <Link className="source" key={s.id} href={s.href} target="_blank">
     <BookIcon/><span>{s.title}<small>Sample TechSpot guide · {s.id}</small></span><ExternalIcon/><span className="sr-only">(opens in a new tab)</span></Link>)}
    {r.references?.map(ref => <a className="official-reference" key={ref.url} href={ref.url} target="_blank" rel="noopener noreferrer">
     <ExternalIcon/><span>{ref.title}<small>Official vendor site</small></span><span className="sr-only">(opens in a new tab)</span></a>)}
   </div>}
   {r.options.length > 0 && <div className="quick-replies" role="group" aria-label="Suggested replies">
    {r.options.map(o => <button type="button" disabled={busy || !latest} onClick={() => onReply(o)} key={o}>{o}</button>)}
   </div>}
   {r.action !== 'HANDOFF' && !quiet.includes(r.response_kind || '') &&
    <FeedbackRow reply={r} ratings={ratings} busy={busy} latest={latest} onFeedback={onFeedback}/>}
   {showProvider && <small className="provider-label">{r.provider}</small>}
  </>}
 </article>;
}
