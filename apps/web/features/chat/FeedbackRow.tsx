'use client';
import {useState} from 'react';
import {canReportFix, type Reply} from '@/lib/api';
import {ThumbDownIcon, ThumbUpIcon} from '@/components/Icons';

export type FeedbackKind = 'rating' | 'fix' | 'question';
type Props = {
 reply: Reply; ratings: Record<string, string>; busy: boolean; latest: boolean;
 onFeedback: (kind: FeedbackKind, value: string, reason?: string, comment?: string) => void;
};

const answerReasons = ['Wrong steps', 'Unclear', 'Wrong guide', 'Didn’t work', 'Other'];
const questionReasons = ['Not relevant', 'Already answered', 'Confusing', 'Other'];

export function FeedbackRow({reply, ratings, busy, latest, onFeedback}: Props) {
 const [asking, setAsking] = useState<FeedbackKind | null>(null);
 const [reason, setReason] = useState('');
 const [comment, setComment] = useState('');
 const voted = (kind: FeedbackKind) => ratings[`${reply.id}-${kind}`];

 function submit(kind: FeedbackKind, withDetails: boolean) {
  onFeedback(kind, 'no', withDetails ? reason : '', withDetails ? comment : '');
  setAsking(null); setReason(''); setComment('');
 }

 if (asking) {
  const reasons = asking === 'question' ? questionReasons : answerReasons;
  return <div className="feedback feedback-detail" role="group" aria-label="Tell us what went wrong">
   <span className="feedback-prompt">What went wrong? <small>Optional</small></span>
   <div className="chips">{reasons.map(r =>
    <button type="button" key={r} className="chip" aria-pressed={reason === r} onClick={() => setReason(reason === r ? '' : r)}>{r}</button>)}
   </div>
   <label htmlFor={`comment-${reply.id}`} className="sr-only">Feedback comment</label>
   <input id={`comment-${reply.id}`} value={comment} maxLength={500} placeholder="Anything else? (no personal information)" onChange={e => setComment(e.target.value)}/>
   <div className="feedback-actions">
    <button type="button" disabled={busy} onClick={() => submit(asking, true)}>Send feedback</button>
    <button type="button" className="ghost" disabled={busy} onClick={() => submit(asking, false)}>Skip</button>
   </div>
  </div>;
 }

 if (reply.action === 'ASK') {
  return <div className="feedback"><div className="feedback-group" role="group" aria-label="Question usefulness">
   <span>Was this question helpful?</span>
   {(['yes', 'no'] as const).map(v => <button type="button" key={v} className="vote" disabled={busy || !!voted('question')} aria-pressed={voted('question') === v}
    onClick={() => v === 'no' ? setAsking('question') : onFeedback('question', v)}>{v === 'yes' ? 'Yes' : 'No'}</button>)}
  </div></div>;
 }

 return <div className="feedback">
  <div className="feedback-group" role="group" aria-label="Answer usefulness">
   <span>Was this useful?</span>
   {(['yes', 'no'] as const).map(v => <button type="button" key={v} className="vote icon" disabled={busy || !!voted('rating')} aria-pressed={voted('rating') === v}
    aria-label={v === 'yes' ? 'Thumbs up' : 'Thumbs down'} title={v === 'yes' ? 'Helpful' : 'Not helpful'}
    onClick={() => v === 'no' ? setAsking('rating') : onFeedback('rating', v)}>{v === 'yes' ? <ThumbUpIcon/> : <ThumbDownIcon/>}</button>)}
  </div>
  {canReportFix(reply) && <div className="feedback-group" role="group" aria-label="Problem resolution">
   <span>{reply.request_type === 'install' ? 'Is your software ready to use?' : 'Did this fix it?'}</span>
   {(['yes', 'no'] as const).map(v => <button type="button" key={v} className="vote" disabled={busy || !!voted('fix') || !latest} aria-pressed={voted('fix') === v}
    onClick={() => onFeedback('fix', v)}>{v === 'yes' ? 'Yes' : 'No'}</button>)}
  </div>}
 </div>;
}
