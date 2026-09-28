# DizerCore-AI  
# ----------------------------------------------------------------------------  
# web.py — dashboard HTML/JS (served by routes.py at "/").  
# Exposes DASHBOARD_HTML only. Logo is served from /static/dizercore.png  
# (mount StaticFiles in dizercoreai.py). Login/Register HTML live in auth.py.  
#  
# Live updates: /status/stream/{job_id} SSE delivers token-smooth deltas for  
# each step key (generate/verify/final + *_thinking). poll() remains as the  
# snapshot hydrator and fallback for finished jobs.  
  
DASHBOARD_HTML = """<!DOCTYPE html><html><head><title>DizerCoreAI</title>  
<link rel="icon" href="/static/dizercore.png">  
<style>  
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;  
         background:#0f172a; color:#f8fafc; margin:0; display:flex; height:100vh; }  
  #left { width:280px; border-right:1px solid #334155; padding:14px; overflow-y:auto; }  
  #right { flex:1; padding:18px; overflow-y:auto; }  
  h2,h3 { color:#38bdf8; }  
  .brand { display:flex; align-items:center; gap:10px; margin-bottom:10px; }  
  .brand img { width:34px; height:34px; border-radius:8px; }  
  .job { padding:7px 9px; border-radius:6px; cursor:pointer; margin-bottom:4px;  
         display:flex; justify-content:space-between; align-items:center; gap:6px; }  
  .job:hover { background:#1e293b; }  
  .job .del { color:#f87171; background:none; border:none; cursor:pointer;  
              font-size:14px; padding:0 2px; }  
  .job .lbl { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }  
  textarea { width:100%; background:#1e293b; color:#f8fafc; border:1px solid #334155;  
             border-radius:8px; padding:10px; font-size:14px; box-sizing:border-box; }  
  input[type=text] { background:#1e293b; color:#f8fafc; border:1px solid #334155;  
                     border-radius:8px; padding:8px; box-sizing:border-box; width:100%; }  
  input[type=range] { width:200px; }  
  button { background:#0ea5e9; color:#0f172a; border:none; border-radius:8px;  
           padding:8px 18px; font-weight:600; cursor:pointer; }  
  button.ghost { background:#334155; color:#f8fafc; }  
  .head { display:flex; align-items:center; justify-content:space-between;  
          margin:16px 0 4px; }  
  .head h3 { margin:0; }  
  button.copy { padding:3px 10px; font-size:12px; background:#334155; color:#f8fafc; }  
  .panel { background:#1e293b; border:1px solid #334155; border-radius:10px;  
           padding:10px; }  
  .panel pre, .panel div.out { white-space:pre-wrap; word-break:break-word;  
           font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px;  
           margin:0; max-height:340px; overflow-y:auto; }  
  .thinking { white-space:pre-wrap; word-break:break-word; color:#94a3b8;  
              font-style:italic; font-size:12px; max-height:160px;  
              overflow-y:auto; border-bottom:1px dashed #334155;  
              margin-bottom:6px; padding-bottom:4px; display:none; }  
  .meta { color:#64748b; font-size:11px; white-space:pre-wrap; margin-top:6px; }  
  .status { font-size:11px; color:#fbbf24; margin-left:8px; }  
  #drop { border:2px dashed #334155; border-radius:10px; padding:12px;  
          text-align:center; color:#94a3b8; font-size:13px; margin-top:8px; }  
  #drop.over { border-color:#38bdf8; color:#38bdf8; }  
  #filelist { font-size:12px; color:#94a3b8; margin-top:4px; }  
  .hint { color:#64748b; font-size:11px; }  
</style></head><body>  
<div id="left">  
  <div class="brand"><img src="/static/dizercore.png"><h2>DizerCoreAI</h2></div>  
  <form method="post" action="/logout"><button class="ghost" type="submit">Logout</button></form>  
  <h3>Jobs</h3><div id="jobs"></div>  
</div>  
<div id="right">  
  <input type="text" id="title" placeholder="Job title (optional)" style="display:none">  
  <textarea id="prompt" rows="4" placeholder="Describe what to build..."></textarea>  
  <div style="margin:8px 0;">  
    Complexity: <input type="range" id="complexity" min="1" max="5" value="3"  
      oninput="document.getElementById('cval').textContent=this.value">  
    <b id="cval">3</b>  
    &nbsp; <span class="hint">1-2 light · 3 normal · 4-5 heavy</span>  
  </div>  
  <input type="file" id="files" multiple  
    accept="image/*,.pdf,.docx,.txt,.md,.sql,.cpp,.c,.h,.hpp,.py,.js,.ts,.json,.yaml,.yml,.csv,.html,.css,.xml,.sh"  
    style="display:none">  
  <div id="drop" onclick="document.getElementById('files').click()">  
    Drop files here or click to browse<br>  
    <span class="hint">images/PDF → vision-capable agents · text/code/docx → folded into prompt</span>  
  </div>  
  <div id="filelist"></div>  
  <div style="margin:10px 0;">  
    <button onclick="run()">Run</button>  
    <button class="ghost" onclick="stopJob()">Stop</button>  
  </div>  
  
  <div class="head"><h3>OpenRouter <span id="generate_status" class="status"></span></h3>  
    <button class="copy" onclick="copyBox('generate',this)">Copy</button></div>  
  <div class="panel">  
    <div id="generate_thinking" class="thinking"></div>  
    <pre id="generate"></pre><div id="generate_meta" class="meta"></div></div>  
  
  <div class="head"><h3>Groq <span id="verify_status" class="status"></span></h3>  
    <button class="copy" onclick="copyBox('verify',this)">Copy</button></div>  
  <div class="panel">  
    <div id="verify_thinking" class="thinking"></div>  
    <pre id="verify"></pre><div id="verify_meta" class="meta"></div></div>  
  
  <div class="head"><h3>Gemini <span id="final_status" class="status"></span></h3>  
    <button class="copy" onclick="copyBox('final',this)">Copy</button></div>  
  <div class="panel">  
    <div id="final_thinking" class="thinking"></div>  
    <pre id="final"></pre><div id="final_meta" class="meta"></div></div>  
  
  <div class="head"><h3>Result <span id="summary_status" class="status"></span></h3>  
    <button class="copy" onclick="copyBox('summary',this)">Copy</button></div>  
  <div class="panel"><div id="summary" class="out"></div>  
    <div id="summary_meta" class="meta"></div></div>  
</div>  
<script>  
const KEYS=['generate','verify','final','summary'];  
let jobId=null, lastUpdated=0, es=null, spinTimer=null;  
  
function meta(model,conf,comments){  
  let s='';  
  if(model) s+='model: '+model;  
  if(conf!==undefined && conf!=='' && conf!==null) s+=(s?'   ':'')+'confidence: '+conf+'%';  
  if(comments) s+=(s?'\\n':'')+'judge: '+comments;  
  return s;  
}  
function copyBox(k,btn){  
  const el=document.getElementById(k);  
  navigator.clipboard.writeText(el.textContent).then(()=>{  
    btn.textContent='Copied'; setTimeout(()=>btn.textContent='Copy',1200);});  
}  
function clearSpinners(){ if(spinTimer){clearInterval(spinTimer); spinTimer=null;}  
  for(const k of KEYS){const s=document.getElementById(k+'_status'); if(s) s.textContent='';} }  
function startSpinners(){  
  clearSpinners(); let n=0;  
  spinTimer=setInterval(()=>{ n=(n+1)%4;  
    for(const k of KEYS){ const s=document.getElementById(k+'_status');  
      if(s && s.dataset.working==='1') s.textContent=' working'+'.'.repeat(n); }  
  },400);  
}  
function setStatus(k,st){  
  const el=document.getElementById(k+'_status'); if(!el) return;  
  if(st==='working'){ el.dataset.working='1'; el.textContent=' working';  
    if(!spinTimer) startSpinners(); }  
  else { el.dataset.working=''; el.textContent = st==='done'?' done':''; }  
}  
function closeStream(){ if(es){ es.close(); es=null; } }  
function openStream(id){  
  closeStream();  
  es=new EventSource('/status/stream/'+id);  
  es.onmessage=ev=>{  
    const m=JSON.parse(ev.data);  
    if(m.key==='_done'){ closeStream(); poll(); return; }  
    const el=document.getElementById(m.key);  
    if(el){  
      el.textContent+=m.delta;  
      if(el.classList.contains('thinking')) el.style.display='block';  
      el.scrollTop=el.scrollHeight;  
    }  
  };  
  es.onerror=()=>{ closeStream(); };   // poll() covers the gap  
}  
async function poll(){  
  if(!jobId) return;  
  const r=await fetch('/status/'+jobId); if(!r.ok) return;  
  const d=await r.json();  
  const steps=d.steps||{};  
  for(const k of KEYS){  
    const el=document.getElementById(k);  
    // SSE owns live appends while running; poll only fills untouched boxes  
    if(!(d.state==='running' && es && el.textContent.length>0))  
      el.textContent=steps[k]||'';  
    const th=document.getElementById(k+'_thinking');  
    if(th){ th.textContent=steps[k+'_thinking']||'';  
      th.style.display=th.textContent?'block':'none'; }  
    document.getElementById(k+'_meta').textContent=  
      meta(steps[k+'_model'],steps[k+'_conf'],steps[k+'_judge_comments']);  
    setStatus(k,steps[k+'_status']||'');  
  }  
  if(d.state==='running' && !es) openStream(jobId);  
  if(d.state!=='running' && d.state!=='queued'){ closeStream(); }  
  lastUpdated=d.updated_at;  
  loadJobs();  
}  
let pollTimer=null;  
function armPoll(){  
  if(pollTimer) clearInterval(pollTimer);  
  pollTimer=setInterval(()=>{ if(jobId) poll(); },1500);  
}  
async function run(){  
  const fd=new FormData();  
  fd.append('prompt',document.getElementById('prompt').value);  
  fd.append('complexity',document.getElementById('complexity').value);  
  for(const f of document.getElementById('files').files) fd.append('files',f);  
  const r=await fetch('/run',{method:'POST',body:fd});  
  if(!r.ok){ alert(await r.text()); return; }  
  const d=await r.json();  
  jobId=d.job_id; clearSpinners();  
  for(const k of KEYS){ document.getElementById(k).textContent='';  
    document.getElementById(k+'_meta').textContent='';  
    const th=document.getElementById(k+'_thinking');  
    th.textContent=''; th.style.display='none';  
    setStatus(k,'working'); }  
  openStream(jobId); armPoll(); poll();  
}  
async function stopJob(){  
  if(!jobId) return;  
  await fetch('/stop/'+jobId,{method:'POST'});  
  poll();  
}  
// ---- files ----  
const drop=document.getElementById('drop'), finput=document.getElementById('files');  
function showFiles(){ document.getElementById('filelist').textContent=  
  [...finput.files].map(f=>f.name).join(', '); }  
finput.onchange=showFiles;  
drop.ondragover=e=>{e.preventDefault(); drop.classList.add('over');};  
drop.ondragleave=()=>drop.classList.remove('over');  
drop.ondrop=e=>{e.preventDefault(); drop.classList.remove('over');  
  finput.files=e.dataTransfer.files; showFiles();};  
// ---- jobs sidebar ----  
async function loadJobs(){  
  const r=await fetch('/jobs'); if(!r.ok) return;  
  const list=await r.json();  
  const div=document.getElementById('jobs'); div.innerHTML='';  
  for(const j of list){  
    const row=document.createElement('div'); row.className='job';  
    const label=document.createElement('span'); label.className='lbl';  
    label.textContent=(j.state==='running'?'● ':'')+j.title;  
    label.onclick=()=>selectJob(j.id);  
    const del=document.createElement('button'); del.className='del';  
    del.textContent='\\u00d7';  
    del.onclick=async ev=>{  
      ev.stopPropagation();  
      await fetch('/jobs/'+j.id,{method:'DELETE'});  
      if(jobId===j.id){ jobId=null; closeStream(); clearSpinners();  
        for(const k of KEYS){ document.getElementById(k).textContent='';  
          document.getElementById(k+'_meta').textContent='';  
          const th=document.getElementById(k+'_thinking');  
          th.textContent=''; th.style.display='none'; } }  
      loadJobs();  
    };  
    row.appendChild(label); row.appendChild(del); div.appendChild(row);  
  }  
}  
async function selectJob(id){  
  jobId=id; lastUpdated=0; closeStream(); clearSpinners();  
  poll();  
}  
// ---- version ----  
fetch('/version').then(r=>r.json()).then(d=>{  
  document.title='DizerCoreAI v'+d.version;  
}).catch(()=>{});  
loadJobs(); armPoll();  
</script>  
</body></html>"""
