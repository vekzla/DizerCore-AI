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
         background:#0f172a; color:#f8fafc; margin:0; padding:0; }  
  .container { display:flex; min-height:100vh; }  
  .sidebar { width:280px; background:#020617; padding:1rem;  
             border-right:1px solid #334155; }  
  .main { flex:1; padding:1rem 1.5rem; }  
  h1 { margin-top:0; }  
  #logo { width:160px; height:auto; display:block; margin:0 auto 0.5rem auto; }  
  #version { font-size:0.8rem; color:#94a3b8; text-align:center; margin-bottom:0.75rem; }  
  #version.update { color:#fbbf24; }  
  #version.ok { color:#4ade80; }  
  .jobrow { padding:.3rem .4rem; cursor:pointer; border-radius:4px;  
            display:flex; justify-content:space-between; gap:.5rem;  
            align-items:center; }  
  .jobrow:hover { background:#1e293b; }  
  .badge { font-size:.75rem; padding:.1rem .4rem; border-radius:3px; }  
  .queued { background:#334155; }  
  .running { background:#0ea5e9; }  
  .done { background:#22c55e; color:#022c22; }  
  .failed { background:#ef4444; }  
  .cancelled { background:#f59e0b; color:#422006; }  
  .del { cursor:pointer; color:#94a3b8; margin-left:.4rem; }  
  .del:hover { color:#f87171; }  
  label { display:block; margin:.6rem 0 .2rem; }  
  input[type=text], input[type=number], input[type=file], textarea, select {  
         width:100%; padding:.45rem; background:#020617; color:#f8fafc;  
         border:1px solid #334155; border-radius:4px; box-sizing:border-box; }  
  .checkrow label { display:inline-block; margin-right:1rem; }  
  .btnrow { display:flex; gap:.5rem; margin-top:.8rem; }  
  .btnrow button { flex:1; }  
  button { padding:.5rem .9rem; border:none; border-radius:4px;  
           background:#2563eb; color:#fff; cursor:pointer; }  
  button.stop { background:#dc2626; }  
  button.clear { background:#475569; }  
  button.copy { padding:.15rem .5rem; font-size:.75rem; background:#334155; }  
  button.copy:hover { background:#475569; }  
  #dropzone { margin-top:.6rem; padding:.8rem; border:2px dashed #475569;  
              border-radius:6px; text-align:center; color:#94a3b8;  
              font-size:.85rem; cursor:pointer; }  
  #dropzone.over { border-color:#38bdf8; color:#e2e8f0; background:#0c1a2e; }  
  pre { background:#020617; border:1px solid #334155; border-radius:4px;  
        padding:.6rem; white-space:pre-wrap; word-wrap:break-word; }  
  .stage { margin-top:1rem; }  
  .stage h3 { margin:0 0 .3rem; display:flex; align-items:center; gap:.6rem; }  
  .modeltag { font-weight:400; font-size:.8rem; color:#94a3b8; }  
  .thinking { color:#94a3b8; font-style:italic; border-left:3px solid #334155;  
              padding-left:.6rem; }  
  .spin { display:inline-block; width:.8em; height:.8em;  
          border:2px solid #94a3b8; border-top-color:#38bdf8;  
          border-radius:50%; animation:sp 1s linear infinite;  
          vertical-align:middle; margin-right:.35rem; }  
  @keyframes sp { to { transform:rotate(360deg); } }  
</style></head><body><div class="container">  
<div class="sidebar">  
  <img id="logo" src="/static/dizercore.png" alt="DizerCoreAI">  
  <div id="version"></div>  
  <h2>Jobs</h2>  
  <div id="jobs"></div>  
</div>  
<div class="main">  
  <h1>DizerCoreAI</h1>  
  <form id="runform">  
    <label>Title (optional)</label>  
    <input id="title" type="text" maxlength="80" placeholder="Short title">  
    <label>Prompt *</label>  
    <textarea id="prompt" rows="4" required></textarea>  
    <div id="dropzone">Drag &amp; drop files here, or use the picker below</div>  
    <input id="dzfiles" type="file" multiple style="display:none">  
    <label>Attachments (text/code/images/PDF — 5&nbsp;MB each, 50&nbsp;MB total)</label>  
    <input type="file" name="files" multiple>  
    <div id="filelist" style="font-size:.85rem; color:#94a3b8;"></div>  
    <label>Complexity (1–5)</label>  
    <input type="number" name="complexity" min="1" max="5" value="3">  
    <div class="checkrow">  
      <label><input type="checkbox" name="openrouter" checked> OpenRouter</label>  
      <label><input type="checkbox" name="groq" checked> Groq</label>  
      <label><input type="checkbox" name="gemini" checked> Gemini</label>  
    </div>  
    <div class="btnrow">  
      <button type="submit">Run</button>  
      <button type="button" class="clear" onclick="clearInput()">Clear</button>  
      <button type="button" class="stop" onclick="stopJob()">Stop</button>  
    </div>  
  </form>  
  <div id="stages"></div>  
</div>  
</div>  
<script>  
let jobId=null, lastUpdated=0, es=null;  
let chosenFiles=[];  
  
const jobArea=document.getElementById('stages');  
const fileInput=document.querySelector('input[name="files"]');  
const fileList=document.getElementById('filelist');  
const dropzone=document.getElementById('dropzone');  
const dzfiles=document.getElementById('dzfiles');  
  
const STAGES=[  
  ['generate','OpenRouter'],  
  ['verify','Groq'],  
  ['final','Gemini'],  
  ['summary','Summary'],  
];  
for(const [key,label] of STAGES){  
  jobArea.insertAdjacentHTML('beforeend',  
    '<div class="stage"><h3>'+label+  
    ' <span id="'+key+'_model" class="modeltag"></span>'+  
    ' <button type="button" class="copy" onclick="copyStage(\\''+key+'\\')">Copy</button>'+  
    ' <span id="'+key+'_spin" class="spin" style="display:none"></span></h3>'+  
    '<pre id="'+key+'"></pre>'+  
    '<pre id="'+key+'_thinking" class="thinking" style="display:none"></pre></div>');  
}  
document.getElementById('summary').insertAdjacentHTML('beforebegin','<b>Best:</b> ');  
  
function copyStage(key){  
  const txt=(document.getElementById(key)||{}).textContent||'';  
  navigator.clipboard.writeText(txt).catch(()=>{});  
}  
  
function syncFileInput(){  
  const dt=new DataTransfer();  
  for(const f of chosenFiles) dt.items.add(f);  
  fileInput.files=dt.files;  
  fileList.textContent=chosenFiles.length  
    ? 'Attached: '+chosenFiles.map(f=>f.name).join(', ')  
    : '';  
}  
fileInput.addEventListener('change',()=>{  
  for(const f of fileInput.files) if(!chosenFiles.some(c=>c.name===f.name&&c.size===f.size)) chosenFiles.push(f);  
  syncFileInput();  
});  
dropzone.addEventListener('click',()=>dzfiles.click());  
dzfiles.addEventListener('change',()=>{  
  for(const f of dzfiles.files) if(!chosenFiles.some(c=>c.name===f.name&&c.size===f.size)) chosenFiles.push(f);  
  dzfiles.value=''; syncFileInput();  
});  
dropzone.addEventListener('dragover',e=>{e.preventDefault();dropzone.classList.add('over');});  
dropzone.addEventListener('dragleave',()=>dropzone.classList.remove('over'));  
dropzone.addEventListener('drop',e=>{  
  e.preventDefault(); dropzone.classList.remove('over');  
  for(const f of e.dataTransfer.files) if(!chosenFiles.some(c=>c.name===f.name&&c.size===f.size)) chosenFiles.push(f);  
  syncFileInput();  
});  
  
function clearInput(){  
  document.getElementById('prompt').value='';  
  document.getElementById('title').value='';  
  chosenFiles=[]; syncFileInput();  
  document.getElementById('prompt').focus();  
}  
  
function badge(s){return '<span class="badge '+s+'">'+s+'</span>';}  
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}  
  
function applySteps(steps,state){  
  for(const [key] of STAGES){  
    const pre=document.getElementById(key);  
    const th=document.getElementById(key+'_thinking');  
    const spin=document.getElementById(key+'_spin');  
    const model=document.getElementById(key+'_model');  
    let st=steps[key+'_status']||'';  
    if((state==='cancelled'||state==='failed')&&(st==='working'||st==='queued')) st='cancelled';  
    model.textContent=steps[key+'_model']||'';  
    if(st==='working'){spin.style.display='inline-block';}  
    else{spin.style.display='none';}  
    if(key==='summary'){  
      const conf=steps['summary_conf'];  
      if(conf!==undefined&&conf!=='') model.textContent+=' — '+conf+'%';  
    }  
    if(steps[key]!==undefined&&steps[key]!==''){  
      const incoming=String(steps[key]);  
      if(incoming.startsWith(pre.textContent)){  
        pre.textContent=incoming;  
      } else {  
        pre.textContent=incoming;  
      }  
    }  
    const tk=key+'_thinking';  
    if(steps[tk]!==undefined&&steps[tk]!==''){  
      th.textContent=steps[tk];  
      th.style.display='block';  
    } else {  
      th.textContent=''; th.style.display='none';  
    }  
  }  
}  
  
async function poll(){  
  if(!jobId) return;  
  const r=await fetch('/status/'+jobId);  
  if(!r.ok) return;  
  const j=await r.json();  
  lastUpdated=j.updated||0;  
  applySteps(j.steps||{}, j.state);  
  loadJobs();  
}  
  
let pollTimer=null;  
function armPoll(){  
  if(pollTimer) clearInterval(pollTimer);  
  pollTimer=setInterval(()=>{poll();loadJobs();},1500);  
}  
  
function closeStream(){ if(es){es.close(); es=null;} }  
  
function openStream(id){  
  closeStream();  
  es=new EventSource('/status/stream/'+id);  
  es.onmessage=(ev)=>{  
    try{  
      const j=JSON.parse(ev.data);  
      lastUpdated=j.updated||lastUpdated;  
      applySteps(j.steps||{}, j.state);  
      loadJobs();  
      if(j.state==='done'||j.state==='failed'||j.state==='cancelled') closeStream();  
    }catch(e){}  
  };  
  es.onerror=()=>{ closeStream(); };  
}  
  
function clearSpinners(){  
  for(const [key] of STAGES){  
    const spin=document.getElementById(key+'_spin');  
    if(spin) spin.style.display='none';  
  }  
}  
  
document.getElementById('runform').addEventListener('submit', async (e)=>{  
  e.preventDefault();  
  const fd=new FormData(e.target);  
  const r=await fetch('/run',{method:'POST',body:fd});  
  if(!r.ok){ alert('Run failed: HTTP '+r.status); return; }  
  const d=await r.json();  
  jobId=d.job_id; lastUpdated=0;  
  openStream(jobId); poll(); loadJobs();  
});  
  
async function stopJob(){  
  let id=jobId;  
  if(!id){  
    const jr=await fetch('/jobs');  
    if(jr.ok){  
      const jobs=await jr.json();  
      const run=jobs.find(j=>j.state==='running'||j.state==='queued');  
      if(run) id=run.id;  
    }  
  }  
  if(!id) return;  
  let r=await fetch('/stop/'+id,{method:'POST'});  
  if(r.status===404||r.status===405) r=await fetch('/stop/'+id);  
  if(!r.ok){  
    let detail=''; try{ detail=(await r.json()).detail||''; }catch(e){}  
    alert('Stop failed: HTTP '+r.status+(detail?' — '+detail:''));  
    return;  
  }  
  closeStream(); poll(); loadJobs();  
}  
  
async function loadJobs(){  
  const r=await fetch('/jobs');  
  if(!r.ok) return;  
  const jobs=await r.json();  
  const div=document.getElementById('jobs');  
  div.innerHTML='';  
  for(const j of jobs){  
    const row=document.createElement('div');  
    row.className='jobrow';  
    const label=document.createElement('span');  
    label.textContent=j.title||j.id;  
    const del=document.createElement('span');  
    del.className='del'; del.textContent='✕';  
    del.onclick=async (ev)=>{  
      ev.stopPropagation();  
      await fetch('/jobs/'+j.id,{method:'DELETE'});  
      if(jobId===j.id){  
        jobId=null; lastUpdated=0; closeStream(); clearSpinners();  
        for(const [key] of STAGES){  
          document.getElementById(key).textContent='';  
          document.getElementById(key+'_model').textContent='';  
          const th=document.getElementById(key+'_thinking');  
          th.textContent=''; th.style.display='none';  
        }  
      }  
      loadJobs();  
    };  
    const b=document.createElement('span'); b.innerHTML=badge(j.state);  
    row.appendChild(b); row.appendChild(label); row.appendChild(del);  
    row.onclick=()=>selectJob(j.id);  
    div.appendChild(row);  
  }  
}  
async function selectJob(id){  
  jobId=id; lastUpdated=0; closeStream(); clearSpinners();  
  openStream(id); poll(); loadJobs();  
}  
fetch('/version').then(r=>r.json()).then(d=>{  
  const el=document.getElementById('version');  
  let t='v'+d.version;  
  if(d.installed_at) t+=' ('+d.installed_at+')';  
  if(d.update_available){  
    el.classList.add('update');  
    t+=' — update available (v'+d.latest+')';  
  } else {  
    el.classList.add('ok');  
    t+=' ✓ up to date';  
  }  
  el.textContent=t;  
  document.title='DizerCoreAI v'+d.version;  
}).catch(()=>{});  
loadJobs(); armPoll();  
</script>  
</body></html>"""
