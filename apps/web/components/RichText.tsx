import {Fragment, type ReactNode} from 'react';

// Replies are plain text. Support the little formatting guides use (**bold**, `code`) and link bare URLs.
const token = /(\*\*[^*\n]+\*\*|`[^`\n]+`|https?:\/\/[^\s)]+)/g;

export function RichText({text}: {text: string}) {
 const parts: ReactNode[] = [];
 let last = 0;
 for (const match of text.matchAll(token)) {
  const value = match[0];
  const at = match.index ?? 0;
  if (at > last) parts.push(text.slice(last, at));
  if (value.startsWith('**')) parts.push(<strong key={at}>{value.slice(2, -2)}</strong>);
  else if (value.startsWith('`')) parts.push(<code key={at}>{value.slice(1, -1)}</code>);
  else {
   const url = value.replace(/[.,;:!?]+$/, '');
   parts.push(<a key={at} href={url} target="_blank" rel="noopener noreferrer">{url}<span className="sr-only"> (opens in a new tab)</span></a>);
   if (url.length < value.length) parts.push(value.slice(url.length));
  }
  last = at + value.length;
 }
 if (last < text.length) parts.push(text.slice(last));
 return <>{parts.map((part, i) => <Fragment key={i}>{part}</Fragment>)}</>;
}
