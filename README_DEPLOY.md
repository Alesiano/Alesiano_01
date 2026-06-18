# 免费部署指南：Alesia.AI

本项目为前后端分离架构，前端 Vue 3 + Vite，后端 Python FastAPI。以下为使用免费平台部署的完整步骤。

---

## 一、前端部署到 Vercel

### 步骤

1. 访问 [vercel.com](https://vercel.com)，用 GitHub 账号登录
2. 点击 **Add New → Project**，导入本项目所在的 GitHub 仓库
3. 在配置页面设置：
   - **Framework Preset**：选择 `Vite`
   - **Root Directory**：`frontend`
   - **Build Command**：`npm run build`（Vercel 会自动识别）
   - **Output Directory**：`dist`（Vercel 会自动识别）
   - **Environment Variables**（见下方）
4. 点击 **Deploy**，等待构建完成

### 环境变量

| 变量名 | 值 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `https://你的后端域名.railway.app` | 后端部署完成后填入，**必须以 `https://` 开头，末尾不加斜杠** |

> **注意**：`VITE_` 前缀的环境变量在 Vite 构建时会被注入到前端代码中。变量值中**不要包含尾随斜杠**（如 `https://xxx.railway.app` 而非 `https://xxx.railway.app/`）。

### 构建确认

构建完成后，Vercel 会提供一个 `xxxxx.vercel.app` 域名，打开即可访问。

---

## 二、后端部署到 Railway 或 Render

### 选项 A：Railway（推荐）

1. 访问 [railway.com](https://railway.com)，用 GitHub 账号登录
2. 点击 **New Project → Deploy from GitHub repo**
3. 选择本项目仓库，设置 **Root Directory** 为 `backend`
4. Railway 会自动检测 `railway.json` 并读取启动命令
5. 在项目 Settings → **Variables** 中添加环境变量（见下方）
6. 部署完成后，Railway 会分配一个 `xxxxx.railway.app` 域名

### 选项 B：Render

1. 访问 [render.com](https://render.com)，用 GitHub 账号登录
2. 点击 **New → Web Service**
3. 连接 GitHub 仓库，设置：
   - **Root Directory**：`backend`
   - **Runtime**：`Python 3`
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`uvicorn main:app --host 0.0.0.0 --port $PORT`
4. 在 **Environment Variables** 中添加环境变量（见下方）
5. 选择 **Free** 方案，点击 **Create Web Service**

### 后端环境变量

在 Railway / Render 的环境变量设置中添加：

| 变量名 | 是否必须 | 说明 |
|---|---|---|
| `AI_API_KEY` | **必须** | ai.yiqiu.dev 的 API 密钥 |
| `AI_BASE_URL` | 可选 | 中转站地址，默认 `https://ai.yiqiu.dev/v1` |
| `AI_MODEL` | 可选 | 默认对话模型，默认 `gpt-3.5-turbo` |
| `CORS_ORIGINS` | **必须** | 设为你的 Vercel 域名，如 `https://my-app.vercel.app`。多个用逗号分隔 |

### 确认后端运行

部署成功后，访问 `https://你的域名.railway.app/api/config`，如果返回 JSON 则说明后端正常运行。

---

## 三、前后端联通

1. 后端部署完成后，记下其域名（如 `https://alesia-api.railway.app`）
2. 回到 Vercel 项目设置，添加/更新环境变量：
   - `VITE_API_BASE_URL` = `https://alesia-api.railway.app`
3. 在 Vercel 中触发 **Redeploy**（Deployments 页面 → 最新部署右侧 `...` → Redeploy）
4. 后端也需要确认 `CORS_ORIGINS` 中包含 Vercel 域名

### 联通验证

打开 Vercel 提供的域名（如 `https://alesia.vercel.app`），在 AI 助手中发送一条消息，如果能收到 AI 回复，说明前后端联通成功。

---

## 四、常见问题

| 问题 | 原因 | 解决 |
|---|---|---|
| 前端请求报 CORS 错误 | 后端 CORS 未配置前端域名 | 在后端 `CORS_ORIGINS` 中添加 Vercel 域名 |
| 前端请求 404 /api/... | `VITE_API_BASE_URL` 未设置或值错误 | 检查环境变量值格式（`https://` 开头，无尾斜杠） |
| Railway 服务休眠 | 免费方案 24h 无请求会自动休眠 | 首次请求需等待几秒唤醒，或使用 UptimeRobot 定时 ping |
| 前端 API Key 不生效 | 前端把 Key 存在 localStorage | 在前端页面设置弹窗中填入 Key，或后端设置 `AI_API_KEY` |

---

## 五、项目结构说明

```
后端+前端/
├── backend/                 # 后端（部署到 Railway/Render）
│   ├── main.py              # FastAPI 应用入口
│   ├── requirements.txt     # Python 依赖
│   ├── Procfile             # Render 部署配置
│   ├── railway.json         # Railway 部署配置
│   └── .env                 # 环境变量（本地开发用，不提交 Git）
├── frontend/                # 前端（部署到 Vercel）
│   ├── src/
│   │   ├── App.vue          # 主页面组件
│   │   ├── main.js          # Vue 入口
│   │   └── api/ai.js        # API 请求封装
│   ├── vite.config.js       # Vite 构建配置
│   ├── package.json         # 前端依赖
│   └── index.html           # HTML 入口
└── README_DEPLOY.md         # 本文件
```
