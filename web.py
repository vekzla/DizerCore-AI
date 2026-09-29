# DizerCore-AI  
# ----------------------------------------------------------------------------  
# web.py — dashboard HTML/JS (served by routes.py at "/").  
# Exposes DASHBOARD_HTML only. Logo is served from /static/dizercore.png  
# (mount StaticFiles in dizercoreai.py). Login/Register HTML live in auth.py.  
#  
# Live updates: /status/stream/{job_id} SSE pushes the full job payload.  
# poll() remains as the snapshot hydrator and fallback for finished jobs.  
  
DASHBOARD_HTML = """<!DOCTYPE html><html><head><title>DizerCoreAI</title>  
<link rel="icon" href="/static/dizercore.png">  
<style>  
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;  
         margin:0; padding:24px; background:#0b1020; color:#dfe7ff; }  
  .shell { max-width:860px; margin:0 auto; }  
  header { display:flex; align-items:center; gap:14px; margin-bottom:14px; }  
  header img { width:160px; height:auto; }  
  #version { font-size:.8rem; color:#5f6b8d; margin-top:4px; }  
  #version.ok { color:#4ade80; }  
  #version.update { color:#fbbf24; }  
  form { background:#111a33; padding:16px; border-radius:12px; }  
  textarea, input[type=text], select { width:100%; box-sizing:border-box;  
      background:#0b1020; color:#dfe7ff; border:1px solid #26315c;  
      border-radius:8px; padding:10px; font-size:.95rem; margin-bottom:10px; }  
  textarea { min-height:110px; resize:vertical; }  
  .row { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:10px; }  
  .row label { font-size:.85rem; color:#9fb0dd; }  
  button { background:#2f6fed; color:#fff; border:none; border-radius:8px;  
      padding:10px 18px; font-size:.9rem; cursor:pointer; }  
  button.clear { background:#3a4670; }  
  button.stop { background:#c0392b; }  
  button:hover { filter:brightness(1.15); }  
  .agents { display:flex; gap:16px; margin-bottom:10px; }  
  .agents label { font-size:.85rem; color:#9fb0dd; display:flex; gap:5px; align-items:center; }  
  #dropzone { border:2px dashed #26315c; border-radius:8px; padding:14px;  
      text-align:center; color:#5f6b8d; font-size:.85rem; margin-bottom:10px; }  
  #dropzone.over { border-color:#2f6fed; color:#9fb0dd; }  
  #filelist { font-size:.8rem; color:#5f6b8d; margin-bottom:10px; }  
  #filelist span { margin-right:10px; }  
  .stage { background:#111a33; border-radius:12px; padding:14px; margin-bottom:12px; }  
  .stage h3 { margin:0 0 8px; font-size:.9rem; color:#9fb0dd;  
      display:flex; align-items:center; gap:8px; }  
  .stage pre { white-space:pre-wrap; word-break:break-word; font-size:.85rem;  
      background:#0b1020; border-radius:8px; padding:10px; margin:0; min-height:20px; }  
  .thinking { color:#7c8bb5; font-style:italic; display:none; }  
  .status { font-size:.75rem; padding:2px 8px; border-radius:20px; }  
  .status.working  { background:#1d2b55; color:#7ea8ff; }  
  .status.done     { background:#123f2a; color:#4ade80; }  
  .status.failed   { background:#4a1524; color:#f87171; }  
  .status.cancelled{ background:#3a3416; color:#fbbf24; }  
  .status.idle     { background:#232a45; color:#5f6b8d; }  
  .spin { display:none; width:12px; height:12px; border:2px solid #26315c;  
      border-top-color:#7ea8ff; border-radius:50%; animation:sp .8s linear infinite; }  
  @keyframes sp { to { transform:rotate(360deg); } }  
  .copy { background:none; border:1px solid #26315c; color:#9fb0dd;  
      padding:2px 10px; font-size:.7rem; margin-left:auto; }  
  #jobsbar { position:fixed; top:0; right:0; width:260px; height:100%;  
      background:#0d1428; border-left:1px solid #26315c; padding:14px;  
      overflow-y:auto; transform:translateX(0); transition:transform .25s; }  
  #jobsbar.hidden { transform:translateX(100%); }  
  #jobsbar h4 { margin:0 0 10px; font-size:.8rem; color:#9fb0dd;  
      display:flex; justify-content:space-between; align-items:center; }  
  #jobsbar .jrow { padding:8px; border-radius:8px; font-size:.8rem;  
      cursor:pointer; display:flex; gap:8px; align-items:center; }  
  #jobsbar .jrow:hover { background:#111a33; }  
  #jobsbar .del { margin-left:auto; color:#f87171; cursor:pointer; }  
  #jobstoggle { position:fixed; top:14px; right:270px; z-index:10;  
      background:#1d2b55; color:#9fb0dd; border:1px solid #26315c;  
      border-radius:8px; padding:6px 12px; font-size:.8rem; }  
</style></head><body>  
<button id="jobstoggle">Jobs</button>  
<div id="jobsbar">  
  <h4>History <span id="jobsclose" style="cursor:pointer">✕</span></h4>  
  <div id="jobs"></div>  
</div>  
<div class="shell">  
  <header>  
    <img src="/static/dizercore.png" alt="DizerCore">  
    <div><h2 style="margin:0">DizerCoreAI</h2><div id="version"></div></div>  
  </header>  
  <form id="runform" onsubmit="run(event)">  
    <input type="text" id="title" placeholder="Title (optional)">  
    <textarea id="prompt" placeholder="Describe what to build..."></textarea>  
    <div id="dropzone">Drag files here or click to attach  
      <input type="file" id="files" name="files" multiple  
             style="display:none" onchange="listFiles()">  
    </div>  
    <div id="filelist"></div>  
    <div class="row">  
      <label>Complexity  
        <select id="complexity">  
          <option>1</option><option>2</option>  
          <option selected>3</option><option>4</option><option>5</option>  
        </select></label>  
      <div class="agents">  
        <label><input type="checkbox" name="openrouter" checked> OpenRouter</label>  
        <label><input type="checkbox" name="groq" checked> Groq</label>  
        <label><input type="checkbox" name="gemini" checked> Gemini</label>  
        <label><input type="checkbox" name="inkling" checked> Judge</label>  
      </div>  
      <button type="submit">Run</button>  
      <button type="button" class="clear" onclick="clearInput()">Clear</button>  
      <button type="button" class="stop" onclick="stopJob()">Stop</button>  
    </div>  
  </form>  
  <div class="stage"><h3>OpenRouter  
    <span id="generate_status" class="status idle">idle</span>  
    <span class="spin" id="generate_spin"></span>  
    <button class="copy" type="button" onclick="copyStage('generate')">Copy</button></h3>  
    <div class="thinking" id="generate_thinking"></div>  
    <pre id="generate"></pre></div>  
  <div class="stage"><h3>Groq  
    <span id="verify_status" class="status idle">idle</span>  
    <span class="spin" id="verify_spin"></span>  
    <button class="copy" type="button" onclick="copyStage('verify')">Copy</button></h3>  
    <div class="thinking" id="verify_thinking"></div>  
    <pre id="verify"></pre></div>  
  <div class="stage"><h3>Gemini  
    <span id="final_status" class="status idle">idle</span>  
    <span class="spin" id="final_spin"></span>  
    <button class="copy" type="button" onclick="copyStage('final')">Copy</button></h3>  
    <div class="thinking" id="final_thinking"></div>  
    <pre id="final"></pre></div>  
  <div class="stage"><h3>Summary  
    <span id="summary_status" class="status idle">idle</span>  
    <span class="spin" id="summary_spin"></span>  
    <span id="summary_conf" style="font-size:.75rem;color:#4ade80"></span>  
    <button class="copy" type="button" onclick="copyStage('summary')">Copy</button></h3>  
    <pre id="summary"></pre></div>  
</div>  
<script>  
let jobId=null, es=null, lastUpdated=0, pollTimer=null;  
const STAGES={openrouter:'generate',groq:'verify',gemini:'final'};  
  
function badge(s){  
  const map={done:['done','#4ade80'],running:['running','#7ea8ff'],  
    failed:['failed','#f87171'],cancelled:['cancelled','#fbbf24']};  
  const [t,c]=map[s]||[s||'idle','#5f6b8d'];  
  return '<span style="color:'+c+'">'+t+'</span>';  
}  
function armPoll(){ clearInterval(pollTimer); pollTimer=setInterval(poll,2000); }  
function closeStream(){ if(es){es.close();es=null;} }  
function openStream(id){  
  closeStream();  
  es=new EventSource('/status/stream/'+id);  
  es.onmessage=ev=>{ try{ applyJob(JSON.parse(ev.data)); }catch(e){} };  
}  
function clearSpinners(){  
  document.querySelectorAll('.spin').forEach(s=>s.style.display='none');  
}  
function spinFor(key,on){  
  const el=document.getElementById(key+'_spin');  
  if(el) el.style.display=on?'inline-block':'none';  
}  
function setStatus(key,txt){  
  const el=document.getElementById(key+'_status');  
  if(el){ el.textContent=txt; el.className='status '+txt; }  
}  
function spinForWorking(){  
  // Show spinners on every enabled stage the moment Run returns, before  
  // the first poll lands.  
  for(const [agent,key] of Object.entries(STAGES)){  
    const cb=document.querySelector('input[name="'+agent+'"]');  
    if(cb && cb.checked) spinFor(key,true);  
  }  
}  
function applyJob(j){  
  if(!j) return;  
  const steps=j.steps||{};  
  for(const key of ['generate','verify','final','summary']){  
    let st=steps[key+'_status']||'idle';  
    // Backend leaves *_status='working' when a job is cancelled mid-stage —  
    // mask it on screen so nothing looks like it's still running.  
    if(j.state==='cancelled' && st==='working') st='cancelled';  
    if(j.state==='failed'    && st==='working') st='failed';  
    setStatus(key,st);  
    spinFor(key, st==='working');  
    if(st==='done'||st==='failed'||st==='cancelled') spinFor(key,false);  
    const pre=document.getElementById(key);  
    if(pre && steps[key]!=null) pre.textContent=steps[key];  
    const th=document.getElementById(key+'_thinking');  
    if(th && steps[key+'_thinking']){ th.textContent=steps[key+'_thinking'];  
      th.style.display='block'; }  
  }  
  const conf=document.getElementById('summary_conf');  
  if(conf && steps.summary_conf) conf.textContent='score: '+steps.summary_conf;  
  const m=document.getElementById('generate');  
  if(steps.generate_model && m) m.dataset.model=steps.generate_model;  
}  
async function poll(){  
  if(!jobId) return;  
  try{  
    const r=await fetch('/status/'+jobId);  
    if(r.ok){ const j=await r.json(); applyJob(j); }  
  }catch(e){}  
}  
async function loadJobs(){  
  try{  
    const r=await fetch('/jobs');  
    if(!r.ok) return;  
    const jobs=await r.json();  
    const div=document.getElementById('jobs');  
    div.innerHTML='';  
    for(const j of jobs){  
      const row=document.createElement('div');  
      row.className='jrow'; row.dataset.id=j.id;  
      const b=document.createElement('span'); b.innerHTML=badge(j.state);  
      const label=document.createElement('span');  
      label.textContent=(j.title||j.prompt||j.id).slice(0,28);  
      const del=document.createElement('span');  
      del.className='del'; del.textContent='✕';  
      del.onclick=async ev=>{  
        ev.stopPropagation();  
        await fetch('/jobs/'+j.id,{method:'DELETE'});  
        if(jobId===j.id){ jobId=null; closeStream(); }  
        loadJobs();  
      };  
      row.appendChild(b); row.appendChild(label); row.appendChild(del);  
      row.onclick=()=>selectJob(j.id);  
      div.appendChild(row);  
    }  
  }catch(e){}  
}  
async function selectJob(id){  
  jobId=id; lastUpdated=0; clearSpinners();  
  openStream(id); poll();  
}  
async function run(ev){  
  ev.preventDefault();  
  const fd=new FormData(ev.target);  
  if(!fd.get('prompt') || !String(fd.get('prompt')).trim()){  
    alert('Prompt is empty.'); return;  
  }  
  try{  
    const r=await fetch('/run',{method:'POST',body:fd});  
    if(!r.ok){  
      let d=''; try{ d=(await r.json()).detail||''; }catch(e){}  
      alert('Run failed: HTTP '+r.status+(d?' — '+JSON.stringify(d):''));  
      return;  
    }  
    const j=await r.json();  
    jobId=j.job_id;  
    spinForWorking();            // show agents working immediately  
    openStream(jobId);           // stream first, poll hydrates  
    poll();  
    loadJobs();                  // history row appears instantly  
  }catch(e){ alert('Run failed: '+e); }  
}  
async function stopJob(){  
  // Fall back to newest running job if none selected.  
  if(!jobId){  
    try{  
      const r=await fetch('/jobs');  
      const jobs=await r.json();  
      const running=jobs.filter(j=>j.state==='running');  
      if(running.length) jobId=running[0].id;  
    }catch(e){}  
  }  
  if(!jobId){ alert('No running job to stop.'); return; }  
  let r=await fetch('/stop/'+jobId,{method:'POST'});  
  if(r.status===404||r.status===405)  
    r=await fetch('/stop/'+jobId);   // GET fallback  
  if(!r.ok) alert('Stop failed: HTTP '+r.status);  
  else{  
    // Mask all working steps instantly so nothing looks alive.  
    for(const key of ['generate','verify','final','summary']){  
      const el=document.getElementById(key+'_status');  
      if(el && el.textContent==='working'){ setStatus(key,'cancelled'); }  
      spinFor(key,false);  
    }  
  }  
  poll();  
}  
function clearInput(){  
  document.getElementById('prompt').value='';  
  document.getElementById('title').value='';  
  const f=document.getElementById('files'); f.value='';  
  document.getElementById('filelist').innerHTML='';  
  document.getElementById('prompt').focus();  
}  
function listFiles(){  
  const f=document.getElementById('files');  
  const div=document.getElementById('filelist');  
  div.innerHTML='';  
  for(const file of f.files){  
    const s=document.createElement('span');  
    s.textContent=file.name+' ('+Math.round(file.size/1024)+'KB)';  
    div.appendChild(s);  
  }  
}  
async function copyStage(key){  
  const el=document.getElementById(key);  
  if(!el||!el.textContent) return;  
  await navigator.clipboard.writeText(el.textContent);  
  const btns=document.querySelectorAll('.stage .copy');  
  btns.forEach(b=>{ if(b.previousSibling||b.parentNode.id.includes(key)){} });  
  event.target.textContent='Copied';  
  setTimeout(()=>{ event.target.textContent='Copy'; },1200);  
}  
// Drag & drop merges into the real file input so files submit normally.  
const dz=document.getElementById('dropzone');  
dz.addEventListener('click',()=>document.getElementById('files').click());  
dz.addEventListener('dragover',ev=>{ev.preventDefault();dz.classList.add('over');});  
dz.addEventListener('dragleave',()=>dz.classList.remove('over'));  
dz.addEventListener('drop',ev=>{  
  ev.preventDefault(); dz.classList.remove('over');  
  const dt=new DataTransfer();  
  const input=document.getElementById('files');  
  for(const f of input.files) dt.items.add(f);  
  for(const f of ev.dataTransfer.files) dt.items.add(f);  
  input.files=dt.files; listFiles();  
});  
// Sidebar: single-click open/close — the previous version had a document-level  
// outside-click closer fighting the toggle, which needed two clicks.  
const bar=document.getElementById('jobsbar');  
const tgl=document.getElementById('jobstoggle');  
tgl.onclick=ev=>{ ev.stopPropagation(); bar.classList.toggle('hidden'); };  
document.getElementById('jobsclose').onclick=  
    ev=>{ ev.stopPropagation(); bar.classList.add('hidden'); };  
bar.onclick=ev=>ev.stopPropagation();  
fetch('/version').then(r=>r.json()).then(d=>{  
  const v=document.getElementById('version');  
  let t='v'+d.version;  
  if(d.installed_at) t+=' ('+d.installed_at+')';  
  if(d.update_available){ t+=' — update available (v'+d.latest+')';  
    v.classList.add('update'); }  
  else { t+=' ✓ up to date'; v.classList.add('ok'); }  
  v.textContent=t;  
  document.title='DizerCoreAI v'+d.version;  
}).catch(()=>{});  
loadJobs(); armPoll();  
</script>  
</body></html>"""
