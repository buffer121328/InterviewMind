# SQLAlchemy 迁移方案

> 从 asyncpg 手写 SQL 迁移到 SQLAlchemy 2.0 + Alembic

## 1. 为什么要迁移

| 痛点 | asyncpg 现状 | SQLAlchemy 后 |
|------|-------------|---------------|
| 表结构管理 | 517 行手写 DDL（`init_db.py`） | ORM 模型即表结构，Alembic 自动迁移 |
| SQL 拼接 | `$1, $2, $3...` 参数占位，手写字段映射 | ORM 查询，类型安全，IDE 补全 |
| 数据转换 | `dict(row)` 手动映射 | ORM 对象自动映射 |
| 迁移管理 | 无，改表只能手动 ALTER TABLE | `alembic revision --autogenerate` |
| 测试 | 难以 mock 数据库 | 可用 SQLite 内存库测试 |
| 代码量 | 每个 repo 大量重复的 SQL 模板 | 通用 CRUD 可大幅减少 |

## 2. 技术选型

```
SQLAlchemy 2.0 (async)  — 异步 ORM，底层仍用 asyncpg 驱动
Alembic                   — 数据库迁移工具
asyncpg                   — 保留，作为 SQLAlchemy 的异步驱动
```

**关键：asyncpg 不删除**，SQLAlchemy 异步模式底层就是 asyncpg，连接池、驱动完全复用。

## 3. 目标目录结构

```
backend/app/
├── api/                  # 路由层（不变）
├── schemas/              # 所有 Pydantic 模型（合并 models/ 回来）
│   ├── __init__.py
│   ├── common.py         # ApiConfig, ErrorResponse, ChatRequest...
│   ├── session.py        # InterviewSession, SessionCreateRequest...
│   ├── candidate_profile.py
│   ├── resume_schemas.py
│   ├── jd_schemas.py
│   ├── voice.py
│   ├── question_bank.py
│   ├── job_application.py
│   ├── project_rewrite_schemas.py
│   ├── unified_report.py
│   └── weakness_report.py
├── models/               # SQLAlchemy ORM 模型（新增）
│   ├── __init__.py       # 重导出所有模型 + Base
│   ├── base.py           # DeclarativeBase, engine, async_session
│   ├── session.py        # Session, Message, UserProfile
│   ├── resume.py         # ResumeResult, GeneratedResume, CandidateMaterial...
│   ├── interview.py      # WeaknessReport, QuestionBankItem...
│   └── application.py    # JobApplication, ApplicationEvent
├── db/                   # 数据库基础设施（精简）
│   ├── __init__.py       # 重导出 engine, get_session
│   ├── config.py         # DATABASE_URL 配置（保留）
│   └── base.py           # 删除，迁移到 models/base.py
├── repositories/         # 数据访问层（用 ORM 重写）
│   ├── session/
│   ├── resume/
│   ├── interview/
│   └── application/
├── services/             # 业务逻辑（不变）
├── alembic/              # 新增：Alembic 迁移目录
│   ├── env.py
│   ├── versions/
│   └── alembic.ini
└── main.py               # 修改 lifespan，用 SQLAlchemy 初始化
```

**核心变化：**
- `models/` 从空壳变成 SQLAlchemy ORM 模型定义
- `schemas/` 合并回原 `models/` 里的领域实体（InterviewSession 等）
- `db/base.py` 的 DatabaseManager 删除，由 SQLAlchemy engine 替代
- `db/init_db.py` 的 517 行 DDL 删除，由 Alembic 迁移替代
- `repositories/` 从手写 SQL 改为 ORM 查询

## 4. 依赖变更

```diff
# pyproject.toml [project] dependencies

- asyncpg>=0.29.0          # 删除，由 sqlalchemy[asyncio] 依赖自动安装
+ sqlalchemy[asyncio]>=2.0.0
+ alembic>=1.13.0

  # psycopg 保留，LangGraph checkpoint 仍需要
  psycopg[binary,pool]>=3.2.0
```

## 5. 分阶段实施计划

### 阶段 0：合并 models/ 到 schemas/（前置，30 分钟）

当前 `models/` 和 `schemas/` 都是 Pydantic，合并到 `schemas/`，删掉 `models/`。

```bash
# 把 models/ 下的文件移回 schemas/
mv app/models/candidate_profile.py app/schemas/
mv app/models/session.py app/schemas/
mv app/models/unified_report.py app/schemas/
mv app/models/weakness_report.py app/schemas/
mv app/models/question_bank.py app/schemas/

# 更新所有 import
# from app.models.session → from app.schemas.session
# from app.models.candidate_profile → from app.schemas.candidate_profile
# ...

# 删除空的 models/ 目录
rm -rf app/models/
```

### 阶段 1：搭建 SQLAlchemy 基础（1-2 小时）

#### 1.1 创建 `models/base.py`

