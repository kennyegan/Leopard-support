import type {Metadata, Viewport} from 'next';
import {Schibsted_Grotesk} from 'next/font/google';
import './globals.css';

const sans = Schibsted_Grotesk({subsets: ['latin'], variable: '--font-sans', display: 'swap'});

export const metadata: Metadata = {
 title: {default: 'Leopard Support · Wentworth IT help', template: '%s · Leopard Support'},
 description: 'Describe a tech problem and get step-by-step help from TechSpot guides at Wentworth Institute of Technology.',
};
export const viewport: Viewport = {
 width: 'device-width', initialScale: 1, viewportFit: 'cover',
 themeColor: [{media: '(prefers-color-scheme: light)', color: '#f6f4ef'}, {media: '(prefers-color-scheme: dark)', color: '#141519'}],
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
 return <html lang="en" className={sans.variable}><body>
  <a href="#main" className="skip-link">Skip to content</a>
  {children}
 </body></html>;
}
