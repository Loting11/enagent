let selectedUser = null;
let state = {stats:{}, users:[], products:[], content:[], subscriptions:[], messages:[]};
let editingContentId = null;

function errorMessage(error) {
  return error?.message || String(error || '操作失败');
}

window.addEventListener('unhandledrejection', event => {
  event.preventDefault();
  toast(errorMessage(event.reason));
});

window.addEventListener('error', event => {
  if (event.message) toast(event.message);
});

async function api(path, options={}) {
  const response = await fetch(path, {
    ...options,
    headers: {'Content-Type':'application/json', ...(options.headers || {})}
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    location.href = `/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`;
    throw new Error('请先登录后台');
  }
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function toast(text) {
  const el = document.querySelector('#toast'); el.textContent = text; el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 2200);
}

async function refresh() {
  const [stats, users, products, content] = await Promise.all([
    api('/api/dashboard'), api('/api/users'), api('/api/products'), api('/api/content')
  ]);
  state = {...state, stats, users, products, content};
  if (selectedUser) selectedUser = users.find(u=>u.id===selectedUser.id) || selectedUser;
  renderStats();
  renderActiveView();
}

function renderStats(){
  const labels = [['users','用户'],['products','产品'],['subscriptions','有效订阅'],['pending_content','待审核'],['messages','互动'],['pushes','已推送']];
  document.querySelector('#stats').innerHTML = labels.map(([k,l])=>`<div class="stat"><strong>${state.stats[k]??0}</strong><span>${l}</span></div>`).join('');
}

function renderActiveView(){
  const active = document.querySelector('.ops-nav button.active')?.dataset.view || 'dashboard';
  renderView(active);
}

function setView(name){
  document.querySelectorAll('.ops-nav button').forEach(b=>b.classList.toggle('active', b.dataset.view===name));
  document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==`view-${name}`);
  renderView(name);
}

function renderView(name){
  if(name==='dashboard')return renderDashboard();
  if(name==='users')return renderUsers();
  if(name==='products')return renderProducts();
  if(name==='content')return renderContent();
  if(name==='push')return renderPush();
  if(name==='messages')return renderMessages();
  if(name==='billing')return renderBilling();
}

function renderDashboard(){
  document.querySelector('#view-dashboard').innerHTML=`
    <section class="grid-2">
      <div class="panel"><div class="panel-title"><h2>今日运营</h2></div><div class="panel-body stack">
        <p>当前接入 ${state.users.length} 位用户，${state.stats.subscriptions||0} 条有效订阅。</p>
        <p class="muted">一个微信 OpenClaw bot 可以承载多个 Agent 产品，后台按订阅关系分发内容。</p>
        <div class="row-actions"><button class="primary" id="dashboardPush">执行一次推送</button><button id="dashboardContent">新增知识内容</button></div>
      </div></div>
      <div class="panel"><div class="panel-title"><h2>待处理</h2></div><div class="panel-body stack">
        <p><b>${state.users.filter(u=>u.subscription_status==='pending').length}</b> 位用户待审核</p>
        <p><b>${state.content.filter(c=>c.review_status==='pending').length}</b> 条内容待审核</p>
        <p><b>${state.users.filter(u=>u.subscription_status==='active').length}</b> 位用户可服务</p>
      </div></div>
    </section>`;
  document.querySelector('#dashboardPush').onclick=runPush;
  document.querySelector('#dashboardContent').onclick=()=>openContentEditor();
}

