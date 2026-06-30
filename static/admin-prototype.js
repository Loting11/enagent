const pageTitles = {overview:'总览',delivery:'推送规则',audience:'用户与分群',knowledge:'知识库',prompt:'提示词与模型',voice:'语音与发音',channel:'渠道与系统'};
const toast = document.querySelector('#prototypeToast');

async function api(path, options={}){
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  const data=await response.json().catch(()=>({}));
  if(response.status===401){
    location.href=`/login?next=${encodeURIComponent(location.pathname+location.search+location.hash)}`;
    throw new Error('请先登录后台');
  }
  if(!response.ok)throw new Error(data.error||'请求失败');
  return data;
}

function showToast(message){
  toast.textContent=message;toast.classList.add('show');
  clearTimeout(window.prototypeToastTimer);
  window.prototypeToastTimer=setTimeout(()=>toast.classList.remove('show'),2200);
}

function openPage(name){
  document.querySelectorAll('.page').forEach(page=>page.classList.toggle('active',page.id===`page-${name}`));
  document.querySelectorAll('.nav-item').forEach(item=>item.classList.toggle('active',item.dataset.page===name));
  document.querySelector('#pageCrumb').textContent=pageTitles[name]||name;
  history.replaceState(null,'',`#${name}`);
  window.scrollTo({top:0,behavior:'smooth'});
}

document.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>openPage(button.dataset.page));
document.querySelectorAll('[data-go]').forEach(button=>button.onclick=()=>openPage(button.dataset.go));
const initial=location.hash.slice(1);if(pageTitles[initial])openPage(initial);

document.querySelector('#themeSelect').onchange=e=>{
  document.documentElement.dataset.theme=e.target.value;
  localStorage.setItem('enagent-prototype-theme',e.target.value);
};
const savedTheme=localStorage.getItem('enagent-prototype-theme');
if(savedTheme){document.documentElement.dataset.theme=savedTheme;document.querySelector('#themeSelect').value=savedTheme;}

document.querySelectorAll('.choice').forEach(choice=>choice.onclick=()=>{
  document.querySelectorAll('.choice').forEach(item=>item.classList.remove('active'));
  choice.classList.add('active');choice.querySelector('input').checked=true;
});

const dialog=document.querySelector('#prototypeDialog');
function showDialog(title,text){document.querySelector('#dialogTitle').textContent=title;document.querySelector('#dialogText').textContent=text;dialog.showModal();}
document.querySelector('#closeDialog').onclick=()=>dialog.close();
document.querySelector('#publishGlobal').onclick=()=>showDialog('3 项草稿已准备发布','正式系统中，这一步会展示变更摘要和受影响用户，确认后再生效。');
document.querySelector('#previewGlobal').onclick=()=>{openPage('delivery');showToast('已打开用户视角预览');};
document.querySelector('#backToConsole').onclick=()=>{location.href='/';};
document.querySelector('#publishRule').onclick=async()=>{
  try{await saveVoiceSettings({fromDelivery:true});showDialog('推送规则已发布','新的规则将在下一次计划任务执行时生效；语音将按当前策略紧跟文字知识点发送。');}
  catch(error){showToast(error.message);}
};
document.querySelector('#sendTest').onclick=()=>showDialog('测试消息已发送','草稿内容已发送到指定测试账号，不影响真实用户的学习记录。');
document.querySelector('#refreshPreview').onclick=()=>showToast('已按当前规则抽取另一条内容');
document.querySelector('#importKnowledge').onclick=()=>showDialog('导入知识库','支持 Excel、CSV、Word、PDF 和网页链接。正式开发时会先进入解析预览，再由你确认入库。');
document.querySelector('#newKnowledge').onclick=()=>showDialog('知识点编辑器','编辑器将包含中英释义、例句、选择题、答案、难度、主题和来源字段。');
document.querySelector('#savePrompt').onclick=()=>showToast('提示词已保存为草稿 v4');
document.querySelector('#publishPrompt').onclick=()=>showDialog('提示词准备发布','正式发布前将自动运行一组回归测试，避免新版本破坏现有回答质量。');

const promptEditor=document.querySelector('#promptEditor');
const charCount=document.querySelector('#charCount');
function updateCount(){charCount.textContent=promptEditor.value.length;}
promptEditor.oninput=updateCount;updateCount();
document.querySelector('#temperature').oninput=e=>document.querySelector('#tempValue').textContent=e.target.value;

const voiceFields={
  provider:'#voiceProvider',api_base:'#voiceApiBase',region:'#voiceRegion',model:'#voiceModel',
  voice_id:'#voiceId',accent:'#voiceAccent',gender:'#voiceGender',speed:'#voiceSpeed',
  pitch:'#voicePitch',instruction:'#voiceInstruction',content_scope:'#deliveryVoiceScope'
};
const voiceEnabled=document.querySelector('#voiceEnabled');
const deliveryVoiceEnabled=document.querySelector('#deliveryVoiceEnabled');

function voiceLabel(config={}){
  const accent=config.accent==='en-GB'?'英音':'美音';
  const gender=config.gender==='male'?'男声':'女声';
  return `${accent} · ${gender}`;
}

