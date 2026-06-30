const form = document.querySelector('#loginForm');
const error = document.querySelector('#loginError');
const button = document.querySelector('#loginButton');

function nextUrl() {
  const value = new URLSearchParams(location.search).get('next') || '/';
  return value.startsWith('/') ? value : '/';
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  error.hidden = true;
  button.disabled = true;
  button.textContent = '正在进入...';
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        username: form.elements.username.value.trim(),
        password: form.elements.password.value
      })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || '登录失败，请稍后再试');
    location.href = nextUrl();
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
    button.disabled = false;
    button.textContent = '进入后台';
  }
});
