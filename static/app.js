let selectedUser = null;

async function api(path, options={}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function toast(text) {
  const el = document.querySelector('#toast'); el.textContent = text; el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 2200);
}

async function refresh() {
  const [stats, users] = await Promise.all([api('/api/dashboard'), api('/api/users')]);
  const labels = [['users','用户'],['active','订阅中'],['messages','消息'],['pushes','已推送']];
  document.querySelector('#stats').innerHTML = labels.map(([k,l])=>`<div class="stat"><strong>${stats[k]}</strong><span>${l}</span></div>`).join('') + `<div class="stat"><strong>${stats.model_configured?'已连接':'Demo'}</strong><span>模型状态</span></div>`;
  document.querySelector('#users').innerHTML = users.map(u=>`<button class="user ${selectedUser?.id===u.id?'active':''}" data-id="${u.id}"><div><b>${u.name}</b><small>${u.channel_user_id}</small></div><span class="badge ${u.subscription_status}">${statusLabel(u.subscription_status)}</span></button>`).join('') || '<p style="padding:16px;color:#69736c">还没有测试用户</p>';
  document.querySelectorAll('.user').forEach(el=>el.onclick=()=>selectUser(Number(el.dataset.id)));
  if (selectedUser) {
    selectedUser = users.find(u=>u.id===selectedUser.id) || null;
    if (selectedUser) await renderChat();
  }
}

function statusLabel(status){return {pending:'未订阅',active:'订阅中',paused:'已暂停',unsubscribed:'已退订'}[status]||status}

async function selectUser(id){
  const users=await api('/api/users'); selectedUser=users.find(u=>u.id===id); await refresh();
}

async function renderChat(){
  document.querySelector('#empty').hidden=true; document.querySelector('#chat').hidden=false;
  document.querySelector('#chatName').textContent=selectedUser.name;
  document.querySelector('#chatStatus').textContent=`${statusLabel(selectedUser.subscription_status)} · 难度 ${selectedUser.difficulty}`;
  const messages=await api(`/api/users/${selectedUser.id}/messages`);
  const box=document.querySelector('#messages');
  box.innerHTML=messages.map(m=>`<div class="message ${m.direction}">${escapeHtml(m.text)}<time>${m.direction==='in'?'用户':'Agent'} · ${m.created_at}</time></div>`).join('');
  box.scrollTop=box.scrollHeight;
}

function escapeHtml(text){const d=document.createElement('div');d.textContent=text;return d.innerHTML}

document.querySelector('#addUser').onclick=async()=>{
  const n=Date.now().toString().slice(-5);
  await api('/api/users',{method:'POST',body:JSON.stringify({name:`测试用户 ${n}`,channel_user_id:`wx_demo_${n}`})});
  toast('已添加测试用户并发送欢迎语'); await refresh();
};

document.querySelector('#messageForm').onsubmit=async e=>{
  e.preventDefault(); if(!selectedUser)return;
  const input=document.querySelector('#messageInput'); const text=input.value.trim(); if(!text)return;
  input.value=''; await api(`/api/users/${selectedUser.id}/messages`,{method:'POST',body:JSON.stringify({text})}); await refresh();
};

document.querySelectorAll('.quick button').forEach(b=>b.onclick=()=>{document.querySelector('#messageInput').value=b.dataset.text;document.querySelector('#messageForm').requestSubmit()});
document.querySelector('#pushOne').onclick=async()=>{await api(`/api/users/${selectedUser.id}/push`,{method:'POST',body:'{}'});toast('知识点已推送');await refresh()};
document.querySelector('#runPush').onclick=async()=>{const r=await api('/api/push/run',{method:'POST',body:'{}'});toast(`已向 ${r.sent} 位订阅用户推送`);await refresh()};

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
  document.querySelector('#callbackUrl').textContent=`https://你的域名${config.callback_path}`;
  wecomDialog.showModal();
}

document.querySelector('#openWecom').onclick=()=>openWecomConfig().catch(e=>toast(e.message));
document.querySelector('#closeWecom').onclick=()=>wecomDialog.close();
document.querySelector('#cancelWecom').onclick=()=>wecomDialog.close();
wecomForm.onsubmit=async e=>{
  e.preventDefault(); const body={};
  ['corp_id','agent_id','test_user_id',...sensitiveFields].forEach(name=>{
    const input=wecomForm.elements[name]; if(!input.disabled && input.value.trim()) body[name]=input.value.trim();
  });
  await api('/api/config/wecom',{method:'POST',body:JSON.stringify(body)});
  wecomDialog.close(); toast('企业微信配置已保存');
};

refresh().catch(e=>toast(e.message));
