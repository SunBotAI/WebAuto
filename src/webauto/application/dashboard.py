"""Zero-configuration Web onboarding for the MCP-first WebAuto runtime."""

from __future__ import annotations

import json

DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WebAuto 配置中心</title>
<style>
:root{color-scheme:dark;--bg:#090d13;--panel:#121925;--panel2:#0d141f;--line:#28364d;--text:#eff5ff;--muted:#9eafc8;--brand:#65dfb6;--blue:#72aaff;--warn:#ffd17d;--danger:#ff8293}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 12% 0,#182b43 0,transparent 30%),var(--bg);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:3;display:flex;justify-content:space-between;align-items:center;padding:16px max(20px,calc((100vw - 1120px)/2));border-bottom:1px solid rgba(114,170,255,.18);background:rgba(9,13,19,.9);backdrop-filter:blur(16px)}
.brand{display:flex;align-items:center;gap:11px}.logo{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,var(--brand),var(--blue));color:#071019;font-weight:900}.brand strong{font-size:18px}.brand small{display:block;color:var(--muted)}
main{max-width:1120px;margin:0 auto;padding:34px 20px 68px}.panel{border:1px solid var(--line);border-radius:18px;background:linear-gradient(155deg,rgba(20,28,41,.98),rgba(12,18,28,.98));box-shadow:0 18px 48px rgba(0,0,0,.22);padding:24px}.hero{display:grid;grid-template-columns:1.3fr .9fr;gap:18px;margin-bottom:18px}
h1{font-size:clamp(30px,4vw,48px);line-height:1.08;margin:7px 0 13px;letter-spacing:-.035em}h2{font-size:19px;margin:0 0 8px}h3{font-size:15px;margin:0 0 12px}.eyebrow{color:var(--brand);font-weight:800;letter-spacing:.08em;text-transform:uppercase;font-size:12px}.muted{color:var(--muted)}
.badges,.chips,.actions{display:flex;gap:9px;flex-wrap:wrap}.badges{margin-top:18px}.badge,.chip{border:1px solid #31506c;border-radius:999px;padding:5px 10px;color:#cfe2ff;background:#102136}.badge.good,.chip.good{border-color:#28634f;color:#9bf0cf;background:#102a22}.badge.warn{border-color:#765b2c;color:#ffdda0;background:#2b210f}
.arch{display:grid;gap:10px}.arch div{padding:13px;border-radius:13px;background:#0c131e;border:1px solid #202e43}.arch b{display:block;color:var(--brand);margin-bottom:2px}.arch span{color:var(--muted)}
.flow{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-bottom:18px}.wide{grid-column:1/-1}.step{display:flex;align-items:flex-start;gap:14px}.number{display:grid;place-items:center;flex:0 0 34px;height:34px;border-radius:11px;background:#172a40;color:var(--blue);font-weight:900}.step-body{min-width:0;flex:1}.notice{padding:13px 15px;border:1px solid #675126;border-radius:12px;background:#2a210f;color:#ffe0a3;margin:15px 0 0}
button{border:0;border-radius:10px;padding:10px 15px;background:linear-gradient(135deg,var(--brand),#4ecba1);color:#07130f;font-weight:800;cursor:pointer}button.secondary{background:#1a2940;color:#dceaff;border:1px solid #31425e}button:hover{filter:brightness(1.08)}button:disabled{opacity:.55;cursor:wait}.actions{margin-top:15px}
.code-grid,.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 18px}.code-head{display:flex;align-items:center;justify-content:space-between;gap:12px}pre{white-space:pre-wrap;word-break:break-word;max-height:340px;overflow:auto;border:1px solid #273750;border-radius:12px;background:#080d14;padding:14px;color:#bed4f5;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}
details.panel{padding:0;margin-top:18px}summary{cursor:pointer;list-style:none;padding:21px 24px;font-weight:800}summary::-webkit-details-marker{display:none}summary:after{content:"＋";float:right;color:var(--blue)}details[open] summary:after{content:"－"}.advanced{border-top:1px solid var(--line);padding:22px 24px 25px}.section{padding:18px 0;border-bottom:1px solid #223047}.section:last-child{border-bottom:0;padding-bottom:0}
label{display:block;color:#cbd8ec;margin:0 0 12px;font-size:13px}input,select{display:block;width:100%;margin-top:6px;border:1px solid #30405a;border-radius:10px;background:#0a111b;color:var(--text);padding:10px 11px;outline:none}input:focus,select:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(114,170,255,.12)}.check{display:flex;align-items:center;gap:9px}.check input{display:inline-block;width:auto;margin:0}.hint{display:block;color:var(--muted);font-size:12px;margin-top:5px}.status{display:inline-flex;align-items:center;gap:7px;color:var(--muted)}.dot{width:9px;height:9px;border-radius:50%;background:#68758a}.dot.ok{background:var(--brand);box-shadow:0 0 12px rgba(101,223,182,.65)}.path{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:#a8c8f5}footer{margin-top:24px;color:var(--muted);text-align:center;font-size:12px}
@media(max-width:800px){.hero,.flow,.code-grid,.form-grid{grid-template-columns:1fr}.wide{grid-column:auto}header{padding:14px 16px}main{padding:24px 16px 48px}}
</style>
</head>
<body>
<header>
  <div class="brand"><div class="logo">W</div><div><strong>WebAuto</strong><small>本地个人管家运行时</small></div></div>
  <div class="status"><i id="health-dot" class="dot"></i><span id="health-text">检查服务</span></div>
</header>
<main>
  <div class="hero">
    <section class="panel">
      <div class="eyebrow">Zero-config · MCP-first</div>
      <h1>不用填运维参数，<br>准备好就交给智能体。</h1>
      <p class="muted">WebAuto 自动管理本地浏览器、目录和安全默认值。你只需把 MCP 接到自己的 AI 客户端；账号登录在真实 Chrome 内完成，WebAuto 不保存账号密码。</p>
      <div class="badges"><span class="badge good">本机自动认证</span><span class="badge good">持久浏览器身份</span><span class="badge">MCP 原子工具</span><span class="badge">写操作审批</span></div>
    </section>
    <section class="panel arch">
      <div><b>你负责</b><span>在专属 Chrome 内登录账号、确认验证码与支付</span></div>
      <div><b>智能体负责</b><span>理解任务、浏览、比较、填写和动态调整</span></div>
      <div><b>WebAuto 负责</b><span>浏览器执行、登录态复用、文件、边界、审批与审计</span></div>
    </section>
  </div>

  <div class="flow">
    <section class="panel">
      <div class="step"><div class="number">1</div><div class="step-body">
        <div class="code-head"><h2>一键准备本机环境</h2><span id="prepare-badge" class="badge warn">检查中</span></div>
        <p class="muted">自动探测 Google Chrome、创建 Profile/Artifact 目录、生成本机凭据，并采用本地单用户默认值。</p>
        <div class="actions"><button id="prepare-local">一键准备</button><button id="test-settings" class="secondary">检查是否就绪</button></div>
        <pre id="prepare-output">正在读取当前状态…</pre>
      </div></div>
    </section>

    <section class="panel">
      <div class="step"><div class="number">2</div><div class="step-body">
        <h2>账号只在浏览器里登录</h2>
        <p class="muted">首次让智能体打开对应网站时，在弹出的专属 Chrome 中手工登录一次。后续使用同一个 <span class="path">default</span> Profile 自动复用登录态。</p>
        <div class="chips"><span class="chip good">淘宝</span><span class="chip good">京东</span><span class="chip good">咸鱼</span><span class="chip">其他网站</span></div>
        <p class="notice">不要在本页填写账号、密码、短信码或支付信息；验证码和安全确认始终由你在 Chrome 内处理。</p>
      </div></div>
    </section>

    <section class="panel wide">
      <div class="step"><div class="number">3</div><div class="step-body">
        <div class="code-head"><div><h2>连接你的智能体</h2><p class="muted">配置会自动生成，不包含 Setup Token 或 MCP Token。复制到 AI 客户端后，任务都在 AI 客户端里说。</p></div><span id="mcp-tool-count" class="badge">加载中</span></div>
        <div class="code-grid">
          <div><div class="code-head"><h3>通用 MCP JSON</h3><button id="copy-json" class="secondary">复制 JSON</button></div><pre id="mcp-json">正在生成…</pre></div>
          <div><div class="code-head"><h3>Codex TOML</h3><button id="copy-codex" class="secondary">复制 TOML</button></div><pre id="mcp-codex">正在生成…</pre></div>
        </div>
        <pre id="mcp-output">正在读取 MCP 连接信息…</pre>
      </div></div>
    </section>
  </div>

  <details class="panel" id="advanced-settings">
    <summary>高级设置（仅故障排查、自定义部署或旧 Agent 兼容时需要）</summary>
    <div class="advanced">
      <p class="notice">本机个人模式无需 PostgreSQL、Redis、模型 API Key、运行目录或 Chrome 路径。下面的字段都不是首次使用必填项。</p>

      <div class="section"><h2>浏览器与访问边界</h2><div class="form-grid">
        <label>执行模式<select id="cfg-browser-mode"><option value="managed">托管 Google Chrome</option><option value="cdp">接管现有 Chrome（CDP）</option><option value="remote">远程专属浏览器（暂未实现）</option></select></label>
        <label>Chrome 路径<input id="cfg-browser-executable" placeholder="留空自动探测"></label>
        <label>CDP 地址<input id="cfg-cdp-endpoint" placeholder="http://127.0.0.1:9222"></label>
        <label class="check"><input id="cfg-headless" type="checkbox">无头运行（个人登录态不推荐）</label>
        <label class="check"><input id="cfg-agent-unrestricted-domains" type="checkbox">允许会话申请 <span class="path">*</span> 全域浏览</label>
        <div class="actions"><button id="detect-browser" class="secondary">重新检测浏览器</button></div>
      </div></div>

      <div class="section"><h2>可选基础设施</h2><p class="muted">开发/个人模式默认使用本地 JSON；Redis 只在远程 Worker/队列模式需要。</p><div class="form-grid">
        <label>环境<select id="cfg-environment"><option value="development">本地个人模式</option><option value="production">生产部署</option></select></label>
        <label>运行目录<input id="cfg-runtime-dir"></label>
        <label>PostgreSQL DSN<input id="secret-database-url" type="password" placeholder="可选；留空保持原值"><small id="configured-database-url" class="hint"></small></label>
        <label>Redis URL<input id="secret-redis-url" type="password" placeholder="可选；留空保持原值"><small id="configured-redis-url" class="hint"></small></label>
        <label>Profile 目录<input id="cfg-profiles-dir"></label>
        <label>Artifact 目录<input id="cfg-artifacts-dir"></label>
      </div><div class="actions"><button id="initialize-database" class="secondary">初始化已配置的 PostgreSQL</button></div></div>

      <div class="section"><h2>安全策略与站点</h2><div class="form-grid">
        <label>购物写操作审批金额<input id="cfg-approval-amount" type="number" min="0" step="0.01"></label>
        <label class="check"><input id="cfg-publish-approval" type="checkbox">发布/改价等写操作必须审批</label>
        <label class="check"><input id="cfg-taobao" type="checkbox">启用淘宝工作流</label>
        <label class="check"><input id="cfg-jd" type="checkbox">启用京东工作流</label>
        <label class="check"><input id="cfg-xianyu" type="checkbox">启用咸鱼工作流</label>
      </div></div>

      <div class="section"><h2>旧内置 Agent 兼容（可选）</h2><p class="muted">外部 MCP 智能体不需要模型配置。只有继续调用旧 <span class="path">butler_message</span> 入口时才启用。</p><div class="form-grid">
        <label class="check"><input id="cfg-agent-enabled" type="checkbox">启用旧内置 Agent</label>
        <label>后端<select id="cfg-agent-backend"><option value="local">本地确定性后端</option><option value="browser_use">Browser Use</option></select></label>
        <label>最大步骤<input id="cfg-agent-max-steps" type="number" min="1" max="500"></label>
        <label>最长运行秒数<input id="cfg-agent-max-duration" type="number" min="1" max="14400"></label>
        <label>模型供应商<input id="cfg-model-provider"></label>
        <label>Base URL<input id="cfg-model-base-url"></label>
        <label>模型名<input id="cfg-model-name"></label>
        <label>API Key<input id="secret-model-api-key" type="password" placeholder="可选；留空保持原值"><small id="configured-model-api-key" class="hint"></small></label>
      </div></div>

      <div class="actions"><button id="save-settings">保存高级设置</button></div>
      <pre id="settings-output">高级诊断信息</pre>
    </div>
  </details>
  <footer>WebAuto 配置中心 · 本页不创建任务、不保存网站账号密码</footer>
</main>
<script>
const API='/v1';
const CSRF_TOKEN="__WEBAUTO_CSRF_TOKEN__";
const byId=id=>document.getElementById(id);
const setValue=(id,value)=>{byId(id).value=value??''};
const setCheck=(id,value)=>{byId(id).checked=Boolean(value)};
const show=(id,value)=>{byId(id).textContent=typeof value==='string'?value:JSON.stringify(value,null,2)};
async function request(path,options={}){
  const method=(options.method||'GET').toUpperCase();
  const headers={'content-type':'application/json',...(options.headers||{})};
  if(!['GET','HEAD','OPTIONS'].includes(method))headers['x-webauto-csrf-token']=CSRF_TOKEN;
  const response=await fetch(API+path,{credentials:'same-origin',...options,headers});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||response.statusText);
  return data;
}
function secretState(settings){
  Object.entries(settings.secrets||{}).forEach(([key,value])=>{
    const target=byId('configured-'+key.replaceAll('_','-'));
    if(target)target.textContent=value?'已加密配置；留空保持原值':'未配置（本机模式可选）';
  });
}
function readiness(settings){
  const ready=Boolean(settings.setup_complete);
  byId('prepare-badge').textContent=ready?'已准备':'待准备';
  byId('prepare-badge').className='badge '+(ready?'good':'warn');
  show('prepare-output',{setup_complete:ready,browser_mode:settings.browser.mode,account_login:'在专属 Chrome 内完成',persistence:settings.secrets.database_url?'PostgreSQL':'本地 JSON',redis:settings.secrets.redis_url?'已配置':'本机模式不需要'});
}
async function loadSettings(){
  const s=await request('/settings');
  setValue('cfg-environment',s.environment);setValue('cfg-runtime-dir',s.runtime_dir);
  setValue('cfg-browser-mode',s.browser.mode);setValue('cfg-browser-executable',s.browser.executable);
  setValue('cfg-cdp-endpoint',s.browser.cdp_endpoint);setCheck('cfg-headless',s.browser.headless);
  setValue('cfg-model-provider',s.model.provider);setValue('cfg-model-base-url',s.model.base_url);setValue('cfg-model-name',s.model.model);
  const a=s.browser_agent||{backend:'local',enabled:false,allow_unrestricted_domains:false,max_steps:50,max_duration_seconds:1200};
  setCheck('cfg-agent-enabled',a.enabled);setValue('cfg-agent-backend',a.backend);setValue('cfg-agent-max-steps',a.max_steps);
  setValue('cfg-agent-max-duration',a.max_duration_seconds);setCheck('cfg-agent-unrestricted-domains',a.allow_unrestricted_domains);
  setValue('cfg-profiles-dir',s.storage.profiles_dir);setValue('cfg-artifacts-dir',s.storage.artifacts_dir);
  setValue('cfg-approval-amount',s.policy.purchase_approval_amount);setCheck('cfg-publish-approval',s.policy.publish_requires_approval);
  setCheck('cfg-taobao',s.sites.taobao);setCheck('cfg-jd',s.sites.jd);setCheck('cfg-xianyu',s.sites.xianyu);
  secretState(s);readiness(s);return s;
}
function configPayload(){
  const secretPairs=[['database_url','secret-database-url'],['redis_url','secret-redis-url'],['model_api_key','secret-model-api-key']];
  return{settings:{
    environment:byId('cfg-environment').value,runtime_dir:byId('cfg-runtime-dir').value,
    browser:{mode:byId('cfg-browser-mode').value,executable:byId('cfg-browser-executable').value,cdp_endpoint:byId('cfg-cdp-endpoint').value,headless:byId('cfg-headless').checked},
    model:{provider:byId('cfg-model-provider').value,base_url:byId('cfg-model-base-url').value,model:byId('cfg-model-name').value},
    browser_agent:{enabled:byId('cfg-agent-enabled').checked,backend:byId('cfg-agent-backend').value,max_steps:Number(byId('cfg-agent-max-steps').value||50),max_duration_seconds:Number(byId('cfg-agent-max-duration').value||1200),allow_unrestricted_domains:byId('cfg-agent-unrestricted-domains').checked},
    storage:{profiles_dir:byId('cfg-profiles-dir').value,artifacts_dir:byId('cfg-artifacts-dir').value},
    policy:{purchase_approval_amount:Number(byId('cfg-approval-amount').value||0),publish_requires_approval:byId('cfg-publish-approval').checked},
    sites:{taobao:byId('cfg-taobao').checked,jd:byId('cfg-jd').checked,xianyu:byId('cfg-xianyu').checked}
  },secrets:Object.fromEntries(secretPairs.filter(([,id])=>byId(id).value).map(([key,id])=>[key,byId(id).value]))};
}
async function loadMcp(){
  try{
    const value=await request('/settings/mcp-client-config');
    show('mcp-json',value.generic_json);show('mcp-codex',value.codex_toml);
    byId('mcp-tool-count').textContent=String(value.tool_count)+' 个 Agent 工具';
    show('mcp-output',{mode:value.mode,transport:value.transport,server:value.server,authentication:value.authentication,requirements:value.requirements});
  }catch(error){show('mcp-output',{error:error.message,action:'刷新本页面后重试'})}
}
async function copyText(id){
  const value=byId(id).textContent;
  try{await navigator.clipboard.writeText(value)}catch(error){show('mcp-output',{error:'复制失败，请手动选择文本',detail:error.message})}
}
byId('prepare-local').onclick=async()=>{
  const button=byId('prepare-local');button.disabled=true;
  try{const result=await request('/settings/prepare-local',{method:'POST'});show('prepare-output',result);await loadSettings();await loadMcp()}catch(error){show('prepare-output',{error:error.message})}finally{button.disabled=false}
};
byId('copy-json').onclick=()=>copyText('mcp-json');
byId('copy-codex').onclick=()=>copyText('mcp-codex');
byId('save-settings').onclick=async()=>{
  try{const result=await request('/settings',{method:'PUT',body:JSON.stringify(configPayload())});['secret-database-url','secret-redis-url','secret-model-api-key'].forEach(id=>setValue(id,''));show('settings-output',result);await loadSettings()}catch(error){show('settings-output',{error:error.message})}
};
byId('test-settings').onclick=async()=>{try{const result=await request('/settings/test',{method:'POST'});show('prepare-output',result);show('settings-output',result)}catch(error){show('prepare-output',{error:error.message})}};
byId('detect-browser').onclick=async()=>{try{const result=await request('/settings/detect-browser');if(result.browsers&&result.browsers.length)setValue('cfg-browser-executable',result.browsers[0].executable);show('settings-output',result)}catch(error){show('settings-output',{error:error.message})}};
byId('initialize-database').onclick=async()=>{if(!confirm('确认初始化已在高级设置中配置的 PostgreSQL？'))return;try{show('settings-output',await request('/settings/initialize-database',{method:'POST'}))}catch(error){show('settings-output',{error:error.message})}};
async function boot(){
  try{const value=await request('/health');byId('health-text').textContent=value.status==='ok'?'服务运行中':'服务异常';byId('health-dot').classList.toggle('ok',value.status==='ok')}catch(error){byId('health-text').textContent='服务不可达'}
  try{await loadSettings()}catch(error){show('prepare-output',{error:error.message,action:'刷新本页面以重新建立本机会话'})}
  await loadMcp();
}
boot();
</script>
</body>
</html>
"""


def render_dashboard(csrf_token: str) -> str:
    """Render the local-only page without exposing the setup or MCP bearer tokens."""

    return DASHBOARD_HTML.replace('"__WEBAUTO_CSRF_TOKEN__"', json.dumps(csrf_token))


__all__ = ["DASHBOARD_HTML", "render_dashboard"]