function renderUsers(){
  document.querySelector('#view-users').innerHTML=`
    <section class="grid-2">
      <div class="panel"><div class="panel-title"><h2>用户</h2><button id="addUser">添加测试用户</button></div><div class="panel-body user-list">
        ${state.users.map(u=>`<button class="user-card ${selectedUser?.id===u.id?'active':''}" data-id="${u.id}"><span><b>${escapeHtml(u.name)}</b><small class="muted">${escapeHtml(u.channel_user_id)}</small></span><span class="badge ${u.subscription_status}">${statusLabel(u.subscription_status)}</span></button>`).join('')||'<div class="empty">还没有用户</div>'}
      </div></div>
      <div class="panel"><div class="panel-title"><h2>${selectedUser?escapeHtml(selectedUser.name):'用户详情'}</h2><div class="row-actions">${selectedUser?'<button id="approveUser">通过审核</button><button id="rejectUser">拒绝</button>':''}</div></div><div class="panel-body" id="userDetail">${selectedUser?'加载中':'请选择一个用户'}</div></div>
    </section>`;
  document.querySelectorAll('.user-card').forEach(el=>el.onclick=()=>selectUser(Number(el.dataset.id)));
  document.querySelector('#addUser').onclick=addUser;
  const approve=document.querySelector('#approveUser'); if(approve)approve.onclick=async()=>{const result=await api(`/api/users/${selectedUser.id}/approve`,{method:'POST',body:'{}'});toast(result.warning||'已通过审核');await refresh()};
  const reject=document.querySelector('#rejectUser'); if(reject)reject.onclick=async()=>{const result=await api(`/api/users/${selectedUser.id}/reject`,{method:'POST',body:'{}'});toast(result.warning||'已拒绝');await refresh()};
  if(selectedUser)renderUserDetail();
}

async function renderUserDetail(){
  const [subscriptions, messages]=await Promise.all([api(`/api/users/${selectedUser.id}/subscriptions`),api(`/api/users/${selectedUser.id}/messages`)]);
  state.subscriptions=subscriptions; state.messages=messages;
  document.querySelector('#userDetail').innerHTML=`
    <div class="stack">
      <div><span class="muted">用户 ID</span><br>${escapeHtml(selectedUser.channel_user_id)}</div>
      <div class="grid-2">${state.products.map(p=>subscriptionCard(p, subscriptions.find(s=>s.product_key===p.product_key))).join('')}</div>
      <form id="messageForm" class="composer"><input id="messageInput" placeholder="模拟微信消息：来一个英语 / 今日早报 / 下一个"><button class="primary">发送</button></form>
      <div class="quick">${['来一个英语','今日早报','下一个','暂停早报','A'].map(t=>`<button data-text="${t}">${t}</button>`).join('')}</div>
      <div class="messages">${messages.slice(-12).map(m=>`<div class="message ${m.direction}">${escapeHtml(m.text)}<time>${m.direction==='in'?'用户':'Agent'} · ${m.created_at}</time></div>`).join('')||'<div class="empty">暂无互动</div>'}</div>
    </div>`;
  document.querySelectorAll('[data-open-product]').forEach(b=>b.onclick=async()=>{await api(`/api/users/${selectedUser.id}/subscriptions`,{method:'POST',body:JSON.stringify({product_key:b.dataset.openProduct,days:7})});toast('已开通 7 天试用');await refresh()});
  document.querySelectorAll('[data-push-product]').forEach(b=>b.onclick=async()=>{await api(`/api/users/${selectedUser.id}/push`,{method:'POST',body:JSON.stringify({product_key:b.dataset.pushProduct})});toast('已推送');await refresh()});
  document.querySelectorAll('[data-pause-product]').forEach(b=>b.onclick=async()=>{await api(`/api/users/${selectedUser.id}/subscriptions/${b.dataset.pauseProduct}`,{method:'POST',body:JSON.stringify({status:'paused'})});toast('已暂停');await refresh()});
  document.querySelector('#messageForm').onsubmit=sendMessage;
  document.querySelectorAll('.quick button').forEach(b=>b.onclick=()=>{document.querySelector('#messageInput').value=b.dataset.text;document.querySelector('#messageForm').requestSubmit()});
}

