const pageTitles = {overview:'总览',delivery:'推送规则',audience:'用户与分群',knowledge:'知识库',prompt:'提示词与模型',channel:'渠道与系统'};
const toast = document.querySelector('#prototypeToast');

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
document.querySelector('#publishRule').onclick=()=>showDialog('推送规则已发布','新的规则将在下一次计划任务执行时生效，并保留当前版本以便回滚。');
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
