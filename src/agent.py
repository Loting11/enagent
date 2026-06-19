import json
import os
import urllib.request


class AgentService:
    def __init__(self):
        self.api_key = os.getenv("MODEL_API_KEY", "")
        self.base_url = os.getenv("MODEL_BASE_URL", "").rstrip("/")
        self.model = os.getenv("MODEL_NAME", "")

    @property
    def configured(self):
        return bool(self.api_key and self.base_url and self.model)

    def answer(self, user, question, content=None):
        if not self.configured:
            if content:
                return (
                    f"你问得很好。{content['term']}（{content['meaning']}）的核心是："
                    f"{content['explanation']}\n\n当前是 Demo 回复；配置模型后，我会结合你的问题继续展开。"
                )
            return "我已经记下这个问题。当前未配置模型接口，配置后我就能进行开放式回答。"

        context = ""
        if content:
            context = json.dumps(content, ensure_ascii=False)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是简洁、准确的 AI 行业英语学习助手。优先用中文解释，保留关键英文表达。回复控制在300字内。",
                },
                {
                    "role": "user",
                    "content": f"用户水平：{user['difficulty']}。当前知识点：{context}\n用户问题：{question}",
                },
            ],
            "temperature": 0.4,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except Exception:
            return "模型服务暂时不可用。我已经保存了你的问题，请稍后再试。"
