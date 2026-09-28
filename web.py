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
  #summary { font-size:18px; font-weight:600; color:#38bdf8; }    
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
  <input id="files" type="file" multiple>    
  <p>Complexity: <span id="cxv">3</span>    
     <input id="cx" type="range" min="1" max="5" value="3"    
            oninput="document.getElementById('cxv').textContent=this.value"></p>    
  <button onclick="run()">Run</button>    
  <button class="stop" onclick="stop()">Stop</button>    
  <hr>    
  <div class="panel"><h3>OpenRouter <span id="generate_status"></span></h3>    
    <div id="generate_meta" class="meta"></div><pre id="generate"></pre></div>    
  <div class="panel"><h3>Groq <span id="verify_status"></span></h3>    
    <div id="verify_meta" class="meta"></div><pre id="verify"></pre></div>    
  <div class="panel"><h3>Gemini <span id="final_status"></span></h3>    
    <div id="final_meta" class="meta"></div><pre id="final"></pre></div>    
  <div class="panel"><h3>Result <span id="summary_status"></span></h3>    
    <div id="summary_meta" class="meta"></div><div id="summary"></div></div>    
</div>    
<script>    
let jobId=null, timer=null, lastUpdated=0;    
    
// Spinner animation for in-flight stages    
const FRAMES=['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏'];    
let fi=0;    
setInterval(()=>{    
  fi=(fi+1)%FRAMES.length;    
  for(const k of ['generate','verify','final','summary']){    
    const el=document.getElementById(k+'_status');    
    if(el && el.dataset.working==='1') el.textContent=FRAMES[fi]+' working…';    
  }    
},80);    
    
function setStatus(key,val){    
  const el=document.getElementById(key+'_status');    
  if(val==='working'){ el.dataset.working='1'; }    
  else { el.dataset.working='0'; el.textContent = val==='done' ? '✓' : ''; }    
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
  if(conf!==undefined && conf!=='') s+=(s?'   ':'')+'confidence: '+conf+'%';    
  if(comments) s+=(s?'\n':'')+'judge: '+comments;    
  return s;    
}    
async function run(){    
  const fd=new FormData();    
  fd.append('title',document.getElementById('title').value);    
  fd.append('prompt',document.getElementById('prompt').value);    
  fd.append('complexity',document.getElementById('cx').value);    
  for(const f of document.getElementById('files').files) fd.append('files',f);    
  const r=await fetch('/run',{method:'POST',body:fd});    
  if(r.ok){ const j=await r.json(); jobId=j.id; lastUpdated=0;    
            if(timer)clearInterval(timer); timer=setInterval(poll,2000); poll();    
            loadJobs(); }    
}    
async function poll(){    
  if(!jobId) return;    
  const r=await fetch('/status/'+jobId);    
  if(!r.ok) return;    
  const j=await r.json();    
  if(j.updated_at===lastUpdated) return;    
  lastUpdated=j.updated_at;    
  document.getElementById('generate').textContent=j.steps.generate||'';    
  document.getElementById('generate_meta').textContent=meta(j.steps.generate_model, j.steps.generate_conf, j.steps.generate_judge_comments);    
  document.getElementById('verify').textContent=j.steps.verify||'';    
  document.getElementById('verify_meta').textContent=meta(j.steps.verify_model, j.steps.verify_conf, j.steps.verify_judge_comments);    
  document.getElementById('final').textContent=j.steps.final||'';    
  document.getElementById('final_meta').textContent=meta(j.steps.final_model, j.steps.final_conf, j.steps.final_judge_comments);    
  document.getElementById('summary').textContent=j.steps.summary||'';    
  document.getElementById('summary_meta').textContent=meta('', j.steps.summary_conf);    
  setStatus('generate', j.steps.generate_status);    
  setStatus('verify', j.steps.verify_status);    
  setStatus('final', j.steps.final_status);    
  setStatus('summary', j.steps.summary_status);    
  if(j.state==='DONE' || j.state==='FAILED' || j.state==='CANCELLED'){    
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
