"""
AI 助手 API —— Python FastAPI 版

接口：
  POST   /api/chat            AI 对话
  POST   /api/image           AI 生图
  GET    /api/history         历史记录
  DELETE /api/history/{id}    删除单条历史
  DELETE /api/history         清空历史
  GET    /api/config          获取默认配置
  POST   /api/config          更新默认配置

启动：uvicorn main:app --reload --port 8080
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import List, Optional

import httpx
from dotenv import load_dotenv, set_key, unset_key
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

DB_PATH = "students.db"
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://ai.yiqiu.dev/v1")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-3.5-turbo")

app = FastAPI(title="AI 助手 API")

# 保留 CORS_ORIGINS 环境变量用于兼容，但中间件直接使用 *
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    if request.method == "OPTIONS":
        response = Response(status_code=200)
    else:
        response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


# ========== 辅助函数 ==========
def _resolve_api_config(request: Request):
    """从前端 Header 或 .env 解析 API 配置"""
    api_key = request.headers.get("X-Api-Key") or AI_API_KEY
    base_url = request.headers.get("X-Api-Base-Url") or AI_BASE_URL
    return api_key, base_url


# ========== 数据模型 ==========
class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
    image: Optional[str] = None
    image_mime: Optional[str] = "image/jpeg"


class ChatResponse(BaseModel):
    reply: str


class ImageRequest(BaseModel):
    prompt: str
    size: str = "1024x1024"


class ImageResponse(BaseModel):
    url: Optional[str] = None
    b64_json: Optional[str] = None


class HistoryItem(BaseModel):
    id: int
    type: str
    model: Optional[str] = None
    input_text: str
    output_text: Optional[str] = None
    image_url: Optional[str] = None
    has_upload_image: bool = False
    created_at: str


class ConfigResponse(BaseModel):
    api_key_hint: str
    base_url: str
    default_model: str


class ConfigUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None


# ========== 数据库 ==========
def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                model TEXT,
                input_text TEXT NOT NULL,
                output_text TEXT,
                image_url TEXT,
                has_upload_image INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_history(row: sqlite3.Row) -> HistoryItem:
    return HistoryItem(
        id=row["id"],
        type=row["type"],
        model=row["model"],
        input_text=row["input_text"],
        output_text=row["output_text"],
        image_url=row["image_url"],
        has_upload_image=bool(row["has_upload_image"]),
        created_at=row["created_at"],
    )


def build_message_content(model: str, text: str, image: Optional[str], mime: str):
    """组装多模态消息（兼容 OpenAI / Claude 中转格式）"""
    image = image.strip().replace("\n", "").replace("\r", "")
    mime = mime or "image/jpeg"

    if model.startswith("claude"):
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": image,
                },
            },
            {"type": "text", "text": text},
        ]

    return [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{image}",
                "detail": "high",
            },
        },
        {"type": "text", "text": text},
    ]


def save_history(
    conn: sqlite3.Connection,
    type_: str,
    input_text: str,
    model: Optional[str] = None,
    output_text: Optional[str] = None,
    image_url: Optional[str] = None,
    has_upload_image: bool = False,
):
    conn.execute(
        """
        INSERT INTO ai_history (type, model, input_text, output_text, image_url, has_upload_image)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (type_, model, input_text, output_text, image_url, int(has_upload_image)),
    )


def _mask_key(key: str) -> str:
    if len(key) <= 4:
        return key[:2] + "****"
    return key[:4] + "****"


# ========== API 接口 ==========
@app.on_event("startup")
def on_startup():
    init_db()


# ---- 配置 ----
@app.get("/api/config", response_model=ConfigResponse)
def get_config():
    return ConfigResponse(
        api_key_hint=_mask_key(AI_API_KEY) if AI_API_KEY else "",
        base_url=AI_BASE_URL,
        default_model=AI_MODEL,
    )