function updateVoiceView(){
  const config=Object.fromEntries(Object.entries(voiceFields).map(([key,selector])=>[key,document.querySelector(selector).value]));
  const enabled=deliveryVoiceEnabled.checked;
  voiceEnabled.checked=enabled;
  document.querySelector('#voiceDeliveryFields').setAttribute('aria-disabled',String(!enabled));
  document.querySelector('#deliveryVoicePreview').hidden=!enabled;
  document.querySelector('#voiceSpeedValue').textContent=`${Number(config.speed).toFixed(2).replace(/0$/,'')}×`;
  document.querySelector('#voicePitchValue').textContent=Number(config.pitch)>0?`+${config.pitch}`:config.pitch;
  document.querySelector('#voiceSampleMeta').textContent=`${voiceLabel(config)} · ${Number(config.speed)===1?'标准语速':config.speed+'×'}`;
  document.querySelector('#voicePreviewMeta').textContent=`${voiceLabel(config)} · 约 6 秒`;
  document.querySelector('#deliveryVoiceProfile').textContent=config.voice_id?`${voiceLabel(config)} · ${config.voice_id}`:'尚未完成语音配置';
  const scopes={term_example:'单词＋英文例句',example:'仅英文例句',all_english:'知识点中的全部英文'};
  document.querySelector('#voiceScopeSummary').textContent=scopes[config.content_scope]||scopes.term_example;
}

async function loadVoiceSettings(){
  const config=await api('/api/config/voice');
  Object.entries(voiceFields).forEach(([key,selector])=>{if(config[key]!==undefined)document.querySelector(selector).value=config[key];});
  voiceEnabled.checked=Boolean(config.enabled);deliveryVoiceEnabled.checked=Boolean(config.enabled);
  const key=document.querySelector('#voiceApiKey');
  key.value='';key.placeholder=config.api_key_configured?'已保存；留空表示不修改':'尚未配置';
  document.querySelector('#voiceKeyStatus').textContent=config.api_key_configured?'✓ API Key 已安全保存':'密钥仅保存在服务器环境变量中';
  document.querySelector('#voiceConfigState').textContent=config.delivery_ready?'可用于推送':(config.model_ready?'模型已配置':'尚未接入');
  document.querySelector('#voiceNavStatus').classList.toggle('live',Boolean(config.delivery_ready));
  const connection=document.querySelector('#voiceConnection');
  connection.classList.toggle('muted',!config.model_ready);
  connection.lastChild.textContent=config.model_ready?' 配置完整':' 等待配置';
  updateVoiceView();
}

async function saveVoiceSettings({fromDelivery=false}={}){
  const body={};
  Object.entries(voiceFields).forEach(([key,selector])=>body[key]=document.querySelector(selector).value);
  body.enabled=fromDelivery?deliveryVoiceEnabled.checked:voiceEnabled.checked;
  const apiKey=document.querySelector('#voiceApiKey').value.trim();if(apiKey)body.api_key=apiKey;
  const result=await api('/api/config/voice',{method:'POST',body:JSON.stringify(body)});
  await loadVoiceSettings();
  return result;
}

deliveryVoiceEnabled.onchange=()=>{voiceEnabled.checked=deliveryVoiceEnabled.checked;updateVoiceView();};
voiceEnabled.onchange=()=>{deliveryVoiceEnabled.checked=voiceEnabled.checked;updateVoiceView();};
Object.values(voiceFields).forEach(selector=>document.querySelector(selector).addEventListener('input',updateVoiceView));
document.querySelector('#saveVoiceConfig').onclick=async()=>{try{await saveVoiceSettings();showToast('语音设置已保存');}catch(error){showToast(error.message);}};
document.querySelector('#testVoiceConfig').onclick=async()=>{try{const result=await api('/api/config/voice/test',{method:'POST',body:'{}'});showDialog('语音配置检查通过',result.message);}catch(error){showToast(error.message);}};
document.querySelector('#playVoiceSample').onclick=()=>showDialog('试听将在模型接入后启用','这里会使用当前文字、音色和语速生成实时试听，不会向企微用户发送。');

document.querySelector('#clearTest').onclick=()=>{document.querySelector('#testMessages').innerHTML='';showToast('测试对话已清空');};
document.querySelector('#testForm').onsubmit=e=>{
  e.preventDefault();const input=document.querySelector('#testInput');const text=input.value.trim();if(!text)return;
  const messages=document.querySelector('#testMessages');
  const user=document.createElement('div');user.className='test-user';user.textContent=text;messages.appendChild(user);
  const agent=document.createElement('div');agent.className='test-agent';agent.textContent='这是原型中的模拟回答。正式系统会使用当前提示词、模型参数和知识库生成结果，并显示耗时与引用来源。';messages.appendChild(agent);
  input.value='';messages.scrollTop=messages.scrollHeight;showToast('已运行一次草稿测试');
};

document.querySelectorAll('input,select,textarea').forEach(control=>{
  control.addEventListener('change',()=>{
    const status=document.querySelector('.draft-status');if(status)status.textContent='草稿已自动保存 · 刚刚';
  });
});

loadVoiceSettings().catch(error=>showToast(error.message));
