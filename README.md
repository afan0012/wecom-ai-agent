# WeCom AI Agent

一个可自部署、可审计的 **企业微信「微信客服」AI Agent**。它把外部微信客服入口、企业微信官方 API、大模型和人工审核的 Markdown 知识库组合在一起。

这不是个人微信自动化工具：它只处理客户通过微信客服链接或二维码发起的会话，不读取个人微信聊天记录，也不绕过平台登录或权限限制。

> 这里既是源码，也是完整制作教程。先读 [从零搭建教程](docs/制作过程与部署教程.md)。

## 能做什么

- 使用企业微信官方微信客服 API 接收与回复外部客户消息；
- 校验回调签名、解密回调、持久化同步游标和消息去重；
- 调用智谱 GLM 的 OpenAI 兼容接口；
- 按企业微信单条 **2048 UTF-8 字节**限制自动拆分长回复，最多发送 5 条；
- 读取 `knowledge/approved/` 中人工审核且标记为可对外使用的 Markdown，并按关键词挑选相关资料供模型参考；
- 提供 `drafts → 人工审核 → approved` 的个人知识库工作流，草稿、私密资料和实际知识库文件不会进入 Git；
- 支持图片理解：客户单独发图会得到简洁识图回复；若紧接着补充文字，图片和文字会一起交给支持视觉的模型；图片只在内存中短暂保存；
- 使用 systemd 保活，使用 Caddy 自动申请 HTTPS 证书。

## 不做什么

- 不读取个人微信、朋友圈、微信群或历史私聊；
- 不冒充主人，不编造报价、订单、合作、行程或联系方式；
- 不自动实现真实人工转接。企业微信接待人员和会话分配规则需按业务自行配置；
- 不把 `knowledge/drafts/` 中的资料交给模型。
- 不把图片资料做成可检索的视觉知识库；这需要独立的多模态索引，适合后续接入 WeKnora、MaxKB 等平台。

## 架构

```text
微信用户
  │ 扫码 / 打开客服链接
  ▼
企业微信「微信客服」
  │ 官方回调事件 + 官方消息接口
  ▼
Caddy（HTTPS） → FastAPI 服务 → SQLite（游标 / 去重）
                         │
                         ├─ 已审核 Markdown 知识库
                         └─ 大模型 API（默认：智谱 GLM）
```

## 五分钟本地体验

```powershell
Copy-Item .env.example .env
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs`。`POST /demo/chat` 默认不存在，避免公网调用模型消耗额度；仅限本机临时调试时，在 `.env` 设置 `ENABLE_DEMO_API=true` 后再调用。未配置模型 Key 时，服务只会返回安全的身份说明，不会连接企业微信。

## 生产部署顺序

1. 准备 Ubuntu 服务器、域名和公网 HTTPS；
2. 配置 80/443 防火墙、Caddy 和 systemd；
3. 在企业微信中创建微信客服账号和自建应用；
4. 填写企业微信回调 URL、Token、EncodingAESKey；
5. 将密钥写进服务器 `.env`，启动服务；
6. 用测试微信账号验证回调、消息回复、长回复拆分和服务重启；
7. 将个人 Markdown/TXT 资料先导入 `knowledge/drafts/`，审核后再放入 `knowledge/approved/`。

逐项入口、填写内容与验收方式见：

- [从零搭建教程](docs/制作过程与部署教程.md)
- [真实搭建复盘与踩坑](docs/真实搭建复盘与踩坑.md)
- [企业微信后台配置](docs/企业微信后台配置.md)
- [知识库审核规则](knowledge/README.md)
- [个人知识库导入与验收](docs/个人知识库导入与验收.md)
- [排障手册](docs/排障手册.md)

## 配置

从 [`.env.example`](.env.example) 创建 `.env`。`.env` 永远不要提交到 Git。

| 变量 | 用途 |
| --- | --- |
| `WECOM_TOKEN` / `WECOM_ENCODING_AES_KEY` | 企业微信回调验签与解密 |
| `WECOM_CORP_ID` / `WECOM_KF_SECRET` | 调用微信客服 API |
| `ZHIPU_API_KEY` | 调用 GLM；不填则退回本地兜底说明 |
| `BOT_NAME` / `BOT_OWNER_NAME` | 机器人对外身份 |
| `KNOWLEDGE_BASE_DIR` | 已审核知识库目录，默认 `knowledge/approved` |
| `VISION_MAX_IMAGE_BYTES` | 单张客户图片的最大字节数，默认 5 MiB |
| `IMAGE_FOLLOWUP_SECONDS` | 客户单独发图后等待补充文字的秒数，默认 2.5 秒 |
| `RAG_API_URL` | 可选的外部 RAG 服务接口 |

## 上线前检查

- [ ] `https://你的域名/healthz` 返回 `{"status":"ok"}`；
- [ ] `.env` 不在 Git 追踪列表中；
- [ ] 企业微信回调保存成功；
- [ ] 测试客户发消息后只收到一次回复；
- [ ] 重启服务后没有回复历史消息；
- [ ] 用长中文回答测试 2048 字节拆分；
- [ ] 知识库仅包含确认可以对外使用的资料。

## 开源与贡献

本项目采用 [MIT License](LICENSE)。欢迎提交问题、教程修正和可复现的部署经验；请勿提交真实密钥、客户消息、二维码截图、域名或服务器地址。安全问题请先阅读 [SECURITY.md](SECURITY.md)。
