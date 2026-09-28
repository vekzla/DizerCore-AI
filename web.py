# DizerCore-AI  
# ----------------------------------------------------------------------------  
# web.py — dashboard HTML/JS (served by routes.py at "/").  
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
           border-radius:6px; cursor:pointer; font-size:14px; }  
  button.stop { background:#b91c1c; }  
  button.copy { background:#334155; padding:2px 10px; font-size:11px;  
                float:right; }  
  button.copy:hover { background:#475569; }  
  input[type=range] { width:100%; }  
  .job { padding:8px; border-bottom:1px solid #334155; cursor:pointer;  
         display:flex; justify-content:space-between; align-items:center; }  
  .job:hover { background:#1e293b; }  
  .job .del { background:none; border:none; color:#b91c1c; padding:0 4px; }  
  .panel { border:1px solid #334155; border-radius:8px; padding:12px;  
           margin-bottom:12px; }  
  .panel pre { white-space:pre-wrap; word-wrap:break-word; max-height:400px;  
               overflow-y:auto; }  
  .meta { font-size:12px; color:#94a3b8; margin:2px 0 8px; white-space:pre-wrap; }  
  #summary { font-size:18px; font-weight:600; color:#38bdf8;  
             white-space:pre-wrap; }  
  #dropzone { border:2px dashed #475569; border-radius:8px; padding:14px;  
              text-align:center; color:#94a3b8; font-size:13px;  
              margin:8px 0 4px; }  
  #dropzone.over { border-color:#38bdf8; background:#1e293b; }  
  #runmsg { color:#f87171; font-size:13px; min-height:16px; margin:6px 0; }  
  .hint { font-size:11px; color:#94a3b8; margin-bottom:8px; }  
  .status { color:#38bdf8; font-size:12px; font-weight:normal; }  
</style></head>  
<body>  
<div id="left">  
  <div class="brand"><img src="/static/dizercore.png" alt="logo"><h2>DizerCoreAI</h2></div>  
  <div id="version" style="font-size:12px;color:#94a3b8;margin-bottom:10px;"></div>  
  <form method="post" action="/logout"><button type="submit">Log out</button></form>  
  <h3>Jobs</h3><div id="jobs"></div>  
</div>  
<div id="right">  
  <h3>New request</h3>  
  <input id="title" placeholder="Job title" style="width:100%;background:#1e293b;color:#f8fafc;border:1px solid #334155;padding:8px;border-radius:6px;margin-bottom:8px;">  
  <textarea id="prompt" placeholder="Describe what to build..."></textarea>  
  <div id="dropzone">Drop text/code files here, or  
    <input id="files" type="file" multiple  
           accept=".txt,.md,.py,.js,.ts,.jsx,.tsx,.json,.yaml,.yml,.toml,.ini,.cfg,.sh,.sql,.html,.css,.c,.h,.cpp,.hpp,.java,.go,.rs,.rb,.php">  
  </div>  
  <div class="hint">Accepted: text/code files  
    (.py, .js, .md, .json, .yaml, .sh, .sql, .html, .css, .c, .cpp, .java, .go, .rs, etc.).  
    Non-text files are attached as binary notes only.</div>  
  <p>Complexity: <span id="cxv">3</span>  
     <input id="cx" type="range" min="1" max="5" value="3"  
            oninput="document.getElementById('cxv').textContent=this.value"></p>  
  <button onclick="run()">Run</button>  
  <button class="stop" onclick="stop()">Stop</button>  
  <div id="runmsg"></div>  
  <hr>  
  <div class="panel"><h3>OpenRouter <span id="generate_status" class="status"></span>  
      <button class="copy" onclick="copyBox('generate',this)">Copy</button></h3>  
    <div id="generate_meta" class="meta"></div><pre id="generate"></pre></div>  
  <div class="panel"><h3>Groq <span id="verify_status" class="status"></span>  
      <button class="copy" onclick="copyBox('verify',this)">Copy</button></h3>  
    <div id="verify_meta" class="meta"></div><pre id="verify"></pre></div>  
  <div class="panel"><h3>Gemini <span id="final_status" class="status"></span>  
      <button class="copy" onclick="copyBox('final',this)">Copy</button></h3>  
    <div id="final_meta" class="meta"></div><pre id="final"></pre></div>  
  <div class="panel"><h3>Result <span id="summary_status" class="status"></span>  
      <button class="copy" onclick="copyBox('summary',this)">Copy</button></h3>  
    <div id="summary_meta" class="meta"></div><div id="summary"></div></div>  
</div>  
<script>  
let jobId=null, lastUpdated=0, userDragging=false;  
  
// ---- animated "working..." indicator: dots grow 1..3 then shrink ----  
let dotPhase=0;  
setInterval(()=>{  
  dotPhase=(dotPhase+1)%6;  
  const n = dotPhase<3 ? dotPhase+1 : 5-dotPhase;   // 1,2,3,2,1,2 ...  
  const dots = '.'.repeat(n);  
  for(const k of ['generate','verify','final','summary']){  
    const el=document.getElementById(k+'_status');  
    if(el && el.dataset.working==='1') el.textContent='working'+dots;  
  }  
},300);  
  
function setStatus(key,val){  
  const el=document.getElementById(key+'_status');  
  if(val==='working'){ el.dataset.working='1'; el.textContent='working.'; }  
  else { el.dataset.working='0'; el.textContent = val==='done' ? '\\u2713' : (val||''); }  
}  
function clearSpinners(){  
  for(const k of ['generate','verify','final','summary']){  
    const el=document.getElementById(k+'_status');  
    el.dataset.working='0'; el.textContent='';  
  }  
}  
function meta(model,conf,comments){  
  let s='';  
  if(model) s+='model: '+model;  
  if(conf!==undefined && conf!=='' && conf!==null) s+=(s?'   ':'')+'confidence: '+conf+'%';  
  if(comments) s+=(s?'\\n':'')+'judge: '+comments;  
  return s;  
}  
  
// ---- copy button (with http:// fallback for non-HTTPS pages) ----  
async function copyBox(key,btn){  
  const el=document.getElementById(key);  
  const text=el.innerText||el.textContent||'';  
  try{ await navigator.clipboard.writeText(text); }  
  catch(e){  
    const ta=document.createElement('textarea');  
    ta.value=text; document.body.appendChild(ta);  
    ta.select(); document.execCommand('copy'); document.body.removeChild(ta);  
  }  
  btn.textContent='Copied!';  
  setTimeout(()=>{ btn.textContent='Copy'; },1500);  
}  
  
// ---- slider: poll() never touches #cx; only block updates while dragging ----  
const slider=document.getElementById('cx');  
slider.addEventListener('pointerdown',()=>userDragging=true);  
window.addEventListener('pointerup',()=>userDragging=false);  
  
// ---- drag and drop files ----  
const dz=document.getElementById('dropzone');  
dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('over');});  
dz.addEventListener('dragleave',()=>dz.classList.remove('over'));  
dz.addEventListener('drop',e=>{  
  e.preventDefault(); dz.classList.remove('over');  
  const inp=document.getElementById('files');  
  const dt=new DataTransfer();  
  for(const f of inp.files) dt.items.add(f);  
  for(const f of e.dataTransfer.files) dt.items.add(f);  
  inp.files=dt.files;  
});  
  
// ---- run / stop ----  
async function run(){  
  const msg=document.getElementById('runmsg'); msg.textContent='';  
  const fd=new FormData();  
  fd.append('prompt',document.getElementById('prompt').value);  
  fd.append('complexity',document.getElementById('cx').value);  
  fd.append('openrouter','on');  
  fd.append('groq','on');  
  fd.append('gemini','on');  
  for(const f of document.getElementById('files').files) fd.append('files',f);  
  let res;  
  try{ res=await fetch('/run',{method:'POST',body:fd}); }  
  catch(e){ msg.textContent='Run failed: network error'; return; }  
  if(!res.ok){  
    let d; try{ d=(await res.json()).detail; }catch(e){ d=res.statusText; }  
    msg.textContent='Run failed: '+(d||res.status);  
    return;  
  }  
  const data=await res.json();  
  jobId=data.job_id; lastUpdated=0; clearSpinners();  
  for(const k of ['generate','verify','final','summary']){  
    document.getElementById(k).textContent='';  
    document.getElementById(k+'_meta').textContent='';  
    setStatus(k,'working');  
  }  
  loadJobs(); poll();  
}  
  
async function stop(){  
  const msg=document.getElementById('runmsg');  
  if(!jobId){ msg.textContent='No job selected.'; return; }  
  let res;  
  try{ res=await fetch('/stop/'+jobId,{method:'POST'}); }  
  catch(e){ msg.textContent='Stop failed: network error'; return; }  
  if(!res.ok) msg.textContent='Stop failed: '+res.status;  
  else { clearSpinners(); poll(); }  
}  
  
// ---- polling ----  
const KEYS=['generate','verify','final','summary'];  
async function poll(){  
  if(!jobId) return;  
  if(userDragging){ setTimeout(poll,400); return; }  
  let res;  
  try{ res=await fetch('/status/'+jobId); }catch(e){ setTimeout(poll,2000); return; }  
  if(!res.ok){ if(res.status===404){ jobId=null; clearSpinners(); } setTimeout(poll,2000); return; }  
  const j=await res.json();  
  if(j.updated_at===lastUpdated && (j.state==='running'||j.state==='queued')){  
    setTimeout(poll,1000); return;  
  }  
  lastUpdated=j.updated_at||0;  
  const steps=j.steps||{};  
  for(const k of KEYS){  
    const txt=steps[k]||'';  
    document.getElementById(k).textContent=txt;  
    document.getElementById(k+'_meta').textContent=  
      meta(steps[k+'_model'],steps[k+'_confidence'],steps[k+'_judge_comments']);  
    const st=steps[k+'_status'];  
    if(st==='working') setStatus(k,'working');  
    else if(txt||st==='done') setStatus(k,'done');  
  }  
  if(j.state==='done'||j.state==='failed'||j.state==='cancelled'){  
    clearSpinners();  
    if(j.state==='failed') document.getElementById('runmsg').textContent=  
      'Job failed: '+(j.error||'unknown error');  
    loadJobs();  
    return;  
  }  
  setTimeout(poll,1000);  
}  
  
// ---- jobs sidebar ----  
async function loadJobs(){  
  let res;  
  try{ res=await fetch('/jobs'); }catch(e){ return; }  
  if(!res.ok) return;  
  const jobs=await res.json();  
  const div=document.getElementById('jobs'); div.innerHTML='';  
  for(const j of jobs){  
    const row=document.createElement('div'); row.className='job';  
    const label=document.createElement('span');  
    label.textContent=(j.title||j.id)+' — '+j.state;  
    label.style.overflow='hidden'; label.style.textOverflow='ellipsis';  
    label.onclick=()=>selectJob(j.id);  
    const del=document.createElement('button'); del.className='del';  
    del.textContent='\\u00d7';  
    del.onclick=async ev=>{  
      ev.stopPropagation();  
      await fetch('/jobs/'+j.id,{method:'DELETE'});  
      if(jobId===j.id){ jobId=null; clearSpinners();  
        for(const k of KEYS){ document.getElementById(k).textContent='';  
          document.getElementById(k+'_meta').textContent=''; } }  
      loadJobs();  
    };  
    row.appendChild(label); row.appendChild(del); div.appendChild(row);  
  }  
}  
async function selectJob(id){  
  jobId=id; lastUpdated=0; clearSpinners();  
  poll();  
}  
  
// ---- version ----  
fetch('/version').then(r=>r.json()).then(d=>{  
  document.getElementById('version').textContent='v'+d.version;  
}).catch(()=>{});  
  
loadJobs();  
</script>  
</body></html>"""
