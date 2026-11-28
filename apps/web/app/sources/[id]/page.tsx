import {cookies} from 'next/headers';
import {BookIcon, ExternalIcon} from '@/components/Icons';
import {PageHeader} from '@/components/PageHeader';
type Section={id:string;title:string;heading:string;section_text:string;steps:string[];source_url:string;corpus_version:string;is_synthetic:boolean;content_owner?:string;reviewed_at?:string;review_due?:string;reference_links?:{title:string;url:string;checked_at:string}[];applicability:Record<string,string>};
export default async function Source({params,searchParams}:{params:Promise<{id:string}>,searchParams:Promise<{version?:string;section?:string}>}){
 const {id}=await params;
 const query=await searchParams;
 const sourceQuery=new URLSearchParams();
 if(typeof query.version==='string')sourceQuery.set('version',query.version);
 if(typeof query.section==='string')sourceQuery.set('section',query.section);
 const token = (await cookies()).get('__Host-techspot')?.value;
 let sections:Section[]=[];
 try{const r=await fetch(`${process.env.API_BASE_URL || "http://127.0.0.1:8000"}/api/guides/${encodeURIComponent(id)}?${sourceQuery}`,{cache:'no-store',headers:token?{Cookie:`__Host-techspot=${encodeURIComponent(token)}`}:{}});if(r.ok)sections=await r.json();}catch{}
 const first=sections[0];
 return <><PageHeader/><main className="document" id="main">
  <p className="doc-kind"><BookIcon size={14}/> {first?.is_synthetic === false ? 'Campus documentation' : 'Synthetic source guide'}</p>
  {first? <>
   <h1>{first.title}</h1>
   {first.is_synthetic ? <p>This fictional guide is for local demonstration only.</p> : <p>Reviewed by {first.content_owner}. Last reviewed: {first.reviewed_at}. Review due: {first.review_due}.</p>}
   <span className="meta">{first.is_synthetic ? <code>{first.source_url}</code> : <a href={first.source_url} target="_blank" rel="noopener noreferrer">Original campus article<span className="sr-only"> (opens in a new tab)</span></a>} · {first.corpus_version}</span>
   {first.reference_links?.map(ref=><a className="official-reference" key={ref.url} href={ref.url} target="_blank" rel="noopener noreferrer"><ExternalIcon/><span>{ref.title}<small>Official vendor reference · checked {ref.checked_at}</small></span><span className="sr-only">(opens in a new tab)</span></a>)}
   {sections.map((s,i)=><section key={i}>
    <h2>{s.heading}</h2><p>{s.section_text}</p>
    {s.steps.length>0&&<ol>{s.steps.map(step=><li key={step}>{step}</li>)}</ol>}
    <p className="applies">Applies to: {Object.entries(s.applicability).map(([k,v])=>`${k}: ${v}`).join(' · ') || 'General diagnostic checks; confirm they fit your situation.'}</p>
   </section>)}
  </>:<><h1>Source unavailable</h1><p>This source is unavailable or your account does not have access. Return to the conversation for help.</p></>}
 </main></>;
}