function subscriptionCard(product, sub){
  return `<div class="subscription-card"><div><b>${escapeHtml(product.name)}</b><br><small class="muted">${escapeHtml(product.description||'')}</small></div>${sub?`<span><span class="badge ${sub.status}">${subscriptionLabel(sub.status)}</span> 推送 ${sub.preferred_hour}:00<br><small class="muted">试用至 ${sub.trial_ends_at||'-'} · 付费至 ${sub.paid_until||'-'}</small></span><div class="row-actions"><button data-push-product="${product.product_key}">推送</button><button data-pause-product="${product.product_key}">暂停</button></div>`:`<button class="primary" data-open-product="${product.product_key}">开通 7 天试用</button>`}</div>`;
}

function renderProducts(){
  document.querySelector('#view-products').innerHTML=`<section class="panel"><div class="panel-title"><h2>Agent 产品</h2></div><div class="panel-body"><table class="table"><thead><tr><th>产品</th><th>默认时间</th><th>付费链接</th><th>状态</th></tr></thead><tbody>${state.products.map(p=>`<tr><td><b>${escapeHtml(p.name)}</b><br><span class="muted">${escapeHtml(p.product_key)} · ${escapeHtml(p.description||'')}</span></td><td>${p.default_push_hour}:00</td><td>${p.payment_url?`<a href="${escapeHtml(p.payment_url)}" target="_blank">查看</a>`:'未设置'}</td><td><span class="badge ${p.enabled?'active':'paused'}">${p.enabled?'启用':'停用'}</span></td></tr>`).join('')}</tbody></table></div></section>`;
}

function renderContent(){
  document.querySelector('#view-content').innerHTML=`<section class="panel"><div class="panel-title"><h2>知识库</h2><button class="primary" id="newContent">新增内容</button></div><div class="panel-body grid-3">${state.content.map(c=>`<article class="content-card"><div class="content-meta"><span class="badge ${c.review_status}">${reviewLabel(c.review_status)}</span><span class="badge">${escapeHtml(c.product_name||c.product_key)}</span><span class="badge">${escapeHtml(c.content_type)}</span></div><h3>${escapeHtml(c.term)}</h3><p>${escapeHtml(c.meaning)}</p><small class="muted">${escapeHtml(c.topic)} ${c.source_url?' · 有来源':''}</small><div class="row-actions"><button data-edit-content="${c.id}">编辑</button>${c.review_status!=='approved'?`<button data-approve-content="${c.id}">通过</button>`:''}</div></article>`).join('')}</div></section>`;
  document.querySelector('#newContent').onclick=()=>openContentEditor();
  document.querySelectorAll('[data-edit-content]').forEach(b=>b.onclick=()=>openContentEditor(state.content.find(c=>c.id===Number(b.dataset.editContent))));
  document.querySelectorAll('[data-approve-content]').forEach(b=>b.onclick=async()=>{const item=state.content.find(c=>c.id===Number(b.dataset.approveContent));await saveContent({...item,review_status:'approved'});toast('已通过审核');await refresh()});
}

function renderPush(){
  document.querySelector('#view-push').innerHTML=`<section class="panel"><div class="panel-title"><h2>推送管理</h2><button class="primary" id="runPushNow">执行推送</button></div><div class="panel-body"><p>系统按每条订阅的推送时间执行。手动执行会向所有有效订阅尝试推送一条内容。</p><p class="muted">微信端支持「来一个英语」「今日早报」「下一个」「这个推过了」。</p></div></section>`;
  document.querySelector('#runPushNow').onclick=runPush;
}

function renderMessages(){
  document.querySelector('#view-messages').innerHTML=`<section class="panel"><div class="panel-title"><h2>互动记录</h2></div><div class="panel-body">${selectedUser?'<div id="messageOnly"></div>':'请先在用户管理中选择一个用户。'}</div></section>`;
  if(selectedUser)api(`/api/users/${selectedUser.id}/messages`).then(messages=>{document.querySelector('#messageOnly').innerHTML=`<div class="messages">${messages.slice(-30).map(m=>`<div class="message ${m.direction}">${escapeHtml(m.text)}<time>${m.direction==='in'?'用户':'Agent'} · ${m.created_at}</time></div>`).join('')}</div>`});
}