@app.post("/api/config")
def update_config(data: ConfigUpdateRequest):
    """更新 .env 中的默认配置（可选功能）"""
    updated = []
    if data.api_key is not None:
        set_key(str(ENV_PATH), "AI_API_KEY", data.api_key)
        global AI_API_KEY
        AI_API_KEY = data.api_key
        updated.append("api_key")
    if data.base_url is not None:
        set_key(str(ENV_PATH), "AI_BASE_URL", data.base_url)
        global AI_BASE_URL
        AI_BASE_URL = data.base_url
        updated.append("base_url")
    if data.default_model is not None:
        set_key(str(ENV_PATH), "AI_MODEL", data.default_model)
        global AI_MODEL
        AI_MODEL = data.default_model
        updated.append("default_model")
    return {"updated": updated}


# ---- 历史记录 ----
@app.get("/api/history", response_model=List[HistoryItem])
def list_history():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_history ORDER BY id DESC LIMIT 50"
        ).fetchall()
        return [row_to_history(row) for row in rows]


@app.delete("/api/history/{history_id}", status_code=204)
def delete_history(history_id: int):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM ai_history WHERE id = ?", (history_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="记录不存在")
        conn.execute("DELETE FROM ai_history WHERE id = ?", (history_id,))


@app.delete("/api/history", status_code=204)
def clear_history():
    with get_db() as conn:
        conn.execute("DELETE FROM ai_history")


# ---- AI 对话 ----
@app.post("/api/chat", response_model=ChatResponse)
async def chat(data: ChatRequest, request: Request):
    """转发到 ai.yiqiu.dev/v1/chat/completions"""
    api_key, base_url = _resolve_api_config(request)

    if not api_key:
        raise HTTPException(status_code=500, detail="请先配置 API Key")

    if not data.message.strip() and not data.image:
        raise HTTPException(status_code=400, detail="请输入问题或上传图片")

    model = (data.model or AI_MODEL).strip()
    if not model:
        raise HTTPException(status_code=400, detail="请选择模型")

    text = data.message.strip() or "请描述这张图片的内容"

    if data.image:
        if len(data.image.strip()) < 100:
            raise HTTPException(status_code=400, detail="图片数据无效，请重新上传")
        mime = data.image_mime or "image/jpeg"
        content = build_message_content(model, text, data.image, mime)
    else:
        content = text

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": content}],
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"AI 服务连接失败: {exc}") from exc

    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {})
            code = err.get("code", "")
            message = err.get("message", resp.text)
            if code == "model_not_found":
                raise HTTPException(
                    status_code=400,
                    detail=f"模型「{model}」不可用。请到 ai.yiqiu.dev 控制台查看你的令牌可用模型。原始信息：{message}",
                )
            raise HTTPException(status_code=resp.status_code, detail=message)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

    result = resp.json()
    try:
        reply = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise HTTPException(status_code=502, detail="AI 返回格式异常") from exc

    with get_db() as conn:
        save_history(
            conn,
            type_="chat",
            model=model,
            input_text=text,
            output_text=reply,
            has_upload_image=bool(data.image),
        )

    return ChatResponse(reply=reply)


# ---- AI 生图 ----
@app.post("/api/image", response_model=ImageResponse)
async def generate_image(data: ImageRequest, request: Request):
    """转发到 ai.yiqiu.dev/v1/images/generations"""
    api_key, base_url = _resolve_api_config(request)

    if not api_key:
        raise HTTPException(status_code=500, detail="请先配置 API Key")

    if not data.prompt.strip():
        raise HTTPException(status_code=400, detail="图片描述不能为空")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-image-2",
                    "prompt": data.prompt.strip(),
                    "n": 1,
                    "size": data.size,
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"AI 服务连接失败: {exc}") from exc

    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {})
            message = err.get("message", resp.text)
            raise HTTPException(status_code=resp.status_code, detail=message)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

    result = resp.json()
    try:
        item = result["data"][0]
    except (KeyError, IndexError) as exc:
        raise HTTPException(status_code=502, detail="AI 返回格式异常") from exc

    image_url = item.get("url")
    if not image_url and item.get("b64_json"):
        image_url = f"data:image/png;base64,{item['b64_json']}"

    with get_db() as conn:
        save_history(
            conn,
            type_="image",
            model="gpt-image-2",
            input_text=data.prompt.strip(),
            image_url=image_url,
        )

    return ImageResponse(url=item.get("url"), b64_json=item.get("b64_json"))
