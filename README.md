# 企微英语知识订阅 Agent — MVP

项目完整说明见：[docs/PROJECT.md](docs/PROJECT.md)

这是一个不依赖真实企微凭据即可运行的功能 Demo，已经包含：

- 模拟企微用户添加与自动欢迎
- `开始 / 暂停 / 恢复 / 退订` 命令
- 个性化知识点推送与内容去重
- A/B/C 选择题互动
- 用户追问与可替换的大模型适配器
- 用户、推送和对话记录管理界面
- 每小时自动检查订阅计划

## 启动

```bash
python3 src/app.py
```

浏览器打开 `http://127.0.0.1:8080`。服务器部署时可监听 `0.0.0.0`，然后通过 `http://服务器IP:8080` 访问。

## 模型配置

复制 `.env.example` 为 `.env`，填写重新生成的 DeepSeek 密钥：

```text
MODEL_API_KEY=重新生成的密钥
MODEL_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat
```

未配置模型时，订阅、推送、答题和固定回复仍可完整演示。

DeepSeek 官方接口兼容 OpenAI 的 Chat Completions 格式。本项目调用
`POST /chat/completions`，默认使用 `deepseek-chat`。

## 后台登录保护

公网部署必须在 `.env` 中配置：

```text
ADMIN_USERNAME=admin
ADMIN_PASSWORD=使用随机生成的强密码
```

管理页面和业务 API 使用 HTTP Basic Authentication；健康检查
`/api/health` 保持公开，方便服务监控。

## 真实企微接入

项目包含企业微信自建应用的标准接口：

- 回调验证与 AES 消息解密：`/wecom/callback`
- 员工文本消息自动建档并交给 Agent 处理
- 通过“发送应用消息”接口主动回复和每日推送
- `MsgId` 去重，回调立即确认，后台异步处理

企微后台的回调 URL 应设置为 `https://你的域名/wecom/callback`。Token 和
EncodingAESKey 必须与后台配置一致。

## 聚合聊天协议通道

管理后台的“协议通道”支持供应商开放平台。配置 App Key、App Secret 和设备
GUID 后，系统会生成带随机认证令牌的回调地址。将完整地址填写到供应商的
“实例通知地址”，外部微信客户的文本消息即可进入现有 Agent；主动推送通过
`/msg/send_text` 发送。供应商密钥只保存在服务器 `.env`，不会提交到仓库。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## GitHub 自动部署

推送到 `main` 后，GitHub Actions 会先测试，再把代码部署到
`/home/ubuntu/english-agent` 并重启 `english-agent`。服务器已有的 `.env`
和 SQLite 数据库不会上传 GitHub，也不会被部署覆盖。

仓库 Actions Secrets 需要配置：

- `DEPLOY_HOST`：服务器 IP
- `DEPLOY_USER`：默认 `ubuntu`
- `DEPLOY_PORT`：默认 `22`
- `DEPLOY_SSH_KEY`：专用部署私钥
