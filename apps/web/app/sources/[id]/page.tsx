import Link from 'next/link';
import {cookies} from 'next/headers';
type Section={id:string;title:string;heading:string;section_text:string;steps:string[];source_url:string;corpus_version:string;is_synthetic:boolean;reference_links?:{title:string;url:string;checked_at:string}[];applicability:Record<string,string>};
export default async function Source({params,searchParams}:{params:Promise<{id:string}>,searchParams:Promise<{version?:string;section?:string}>}){
 const {id}=await params;
 const query=await searchParams;
 const sourceQuery=new URLSearchParams();
 if(typeof query.version==='string')sourceQuery.set('version',query.version);
 if(typeof query.section==='string')sourceQuery.set('section',query.section);
 const token = (await cookies()).get('__Host-techspot')?.value;
 let sections:Section[]=[];
 try{const r=await fetch(`${process.env.API_BASE_URL || "http://127.0.0.1:8000"}/api/guides/${encodeURIComponent(id)}?${sourceQuery}`,{cache:'no-store',headers:token?{Cookie:`__Host-techspot=${encodeURIComponent(token)}`}:{}});if(r.ok)sections=await r.json();}catch{}
 return <main className="document"><Link href="/">← Back to chat</Link><div className="eyebrow">SYNTHETIC SOURCE</div>{sections.length? <><h1>{sections[0].title}</h1><p>This fictional guide is for local demonstration only.</p><code>{sections[0].source_url} · {sections[0].corpus_version}</code>{sections[0].reference_links?.map(ref=><a className="official-reference" key={ref.url} href={ref.url} target="_blank" rel="noopener noreferrer">{ref.title}<small>Official vendor reference · checked {ref.checked_at}</small></a>)}{sections.map((s,i)=><section key={i}><h2>{s.heading}</h2><p>{s.section_text}</p><ol>{s.steps.map(step=><li key={step}>{step}</li>)}</ol><p>Applies to: {Object.entries(s.applicability).map(([k,v])=>`${k}: ${v}`).join(' · ') || 'General diagnostic checks; confirm they fit your situation.'}</p></section>)}</>:<h1>Source unavailable</h1>}</main>;
}
