import type {Metadata, Viewport} from 'next';
import Link from 'next/link';
import {LeopardMark} from '@/components/Icons';
import './globals.css';

export const metadata: Metadata = {
 title: {default: 'Leopard Support · Wentworth IT help', template: '%s · Leopard Support'},
 description: 'Describe a tech problem and get step-by-step help from TechSpot guides at Wentworth Institute of Technology.',
};
export const viewport: Viewport = {themeColor: '#15171c', width: 'device-width', initialScale: 1};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
 return <html lang="en"><body>
  <a href="#main" className="skip-link">Skip to content</a>
  <div className="demo-banner">Demo · Uses sample troubleshooting guides — not official TechSpot advice</div>
  <header className="site-header">
   <Link href="/" className="brand" aria-label="Leopard Support home"><LeopardMark/><span>Leopard <b>Support</b></span></Link>
   <span className="brand-sub">Wentworth Institute of Technology · Senior project</span>
   <nav aria-label="Site"><Link href="/team" className="team-link">Team results</Link></nav>
  </header>
  {children}
  <footer className="site-footer">Leopard Support never submits tickets on its own. Keep passwords and personal information out of chat. A Wentworth senior project.</footer>
 </body></html>;
}
