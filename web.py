# web.py  
# DizerCoreAI — dashboard HTML/JS (served by routes.py at "/").  
# Exposes DASHBOARD_HTML only. Logo is served from /static/dizercore.png  
# (mount StaticFiles in dizercoreai.py). Login/Register HTML live in auth.py.  
  
DASHBOARD_HTML = """<!DOCTYPE html><html><head><title>DizerCoreAI</title>  
<link rel="icon" href="/static/dizercore.png">  
<style>  
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;  
         background:#0f172a; color:#f8fafc; margin:0; display:flex; height:100vh; }  
  #left { width:280px; border-right:1px solid #334155; padding:14px; overflow-y:auto; }  
  #right { flex:1; padding:18px; overflow-y:auto; }  
  h2,h3 { color:#38bdf8; }  
  .brand { display:flex; align-items:center; gap:10px; margin-bottom:8px; }  
  .brand img { width:40px; height:40px; object-fit:contain; }  
  textarea { width:100%; height:90px; background:#1e293b; color:#f8fafc;  
             border:1px solid #334155; padding:10px; border-radius:6px; }  
  button { background:#0284c7; color:#fff; border:none; padding:9px 16px;  
           border-radius:6px; cursor:pointer; margin-top:6px; }  
  button.stop { background:#b91c1c; }  
  button.clear { background:#475569; }  
  pre { background:#1e293b; padding:12px; border-radius:6px; white-space:pre-wrap;  
        word-wrap:break-word; }  
  .job { padding:8px; border:1px solid #334155; border-radius:6px; margin-bottom:6px;  
         font-size:13px; display:flex; justify-content:space-between; align-items:center; }  
  .jtitle { cursor:pointer; flex:1; }  
  .del { background:#b91c1c; color:#fff; border:none; border-radius:4px;  
         padding:2px 8px; margin:0 0 0 6px; cursor:pointer; line-height:1; }  
  #drop { border:2px dashed #334155; border-radius:6px; padding:16px; text-align:center;  
          color:#94a3b8; margin:8px 0; cursor:pointer; }  
  #drop.hover { border-color:#38bdf8; color:#38bdf8; }  
  label { font-size:13px; margin-right:12px; }  
  .meta { font-size:12px; color:#94a3b8; margin:2px 0 8px; }  
  .fitem { display:inline-block; background:#1e293b; border:1px solid #334155;  
           border-radius:4px; padding:2px 6px; margin:2px; font-size:12px; }  
  .fitem .x { color:#f87171; cursor:pointer; margin-left:6px; font-weight:bold; }  
  #complexity_val { color:#38bdf8; font-weight:bold; }  
  #version { font-size:11px; color:#64748b; margin-top:2px; }  
  #summary_box { border:1px solid #334155; border-radius:6px; padding:12px;  
                 margin-top:10px; background:#1e293b; }  
  #summary_box h3 { margin-top:0; }  
  /* Every agent/judge heading is a fixed row: title + spinner on the left,  
     the Copy button pinned to the right so it never moves when the <pre> grows. */  
  .agent-head { display:flex; align-items:center; margin-bottom:0; }  
  .spin { color:#38bdf8; font-size:13px; font-weight:normal; margin-left:8px;  
          font-family:monospace; }  
  .copybtn { margin-left:auto; background:#334155; color:#f8fafc; border:none;  
             padding:3px 12px; border-radius:4px; cursor:pointer; font-size:12px;  
             margin-top:0; }  
  .copybtn:hover { background:#475569; }  
</style></head>  
<body>  
<div id="left">  
  <div class="brand"><img src="/static/dizercore.png" alt="DizerCoreAI"><h2>DizerCoreAI</h2></div>  
  <div id="version"></div>  
  <form method="post" action="/logout"><button>Log out</button></form>  
  <h3>History</h3>  
  <div id="jobs"></div>  
</div>  
<div id="right">  
  <textarea id="prompt" placeholder="Describe the task..."></textarea>  
  <div id="drop">Drag &amp; drop files here (.txt .h .cpp .sql images), or click to browse  
    <input id="file" type="file" multiple style="display:none">  
  </div>  
  <div id="filelist"></div>  
  <div style="margin:8px 0;">  
    <label>Complexity:  
      <input type="range" id="complexity" min="1" max="5" value="3"  
             oninput="document.getElementById('complexity_val').textContent=this.value + tierName(this.value)">  
      <span id="complexity_val">3 (normal)</span>  
    </label>  
  </div>  
  <div>  
    <label><input type="checkbox" id="openrouter" checked> OpenRouter</label>  
    <label><input type="checkbox" id="groq" checked> Groq</label>  
    <label><input type="checkbox" id="gemini" checked> Gemini</label>  
    <label><input type="checkbox" id="inkling" checked> Judge Pool</label>  
  </div>  
  <button onclick="run()">Run</button>  
  <button class="stop" onclick="stop()">Stop</button>  
  <button class="clear" onclick="clearChat()">Clear chat</button>  
  <p id="state"></p>  
  
  <h3 class="agent-head">OpenRouter<span class="spin" id="generate_spin"></span>  
    <button class="copybtn" onclick="copyText('generate', this)">Copy</button></h3>  
  <div class="meta" id="generate_meta"></div><pre id="generate"></pre>  
  
  <h3 class="agent-head">Groq<span class="spin" id="verify_spin"></span>  
    <button class="copybtn" onclick="copyText('verify', this)">Copy</button></h3>  
  <div class="meta" id="verify_meta"></div><pre id="verify"></pre>  
  
  <h3 class="agent-head">Gemini<span class="spin" id="final_spin"></span>  
    <button class="copybtn" onclick="copyText('final_out', this)">Copy</button></h3>  
  <div class="meta" id="final_meta"></div><pre id="final_out"></pre>  
  
  <div id="summary_box">  
    <h3 class="agent-head">Judge Pool — best output<span class="spin" id="summary_spin"></span>  
      <button class="copybtn" onclick="copyText('summary', this)">Copy</button></h3>  
    <div class="meta" id="summary_meta"></div>  
    <pre id="summary"></pre>  
  </div>  
</div>  
<script>  
let jobId=null, timer=null, lastUpdated=0, chosen=[];  
// Which stages are currently "working" (drives the animated spinner).  
let spinning={generate:false, verify:false, final:false, summary:false};  
let spinFrame=0;  
const SPIN_FRAMES=['----','-·--','--·-','---·','·---','--·--'];  
const drop=document.getElementById('drop'), fileInput=document.getElementById('file');  
drop.onclick=()=>fileInput.click();  
['dragover','dragenter'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('hover');}));  
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('hover');}));  
drop.addEventListener('drop',ev=>{addFiles(ev.dataTransfer.files);});  
fileInput.addEventListener('change',()=>{addFiles(fileInput.files); fileInput.value='';});  
function tierName(v){ v=+v; return v<=2?' (light)':(v===3?' (normal)':' (heavy)'); }  
function addFiles(fl){ for(const f of fl) chosen.push(f); renderFiles(); }  
function renderFiles(){  
  const box=document.getElementById('filelist'); box.innerHTML='';  
  chosen.forEach((f,i)=>{  
    const s=document.createElement('span'); s.className='fitem';  
    s.textContent=f.name;  
    const x=document.createElement('span'); x.className='x'; x.textContent='×';  
    x.onclick=()=>{ chosen.splice(i,1); renderFiles(); };  
    s.appendChild(x); box.appendChild(s);  
  });  
}  
// Copy the given <pre>'s text to the clipboard, with brief button feedback.  
function copyText(id, btn){  
  const el=document.getElementById(id);  
  const txt=el ? el.textContent : '';  
  if(!txt){ const o=btn.textContent; btn.textContent='Nothing'; setTimeout(()=>btn.textContent=o,1000); return; }  
  const done=()=>{ const o=btn.dataset.label||'Copy'; btn.textContent='Copied'; setTimeout(()=>btn.textContent=o,1200); };  
  const fail=()=>{ btn.textContent='Failed'; setTimeout(()=>btn.textContent='Copy',1200); };  
  if(navigator.clipboard && navigator.clipboard.writeText){  
    navigator.clipboard.writeText(txt).then(done).catch(fail);  
  } else {  
    // Fallback for non-HTTPS / older browsers.  
    const ta=document.createElement('textarea'); ta.value=txt;  
    ta.style.position='fixed'; ta.style.opacity='0'; document.body.appendChild(ta);  
    ta.select(); try{ document.execCommand('copy'); done(); }catch(e){ fail(); }  
    document.body.removeChild(ta);  
  }  
}  
// Animate a "working ----" indicator next to any stage marked working.  
function animateSpinners(){  
  spinFrame=(spinFrame+1)%SPIN_FRAMES.length;  
  const frame=SPIN_FRAMES[spinFrame];  
  for(const key of ['generate','verify','final','summary']){  
    const el=document.getElementById(key+'_spin');  
    if(!el) continue;  
    el.textContent = spinning[key] ? ('working '+frame) : '';  
  }  
}  
setInterval(animateSpinners, 300);  
function clearSpinners(){  
  spinning={generate:false, verify:false, final:false, summary:false};  
  for(const key of ['generate','verify','final','summary']){  
    const el=document.getElementById(key+'_spin'); if(el) el.textContent='';  
  }  
}  
function clearChat(){  
  document.getElementById('prompt').value='';  
  chosen=[]; renderFiles();  
  document.getElementById('state').textContent='';  
  for(const id of ['generate','verify','final_out','summary']) document.getElementById(id).textContent='';  
  for(const id of ['generate_meta','verify_meta','final_meta','summary_meta']) document.getElementById(id).textContent='';  
  clearSpinners();  
  jobId=null; if(timer) clearInterval(timer);  
}  
async function run(){  
  const body=new FormData();  
  body.append('prompt', document.getElementById('prompt').value);  
  body.append('complexity', document.getElementById('complexity').value);  
  body.append('openrouter', document.getElementById('openrouter').checked?'on':'off');  
  body.append('groq', document.getElementById('groq').checked?'on':'off');  
  body.append('gemini', document.getElementById('gemini').checked?'on':'off');  
  body.append('inkling', document.getElementById('inkling').checked?'on':'off');  
  for(const f of chosen) body.append('files', f);  
  const r=await fetch('/run',{method:'POST',body});  
  if(!r.ok){ document.getElementById('state').textContent='Error: '+(await r.text()); return; }  
  jobId=(await r.json()).job_id; lastUpdated=0;  
  if(timer) clearInterval(timer);  
  timer=setInterval(poll,2000); poll(); loadJobs();  
}  
function meta(model, conf){  
  let s = model ? ('model: '+model) : '';  
  if(conf!==undefined && conf!==null && conf!=='') s += (s?'  •  ':'') + 'confidence: '+conf+'%';  
  return s;  
}  
async function poll(){  
  if(!jobId) return;  
  const r=await fetch('/status/'+jobId); if(!r.ok) return;  
  const j=await r.json();  
  if(j.updated_at!==lastUpdated){  
    lastUpdated=j.updated_at;  
    document.getElementById('state').textContent=j.state+(j.error?(' - '+j.error):'');  
    document.getElementById('generate').textContent=j.steps.generate||'';  
    document.getElementById('verify').textContent=j.steps.verify||'';  
    document.getElementById('final_out').textContent=j.steps.final||'';  
    document.getElementById('generate_meta').textContent=meta(j.steps.generate_model, j.steps.generate_conf);  
    document.getElementById('verify_meta').textContent=meta(j.steps.verify_model, j.steps.verify_conf);  
    document.getElementById('final_meta').textContent=meta(j.steps.final_model, j.steps.final_conf);  
    document.getElementById('summary').textContent=j.steps.summary||'';  
    document.getElementById('summary_meta').textContent=meta('', j.steps.summary_conf);  
    // Drive the "working" spinners from the live per-stage status flags.  
    spinning.generate = (j.steps.generate_status==='working');  
    spinning.verify   = (j.steps.verify_status==='working');  
    spinning.final    = (j.steps.final_status==='working');  
    spinning.summary  = (j.steps.summary_status==='working');  
  }  
  if(['done','failed','cancelled'].includes(j.state)){  
    clearInterval(timer); clearSpinners(); loadJobs();  
  }  
}  
async function stop(){ if(jobId) await fetch('/stop/'+jobId,{method:'POST'}); }  
async function delJob(id, ev){  
  ev.stopPropagation();  
  await fetch('/jobs/'+id,{method:'DELETE'});  
  if(jobId===id){ jobId=null; if(timer) clearInterval(timer); clearSpinners(); }  
  loadJobs();  
}  
async function loadJobs(){  
  const r=await fetch('/jobs'); if(!r.ok) return;  
  const list=await r.json(); const box=document.getElementById('jobs'); box.innerHTML='';  
  for(const j of list){  
    const d=document.createElement('div'); d.className='job';  
    const t=document.createElement('span'); t.className='jtitle';  
    t.textContent='['+j.state+'] '+j.title;  
    t.onclick=()=>{ jobId=j.id; lastUpdated=0; if(timer)clearInterval(timer);  
                    timer=setInterval(poll,2000); poll(); };  
    const x=document.createElement('button'); x.className='del'; x.textContent='×';  
    x.onclick=(ev)=>delJob(j.id, ev);  
    d.appendChild(t); d.appendChild(x);  
    box.appendChild(d);  
  }  
}  
loadJobs();  
fetch('/version').then(r=>r.json())  
  .then(v=>{document.getElementById('version').textContent='version '+v.version;});  
</script>  
</body></html>"""
