'use client';
import {CopyIcon, MailIcon} from '@/components/Icons';

type Props = {
 draft: string; busy: boolean; supportEmail: string;
 onChange: (draft: string) => void; onSave: (then?: 'copy' | 'email') => void;
};

// The backend writes drafts as "Field: value" lines; show those as a summary above the editor.
function fields(draft: string) {
 return draft.split('\n').map(line => line.match(/^([A-Z][A-Za-z ]{2,30}):\s*(.+)$/)).filter(m => m !== null)
  .map(m => ({label: m[1], value: m[2]})).filter(f => !/^none( reported)?$/i.test(f.value));
}

export function TicketDraft({draft, busy, supportEmail, onChange, onSave}: Props) {
 const summary = fields(draft);
 return <section className="ticket">
  <h2>Your editable ticket draft</h2>
  <p className="muted">Nothing has been submitted. Check the details and remove anything personal, then copy it or email it to TechSpot.</p>
  {summary.length > 0 && <dl className="ticket-summary">{summary.map(f => <div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl>}
  <label htmlFor="draft" className="sr-only">Ticket draft</label>
  <textarea id="draft" value={draft} maxLength={5000} rows={8} onChange={e => onChange(e.target.value)}/>
  <div className="actions">
   <button type="button" disabled={busy} onClick={() => onSave()}>Save draft</button>
   <button type="button" className="secondary" disabled={busy} onClick={() => onSave('copy')}><CopyIcon/> Copy draft</button>
   <button type="button" className="secondary" disabled={busy} onClick={() => onSave('email')}><MailIcon/> Email to TechSpot</button>
  </div>
  {!supportEmail && <small className="hint">Email opens your mail app with the draft filled in; add the TechSpot address before sending.</small>}
 </section>;
}