```python
# app/models/base.py
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.db.config import DATABASE_URL

# SQLAlchemy 2.0 声明式基类
class Base(DeclarativeBase):
    pass

# 异步引擎（底层驱动 = asyncpg）
engine: AsyncEngine = create_async_engine(
    DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
    pool_size=5,
    max_overflow=10,
)

# 异步会话工厂
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """FastAPI 依赖注入用"""
    async with async_session() as session:
        yield session


async def init_db():
    """创建所有表（仅开发用，生产用 Alembic）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

#### 1.2 创建 ORM 模型

以 `sessions` 表为例：

```python
# app/models/session.py
from datetime import datetime
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class SessionModel(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default_user")
    title: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    mode: Mapped[str] = mapped_column(String)
    resume_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    resume_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    interview_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    max_questions: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String, default="active")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    series_id: Mapped[str | None] = mapped_column(String, nullable=True)
    round_index: Mapped[int] = mapped_column(Integer, default=1)
    round_type: Mapped[str] = mapped_column(String, default="tech_initial")
    parent_session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.session_id"), nullable=True
    )

    # 关系
    messages: Mapped[list["MessageModel"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.session_id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    question_index: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    audio_url: Mapped[str | None] = mapped_column(String, nullable=True)

    session: Mapped["SessionModel"] = relationship(back_populates="messages")


class UserProfileModel(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, unique=True)
    profile_data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
```

其他表（`resume_results`, `job_applications`, `question_bank_items` 等）同理，每个表对应一个 ORM 模型。

#### 1.3 `models/__init__.py` 重导出

```python
# app/models/__init__.py
from .base import Base, engine, async_session, get_session, init_db
from .session import SessionModel, MessageModel, UserProfileModel
from .resume import ResumeResultModel, GeneratedResumeModel, CandidateMaterialModel, ...
from .interview import WeaknessReportModel, QuestionBankItemModel, ...
from .application import JobApplicationModel, ApplicationEventModel

__all__ = [
    "Base", "engine", "async_session", "get_session", "init_db",
    "SessionModel", "MessageModel", "UserProfileModel",
    ...
]
```

### 阶段 2：配置 Alembic（30 分钟）

```bash
cd backend
alembic init alembic
```

编辑 `alembic/env.py`：

```python
from app.models import Base
from app.models.base import engine

target_metadata = Base.metadata

# 异步模式
def run_migrations_online():
    connectable = engine
    async def do_run():
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    import asyncio
    asyncio.run(do_run())
```

编辑 `alembic.ini`：

```ini
sqlalchemy.url = postgresql+asyncpg://agent_interview:cheng123@localhost:5432/agent_interview
```

**首次迁移（从现有数据库）：**

```bash
# 基于现有表结构生成初始迁移（不会重建表）
alembic revision --autogenerate -m "initial_from_existing_db"
```

### 阶段 3：逐个重写 Repository（核心工作，4-6 小时）

以 `session_repo.py` 为例，对比改写：

**改写前（asyncpg 手写 SQL）：**

```python
async def create_session(self, session_id, mode, ...):
    async with db_manager.get_connection() as conn:
        await conn.execute('''
            INSERT INTO sessions (session_id, user_id, title, ...)
            VALUES ($1, $2, $3, ...)
        ''', session_id, user_id, title, ...)
        return await self.get_session(session_id)
```

**改写后（SQLAlchemy ORM）：**

```python
from sqlalchemy import select
from app.models import async_session, SessionModel
from app.schemas.session import InterviewSession, SessionMetadata

class SessionRepo:
    async def create_session(self, session_id: str, mode: str, ...) -> InterviewSession:
        async with async_session() as db:
            db_obj = SessionModel(
                session_id=session_id,
                user_id=user_id,
                title=title,
                created_at=now,
                updated_at=now,
                mode=mode,
                ...
            )
            db.add(db_obj)
            await db.commit()
            await db.refresh(db_obj)
            return self._to_schema(db_obj)

    async def get_session(self, session_id: str, ...) -> InterviewSession | None:
        async with async_session() as db:
            stmt = select(SessionModel).where(SessionModel.session_id == session_id)
            result = await db.execute(stmt)
            db_obj = result.scalar_one_or_none()
            if not db_obj:
                return None
            return self._to_schema(db_obj)

    def _to_schema(self, db_obj: SessionModel) -> InterviewSession:
        """ORM 对象 → Pydantic schema"""
        return InterviewSession(
            session_id=db_obj.session_id,
            title=db_obj.title,
            created_at=db_obj.created_at.isoformat(),
            updated_at=db_obj.updated_at.isoformat(),
            metadata=SessionMetadata(
                mode=db_obj.mode,
                resume_filename=db_obj.resume_filename,
                ...
            ),
            messages=[...],
        )
```

**关键变化：**
- `db_manager.get_connection()` → `async_session() as db`
- 手写 SQL → `select()`, `db.add()`, `db.commit()`
- 手动 `dict(row)` 映射 → `_to_schema()` 统一转换
- 事务管理：`async with db.begin():` 或手动 `await db.commit()`

#### 重写优先级

按使用频率和复杂度排序：

| 优先级 | 文件 | 说明 |
|--------|------|------|
| P0 | `session/session_repo.py` | 最核心，使用最频繁 |
| P0 | `session/repo_impl/` | 会话子仓库 |
| P1 | `resume/resume_repo.py` | 简历相关 |
| P1 | `resume/resume_generation_repo.py` | 简历生成 |
| P2 | `interview/question_bank_repo.py` | 题库 |
| P2 | `application/job_application_repo.py` | 投递 |
| P3 | 其余 repo | 低频使用 |

### 阶段 4：清理旧代码（1 小时）

1. **删除 `db/base.py`** — `DatabaseManager` 和 `TransactionManager` 不再需要
2. **删除 `db/init_db.py`** — 517 行 DDL 由 Alembic 接管
3. **更新 `db/__init__.py`** — 只重导出 `engine`, `get_session`, `config`
4. **更新 `main.py`** — lifespan 中 `await db_manager.connect()` → `await init_db()`
5. **更新 `db/config.py`** — 添加 `SQLALCHEMY_DATABASE_URL`（`postgresql+asyncpg://...`）

### 阶段 5：验证与测试（1-2 小时）

1. 启动服务，确认所有 API 正常
2. 运行 Alembic 迁移，确认表结构一致
3. 测试关键路径：创建会话 → 发消息 → 获取画像 → 生成报告

## 6. 风险与回退

| 风险 | 缓解措施 |
|------|----------|
| 性能回退 | SQLAlchemy 2.0 async 性能接近原生 asyncpg；JSONB 字段用 `mapped_column(JSONB)` |
| 复杂查询 | 仍可用 `await db.execute(text("SELECT ..."))` 写原生 SQL |
| LangGraph checkpoint | 它用 psycopg，不走 SQLAlchemy，互不影响 |
| 迁移出错 | Alembic 支持 downgrade；开发阶段可 `drop_all + create_all` |
| 回退方案 | 保留 `db/base.py` 的 `DatabaseManager` 直到所有 repo 迁移完毕再删 |

## 7. 目录结构对照表

| 现在 | 迁移后 | 说明 |
|------|--------|------|
| `schemas/` | `schemas/` | 不变，合并 models/ 进来 |
| `models/` (空) | `models/` (ORM) | 新增 SQLAlchemy 模型 |
| `db/base.py` (DatabaseManager) | 删除 | 由 SQLAlchemy engine 替代 |
| `db/init_db.py` (517行DDL) | 删除 | 由 Alembic 迁移替代 |
| `db/config.py` | `db/config.py` | 保留，加 `SQLALCHEMY_DATABASE_URL` |
| `repositories/` | `repositories/` | 重写为 ORM 查询 |
| `services/` | `services/` | 不变 |
| `api/` | `api/` | 不变 |
| — | `alembic/` | 新增 |

## 8. 时间估算

| 阶段 | 时间 | 可并行 |
|------|------|--------|
| 阶段 0：合并 models → schemas | 30 分钟 | — |
| 阶段 1：SQLAlchemy 基础 + ORM 模型 | 1-2 小时 | — |
| 阶段 2：Alembic 配置 | 30 分钟 | — |
| 阶段 3：逐个重写 Repository | 4-6 小时 | ✅ 可按领域并行 |
| 阶段 4：清理旧代码 | 1 小时 | — |
| 阶段 5：验证测试 | 1-2 小时 | — |
| **总计** | **8-11 小时** | |

## 9. 示例：完整 ORM 模型定义

以下是所有表的 ORM 模型定义，对应 `init_db.py` 中的 13 张表：

```python
# app/models/session.py
class SessionModel(Base): ...      # sessions
class MessageModel(Base): ...      # messages
class UserProfileModel(Base): ...  # user_profile

# app/models/resume.py
class ResumeResultModel(Base): ...          # resume_results
class GeneratedResumeModel(Base): ...      # generated_resumes
class CandidateMaterialModel(Base): ...    # candidate_materials
class ResumeAssemblyResultModel(Base): ... # resume_assembly_results
class ProjectRewriteRecordModel(Base): ... # project_rewrite_records

# app/models/interview.py
class WeaknessReportModel(Base): ...       # interview_weakness_reports
class QuestionBankItemModel(Base): ...     # question_bank_items
class QuestionBankImportModel(Base): ...  # question_bank_imports

# app/models/application.py
class JobApplicationModel(Base): ...       # job_applications
class ApplicationEventModel(Base): ...     # application_events

# app/models/jd.py
class JdAnalysisResultModel(Base): ...     # jd_analysis_results
```

每张表的字段完全对应 `init_db.py` 中的 DDL，类型映射：

| PostgreSQL | SQLAlchemy |
|------------|-----------|
| `TEXT` | `String` 或 `Text` |
| `INTEGER` | `Integer` |
| `SERIAL` | `Integer, autoincrement=True` |
| `BOOLEAN` | `Boolean` |
| `TIMESTAMP` | `DateTime` |
| `JSONB` | `JSONB` (from `sqlalchemy.dialects.postgresql`) |
| `REFERENCES ... ON DELETE CASCADE` | `ForeignKey(..., ondelete="CASCADE")` |