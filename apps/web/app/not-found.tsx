import Link from 'next/link';

export default function NotFound() {
 return <main className="document" id="main">
  <div className="eyebrow">404</div>
  <h1>Page not found</h1>
  <p>That page doesn’t exist. Head back to the chat to keep troubleshooting.</p>
  <Link href="/" className="button">Back to chat</Link>
 </main>;
}
