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
    <label><input type="checkbox" id="openrouter" checked> OpenRouter (generate code)</label>  
    <label><input type="checkbox" id="groq" checked> Groq (verify vs input)</label>  
    <label><input type="checkbox" id="gemini" checked> Gemini (final cleaned code)</label>  
  </div>  
  <button onclick="run()">Run</button>  
  <button class="stop" onclick="stop()">Stop</button>  
  <button class="clear" onclick="clearChat()">Clear chat</button>  
  <p id="state"></p>  
  <h3>1. OpenRouter generated code</h3>  
  <div class="meta" id="generate_meta"></div><pre id="generate"></pre>  
  <h3>2. Groq verification</h3>  
  <div class="meta" id="verify_meta"></div><pre id="verify"></pre>  
  <h3>3. Gemini final cleaned / optimised code</h3>  
  <div class="meta" id="final_meta"></div><pre id="final_out"></pre>  
</div>  
<script>  
let jobId=null, timer=null, lastUpdated=0, chosen=[];  
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
function clearChat(){  
  document.getElementById('prompt').value='';  
  chosen=[]; renderFiles();  
  document.getElementById('state').textContent='';  
  for(const id of ['generate','verify','final_out']) document.getElementById(id).textContent='';  
  for(const id of ['generate_meta','verify_meta','final_meta']) document.getElementById(id).textContent='';  
  jobId=null; if(timer) clearInterval(timer);  
}  
async function run(){  
  const body=new FormData();  
  body.append('prompt', document.getElementById('prompt').value);  
  body.append('complexity', document.getElementById('complexity').value);  
  body.append('openrouter', document.getElementById('openrouter').checked?'on':'off');  
  body.append('groq', document.getElementById('groq').checked?'on':'off');  
  body.append('gemini', document.getElementById('gemini').checked?'on':'off');  
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
    document.getElementById('generate_meta').textContent=meta(j.steps.generate_model, j.steps.generate_confidence);  
    document.getElementById('verify_meta').textContent=meta(j.steps.verify_model, j.steps.verify_confidence);  
    document.getElementById('final_meta').textContent=meta(j.steps.final_model, j.steps.final_confidence);  
  }  
  if(['done','failed','cancelled'].includes(j.state)){ clearInterval(timer); loadJobs(); }  
}  
async function stop(){ if(jobId) await fetch('/stop/'+jobId,{method:'POST'}); }  
async function delJob(id, ev){  
  ev.stopPropagation();  
  await fetch('/jobs/'+id,{method:'DELETE'});  
  if(jobId===id){ jobId=null; if(timer) clearInterval(timer); }  
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
