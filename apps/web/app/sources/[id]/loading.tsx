export default function Loading() {
 return <main className="document" id="main" aria-busy="true">
  <p role="status" className="sr-only">Loading guide…</p>
  <div className="skeleton" style={{width: '30%'}}/>
  <div className="skeleton" style={{width: '70%', height: 30}}/>
  <div className="skeleton"/><div className="skeleton"/><div className="skeleton" style={{width: '60%'}}/>
 </main>;
}
