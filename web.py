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
  #left { width:280px; border-right:1px solid #334155; padding:14px; overflow-y:auto;  
          display:flex; flex-direction:column; }  
  #left img.logo { width:64px; height:64px; border-radius:10px; margin-bottom:6px; }  
  #version { font-size:11px; color:#475569; margin-bottom:10px; }  
  #version.ok { color:#4ade80; }  
  #version.update { color:#fbbf24; }  
  #left h3 { margin:0 0 10px; font-size:14px; color:#94a3b8; text-transform:uppercase;  
             letter-spacing:.5px; }  
  #jobs { overflow-y:auto; flex:1; }  
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
  .b-pending { background:#1e3a8a; color:#93c5fd; }  
  #right { flex:1; padding:18px; overflow-y:auto; display:flex; flex-direction:column; }  
  textarea#prompt { width:100%; height:110px; background:#1e293b; color:#f8fafc;  
                    border:1px solid #334155; border-radius:8px; padding:10px;  
                    font-size:14px; resize:vertical; box-sizing:border-box; }  
  #dropzone { border:2px dashed #334155; border-radius:8px; padding:10px;  
              margin-top:8px; font-size:12px; color:#64748b; text-align:center; }  
  #dropzone.over { border-color:#2563eb; color:#93c5fd; background:#0b1220; }  
  .row { display:flex; gap:10px; margin:10px 0; flex-wrap:wrap; align-items:center; }  
  .row label { font-size:13px; color:#cbd5e1; }  
  select,input[type=number] { background:#1e293b; color:#f8fafc;  
                              border:1px solid #334155; border-radius:6px; padding:4px 6px; }  
  button { background:#2563eb; border:none; color:#fff; padding:8px 16px;  
           border-radius:8px; cursor:pointer; font-size:14px; }  
  button:hover { background:#1d4ed8; }  
  button.stop { background:#b91c1c; }  
  button.stop:hover { background:#991b1b; }  
  button.ghost { background:#334155; }  
  button.ghost:hover { background:#475569; }  
  button.copy { background:#334155; padding:2px 8px; font-size:11px; float:right; }  
  button.copy:hover { background:#475569; }  
  .stage { margin-top:16px; border:1px solid #334155; border-radius:10px; padding:12px; }  
  .stage h4 { margin:0 0 8px; font-size:13px; color:#94a3b8; text-transform:uppercase; }  
  .stage .meta { font-size:12px; color:#64748b; margin-bottom:6px; clear:both; }  
  .stage pre { white-space:pre-wrap; word-wrap:break-word; background:#0b1220;  
               border-radius:6px; padding:10px; font-size:13px; max-height:400px;  
               overflow-y:auto; }  
  .thinking { border-left:3px solid #7c3aed; background:#1b1230; margin:8px 0;  
              padding:8px; font-size:12px; color:#c4b5fd; white-space:pre-wrap; }  
  #files { font-size:12px; color:#64748b; }  
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
  <form id="runform" onsubmit="return runJob(event)">  
    <textarea id="prompt" name="prompt" placeholder="Describe what to build..." required></textarea>  
    <div id="dropzone">Drag &amp; drop files here, or use the picker below</div>  
    <div class="row">  
      <label>Complexity  
        <select name="complexity"><option>1</option><option>2</option>  
          <option selected>3</option><option>4</option><option>5</option></select></label>  
      <label><input type="checkbox" name="openrouter" checked> OpenRouter</label>  
      <label><input type="checkbox" name="groq" checked> Groq</label>  
      <label><input type="checkbox" name="gemini" checked> Gemini</label>  
      <label><input type="checkbox" name="inkling" checked> Judge</label>  
      <input type="file" id="files" name="files" multiple>  
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
  <div class="stage" id="w-summary"><h4>Winner / Summary  
    <button type="button" class="copy" onclick="copyStage('summary',this)">Copy</button></h4>  
    <div class="meta" id="summary_meta"></div>  
    <pre id="summary"></pre></div>  
</div>  
<script>  
let jobId=null, lastUpdated=0, es=null, pollTimer=null;  
const KEYS=['generate','verify','final','summary'];  
const TERMINAL=['done','failed','cancelled'];  
  
function clearInput(){  
  document.getElementById('prompt').value='';  
  const f=document.getElementById('files'); f.value='';  
  document.getElementById('dropzone').textContent='Drag & drop files here, or use the picker below';  
  document.getElementById('prompt').focus();  
}  
function closeStream(){ if(es){ es.close(); es=null; } }  
function clearSpinners(){  
  for(const k of KEYS){ const el=document.getElementById(k+'_meta'); if(el) el.innerHTML=''; }  
}  
function clearStages(){  
  for(const k of KEYS){  
    document.getElementById(k).textContent='';  
    document.getElementById(k+'_meta').textContent='';  
    const th=document.getElementById(k+'_thinking');  
    th.textContent=''; th.style.display='none';  
  }  
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
// Render one job's steps; when the job is in a terminal state, any step still  
// marked "working" is shown as its terminal label so spinners never stick.  
function renderJob(j){  
  const term=TERMINAL.includes((j.state||'').toLowerCase());  
  for(const k of KEYS){  
    let st=j.steps[k+'_status']||'';  
    if(term && st==='working') st=j.state;  
    const meta=(j.steps[k+'_model']||'')+(st?' — '+st:'');  
    const metaEl=document.getElementById(k+'_meta');  
    if(meta) metaEl.innerHTML=(st==='working'?'<span class="spin"></span>':'')+meta;  
    else metaEl.innerHTML='';  
    if(j.steps[k]) document.getElementById(k).textContent=j.steps[k];  
    const th=j.steps[k+'_thinking'];  
    const thEl=document.getElementById(k+'_thinking');  
    if(th){ thEl.style.display='block'; thEl.textContent=th; }  
    else { thEl.style.display='none'; }  
  }  
  const conf=j.steps['summary_conf'];  
  if(conf) document.getElementById('summary_meta').textContent='score '+conf;  
}  
async function runJob(e){  
  e.preventDefault();  
  const fd=new FormData(document.getElementById('runform'));  
  const r=await fetch('/run',{method:'POST',body:fd});  
  if(!r.ok){  
    let d={}; try{ d=await r.json(); }catch(x){}  
    alert('Run failed: HTTP '+r.status+' '+(d.detail||''));  
    return false;  
  }  
  const d=await r.json();  
  jobId=d.job_id; lastUpdated=0; closeStream(); clearStages();  
  // Seed the history row immediately so it shows the moment Run is clicked,  
  // then hydrate from the server list.  
  prependJobRow(jobId, fd.get('prompt')||'', 'running');  
  openStream(jobId); poll(); loadJobs();  
  return false;  
}  
function prependJobRow(id,prompt,state){  
  const div=document.getElementById('jobs');  
  const row=document.createElement('div');  
  row.className='jobrow sel'; row.dataset.jid=id;  
  const b=document.createElement('span'); b.innerHTML=badge(state);  
  const label=document.createElement('span'); label.className='joblbl';  
  label.textContent=(prompt||'').slice(0,60)||id;  
  const del=document.createElement('button'); del.className='jobdel'; del.textContent='x';  
  del.onclick=async (ev)=>{ ev.stopPropagation(); await fetch('/jobs/'+id,{method:'DELETE'});  
    if(jobId===id){ jobId=null; closeStream(); clearStages(); } loadJobs(); };  
  row.appendChild(b); row.appendChild(label); row.appendChild(del);  
  row.onclick=()=>selectJob(id);  
  div.insertBefore(row, div.firstChild);  
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
    let d={}; try{ d=await r.json(); }catch(e){}  
    alert('Stop failed: HTTP '+r.status+' '+(d.detail||''));  
    return;  
  }  
  closeStream(); poll(); loadJobs();  
}  
function badge(state){  
  const s=(state||'').toLowerCase();  
  const c=s==='running'?'b-running':s==='done'?'b-done':s==='failed'?'b-failed':  
           s==='pending'?'b-pending':'b-cancelled';  
  return '<span class="badge '+c+'">'+s+'</span>';  
}  
async function poll(){  
  if(!jobId) return;  
  const r=await fetch('/status/'+jobId); if(!r.ok) return;  
  const j=await r.json();  
  lastUpdated=j.updated||0;  
  renderJob(j);  
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
      renderJob(d);  
      if(d.state && TERMINAL.includes((d.state||'').toLowerCase())){  
        closeStream(); loadJobs();  
      }  
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
    label.textContent=(j.prompt||'').slice(0,60);  
    const del=document.createElement('button'); del.className='jobdel'; del.textContent='x';  
    del.onclick=async (ev)=>{  
      ev.stopPropagation();  
      await fetch('/jobs/'+j.id,{method:'DELETE'});  
      if(jobId===j.id){ jobId=null; closeStream(); clearStages(); }  
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
    t+=' — update available (v'+d.latest+')';  
    el.classList.add('update');  
  } else {  
    t+=' ✓ up to date';  
    el.classList.add('ok');  
  }  
  el.textContent=t;  
  document.title='DizerCoreAI v'+d.version;  
}).catch(()=>{});  
loadJobs(); armPoll();  
</script>  
</body></html>"""
