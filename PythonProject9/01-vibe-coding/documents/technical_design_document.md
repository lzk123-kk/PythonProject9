# 黑马程序员智能问答系统 — 技术设计文档

> 基于 RAG（检索增强生成）+ Milvus 向量数据库，面向 IT 教育场景的智能答疑系统。

---

## 目录

1. [系统架构总览](#1-系统架构总览)
2. [技术栈选型](#2-技术栈选型)
3. [数据库设计](#3-数据库设计)
4. [Milvus 向量库设计](#4-milvus-向量库设计)
5. [RAG 处理流水线](#5-rag-处理流水线)
6. [API 接口设计](#6-api-接口设计)
7. [核心模块设计](#7-核心模块设计)
8. [目录结构](#8-目录结构)
9. [部署与启动](#9-部署与启动)
10. [环境变量配置](#10-环境变量配置)

---

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                           前端 (edu_rag_UI)                         │
│         首页 / 会话界面 / 学科选择  ←  Streamlit 或 FastAPI Static  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTP / SSE
┌───────────────────────────▼─────────────────────────────────────────┐
│                     FastAPI  API Server                              │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │  POST /chat  │  │POST /stream  │  │  GET  /subjects          │   │
│  │  GET  /status│  │  POST /clear  │  │  GET  /history/<id>      │   │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘   │
│         │                 │                       │                 │
│  ┌──────▼─────────────────▼───────────────────────▼──────────────┐  │
│  │                      RAGQueryService                           │  │
│  │                                                               │  │
│  │  ┌─────────────┐   ┌──────────────┐   ┌───────────────────┐   │  │
│  │  │ 1.意图识别   │ → │ 2.RAG检索    │ → │ 3.答案生成        │   │  │
│  │  │ (LLM)       │   │ (Milvus+SQL) │   │ (LLM + Rerank)    │   │  │
│  │  └─────────────┘   └──────────────┘   └───────────────────┘   │  │
│  └───────────────────────────────┬───────────────────────────────┘  │
│                                  │                                   │
│  ┌───────────────────────────────▼───────────────────────────────┐  │
│  │                     ConversationMemory                         │  │
│  │      MySQL: 会话历史 / 用户偏好 / 查询记录                      │  │
│  └───────────────────────────────┬───────────────────────────────┘  │
└──────────────────────────────────┼───────────────────────────────────┘
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
     ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
     │    MySQL    │        │   Milvus    │        │  Qwen LLM   │
     │ edu_rag DB  │        │ Vector DB   │        │ OpenAI Compat│
     └─────────────┘        └─────────────┘        └─────────────┘
```

### 核心流程

```
用户提问
   │
   ▼
[意图识别] ──→ LLM 分析：简单问候 / 学科知识 / 通用闲聊
   │
   ├─ 问候 → 直接回复（不调用 RAG）
   │
   ├─ 学科知识 → RAG 检索 → 组装上下文 → LLM 生成答案
   │                    │
   │                    ▼
   │              Milvus 语义搜索（top-k=10）
   │              MySQL 元数据过滤（学科标签）
   │
   └─ 闲聊 → 直接回复（不调用 RAG）
          │
          ▼
   [记忆管理] 保存对话历史到 MySQL
          │
          ▼
   返回结果（即时 or 流式 SSE）
```

---

## 2. 技术栈选型

| 层级 | 技术 | 版本 | 说明 |
|------|------|------|------|
| Web 框架 | FastAPI + uvicorn | 0.138.0 | 异步高性能 REST/SSE 服务 |
| 向量数据库 | Milvus | 2.5.6 | 高维向量存储与语义检索 |
| 关系数据库 | MySQL | 8.0 | 会话历史、用户偏好、查询记录 |
| LLM 接入 | langchain_openai | - | OpenAI 兼容接口，统一对接千问/火山 |
| 提示管理 | langchain_core | 1.4.9 | ChatPromptTemplate、消息模板 |
| 向量嵌入 | DashScope text-embedding-v3 | - | 1024 维中文语义向量 |
| 大语言模型 | 阿里云千问 (qwen-plus) | - | 主 LLM，OpenAI 兼容端点 |
| 数据分块 | langchain TextSplitter | - | 按学科切分文档，控制 chunk 粒度 |
| 缓存 / 限流 | Redis（可选） | - | 热点查询缓存，防刷 |
| 日志 | logging + structlog | - | 结构化日志，文件 + 控制台双输出 |
| 配置管理 | python-dotenv + pydantic | - | .env 热加载，Pydantic Settings 校验 |

---

## 3. 数据库设计

**数据库名**：`edu_rag`

### 3.1 会话表 `sessions`

记录每个用户的独立会话，支持多会话并行。

```sql
CREATE TABLE sessions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '会话ID',
    session_id  VARCHAR(36) NOT NULL UNIQUE COMMENT 'UUID，前端传入或服务端生成',
    user_id     VARCHAR(64) NOT NULL COMMENT '用户标识（学号/手机号）',
    subject     VARCHAR(50) DEFAULT NULL COMMENT '当前选中学科，NULL=不限',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后活跃时间',
    message_count INT DEFAULT 0 COMMENT '对话轮数',
    INDEX idx_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话表';
```

### 3.2 对话消息表 `messages`

```sql
CREATE TABLE messages (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '消息ID',
    session_id  VARCHAR(36) NOT NULL COMMENT '所属会话',
    role        ENUM('user','assistant','system') NOT NULL COMMENT '消息角色',
    content     TEXT NOT NULL COMMENT '消息内容',
    is_rag      TINYINT(1) DEFAULT 0 COMMENT '是否走RAG检索（0=直接回答，1=RAG增强）',
    rag_sources JSON DEFAULT NULL COMMENT 'RAG检索来源摘要（topic + score）',
    latency_ms  INT DEFAULT NULL COMMENT '响应耗时（ms）',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_session (session_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息表';
```

### 3.3 用户偏好表 `user_profiles`

```sql
CREATE TABLE user_profiles (
    profile_key   VARCHAR(50) NOT NULL COMMENT '偏好键名',
    profile_value VARCHAR(500) NOT NULL COMMENT '偏好值',
    user_id       VARCHAR(64) NOT NULL COMMENT '用户标识',
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_key, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户偏好设置';
```

### 3.4 学科元数据表 `subjects`

```sql
CREATE TABLE subjects (
    subject_code VARCHAR(30) PRIMARY KEY COMMENT '学科代码，如 python/mysql/fastapi',
    subject_name VARCHAR(100) NOT NULL COMMENT '学科中文名',
    description  TEXT COMMENT '学科简介（用于生成embedding的元数据）',
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学科知识目录';
```

### 3.5 查询日志表 `query_logs`

```sql
CREATE TABLE query_logs (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id  VARCHAR(36) NOT NULL,
    query_text  TEXT NOT NULL COMMENT '用户原始提问',
    intent      VARCHAR(50) COMMENT '识别到的意图',
    top_k       INT COMMENT 'RAG召回条数',
    top_score   DECIMAL(5,4) COMMENT '最高相似度得分',
    response    TEXT COMMENT '系统最终回答',
    latency_ms  INT COMMENT '总耗时ms',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='查询日志（用于效果评估）';
```

---

## 4. Milvus 向量库设计

### 4.1 Collection 设计

```
Collection: edu_knowledge_chunks
├── id            INT64   PRIMARY KEY AUTO
├── chunk_id      VARCHAR(64)   -- 唯一标识，md5(chunk_content + subject)
├── subject       VARCHAR(50)   -- 学科标签，用于精确过滤
├── title         VARCHAR(200)  -- 章节/知识点标题
├── content       TEXT          -- 文本内容（原始 chunk）
├── source_file   VARCHAR(200)  -- 来源文件路径（追溯用）
├── page_num      INT           -- 原文件页码
├── embedding     FLOAT_VECTOR  -- 1024维向量
└── (可选) chunk_order  INT    -- 在同一片段中的顺序
```

### 4.2 索引设计

```python
index_params = {
    "index_type": "IVF_FLAT",      # 数据量 < 100万时用 IVF_FLAT，简单稳定
    "metric_type": "COSINE",       # 余弦相似度，适合文本语义
    "params": {"nlist": 128}       # 簇数量；nRows≈10万时取 16*sqrt(100000)≈5000，向上取整
}
```

### 4.3 查询设计（带学科过滤）

```python
# 步骤1：先过滤学科，再向量检索
filter_expr = f"subject == '{subject}'"   # 学科精确匹配，Milvus 标量过滤

# 步骤2：向量检索 top-k
results = collection.search(
    data=[query_embedding],
    anns_field="embedding",
    param={"metric_type": "COSINE", "params": {"nprobe": 16}},
    limit=10,                  # RAG_TOP_K=10
    output_fields=["chunk_id", "title", "content", "source_file", "page_num"],
    expr=filter_expr           # 学科过滤在向量检索前完成
)

# 步骤3：过滤低分结果
filtered = [r for r in results[0] if r.distance >= SCORE_THRESHOLD]  # 默认 0.7
```

---

## 5. RAG 处理流水线

### 5.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RAG 检索增强生成流水线                            │
│                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│  │ 文档入库  │ →  │ 分块处理  │ →  │ Embedding│ →  │ Milvus   │         │
│  │ 脚本      │    │          │    │ 向量化   │    │ 入库     │         │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘         │
│                                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐         │
│  │ 用户提问  │ →  │ 意图识别  │ →  │ 语义检索  │ →  │ LLM生成  │         │
│  │ (FastAPI)│    │ (LLM)    │    │(Milvus)  │    │ (RAG)    │         │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘         │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        检索增强 Prompt 构建                      │   │
│  │                                                                 │   │
│  │  system_prompt = """                                             │   │
│  │    你是黑马程序员AI学习助手，专门解答IT编程问题。                  │   │
│  │    请根据以下【参考资料】回答用户问题。                            │   │
│  │    如果参考资料中没有相关内容，请明确告知用户"暂未找到相关资料"， │   │
│  │    并给出你能做的最佳解答。                                      │   │
│  │    【参考资料】：                                                │   │
│  │    {context}                                                     │   │
│  │    用户问题：{question}                                          │   │
│  │  """                                                             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 文档入库脚本 `scripts/import_docs.py`

```python
"""
文档入库流程：
  1. 读取 data/knowledge/ 下所有 .md / .txt 文件
  2. 按学科分类（文件名或目录名决定学科）
  3. TextSplitter 分块（parent_chunk=1200字符，child_chunk=300字符，overlap=50）
  4. 调用 DashScope text-embedding-v3 生成 1024 维向量
  5. 批量写入 Milvus collection: edu_knowledge_chunks
"""
```

分块策略说明：
- **Parent-Child 策略**：用大段文本（1200字）做检索定位，返回小段文本（300字）给 LLM，兼顾检索精度与上下文完整。
- 每个 chunk 附带 `subject`（学科）、`title`（章节名）、`source_file`（来源路径）。

### 5.3 检索增强流程图（运行时）

```
用户输入："Python里怎么用列表推导式？"
   │
   ▼
[意图识别 LLM]
   输入：用户历史 + 当前问题
   输出：{"intent": "python_knowledge", "subject": "python", "rewritten_query": "Python列表推导式用法"}
   │
   ▼
[Milvus 语义检索]
   查询向量 = embedding("Python列表推导式用法")
   过滤：subject == "python"
   返回：top-10 chunks，过滤 score < 0.7 的低分结果
   结果：[chunk1, chunk2, ..., chunkN]
   │
   ▼
[Prompt 组装]
   system = """你是黑马程序员AI学习助手...
              【参考资料】
              {chunk1.content}
              {chunk2.content}
              ..."""
   user   = "Python里怎么用列表推导式？"
   │
   ▼
[LLM 生成答案]
   model = qwen-plus (OpenAI兼容接口)
   stream = True → SSE 逐字输出
   │
   ▼
[写入记忆]
   MySQL: messages 表插入 user/assistant 两条记录
   更新 sessions.message_count +1
   │
   ▼
返回 SSE 流或完整 JSON
```

---

## 6. API 接口设计

基于 FastAPI，端口 **8888**。

### 6.1 基础接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 返回前端页面（静态HTML） |
| `GET` | `/api/health` | 健康检查，返回各服务状态 |
| `GET` | `/api/subjects` | 获取学科列表（含简介） |

### 6.2 会话管理

| 方法 | 路径 | 请求体 | 说明 |
|------|------|--------|------|
| `POST` | `/api/sessions` | `{"user_id": "xxx", "subject": "python"}` | 创建会话，返回 `session_id` |
| `GET` | `/api/sessions/{session_id}/messages` | — | 获取会话历史（最近50条） |
| `POST` | `/api/sessions/{session_id}/clear` | — | 清空当前会话历史 |

### 6.3 问答接口

```python
# 即时回答模式
class ChatRequest(BaseModel):
    session_id: str
    message: str
    subject: str | None = None   # 覆盖当前学科

class ChatResponse(BaseModel):
    status: str
    session_id: str
    message: str
    rag_used: bool               # 是否使用了RAG
    sources: list[dict]          # 检索来源摘要 [{"title":..., "score":...}]
    latency_ms: int
```

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 即时回答，同步返回完整结果 |
| `POST` | `/api/chat/stream` | 流式回答，SSE 逐字输出（模拟自然对话） |

### 6.4 流式 SSE 协议

```
POST /api/chat/stream
Content-Type: application/json

body: {"session_id": "xxx", "message": "Python列表推导式怎么用？"}

响应（SSE）：
  data: {"type":"start","session_id":"xxx","rag_used":true}

  data: {"type":"chunk","text":"Python"}
  data: {"type":"chunk","text":"列表"}
  data: {"type":"chunk","text":"推导式"}
  ...
  data: {"type":"done","latency_ms":1230,"sources":[{"title":"...","score":0.91}]}
```

### 6.5 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/status` | 系统整体状态（Milvus/MySQL/LLM连通性） |
| `POST` | `/api/admin/import` | 触发文档重新入库（手动召回） |
| `GET` | `/api/admin/stats` | 查询统计（今日问答数、平均耗时、RAG命中率） |

---

## 7. 核心模块设计

### 7.1 目录结构

```
01-vibe-coding/
├── .env                          # 环境变量（gitignore）
├── .env.example                  # 环境变量模板
├── main.py                       # FastAPI 入口
├── config.py                     # 配置类（从 .env 读取）
├── create_logger.py              # 日志初始化
├── api_server.py                 # FastAPI 路由注册
├── rag_service.py                # RAG 检索服务（核心）
├── chat_service.py               # 对话服务（整合 RAG + LLM + 记忆）
├── prompts.py                    # 所有 Prompt 模板
├── memory.py                     # 对话记忆管理（MySQL持久化）
├── database.py                   # SQLAlchemy 模型 + 会话管理
├── schemas.py                    # Pydantic 请求/响应模型
├── scripts/
│   ├── import_docs.py            # 文档入库脚本（分块+向量化+Milvus写入）
│   └── init_db.py                # 数据库建表脚本
├── data/
│   ├── ai_data/                  # 学科知识文档（.md/.txt）
│   │   ├── python/
│   │   │   ├── 变量与数据类型.md
│   │   │   ├── 列表推导式.md
│   │   │   └── ...
│   │   ├── mysql/
│   │   ├── fastapi/
│   │   └── ...
│   └── edu_rag_UI/              # 前端静态资源
└── logs/
    └── app.log
```

### 7.2 `config.py` — 配置中心

```python
"""
配置类：从 .env 文件读取所有参数，Pydantic 做类型校验
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ---- 应用 ----
    app_name: str = "edu_rag"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8888

    # ---- MySQL ----
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "edu_rag"
    db_user: str = "root"
    db_password: str = "change_me"
    db_url: str = ""   # 自动拼接：mysql+pymysql://user:pass@host:port/db_name

    # ---- Milvus ----
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection: str = "edu_knowledge_chunks"
    milvus_dimension: int = 1024
    milvus_metric: str = "COSINE"
    milvus_nlist: int = 128
    milvus_nprobe: int = 16

    # ---- LLM（千问）----
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    qwen_temperature: float = 0.1
    qwen_max_tokens: int = 2000

    # ---- Embedding（千问）----
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # ---- RAG 参数 ----
    rag_top_k: int = 10
    rag_score_threshold: float = 0.7
    parent_chunk_size: int = 1200
    child_chunk_size: int = 300
    chunk_overlap: int = 50
    data_dir: str = "./data/ai_data"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

### 7.3 `rag_service.py` — RAG 检索服务（核心）

```python
"""
RAG 检索服务：封装 Milvus 向量检索 + 文本组装
职责单一，供 chat_service 调用
"""
import requests
from pymilvus import connections, Collection, utility
from config import settings


class RAGService:

    def __init__(self):
        self._connect_milvus()
        self._collection = Collection(settings.milvus_collection)
        self._collection.load()  # 加载到内存，加速检索

    def _connect_milvus(self):
        connections.connect(
            alias="default",
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )

    def _get_embedding(self, text: str) -> list:
        """调用千问 Embedding API，返回 1024 维向量"""
        resp = requests.post(
            f"{settings.qwen_base_url}/embeddings",
            headers={"Authorization": f"Bearer {settings.qwen_api_key}"},
            json={
                "model": settings.embedding_model,
                "input": [text],
                "dimensions": settings.embedding_dim,
            },
            timeout=30,
        )
        return resp.json()["data"][0]["embedding"]

    def retrieve(self, query: str, subject: str | None = None) -> list[dict]:
        """
        检索相关知识点

        参数：
            query:     用户问题（会被改写后检索）
            subject:   学科过滤，None 表示全学科

        返回：
            list[dict]:  [{chunk_id, title, content, source_file, score}, ...]
        """
        # 1. 生成查询向量
        query_vec = self._get_embedding(query)

        # 2. 构建过滤条件
        filter_expr = f"subject == '{subject}'" if subject else ""

        # 3. 向量检索
        results = self._collection.search(
            data=[query_vec],
            anns_field="embedding",
            param={
                "metric_type": settings.milvus_metric,
                "params": {"nprobe": settings.milvus_nprobe},
            },
            limit=settings.rag_top_k,
            output_fields=["chunk_id", "title", "content", "source_file"],
            expr=filter_expr if filter_expr else None,
        )

        # 4. 过滤低分结果
        hits = []
        for hit_list in results:
            for hit in hit_list:
                if hit.distance >= settings.rag_score_threshold:
                    hits.append({
                        "chunk_id": hit.entity.get("chunk_id"),
                        "title": hit.entity.get("title"),
                        "content": hit.entity.get("content"),
                        "source_file": hit.entity.get("source_file"),
                        "score": round(hit.distance, 4),
                    })
        return hits

    def build_context(self, hits: list[dict]) -> str:
        """将检索结果拼接成 Prompt 上下文字符串"""
        if not hits:
            return "（未检索到相关参考资料）"
        parts = []
        for i, h in enumerate(hits, 1):
            parts.append(f"【资料{i}】《{h['title']}》(来源: {h['source_file']})\n{h['content']}")
        return "\n\n".join(parts)
```

### 7.4 `prompts.py` — Prompt 模板

```python
"""
Prompt 模板管理：集中定义所有 LLM 对话模板
"""
from langchain_core.prompts import ChatPromptTemplate


class Prompts:

    # ── 意图识别 ──────────────────────────────────────────────
    @staticmethod
    def intent_prompt():
        return ChatPromptTemplate.from_messages([
            ("system", """你是一个意图识别助手。分析用户的提问，判断其意图类型。

意图类型：
  - python_knowledge  ：Python 编程相关问题
  - mysql_knowledge   ：MySQL 数据库相关问题
  - fastapi_knowledge ：FastAPI / 后端开发相关问题
  - greeting          ：日常问候（你好、谢谢等）
  - out_of_scope      ：超出教学范围的问题

输出JSON格式，不要输出其他内容：
{{"intent": "...", "subject": "python"|"mysql"|"fastapi"|null}}"""),
            ("human", "{query}"),
        ])

    # ── RAG 问答系统提示 ──────────────────────────────────────
    @staticmethod
    def rag_qa_prompt():
        return ChatPromptTemplate.from_messages([
            ("system", """你是黑马程序员AI学习助手，专注于解答IT编程问题。

要求：
1. 严格基于【参考资料】中的内容作答，不得编造资料中不存在的信息
2. 如果参考资料不足，明确说明"暂未找到相关资料"，并尝试用已有知识补充
3. 回答结构清晰，优先给出代码示例
4. 语言简洁，避免冗余
5. 使用 Markdown 格式组织回答

【参考资料】
{context}

请回答用户的问题。"""),
            ("human", "{question}"),
        ])

    # ── 直接回答（非RAG场景）──────────────────────────────────
    @staticmethod
    def direct_answer_prompt():
        return ChatPromptTemplate.from_messages([
            ("system", """你是黑马程序员AI学习助手，专注于解答IT编程问题。请用简洁清晰的
语言直接回答用户问题，必要时提供代码示例。使用 Markdown 格式。"""),
            ("human", "{question}"),
        ])

    # ── 问候回复 ──────────────────────────────────────────────
    GREETING_RESPONSES = [
        "你好！我是黑马程序员AI学习助手，有任何编程问题随时问我～",
        "嗨！我是你的学习助手，今天想学点什么？",
        "你好呀！欢迎来到黑马程序员智能问答系统，有问题尽管问！",
    ]
```

### 7.5 `chat_service.py` — 对话服务（核心编排）

```python
"""
对话服务：整合意图识别 → RAG检索 → LLM生成 → 记忆管理
架构：单入口，内部多分支
"""
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from memory import ConversationMemory
from rag_service import RAGService
from prompts import Prompts
from config import settings


class ChatService:

    def __init__(self):
        self.llm = ChatOpenAI(
            openai_api_key=settings.qwen_api_key,
            openai_api_base=settings.qwen_base_url,
            model=settings.qwen_model,
            temperature=settings.qwen_temperature,
            max_tokens=settings.qwen_max_tokens,
        )
        self.rag = RAGService()
        self.memory = ConversationMemory()  # MySQL 持久化记忆

    # ── 主入口 ────────────────────────────────────────────────
    async def chat(self, session_id: str, message: str, subject: str | None = None) -> dict:
        """
        标准模式：同步返回完整答案
        返回：{status, message, rag_used, sources, latency_ms}
        """
        # 1. 保存用户消息到记忆
        self.memory.add_message(session_id, "user", message)

        # 2. 意图识别
        intent = await self._recognize_intent(message)

        # 3. 根据意图分流
        if intent["intent"] == "greeting":
            answer = self._random_greeting()
            rag_used, sources = False, []
        elif intent["intent"] == "out_of_scope":
            answer = "这个问题超出了我的知识范围，建议咨询授课老师哦～"
            rag_used, sources = False, []
        else:
            # 4. RAG 检索
            hits = self.rag.retrieve(message, subject or intent.get("subject"))
            rag_used = len(hits) > 0
            sources = [{"title": h["title"], "score": h["score"]} for h in hits]
            context = self.rag.build_context(hits)

            # 5. LLM 生成答案
            prompt = Prompts.rag_qa_prompt() if rag_used else Prompts.direct_answer_prompt()
            chain = prompt | self.llm | StrOutputParser()
            answer = await chain.ainvoke({
                "context": context,
                "question": message,
            })

        # 6. 保存助手回复到记忆
        self.memory.add_message(session_id, "assistant", answer, rag_used=rag_used, sources=sources)

        return {
            "status": "success",
            "message": answer,
            "rag_used": rag_used,
            "sources": sources,
        }

    # ── 流式版本 ──────────────────────────────────────────────
    async def chat_stream(self, session_id: str, message: str, subject: str | None = None):
        """
        流式生成：yield 每个 token，前端实时展示
        """
        self.memory.add_message(session_id, "user", message)
        intent = await self._recognize_intent(message)

        if intent["intent"] == "greeting":
            answer = self._random_greeting()
            yield {"type": "start", "rag_used": False}
            for token in answer:
                yield {"type": "chunk", "text": token}
            yield {"type": "done"}
            return

        hits = self.rag.retrieve(message, subject or intent.get("subject"))
        rag_used = len(hits) > 0
        sources = [{"title": h["title"], "score": h["score"]} for h in hits]
        context = self.rag.build_context(hits)

        prompt = Prompts.rag_qa_prompt() if rag_used else Prompts.direct_answer_prompt()
        chain = prompt | self.llm | StrOutputParser()

        full_answer = ""
        yield {"type": "start", "rag_used": rag_used, "sources": sources}
        async for token in chain.astream({"context": context, "question": message}):
            full_answer += token
            yield {"type": "chunk", "text": token}
        yield {"type": "done"}

        self.memory.add_message(session_id, "assistant", full_answer, rag_used=rag_used, sources=sources)

    # ── 辅助方法 ──────────────────────────────────────────────
    async def _recognize_intent(self, query: str) -> dict:
        """调用 LLM 识别意图，返回 JSON dict"""
        prompt = Prompts.intent_prompt()
        chain = prompt | self.llm | StrOutputParser()
        result = await chain.ainvoke({"query": query})
        # 解析 JSON（需处理 LLM 可能返回的代码块标记）
        import json, re
        clean = re.sub(r"```json\s*", "", result).strip().rstrip("`").strip()
        return json.loads(clean)

    def _random_greeting(self) -> str:
        import random
        return random.choice(Prompts.GREETING_RESPONSES)
```

### 7.6 `memory.py` — 记忆管理（MySQL 持久化）

```python
"""
记忆管理：会话历史、用户偏好持久化到 MySQL
支持快速清空当前会话，服务重启后自动恢复
"""
import pymysql
from config import settings


class ConversationMemory:
    def __init__(self):
        self._conn = None

    def _get_conn(self):
        if self._conn is None or not self._conn.open:
            self._conn = pymysql.connect(
                host=settings.db_host,
                port=settings.db_port,
                user=settings.db_user,
                password=settings.db_password,
                database=settings.db_name,
                charset="utf8mb4",
            )
        return self._conn

    def add_message(self, session_id: str, role: str, content: str,
                    rag_used: bool = False, sources: list = None):
        """写入一条对话消息"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (session_id, role, content, is_rag, rag_sources) "
                "VALUES (%s, %s, %s, %s, %s)",
                (session_id, role, content, int(rag_used),
                 __import__('json').dumps(sources, ensure_ascii=False) if sources else None),
            )
            conn.commit()
            cur.execute("SELECT MAX(id) FROM messages WHERE session_id=%s", (session_id,))
            msg_id = cur.fetchone()[0]
            # 更新会话 message_count
            cur.execute(
                "UPDATE sessions SET message_count=message_count+1, updated_at=NOW() "
                "WHERE session_id=%s", (session_id,)
            )
            conn.commit()
        return msg_id

    def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        """获取会话历史，按时间倒序"""
        conn = self._get_conn()
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE session_id=%s ORDER BY id DESC LIMIT %s",
                (session_id, limit),
            )
            rows = cur.fetchall()
        return list(reversed(rows))  # 正序返回

    def clear_session(self, session_id: str):
        """清空指定会话的所有消息"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages WHERE session_id=%s", (session_id,))
            cur.execute(
                "UPDATE sessions SET message_count=0 WHERE session_id=%s", (session_id,)
            )
            conn.commit()
```

---

## 8. 目录结构

```
D:\aiprotject\PythonProject9\01-vibe-coding\
├── .env.example                     # 环境变量模板（已存在）
├── .env                             # 本地环境变量（不提交 git）
├── main.py                          # FastAPI 应用入口
├── config.py                        # 配置类（Settings）
├── create_logger.py                 # 日志初始化
├── api_server.py                    # FastAPI 路由（参考 SmartVoyage 模式）
├── rag_service.py                   # ★ RAG 检索服务（Milvus + Embedding）
├── chat_service.py                  # ★ 对话服务（意图识别 + RAG + LLM 编排）
├── prompts.py                       # Prompt 模板管理
├── memory.py                        # 对话记忆（MySQL 持久化）
├── database.py                      # 数据库连接 & 会话 CRUD
├── schemas.py                       # Pydantic 数据模型
├── requirements.txt                 # Python 依赖清单
├── documents/
│   └── product_requirement_document.md
├── data/
│   ├── ai_data/                     # 学科知识文档目录
│   │   ├── python/
│   │   │   ├── 01_变量与数据类型.md
│   │   │   ├── 02_列表与元组.md
│   │   │   ├── 03_字典与集合.md
│   │   │   ├── 04_函数.md
│   │   │   ├── 05_面向对象.md
│   │   │   ├── 06_列表推导式.md
│   │   │   └── README.md
│   │   ├── mysql/
│   │   │   ├── 01_SQL基础语法.md
│   │   │   ├── 02_索引与优化.md
│   │   │   └── README.md
│   │   ├── fastapi/
│   │   │   ├── 01_FastAPI简介.md
│   │   │   ├── 02_路由与请求模型.md
│   │   │   ├── 03_依赖注入.md
│   │   │   └── README.md
│   │   └── langchain/
│   │       ├── 01_LangChain概述.md
│   │       └── README.md
│   └── edu_rag_UI/                  # 前端静态资源
├── scripts/
│   ├── import_docs.py               # 文档入库脚本（分块→Embedding→Milvus）
│   └── init_db.py                   # 数据库初始化建表
└── logs/
    └── app.log
```

---

## 9. 部署与启动

### 9.1 环境准备

```bash
# 1. 创建虚拟环境
conda create -n edu_rag python=3.11 -y
conda activate edu_rag

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动依赖服务（Docker Compose）
cd infra/
docker-compose up -d   # 启动 Milvus + MySQL

# 4. 初始化数据库
python scripts/init_db.py

# 5. 导入学科文档到 Milvus
python scripts/import_docs.py
```

### 9.2 启动服务

```bash
# 开发模式
python main.py

# 或直接使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8888 --reload
```

### 9.3 服务验证

```bash
# 健康检查
curl http://localhost:8888/api/health

# 获取学科列表
curl http://localhost:8888/api/subjects

# 测试问答（即时模式）
curl -X POST http://localhost:8888/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test001","message":"Python列表推导式怎么用？"}'

# 测试问答（流式模式）
curl -X POST http://localhost:8888/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test001","message":"Python列表推导式怎么用？"}' \
  -N
```

---

## 10. 环境变量配置

复制 `.env.example` 为 `.env` 并填入真实密钥：

```bash
cp .env.example .env
```

关键配置说明：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QWEN_API_KEY` | 阿里云 DashScope API Key | — |
| `QWEN_MODEL` | 使用的千问模型 | `qwen-plus` |
| `MILVUS_HOST` | Milvus 向量库地址 | `localhost` |
| `MILVUS_COLLECTION_NAME` | 向量集合名 | `edu_knowledge_chunks` |
| `MILVUS_DIMENSION` | 向量维度（须与 Embedding 模型一致） | `1024` |
| `RAG_TOP_K` | 检索返回条数 | `10` |
| `RAG_SCORE_THRESHOLD` | 相似度阈值，低于此值不采用 | `0.7` |
| `PARENT_CHUNK_SIZE` | 父块大小（字符） | `1200` |
| `CHILD_CHUNK_SIZE` | 子块大小（字符） | `300` |
| `DB_HOST / DB_NAME / DB_USER / DB_PASSWORD` | MySQL 连接配置 | — |

---

## 附录 A：RAG 效果评估指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 意图识别准确率 | > 90% | 是否正确识别学科意图 |
| RAG 检索命中率 | > 80% | top-1 结果与问题相关的比例 |
| 答案相关性 | > 85% | 人工抽检，答案是否切题 |
| 首字延迟（TTFT） | < 1s | 流式模式下第一个 token 的输出时间 |
| 端到端延迟（P95） | < 5s | 从提问到完整答案的时间 |
| 幻觉率 | < 5% | 答案中编造信息的比例 |

---

## 附录 B：关键技术决策说明

| 决策 | 选择 | 理由 |
|------|------|------|
| 向量数据库 | Milvus | 开源、支持标量过滤、性能优异，项目已有 pymilvus 依赖 |
| Embedding 模型 | 千问 text-embedding-v3 | 中文语义理解强，1024维，OpenAI兼容接口，与项目现有配置一致 |
| LLM | 千问 qwen-plus | 性价比高，中文能力强，OpenAI兼容接口 |
| 分块策略 | Parent-Child（1200/300） | 平衡检索精度与上下文完整性 |
| 相似度度量 | COSINE | 文本语义检索的标准选择 |
| 流式输出 | SSE | 无需 WebSocket，兼容性好，前端处理简单 |
| 记忆持久化 | MySQL | 项目已有 MySQL 基础设施，结构化数据查询灵活 |
