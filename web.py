# DizerCore-AI  
# ----------------------------------------------------------------------------  
# web.py — dashboard HTML/JS (served by routes.py at "/").  
# Exposes DASHBOARD_HTML only. Logo is served from /static/dizercore.png  
# (mount StaticFiles in dizercoreai.py). Login/Register HTML live in auth.py.  
#  
# Live updates: /status/stream/{job_id} SSE delivers deltas for each step key  
# (generate/verify/final + *_thinking). poll() is the snapshot fallback.  
DASHBOARD_HTML = """<!DOCTYPE html><html><head><title>DizerCoreAI</title>  
<link rel="icon" href="/static/dizercore.png">  
<style>  
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;  
         background:#0f172a; color:#f8fafc; margin:0; display:flex; height:100vh; }  
  #left { width:240px; border-right:1px solid #334155; padding:14px; overflow-y:auto;  
          display:flex; flex-direction:column; align-items:center; }  
  #left img.logo { width:128px; height:128px; border-radius:12px; margin-bottom:6px; }  
  #version { font-size:12px; margin-bottom:16px; text-align:center; color:#64748b; }  
  #version .ok { color:#22c55e; }  
  #version.update { color:#fbbf24; }  
  #left h3 { align-self:flex-start; margin:0 0 10px; font-size:14px; color:#94a3b8;  
             text-transform:uppercase; letter-spacing:.5px; }  
  #jobs { width:100%; }  
  .jobrow { display:flex; align-items:center; gap:6px; padding:4px 6px;  
            border-radius:6px; cursor:pointer; }  
  .jobrow:hover { background:#1e293b; }  
  .jobrow.sel { background:#334155; }  
  .joblbl { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;  
            font-size:13px; }  
  .jobdel { border:none; background:transparent; color:#64748b; cursor:pointer;  
            font-size:14px; padding:0 2px; }  
  .jobdel:hover { color:#ef4444; }  
  .badge { font-size:10px; padding:1px 6px; border-radius:8px; }  
  .b-running { background:#854d0e; color:#fde047; }  
  .b-done { background:#14532d; color:#86efac; }  
  .b-failed { background:#7f1d1d; color:#fca5a5; }  
  .b-cancelled { background:#334155; color:#cbd5e1; }  
  #right { flex:1; padding:18px; overflow-y:auto; display:flex; flex-direction:column; }  
  #right h1 { margin:0 0 14px; font-size:22px; }  
  label.fld { display:block; font-size:12px; color:#94a3b8; margin:10px 0 4px; }  
  input[type=text], textarea#prompt, input[type=number] {  
      width:100%; background:#1e293b; color:#f8fafc; border:1px solid #334155;  
      border-radius:8px; padding:10px; font-size:14px; box-sizing:border-box; }  
  textarea#prompt { height:110px; resize:vertical; }  
  #dropzone { border:2px dashed #334155; border-radius:8px; padding:14px;  
              margin-top:8px; font-size:12px; color:#64748b; text-align:center; }  
  #dropzone.over { border-color:#2563eb; color:#93c5fd; background:#0b1220; }  
  .row { display:flex; gap:16px; margin:12px 0; flex-wrap:wrap; align-items:center; }  
  .row label { font-size:13px; color:#cbd5e1; }  
  .btnrow { display:flex; gap:10px; margin:12px 0; }  
  .btnrow button { flex:1; }  
  button { background:#2563eb; border:none; color:#fff; padding:10px 16px;  
           border-radius:8px; cursor:pointer; font-size:14px; }  
  button:hover { background:#1d4ed8; }  
  button.ghost { background:#334155; }  
  button.ghost:hover { background:#475569; }  
  button.stop { background:#b91c1c; }  
  button.stop:hover { background:#991b1b; }  
  button.copy { background:#334155; padding:2px 8px; font-size:11px; margin-left:8px; }  
  button.copy:hover { background:#475569; }  
  .stage { margin-top:16px; border:1px solid #334155; border-radius:10px; padding:12px; }  
  .stage h4 { margin:0 0 8px; font-size:13px; color:#94a3b8; text-transform:uppercase; }  
  .stage .meta { font-size:12px; color:#64748b; margin-bottom:6px; }  
  .stage pre { white-space:pre-wrap; word-wrap:break-word; background:#0b1220;  
               border-radius:6px; padding:10px; font-size:13px; max-height:400px;  
               overflow-y:auto; }  
  .thinking { border-left:3px solid #7c3aed; background:#1b1230; margin:8px 0;  
              padding:8px; font-size:12px; color:#c4b5fd; white-space:pre-wrap; }  
  .spin { display:inline-block; width:12px; height:12px; border:2px solid #475569;  
          border-top-color:#f8fafc; border-radius:50%; animation:sp .8s linear infinite;  
          vertical-align:middle; margin-right:6px; }  
  @keyframes sp { to { transform:rotate(360deg); } }  
</style></head><body>  
<div id="left">  
  <img class="logo" src="/static/dizercore.png" alt="DizerCore">  
  <div id="version"></div>  
  <h3>Jobs</h3>  
  <div id="jobs"></div>  
</div>  
<div id="right">  
  <h1>DizerCoreAI</h1>  
  <form id="runform" onsubmit="return runJob(event)">  
    <label class="fld">Title (optional)</label>  
    <input type="text" name="title" id="title" placeholder="Short label for this job">  
    <label class="fld">Prompt *</label>  
    <textarea id="prompt" name="prompt" placeholder="Describe what to build..." required></textarea>  
    <div id="dropzone">Drag &amp; drop files here, or use the picker below</div>  
    <label class="fld">Attachments (text/code/images/PDF — 5 MB each, 50 MB total)</label>  
    <input type="file" id="files" name="files" multiple>  
    <label class="fld">Complexity (1&ndash;5)</label>  
    <input type="number" name="complexity" id="complexity" min="1" max="5" value="3">  
    <div class="row">  
      <label><input type="checkbox" name="openrouter" checked> OpenRouter</label>  
      <label><input type="checkbox" name="groq" checked> Groq</label>  
      <label><input type="checkbox" name="gemini" checked> Gemini</label>  
      <label><input type="checkbox" name="inkling" checked> Judge</label>  
    </div>  
    <div class="btnrow">  
      <button type="submit">Run</button>  
      <button type="button" class="ghost" onclick="clearInput()">Clear</button>  
      <button type="button" class="stop" onclick="stopJob()">Stop</button>  
    </div>  
  </form>  
  <div class="stage" id="w-generate"><h4>OpenRouter  
    <button type="button" class="copy" onclick="copyStage('generate',this)">Copy</button></h4>  
    <div class="meta" id="generate_meta"></div>  
    <div class="thinking" id="generate_thinking" style="display:none"></div>  
    <pre id="generate"></pre></div>  
  <div class="stage" id="w-verify"><h4>Groq  
    <button type="button" class="copy" onclick="copyStage('verify',this)">Copy</button></h4>  
    <div class="meta" id="verify_meta"></div>  
    <div class="thinking" id="verify_thinking" style="display:none"></div>  
    <pre id="verify"></pre></div>  
  <div class="stage" id="w-final"><h4>Gemini  
    <button type="button" class="copy" onclick="copyStage('final',this)">Copy</button></h4>  
    <div class="meta" id="final_meta"></div>  
    <div class="thinking" id="final_thinking" style="display:none"></div>  
    <pre id="final"></pre></div>  
  <div class="stage" id="w-summary"><h4>Summary  
    <button type="button" class="copy" onclick="copyStage('summary',this)">Copy</button></h4>  
    <div class="meta" id="summary_meta"></div>  
    <div style="font-size:12px;color:#94a3b8">Best:</div>  
    <pre id="summary"></pre></div>  
</div>  
<script>  
let jobId=null, lastUpdated=0, es=null, pollTimer=null;  
const KEYS=['generate','verify','final','summary'];  
  
function clearInput(){  
  document.getElementById('title').value='';  
  document.getElementById('prompt').value='';  
  const f=document.getElementById('files'); f.value='';  
  const dz=document.getElementById('dropzone');  
  dz.textContent='Drag & drop files here, or use the picker below';  
  document.getElementById('prompt').focus();  
}  
function closeStream(){ if(es){ es.close(); es=null; } }  
function clearSpinners(){  
  for(const k of KEYS){ const el=document.getElementById(k+'_meta'); if(el) el.innerHTML=''; }  
}  
function copyStage(key,btn){  
  const t=document.getElementById(key).textContent;  
  navigator.clipboard.writeText(t).then(()=>{  
    btn.textContent='Copied'; setTimeout(()=>{btn.textContent='Copy';},1200);  
  }).catch(()=>{ btn.textContent='Fail'; setTimeout(()=>{btn.textContent='Copy';},1200); });  
}  
// ---- drag and drop: files land in the same input the form submits ----  
const dz=document.getElementById('dropzone'), fi=document.getElementById('files');  
dz.addEventListener('dragover',e=>{ e.preventDefault(); dz.classList.add('over'); });  
dz.addEventListener('dragleave',()=>dz.classList.remove('over'));  
dz.addEventListener('drop',e=>{  
  e.preventDefault(); dz.classList.remove('over');  
  const dt=new DataTransfer();  
  for(const f of fi.files) dt.items.add(f);  
  for(const f of e.dataTransfer.files) dt.items.add(f);  
  fi.files=dt.files;  
  dz.textContent=fi.files.length+' file(s) attached';  
});  
async function runJob(e){  
  e.preventDefault();  
  const form=document.getElementById('runform');  
  const prompt=document.getElementById('prompt').value.trim();  
  if(!prompt){ alert('Prompt is required.'); return false; }  
  const fd=new FormData(form);  
  // Guarantee prompt is present even if the field name were ever stripped.  
  fd.set('prompt', prompt);  
  const r=await fetch('/run',{method:'POST',body:fd});  
  if(!r.ok){  
    let d={}; try{ d=await r.json(); }catch(x){}  
    alert('Run failed: HTTP '+r.status+(d.detail?(' — '+JSON.stringify(d.detail)):''));  
    return false;  
  }  
  const d=await r.json();  
  jobId=d.job_id; lastUpdated=0; closeStream(); clearSpinners();  
  for(const k of KEYS){  
    document.getElementById(k).textContent='';  
    document.getElementById(k+'_meta').textContent='';  
    const th=document.getElementById(k+'_thinking'); th.textContent=''; th.style.display='none';  
  }  
  openStream(jobId); poll(); loadJobs();  
  return false;  
}  
async function stopJob(){  
  let target=jobId;  
  try{  
    const jr=await fetch('/jobs'); const jobs=await jr.json();  
    const running=jobs.filter(j=>j.state==='running');  
    if(target){ const j=jobs.find(j=>j.id===target);  
      if(j && j.state!=='running' && running.length) target=running[0].id; }  
    else if(running.length){ target=running[0].id; }  
    if(!target){ alert('No running job to stop.'); return; }  
  }catch(err){ if(!target){ alert('Cannot list jobs: '+err); return; } }  
  jobId=target;  
  let r=await fetch('/stop/'+target,{method:'POST'});  
  if(r.status===404||r.status===405){ r=await fetch('/stop/'+target); }  
  if(!r.ok){  
    let d={}; try{ d=await r.json(); }catch(x){}  
    alert('Stop failed: HTTP '+r.status+' '+(d.detail||''));  
    return;  
  }  
  closeStream(); poll(); loadJobs();  
}  
function badge(state){  
  const s=(state||'').toLowerCase();  
  const c=s==='running'?'b-running':s==='done'?'b-done':s==='failed'?'b-failed':'b-cancelled';  
  return '<span class="badge '+c+'">'+s+'</span>';  
}  
function applySteps(steps,state){  
  const cancelled=(state||'').toLowerCase()==='cancelled';  
  for(const k of KEYS){  
    let status=steps[k+'_status']||'';  
    if(cancelled && status==='working') status='cancelled';  
    const model=steps[k+'_model']||'';  
    const meta=steps[k+'_meta']||(model+(status?' — '+status:''));  
    if(meta) document.getElementById(k+'_meta').innerHTML =  
      (status==='working'?'<span class="spin"></span>':'')+meta;  
    if(steps[k]!==undefined) document.getElementById(k).textContent=steps[k];  
    const th=steps[k+'_thinking'];  
    const thEl=document.getElementById(k+'_thinking');  
    if(th){ thEl.style.display='block'; thEl.textContent=th; }  
  }  
  const conf=steps['summary_conf']; if(conf) document.getElementById('summary_meta').textContent='score '+conf;  
}  
async function poll(){  
  if(!jobId) return;  
  const r=await fetch('/status/'+jobId); if(!r.ok) return;  
  const j=await r.json();  
  lastUpdated=j.updated||0;  
  applySteps(j.steps||{}, j.state);  
  if(j.state==='running'||j.state==='pending'){ armPoll(); }  
}  
function armPoll(){  
  if(pollTimer) clearTimeout(pollTimer);  
  pollTimer=setTimeout(poll,1500);  
}  
function openStream(id){  
  closeStream();  
  es=new EventSource('/status/stream/'+id);  
  es.onmessage=(e)=>{  
    try{  
      const d=JSON.parse(e.data);  
      if(d.steps) applySteps(d.steps, d.state);  
      if(d.state && d.state!=='running' && d.state!=='pending'){ closeStream(); loadJobs(); }  
    }catch(x){}  
  };  
  es.onerror=()=>{ closeStream(); poll(); };  
}  
async function loadJobs(){  
  const r=await fetch('/jobs'); if(!r.ok) return;  
  const jobs=await r.json();  
  const div=document.getElementById('jobs'); div.innerHTML='';  
  for(const j of jobs){  
    const row=document.createElement('div');  
    row.className='jobrow'+(j.id===jobId?' sel':'');  
    const label=document.createElement('span'); label.className='joblbl';  
    label.textContent=(j.title||j.prompt||'').slice(0,60);  
    const del=document.createElement('button'); del.className='jobdel'; del.textContent='x';  
    del.onclick=async (ev)=>{  
      ev.stopPropagation();  
      await fetch('/jobs/'+j.id,{method:'DELETE'});  
      if(jobId===j.id){  
        jobId=null; closeStream();  
        for(const k of KEYS){ document.getElementById(k).textContent='';  
          document.getElementById(k+'_meta').textContent='';  
          const th=document.getElementById(k+'_thinking');  
          th.textContent=''; th.style.display='none'; } }  
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
// ---- version + up-to-date indicator ----  
fetch('/version').then(r=>r.json()).then(d=>{  
  const el=document.getElementById('version');  
  const v='v'+(d.version||'?');  
  if(d.update_available){  
    el.classList.add('update');  
    el.textContent=v+' — update available (v'+(d.latest||'?')+')';  
  }else{  
    el.innerHTML=v+' <span class="ok">&#10003; up to date</span>';  
  }  
  document.title='DizerCoreAI '+v;  
}).catch(()=>{});  
loadJobs(); armPoll();  
</script>  
</body></html>"""
