'use client';

export default function Error({reset}: {error: Error; reset: () => void}) {
 return <main className="document" id="main">
  <h1>This page hit a problem</h1>
  <p role="alert">Try again. If it keeps happening, start a new conversation from the home page.</p>
  <button type="button" className="primary" onClick={reset}>Try again</button>
 </main>;
}
