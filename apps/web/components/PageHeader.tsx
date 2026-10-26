import Link from 'next/link';
import {ArrowLeftIcon} from './Icons';
import {LeopardMark} from './LeopardMark';

// Header for pages outside the chat: guide viewer, team results, errors.
export function PageHeader() {
 return <header className="topbar page-header">
  <div className="topbar-start"><Link href="/" className="wordmark" aria-label="Leopard Support home"><LeopardMark size={28} tile/><span>Leopard Support</span></Link></div>
  <div className="topbar-end"><Link href="/" className="back-link"><ArrowLeftIcon/> Back to chat</Link></div>
 </header>;
}
