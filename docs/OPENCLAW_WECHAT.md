# OpenClaw 微信入口接入说明

目标：新增一个微信扫码添加的 OpenClaw bot，把微信私聊消息转入当前英语订阅 Agent。

## 1. 后台保存配置

打开后台首页，点击“微信 OpenClaw”。

建议配置：

- 启用入口：启用
- Bot 名称：AI 英语订阅助手
- OpenClaw CLI 路径：`/Users/zhouti/.local/opt/node-v24.17.0-darwin-arm64/bin/openclaw`
- 渠道 ID：`openclaw-weixin`
- 微信账号 ID：扫码登录后生成的 accountId

保存后后台会生成一个带 token 的回调地址：

```text
/openclaw/callback?token=...
```

OpenClaw agent 收到微信消息后，应把消息 POST 到这个地址。

## 2. 扫码登录新的微信 bot

不要复用已有的 `MOSO小助手` 或 `xhs-bot`，建议单独登录一个微信号作为英语学习助手。

优先在后台点击“生成登录二维码”。后台会启动 OpenClaw 登录会话，并把终端二维码/扫码提示显示在弹窗里。手机扫码确认后，点击“检查状态”，记下新出现的账号 ID，例如：

```text
openclaw-weixin xxxxx-im-bot (AI英语助手)
```

把 `xxxxx-im-bot` 填回后台的“微信账号 ID”，并保存。

命令行方式作为备选：

```bash
openclaw channels login --channel openclaw-weixin
openclaw channels status --probe
```

## 3. 创建并绑定英语 Agent

```bash
openclaw agents add enagent \
  --workspace /Users/zhouti/.openclaw/agents/enagent/workspace \
  --model deepseek/deepseek-chat \
  --bind openclaw-weixin:xxxxx-im-bot \
  --non-interactive
```

如果 agent 已存在，只补绑定：

```bash
openclaw agents bind --agent enagent --bind openclaw-weixin:xxxxx-im-bot
```

## 4. OpenClaw agent 转发规则

给 `enagent` 的 OpenClaw workspace 写入规则：

```text
你是微信入口转发助手。收到微信私聊文本后，把 sender、text、name、message_id
POST 到 English Agent 的 /openclaw/callback?token=...。
不要自己生成课程内容；English Agent 会完成订阅、推送、答题和回复发送。
```

可直接使用仓库里的模板：

```text
openclaw-wechat-enagent/agent-instructions.md
```

请求 JSON 示例：

```json
{
  "sender": "{{sender_id}}",
  "name": "{{sender_name}}",
  "text": "{{message_text}}",
  "message_id": "{{message_id}}"
}
```

## 5. 验证

1. 用微信添加这个 bot。
2. 发送 `开始`。
3. 后台用户列表应出现 `openclaw:...` 用户，状态为“待审核”。
4. 管理员选中该用户，点击“通过审核”。
5. 用户发送 `来一个`，应收到一条 AI 英语知识点。
6. 回复 `A` / `B` / `C`，应收到判题反馈。

说明：自动每日推送会复用同一个 `openclaw:...` 用户 ID，通过 OpenClaw CLI 主动回发微信消息。
