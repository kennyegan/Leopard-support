import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';
export const metadata: Metadata = { title: 'TechSpot Assist · Demo', description: 'A synthetic IT support research demonstration.' };
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>) {
 return <html lang="en"><body><div className="demo-banner">DEMO — synthetic troubleshooting guides; not official TechSpot advice</div><header><Link href="/" className="brand"><span className="mark">T</span> TechSpot <span className="light">Assist</span></Link><span className="research-label">A student research project</span><Link href="/team" className="team-link">Team results ↗</Link></header>{children}<footer>Built for a local demonstration · No tickets are submitted · Keep passwords and personal information out of chat.</footer></body></html>;
}
