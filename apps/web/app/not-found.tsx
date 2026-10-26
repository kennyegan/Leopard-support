import Link from 'next/link';
import {PageHeader} from '@/components/PageHeader';

export default function NotFound() {
 return <><PageHeader/><main className="document" id="main">
  <h1>Page not found</h1>
  <p>That page doesn’t exist. Head back to the chat to keep troubleshooting.</p>
  <Link href="/" className="button primary">Back to chat</Link>
 </main></>;
}