function renderBilling(){
  document.querySelector('#view-billing').innerHTML=`<section class="panel"><div class="panel-title"><h2>收费权益</h2></div><div class="panel-body stack"><p>第一版先做权益占位：每个产品可配置付费链接，用户订阅可设置试用、付费、暂停或过期。</p><p>默认试用期：7 天。真实支付后，把支付成功回调接到订阅权益更新即可。</p></div></section>`;
}

function statusLabel(status){return {pending:'待审核',active:'可服务',paused:'已暂停',unsubscribed:'已退订'}[status]||status}
function subscriptionLabel(status){return {trial:'试用',paid:'已付费',active:'有效',paused:'已暂停',expired:'已过期'}[status]||status}
function reviewLabel(status){return {pending:'待审核',approved:'已通过',rejected:'已拒绝'}[status]||status}
async function selectUser(id){selectedUser=state.users.find(u=>u.id===id);setView('users')}
function escapeHtml(text){const d=document.createElement('div');d.textContent=text??'';return d.innerHTML}
async function addUser(){const n=Date.now().toString().slice(-5);await api('/api/users',{method:'POST',body:JSON.stringify({name:`测试用户 ${n}`,channel_user_id:`wx_demo_${n}`})});toast('已添加测试用户');await refresh()}
async function sendMessage(e){e.preventDefault();const input=document.querySelector('#messageInput');const text=input.value.trim();if(!text)return;input.value='';await api(`/api/users/${selectedUser.id}/messages`,{method:'POST',body:JSON.stringify({text})});await refresh()}
async function runPush(){const r=await api('/api/push/run',{method:'POST',body:'{}'});toast(`已推送 ${r.sent} 条订阅内容`);await refresh()}
document.querySelectorAll('.ops-nav button').forEach(b=>b.onclick=()=>setView(b.dataset.view));
document.querySelector('#runPush').onclick=runPush;
document.querySelector('#logout').onclick=async()=>{await fetch('/api/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});location.href='/login'};

const contentDialog=document.querySelector('#contentDialog');
const contentForm=document.querySelector('#contentForm');
function openContentEditor(item=null){
  editingContentId=item?.id||null;
  contentForm.elements.product_key.innerHTML=state.products.map(p=>`<option value="${p.product_key}">${escapeHtml(p.name)}</option>`).join('');
  const defaults={product_key:'ai_english',content_type:'knowledge_card',term:'',meaning:'',explanation:'',example_en:'',example_cn:'',question:'',options:'A. 已理解\nB. 不确定\nC. 稍后再看',answer:'A',difficulty:'1',topic:'General',review_status:'pending',enabled:'1',source_url:''};
  const data=item?{...item,options:JSON.parse(item.options_json||'[]').join('\n')}:defaults;
  Object.keys(defaults).forEach(k=>{if(contentForm.elements[k])contentForm.elements[k].value=data[k]??defaults[k]});
  contentDialog.showModal();
}
async function saveContent(data){
  const body={...data};
  if(body.options_json&&!body.options)body.options=JSON.parse(body.options_json).join('\n');
  const path=body.id?`/api/content/${body.id}`:'/api/content';
  return api(path,{method:'POST',body:JSON.stringify(body)});
}
document.querySelector('#closeContent').onclick=()=>contentDialog.close();
document.querySelector('#cancelContent').onclick=()=>contentDialog.close();
contentForm.onsubmit=async e=>{
  e.preventDefault();
  const body={};
  Array.from(contentForm.elements).forEach(el=>{if(el.name)body[el.name]=el.value});
  if(editingContentId)body.id=editingContentId;
  await saveContent(body);
  contentDialog.close();toast('知识内容已保存');await refresh();
};

const wecomDialog=document.querySelector('#wecomDialog');
const wecomForm=document.querySelector('#wecomForm');
const sensitiveFields=['secret','token','encoding_aes_key'];

async function openWecomConfig(){
  const config=await api('/api/config/wecom');
  ['corp_id','agent_id','test_user_id'].forEach(name=>wecomForm.elements[name].value=config[name]||'');
  sensitiveFields.forEach(name=>{
    const input=wecomForm.elements[name]; input.value='';
    input.placeholder=config[`${name}_configured`]?'已保存；留空表示不修改':'尚未配置';
    document.querySelector(`[data-status="${name}"]`).textContent=config[`${name}_configured`]?'✓ 已安全保存':'';
  });
  const secure=location.protocol==='https:';
  const notice=document.querySelector('#securityNotice');
  notice.textContent=secure?'当前为 HTTPS 安全连接，可以填写全部配置。':'当前为 HTTP：为避免密钥泄露，Secret、Token 和 AESKey 暂不可提交；域名 HTTPS 配置后会自动开放。';
  notice.className=`notice ${secure?'safe':'warning'}`;
  sensitiveFields.forEach(name=>wecomForm.elements[name].disabled=!secure);
  document.querySelector('#wecomStatus').innerHTML=`<span class="${config.callback_ready?'ready':''}">${config.callback_ready?'✓':'○'} 回调配置</span><span class="${config.send_ready?'ready':''}">${config.send_ready?'✓':'○'} 主动发送</span>`;
  document.querySelector('#callbackUrl').textContent=secure?`${location.origin}${config.callback_path}`:`https://你的域名${config.callback_path}`;
  const testButton=document.querySelector('#testWecom');
  testButton.disabled=!secure||!config.send_ready||!config.test_user_id;
  testButton.title=!secure?'请先启用 HTTPS':(!config.send_ready?'请先完成应用配置':'');
  wecomDialog.showModal();
}

document.querySelector('#openWecom').onclick=()=>openWecomConfig().catch(e=>toast(e.message));
document.querySelector('#closeWecom').onclick=()=>wecomDialog.close();
document.querySelector('#cancelWecom').onclick=()=>wecomDialog.close();
document.querySelector('#testWecom').onclick=async()=>{
  await api('/api/config/wecom/test',{method:'POST',body:'{}'});
  toast('测试消息已发送到企微');
};
wecomForm.onsubmit=async e=>{
  e.preventDefault(); const body={};
  ['corp_id','agent_id','test_user_id',...sensitiveFields].forEach(name=>{
    const input=wecomForm.elements[name]; if(!input.disabled && input.value.trim()) body[name]=input.value.trim();
  });
  await api('/api/config/wecom',{method:'POST',body:JSON.stringify(body)});
  wecomDialog.close(); toast('企业微信配置已保存');
};

const juheDialog=document.querySelector('#juheDialog');
const juheForm=document.querySelector('#juheForm');

async function openJuheConfig(){
  const config=await api('/api/config/juhe');
  ['api_url','app_key','guid'].forEach(name=>juheForm.elements[name].value=config[name]||'');
  const secret=juheForm.elements.app_secret; secret.value='';
  secret.placeholder=config.app_secret_configured?'已保存；留空表示不修改':'尚未配置';
  document.querySelector('[data-juhe-status="app_secret"]').textContent=config.app_secret_configured?'✓ 已安全保存':'';
  const privateCdn=juheForm.elements.private_cdn_url; privateCdn.value='';
  privateCdn.placeholder=config.private_cdn_url_configured?'已保存；留空表示不修改':'由供应商提供，语音功能必需';
  document.querySelector('[data-juhe-status="private_cdn_url"]').textContent=config.private_cdn_url_configured?'✓ 已安全保存':'';
  const secure=location.protocol==='https:';
  const notice=document.querySelector('#juheSecurityNotice');
  notice.textContent=secure?'当前为 HTTPS 安全连接。配置只保存在服务器，不会写入代码仓库。':'当前为 HTTP，已禁止提交 App Secret。';
  notice.className=`notice ${secure?'safe':'warning'}`;
  secret.disabled=!secure;
  privateCdn.disabled=!secure;
  document.querySelector('#juheStatus').innerHTML=`<span class="${config.callback_ready?'ready':''}">${config.callback_ready?'✓':'○'} 回调入口</span><span class="${config.send_ready?'ready':''}">${config.send_ready?'✓':'○'} 文本发送</span><span class="${config.voice_ready?'ready':''}">${config.voice_ready?'✓':'○'} 语音发送</span>`;
  document.querySelector('#juheCallbackUrl').textContent=secure?`${location.origin}${config.callback_path}`:`https://你的域名${config.callback_path}`;
  const test=document.querySelector('#testJuhe');
  test.disabled=!secure||!config.send_ready;
  test.title=!secure?'请先启用 HTTPS':(!config.send_ready?'请先保存全部配置':'');
  const register=document.querySelector('#registerJuheCallback');
  register.disabled=!secure||!config.send_ready||!config.callback_ready;
  register.title=!config.callback_ready?'请先保存配置以生成安全回调地址':'';
  juheDialog.showModal();
}

document.querySelector('#openJuhe').onclick=()=>openJuheConfig().catch(e=>toast(e.message));
document.querySelector('#closeJuhe').onclick=()=>juheDialog.close();
document.querySelector('#cancelJuhe').onclick=()=>juheDialog.close();
document.querySelector('#testJuhe').onclick=async()=>{
  await api('/api/config/juhe/test',{method:'POST',body:'{}'});
  toast('开放平台凭证和设备实例有效');
};
document.querySelector('#registerJuheCallback').onclick=async()=>{
  await api('/api/config/juhe/callback/register',{method:'POST',body:'{}'});
  toast('供应商实例通知地址已配置');
};
juheForm.onsubmit=async e=>{
  e.preventDefault(); const body={};
  ['api_url','app_key','guid','app_secret','private_cdn_url'].forEach(name=>{
    const input=juheForm.elements[name]; if(!input.disabled && input.value.trim()) body[name]=input.value.trim();
  });
  await api('/api/config/juhe',{method:'POST',body:JSON.stringify(body)});
  juheDialog.close(); toast('聚合聊天配置已保存');
};

const openclawDialog=document.querySelector('#openclawDialog');
const openclawForm=document.querySelector('#openclawForm');
let openclawLoginTimer=null;

function cleanTerminalOutput(output){
  return String(output||'').replace(/\x1B\[[0-?]*[ -/]*[@-~]/g,'').replace(/\r/g,'');
}

function extractTerminalQr(output){
  const groups=[];
  let group=[];
  const finish=()=>{if(group.length>=4)groups.push(group);group=[];};
  cleanTerminalOutput(output).split('\n').forEach(line=>{
    const isQrLine=/^[█▀▄ ]+$/.test(line)&&/[█▀▄]/.test(line)&&line.length>=12;
    if(isQrLine)group.push(line); else finish();
  });
  finish();
  const best=groups.sort((a,b)=>b.length-a.length)[0];
  return best?best.join('\n'):'';
}

function renderOpenclawLogin(result){
  const panel=document.querySelector('#openclawOutputPanel');
  const qrPanel=document.querySelector('#openclawQrPanel');
  const qr=document.querySelector('#openclawQr');
  const logs=document.querySelector('#openclawLogDetails');
  const output=document.querySelector('#openclawOutput');
  const title=document.querySelector('#openclawOutputTitle');
  const hint=document.querySelector('#openclawOutputHint');
  const text=cleanTerminalOutput(result.output);
  const qrText=extractTerminalQr(text);
  panel.hidden=false;
  panel.classList.toggle('is-running', !!result.running);
  openclawDialog.classList.toggle('is-scanning', !!qrText);
  qrPanel.hidden=!qrText;
  qr.textContent=qrText;
  logs.open=!qrText;
  title.textContent=qrText?'微信扫码绑定':'二维码输出';
  hint.textContent=qrText?'请使用微信扫描上方二维码':(result.running?'二维码生成中，请稍候':'OpenClaw 输出结果');
  output.textContent=text||'等待 OpenClaw 输出二维码…';
  output.scrollTop=0;
  output.scrollLeft=0;
  if(qrText)requestAnimationFrame(()=>panel.scrollIntoView({block:'start',behavior:'smooth'}));
  if(!result.running&&openclawLoginTimer){
    clearInterval(openclawLoginTimer);openclawLoginTimer=null;
  }
}

async function pollOpenclawLogin(){
  try{renderOpenclawLogin(await api('/api/config/openclaw/login'));}
  catch(error){
    document.querySelector('#openclawOutputPanel').hidden=false;
    document.querySelector('#openclawOutputPanel').classList.remove('is-running');
    openclawDialog.classList.remove('is-scanning');
    document.querySelector('#openclawQrPanel').hidden=true;
    document.querySelector('#openclawLogDetails').open=true;
    document.querySelector('#openclawOutputHint').textContent='OpenClaw 输出结果';
    document.querySelector('#openclawOutput').textContent=error.message;
  }
}

async function openOpenclawConfig(){
  const config=await api('/api/config/openclaw');
  ['cli_path','channel','account_id','bot_name'].forEach(name=>openclawForm.elements[name].value=config[name]||'');
  openclawForm.elements.enabled.value=config.enabled?'true':'false';
  document.querySelector('#openclawStatus').innerHTML=`<span class="${config.cli_ready?'ready':''}">${config.cli_ready?'✓':'○'} OpenClaw CLI</span><span class="${config.callback_ready?'ready':''}">${config.callback_ready?'✓':'○'} 回调令牌</span><span class="${config.send_ready?'ready':''}">${config.send_ready?'✓':'○'} 主动发送</span>`;
  renderOpenclawAccounts(config.accounts||[]);
  document.querySelector('#openclawCallbackUrl').textContent=config.callback_url;
  document.querySelector('#openclawOutputPanel').hidden=true;
  openclawDialog.classList.remove('is-scanning');
  document.querySelector('#openclawQrPanel').hidden=true;
  document.querySelector('#openclawLogDetails').open=false;
  document.querySelector('#openclawOutputPanel').classList.remove('is-running');
  document.querySelector('#openclawOutputTitle').textContent='二维码输出';
  document.querySelector('#openclawOutputHint').textContent='请用微信扫码完成绑定';
  document.querySelector('#startOpenclawLogin').disabled=!config.cli_ready;
  document.querySelector('#startOpenclawLogin').title=config.cli_ready?'':'服务器未安装 OpenClaw，暂时不能生成二维码';
  openclawDialog.showModal();
}

function renderOpenclawAccounts(accounts){
  const box=document.querySelector('#openclawAccounts');
  box.innerHTML=accounts.length?accounts.map(account=>`<div class="account-row"><div><b>${escapeHtml(account.name||account.account_id)}</b>${account.is_default?'<span class="badge active">默认</span>':''}<small>${escapeHtml(account.account_id)} · ${escapeHtml(account.channel)}</small></div><div class="row-actions"><button type="button" data-use-account="${escapeHtml(account.account_id)}">填入</button><button type="button" data-default-account="${escapeHtml(account.account_id)}">设默认</button></div></div>`).join(''):'<div class="empty">还没有保存微信 bot 账号。扫码后把账号 ID 保存到这里。</div>';
  box.querySelectorAll('[data-use-account]').forEach(button=>button.onclick=()=>{
    const account=accounts.find(item=>item.account_id===button.dataset.useAccount);
    if(!account)return;
    openclawForm.elements.account_id.value=account.account_id;
    openclawForm.elements.bot_name.value=account.name||'';
    openclawForm.elements.channel.value=account.channel||'openclaw-weixin';
  });
  box.querySelectorAll('[data-default-account]').forEach(button=>button.onclick=async()=>{
    await api(`/api/config/openclaw/accounts/${encodeURIComponent(button.dataset.defaultAccount)}`,{method:'POST',body:'{}'});
    toast('默认微信 bot 已更新');
    await openOpenclawConfig();
  });
}

document.querySelector('#openOpenclaw').onclick=()=>openOpenclawConfig().catch(e=>toast(e.message));
document.querySelector('#closeOpenclaw').onclick=()=>openclawDialog.close();
document.querySelector('#cancelOpenclaw').onclick=()=>openclawDialog.close();
document.querySelector('#startOpenclawLogin').onclick=async()=>{
  const accountId=openclawForm.elements.account_id.value.trim();
  renderOpenclawLogin(await api('/api/config/openclaw/login/start',{method:'POST',body:JSON.stringify({account_id:accountId})}));
  if(openclawLoginTimer)clearInterval(openclawLoginTimer);
  openclawLoginTimer=setInterval(pollOpenclawLogin,1600);
};
document.querySelector('#saveOpenclawAccount').onclick=async()=>{
  const accountId=openclawForm.elements.account_id.value.trim();
  if(!accountId)return toast('请先填写微信账号 ID');
  await api('/api/config/openclaw/accounts',{method:'POST',body:JSON.stringify({
    account_id:accountId,
    name:openclawForm.elements.bot_name.value.trim()||accountId,
    channel:openclawForm.elements.channel.value.trim()||'openclaw-weixin',
    enabled:true,
    is_default:false
  })});
  toast('微信 bot 账号已保存');
  await openOpenclawConfig();
};
document.querySelector('#stopOpenclawLogin').onclick=async()=>{
  renderOpenclawLogin(await api('/api/config/openclaw/login/stop',{method:'POST',body:'{}'}));
  if(openclawLoginTimer){clearInterval(openclawLoginTimer);openclawLoginTimer=null;}
};
document.querySelector('#checkOpenclaw').onclick=async()=>{
  const panel=document.querySelector('#openclawOutputPanel');
  const qrPanel=document.querySelector('#openclawQrPanel');
  const logs=document.querySelector('#openclawLogDetails');
  const output=document.querySelector('#openclawOutput');
  panel.hidden=false; panel.classList.add('is-running'); qrPanel.hidden=true; logs.open=true; openclawDialog.classList.remove('is-scanning');
  document.querySelector('#openclawOutputTitle').textContent='状态检查';
  document.querySelector('#openclawOutputHint').textContent='正在检查 OpenClaw 状态';
  output.textContent='正在检查 OpenClaw 状态…';
  try{
    const result=await api('/api/config/openclaw/status',{method:'POST',body:'{}'});
    panel.classList.remove('is-running');
    document.querySelector('#openclawOutputTitle').textContent='状态检查';
    document.querySelector('#openclawOutputHint').textContent='OpenClaw 输出结果';
    output.textContent=result.output||'OpenClaw 状态正常';
  }catch(error){
    panel.classList.remove('is-running');
    document.querySelector('#openclawOutputTitle').textContent='状态检查';
    document.querySelector('#openclawOutputHint').textContent='OpenClaw 输出结果';
    output.textContent=error.message;
  }
};
openclawForm.onsubmit=async e=>{
  e.preventDefault(); const body={};
  ['enabled','cli_path','channel','account_id','bot_name'].forEach(name=>{
    const input=openclawForm.elements[name]; body[name]=input.value.trim();
  });
  await api('/api/config/openclaw',{method:'POST',body:JSON.stringify(body)});
  openclawDialog.close(); toast('OpenClaw 微信入口配置已保存');
};

refresh().catch(e=>toast(e.message));
