"""校务通核心逻辑：本地 RAG、RBAC 权限隔离、审计和问答记录。"""

import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import sqlite3
import tempfile
import time
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_text_splitters import RecursiveCharacterTextSplitter
from docx import Document as WordDocument
import jieba
from rank_bm25 import BM25Okapi
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx"}
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_QUESTION_LENGTH = 500
GROUPS = {
    "student": "学生文档",
    "counselor": "辅导员文档",
    "admin": "管理员文档",
}
ROLE_NAMES = {
    "student": "学生",
    "counselor": "辅导员",
    "admin": "管理员",
}
# 角色可访问的独立知识库。所有检索和原文读取均在此再次校验。
ROLE_ACCESS = {
    "student": ("student",),
    "counselor": ("student", "counselor"),
    "admin": ("student", "counselor", "admin"),
}
COLLECTIONS = {
    "student": "campus_student",
    "counselor": "campus_counselor",
    "admin": "campus_admin",
}
QUERY_EXPANSIONS = {
    "缓考": "缓考 考试 申请 条件 材料 流程 审批",
    "补考": "补考 重修 考试 成绩 申请",
    "重修": "重修 补考 选课 学分 成绩",
    "休学": "休学 复学 学籍 申请 流程",
    "复学": "复学 休学 学籍 申请 流程",
    "退学": "退学 学籍 申请 审批",
    "转专业": "转专业 专业 申请 条件 考核",
    "奖学金": "奖学金 评定 申请 条件 金额",
    "助学金": "助学金 困难认定 申请 材料",
    "请假": "请假 销假 审批 辅导员",
    "选课": "选课 退课 补选 学分",
    "成绩": "成绩 查询 复核 绩点 学分",
}
CORE_SYNONYMS = {
    "缓考": ("缓考", "延期考试", "延缓考试"),
    "补考": ("补考",),
    "重修": ("重修",),
    "休学": ("休学",),
    "复学": ("复学",),
    "退学": ("退学",),
    "转专业": ("转专业", "调整专业"),
    "奖学金": ("奖学金",),
    "助学金": ("助学金",),
    "请假": ("请假",),
    "选课": ("选课",),
    "成绩": ("成绩",),
}
STOPWORDS = {
    "什么", "怎么", "如何", "需要", "可以", "请问", "一下", "知道", "告诉我",
    "本科生", "学生", "学校", "相关", "规定", "办理", "申请", "的", "了", "吗",
}


class CampusRAG:
    """校务通本地核心。actor 必须包含 username 和 role。"""

    def __init__(
        self,
        data_dir: str = "data",
        db_dir: str = "chroma_db",
        system_db: str = "campus_system.db",
        llm_model: str = "qwen2.5:7b",
        embedding_model: str = "bge-m3",
        ollama_base_url: str = "http://localhost:11434",
        chunk_size: int = 500,
        chunk_overlap: int = 80,
        reranker_model: str = "BAAI/bge-reranker-base",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.db_dir = Path(db_dir)
        self.system_db = Path(system_db)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        for group in GROUPS:
            (self.data_dir / GROUPS[group]).mkdir(parents=True, exist_ok=True)

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._vectorstores: dict[str, Chroma] = {}
        self._chunk_cache: dict[str, list[Document]] = {}
        self._bm25_cache: dict[str, tuple[BM25Okapi, list[list[str]]]] = {}
        self.llm_model = llm_model
        self.reranker_model = reranker_model
        self._reranker: Any = None
        self._ocr_engine: Any = None
        self.embeddings = OllamaEmbeddings(model=embedding_model, base_url=ollama_base_url)
        self.llm = OllamaLLM(
            model=llm_model,
            base_url=ollama_base_url,
            temperature=0.1,
            top_p=0.8,
            repeat_penalty=1.15,
            num_predict=650,
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", ".", " ", ""],
        )
        self._init_system_db()

    # ---------- 通用与权限 ----------

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _role(actor: dict[str, str]) -> str:
        role = str(actor.get("role", ""))
        if role not in ROLE_ACCESS or not actor.get("username"):
            raise PermissionError("登录状态无效，请重新登录。")
        return role

    def _allowed_groups(self, actor: dict[str, str]) -> tuple[str, ...]:
        return ROLE_ACCESS[self._role(actor)]

    def _require_admin(self, actor: dict[str, str]) -> None:
        if self._role(actor) != "admin":
            raise PermissionError("仅管理员可以执行文档管理操作。")

    @staticmethod
    def _safe_filename(filename: str) -> str:
        # 同时处理 Windows 与 POSIX 分隔符，防止路径穿越。
        name = filename.replace("\\", "/").split("/")[-1].strip()
        if not name or name in {".", ".."} or any(ord(c) < 32 for c in name):
            raise ValueError("文件名无效。")
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError("仅支持 PDF、TXT 和 DOCX 文件；旧版 DOC 请先另存为 DOCX。")
        return name

    def _path(self, group: str, filename: str) -> Path:
        if group not in GROUPS:
            raise ValueError("未知文档分组。")
        return self.data_dir / GROUPS[group] / self._safe_filename(filename)

    def _vectorstore(self, group: str) -> Chroma:
        if group not in GROUPS:
            raise ValueError("未知知识库分组。")
        if group not in self._vectorstores:
            self._vectorstores[group] = Chroma(
                collection_name=COLLECTIONS[group],
                embedding_function=self.embeddings,
                persist_directory=str(self.db_dir),
            )
        return self._vectorstores[group]

    # ---------- 用户、密码与审计 ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.system_db, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_system_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    iterations INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qa_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    confidence INTEGER NOT NULL DEFAULT 0,
                    model TEXT NOT NULL DEFAULT '',
                    retrieval_mode TEXT NOT NULL DEFAULT 'hybrid',
                    feedback TEXT NOT NULL DEFAULT '',
                    feedback_at TEXT,
                    rerank_used INTEGER NOT NULL DEFAULT 0,
                    resolved_question TEXT NOT NULL DEFAULT '',
                    trust_score INTEGER NOT NULL DEFAULT 0,
                    trust_explanation TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS document_checks (
                    group_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    sensitive_count INTEGER NOT NULL DEFAULT 0,
                    warning TEXT NOT NULL DEFAULT '',
                    checked_at TEXT NOT NULL,
                    PRIMARY KEY (group_name, filename)
                );
                CREATE TABLE IF NOT EXISTS document_meta (
                    group_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    academic_year TEXT NOT NULL DEFAULT '',
                    effective_date TEXT NOT NULL DEFAULT '',
                    expiry_date TEXT NOT NULL DEFAULT '',
                    is_current INTEGER NOT NULL DEFAULT 1,
                    replaces TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (group_name, filename)
                );
                CREATE TABLE IF NOT EXISTS document_governance (
                    group_name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    key_points_json TEXT NOT NULL DEFAULT '[]',
                    detected_dates_json TEXT NOT NULL DEFAULT '[]',
                    conflicts_json TEXT NOT NULL DEFAULT '[]',
                    analysis_notice TEXT NOT NULL DEFAULT '',
                    analyzed_at TEXT NOT NULL,
                    PRIMARY KEY (group_name, filename)
                );
                CREATE TABLE IF NOT EXISTS forum_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'visible',
                    moderation_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forum_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    parent_id INTEGER,
                    username TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'visible',
                    moderation_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forum_reactions (
                    username TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    reaction TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (username, target_type, target_id, reaction)
                );
                CREATE TABLE IF NOT EXISTS lost_found_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    location TEXT NOT NULL,
                    happened_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    price REAL NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    risk_status TEXT NOT NULL DEFAULT 'visible',
                    risk_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schedule_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    course_name TEXT NOT NULL,
                    weekday INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    teacher TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    location TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    capacity INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'published',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity_enrollments (
                    activity_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (activity_id, username)
                );
                CREATE TABLE IF NOT EXISTS study_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    major TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    plan_text TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mood_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'visible',
                    moderation_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mood_checkins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    mood_score INTEGER NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    response TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS private_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'delivered',
                    moderation_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    read_at TEXT
                );
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    username TEXT NOT NULL,
                    retrieval_mode TEXT NOT NULL,
                    rerank_used INTEGER NOT NULL DEFAULT 0,
                    case_count INTEGER NOT NULL,
                    recall_1 REAL NOT NULL,
                    recall_3 REAL NOT NULL,
                    mrr REAL NOT NULL,
                    refusal_accuracy REAL NOT NULL,
                    avg_latency_ms REAL NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_role
                    ON audit_logs(role, created_at);
                CREATE INDEX IF NOT EXISTS idx_qa_user
                    ON qa_records(username, created_at);
                CREATE INDEX IF NOT EXISTS idx_forum_posts_created
                    ON forum_posts(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_private_messages_users
                    ON private_messages(sender, recipient, created_at);
                CREATE INDEX IF NOT EXISTS idx_schedule_user_day
                    ON schedule_entries(username, weekday);
                """
            )

        # 老版本数据库原地升级，不清空历史问答。
        with self._connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(qa_records)")}
            additions = {
                "confidence": "INTEGER NOT NULL DEFAULT 0",
                "model": "TEXT NOT NULL DEFAULT ''",
                "retrieval_mode": "TEXT NOT NULL DEFAULT 'hybrid'",
                "feedback": "TEXT NOT NULL DEFAULT ''",
                "feedback_at": "TEXT",
                "rerank_used": "INTEGER NOT NULL DEFAULT 0",
                "resolved_question": "TEXT NOT NULL DEFAULT ''",
                "trust_score": "INTEGER NOT NULL DEFAULT 0",
                "trust_explanation": "TEXT NOT NULL DEFAULT ''",
            }
            for name, definition in additions.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE qa_records ADD COLUMN {name} {definition}")

        # 仅首次运行创建演示账户；修改密码后不会被覆盖。
        defaults = (
            ("student", "student", "Student@123"),
            ("counselor", "counselor", "Counselor@123"),
            ("admin", "admin", "Admin@123"),
        )
        for username, role, password in defaults:
            with self._connect() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM users WHERE username = ?", (username,)
                ).fetchone()
            if not exists:
                salt, digest, iterations = self._hash_password(password)
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                        (username, role, salt, digest, iterations, self._now()),
                    )

    @staticmethod
    def _hash_password(password: str, salt: str | None = None) -> tuple[str, str, int]:
        iterations = 260_000
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
        ).hex()
        return salt, digest, iterations

    def _audit(
        self,
        username: str,
        role: str,
        action: str,
        resource: str = "",
        detail: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_logs (created_at, username, role, action, resource, detail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (self._now(), username, role, action, resource, detail[:2000]),
            )

    def authenticate(self, username: str, password: str) -> dict[str, str] | None:
        username = username.strip()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()

        valid = False
        role = "unknown"
        if row:
            role = row["role"]
            # 使用账户保存的迭代数重新计算，兼容未来调整。
            candidate = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(row["salt"]),
                int(row["iterations"]),
            ).hex()
            valid = hmac.compare_digest(candidate, row["password_hash"])

        self._audit(
            username or "空用户名",
            role,
            "login_success" if valid else "login_failed",
            detail="本地账号密码登录",
        )
        return {"username": username, "role": role} if valid else None

    def change_password(
        self, actor: dict[str, str], old_password: str, new_password: str
    ) -> None:
        username = actor["username"]
        self._role(actor)
        if len(new_password) < 8:
            raise ValueError("新密码至少需要 8 个字符。")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if not row:
            raise PermissionError("账户不存在。")
        old_hash = hashlib.pbkdf2_hmac(
            "sha256",
            old_password.encode("utf-8"),
            bytes.fromhex(row["salt"]),
            int(row["iterations"]),
        ).hex()
        if not hmac.compare_digest(old_hash, row["password_hash"]):
            raise ValueError("原密码不正确。")
        salt, digest, iterations = self._hash_password(new_password)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET salt = ?, password_hash = ?, iterations = ?"
                " WHERE username = ?",
                (salt, digest, iterations, username),
            )
        self._audit(username, actor["role"], "change_password")

    # ---------- 文档加载与单文档索引 ----------

    @staticmethod
    def _read_txt(path: Path) -> str:
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _read_docx(path: Path) -> str:
        """提取 DOCX 正文与表格；不依赖本机安装 Microsoft Word。"""
        word = WordDocument(str(path))
        lines = [p.text.strip() for p in word.paragraphs if p.text.strip()]
        for table in word.tables:
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
        return "\n".join(lines).strip()

    @staticmethod
    def _mask_sensitive(text: str) -> str:
        text = re.sub(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)", r"\1****\2", text)
        text = re.sub(r"(?<!\d)(\d{6})\d{8}(\d{3}[0-9Xx])(?!\d)", r"\1********\2", text)
        text = re.sub(r"((?:学号|学生号)\s*[:：]?\s*)\d{6,20}", r"\1[已脱敏]", text)
        return text

    def preflight_document(
        self, actor: dict[str, str], group: str, filename: str, content: bytes,
        allow_ocr: bool = False,
    ) -> dict[str, Any]:
        """上传前检查可读性、加密、扫描 PDF 与常见敏感信息。"""
        self._require_admin(actor)
        filename = self._safe_filename(filename)
        suffix = Path(filename).suffix.lower()
        warnings: list[str] = []
        encrypted = False
        scanned = False
        fatal = False
        text = ""
        if len(content) > MAX_FILE_SIZE:
            warning = "文件超过 50 MB，请拆分或压缩后再导入"
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO document_checks"
                    " (group_name, filename, sensitive_count, warning, checked_at)"
                    " VALUES (?, ?, 0, ?, ?)",
                    (group, filename, warning, self._now()),
                )
            return {
                "ok": False, "warning": warning, "encrypted": False, "scanned": False,
                "sensitive_count": 0,
                "sensitive_counts": {"手机号": 0, "身份证号": 0, "学号": 0},
                "char_count": 0,
            }
        try:
            if suffix == ".pdf":
                reader = PdfReader(io.BytesIO(content))
                encrypted = bool(reader.is_encrypted)
                if encrypted:
                    warnings.append("PDF 已加密，请先解除密码保护")
                else:
                    page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
                    text = "\n".join(page_texts)
                    if not reader.pages or len(text.strip()) < max(20, len(reader.pages) * 10):
                        scanned = True
                        warnings.append(
                            "疑似扫描/图片型 PDF，将在入库时执行本地 OCR"
                            if allow_ocr else
                            "疑似扫描/图片型 PDF，当前无法有效提取文字，请先 OCR"
                        )
            elif suffix == ".docx":
                if not zipfile.is_zipfile(io.BytesIO(content)):
                    encrypted = True
                    warnings.append("DOCX 无法读取，可能已加密或实际是旧版 DOC")
                else:
                    word = WordDocument(io.BytesIO(content))
                    lines = [p.text.strip() for p in word.paragraphs if p.text.strip()]
                    for table in word.tables:
                        for row in table.rows:
                            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
                    text = "\n".join(lines)
            else:
                raw = content
                for encoding in ("utf-8-sig", "utf-8", "gb18030"):
                    try:
                        text = raw.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    text = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            fatal = True
            warnings.append(f"文件预检失败：{exc}")

        if not encrypted and not scanned and not text.strip():
            fatal = True
            warnings.append("未检测到可读取文字")
        sensitive_counts = {
            "手机号": len(re.findall(r"(?<!\d)1[3-9]\d{9}(?!\d)", text)),
            "身份证号": len(re.findall(r"(?<!\d)\d{17}[0-9Xx](?!\d)", text)),
            "学号": len(re.findall(r"(?:学号|学生号)\s*[:：]?\s*\d{6,20}", text)),
        }
        sensitive_count = sum(sensitive_counts.values())
        if sensitive_count:
            warnings.append(f"检测到 {sensitive_count} 处潜在敏感信息，请确认是否允许入库")
        ok = not fatal and not encrypted and (not scanned or allow_ocr)
        warning = "；".join(warnings)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO document_checks"
                " (group_name, filename, sensitive_count, warning, checked_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (group, filename, sensitive_count, warning, self._now()),
            )
        return {
            "ok": ok,
            "warning": warning,
            "encrypted": encrypted,
            "scanned": scanned,
            "sensitive_count": sensitive_count,
            "sensitive_counts": sensitive_counts,
            "char_count": len(text.strip()),
        }

    def _ocr_pdf_page(self, path: Path, page_index: int) -> str:
        """使用 PyMuPDF 渲染页面，再由 RapidOCR 在本地识别中文。"""
        try:
            import fitz
            import numpy as np
            from PIL import Image
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "扫描件 OCR 需要安装 pymupdf、rapidocr_onnxruntime、numpy 和 pillow。"
            ) from exc
        if self._ocr_engine is None:
            self._ocr_engine = RapidOCR()
        with fitz.open(str(path)) as pdf:
            if page_index < 0 or page_index >= len(pdf):
                return ""
            pixmap = pdf[page_index].get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
            result, _ = self._ocr_engine(np.asarray(image))
        return "\n".join(
            str(item[1]).strip() for item in (result or [])
            if len(item) >= 2 and str(item[1]).strip()
        )

    def _load_file(
        self, group: str, filename: str, use_ocr: bool = False
    ) -> list[Document]:
        path = self._path(group, filename)
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在：{GROUPS[group]}/{filename}")
        documents: list[Document] = []
        if path.suffix.lower() == ".pdf":
            for page in PyPDFLoader(str(path)).load():
                page_index = int(page.metadata.get("page", 0))
                text = page.page_content.strip()
                used_ocr = False
                if use_ocr and len(re.sub(r"\s+", "", text)) < 20:
                    text = self._ocr_pdf_page(path, page_index).strip()
                    used_ocr = bool(text)
                if text:
                    documents.append(
                        Document(
                            page_content=text,
                            metadata={
                                "source": filename,
                                "page": page_index + 1,
                                "file_type": "pdf",
                                "ocr": used_ocr,
                            },
                        )
                    )
        elif path.suffix.lower() == ".docx":
            text = self._read_docx(path)
            if text:
                documents.append(
                    Document(
                        page_content=text,
                        metadata={"source": filename, "file_type": "docx"},
                    )
                )
        else:
            text = self._read_txt(path).strip()
            if text:
                documents.append(
                    Document(
                        page_content=text,
                        metadata={"source": filename, "file_type": "txt"},
                    )
                )
        if not documents:
            raise ValueError(
                f"{filename} 中没有可读取的文字；扫描版 PDF 或纯图片 Word 需先 OCR。"
            )
        return documents

    def save_document(
        self, actor: dict[str, str], group: str, filename: str, content: bytes
    ) -> str:
        self._require_admin(actor)
        if not content:
            raise ValueError(f"{filename} 是空文件。")
        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"{filename} 超过 50 MB，请拆分或压缩后再导入。")
        path = self._path(group, filename)
        path.write_bytes(content)
        self._audit(
            actor["username"], actor["role"], "upload_document",
            f"{group}/{path.name}", f"{len(content)} bytes",
        )
        return path.name

    def index_document(
        self, actor: dict[str, str], group: str, filename: str, use_ocr: bool = False
    ) -> int:
        """只删除并重写当前文件的向量，不影响同库其他文档。"""
        self._require_admin(actor)
        filename = self._safe_filename(filename)
        documents = self._load_file(group, filename, use_ocr=use_ocr)
        chunks = [d for d in self.splitter.split_documents(documents) if d.page_content.strip()]
        for index, doc in enumerate(chunks, start=1):
            doc.metadata.update({
                "group": group,
                "source": filename,
                "doc_id": f"{group}/{filename}",
                "chunk": index,
            })
        store = self._vectorstore(group)
        # 重建前保留旧向量；新增失败时直接写回旧向量，避免 embedding 服务故障也不丢索引。
        previous = store.get(
            where={"source": filename},
            include=["documents", "metadatas", "embeddings"],
        )
        store.delete(where={"source": filename})
        try:
            if chunks:
                for start in range(0, len(chunks), 32):
                    store.add_documents(chunks[start:start + 32])
        except Exception as exc:
            store.delete(where={"source": filename})
            old_ids = list(previous.get("ids") or [])
            if old_ids:
                try:
                    store._collection.add(
                        ids=old_ids,
                        documents=list(previous.get("documents") or []),
                        metadatas=list(previous.get("metadatas") or []),
                        embeddings=previous.get("embeddings"),
                    )
                except Exception as rollback_exc:
                    self._audit(actor["username"], actor["role"], "index_rollback_failed",
                                f"{group}/{filename}", str(rollback_exc))
                    raise RuntimeError(
                        f"重建失败，且旧索引自动恢复失败：{rollback_exc}。"
                        "请修复模型服务后再次重新向量化。"
                    ) from exc
            rollback_note = "已恢复原有索引" if old_ids else "本次未写入新索引"
            self._audit(actor["username"], actor["role"], "index_rollback",
                        f"{group}/{filename}", rollback_note)
            raise RuntimeError(f"重建失败，{rollback_note}：{exc}") from exc
        self._chunk_cache.pop(group, None)
        self._bm25_cache.pop(group, None)
        self._audit(
            actor["username"], actor["role"], "index_document",
            f"{group}/{filename}", f"{len(chunks)} 个切片",
        )
        return len(chunks)

    def delete_document(self, actor: dict[str, str], group: str, filename: str) -> None:
        self._require_admin(actor)
        path = self._path(group, filename)
        self._vectorstore(group).delete(where={"source": path.name})
        path.unlink(missing_ok=True)
        self._chunk_cache.pop(group, None)
        self._bm25_cache.pop(group, None)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM document_checks WHERE group_name = ? AND filename = ?",
                (group, path.name),
            )
            conn.execute(
                "DELETE FROM document_meta WHERE group_name = ? AND filename = ?",
                (group, path.name),
            )
            conn.execute(
                "DELETE FROM document_governance WHERE group_name = ? AND filename = ?",
                (group, path.name),
            )
        self._audit(
            actor["username"], actor["role"], "delete_document", f"{group}/{path.name}"
        )

    @staticmethod
    def _validate_date(value: str, label: str) -> str:
        value = value.strip()
        if not value:
            return ""
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{label}必须使用 YYYY-MM-DD 格式。") from exc
        return value

    def set_document_metadata(
        self,
        actor: dict[str, str],
        group: str,
        filename: str,
        academic_year: str = "",
        effective_date: str = "",
        expiry_date: str = "",
        is_current: bool = True,
        replaces: str = "",
    ) -> None:
        self._require_admin(actor)
        path = self._path(group, filename)
        if not path.is_file():
            raise FileNotFoundError("只能为已保存的文档设置版本信息。")
        effective_date = self._validate_date(effective_date, "生效日期")
        expiry_date = self._validate_date(expiry_date, "失效日期")
        if effective_date and expiry_date and effective_date > expiry_date:
            raise ValueError("失效日期不能早于生效日期。")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO document_meta"
                " (group_name, filename, academic_year, effective_date, expiry_date,"
                " is_current, replaces, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (group, path.name, academic_year.strip()[:40], effective_date,
                 expiry_date, int(bool(is_current)), replaces.strip()[:200], self._now()),
            )
        self._audit(actor["username"], actor["role"], "document_metadata",
                    f"{group}/{path.name}", f"{academic_year}；现行={bool(is_current)}")

    def _document_meta_map(self) -> dict[tuple[str, str], dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM document_meta").fetchall()
        result = {}
        today = date.today().isoformat()
        for row in rows:
            current = bool(row["is_current"])
            status = "现行有效" if current else "历史版本"
            if row["effective_date"] and row["effective_date"] > today:
                current, status = False, "尚未生效"
            if row["expiry_date"] and row["expiry_date"] < today:
                current, status = False, "已过期"
            result[(row["group_name"], row["filename"])] = {
                "academic_year": row["academic_year"],
                "effective_date": row["effective_date"],
                "expiry_date": row["expiry_date"],
                "is_current": current,
                "status": status,
                "replaces": row["replaces"],
            }
        return result

    def list_documents(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        result = []
        metadata_map = self._document_meta_map()
        for group in self._allowed_groups(actor):
            folder = self.data_dir / GROUPS[group]
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    result.append({
                        "doc_id": f"{group}/{path.name}",
                        "group": group,
                        "group_name": GROUPS[group],
                        "filename": path.name,
                        "size_kb": round(path.stat().st_size / 1024, 1),
                        "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    })
                    result[-1].update(metadata_map.get((group, path.name), {
                        "academic_year": "", "effective_date": "", "expiry_date": "",
                        "is_current": True, "status": "现行有效", "replaces": "",
                    }))
        return result

    def accessible_chunk_count(self, actor: dict[str, str]) -> int:
        return sum(
            int(self._vectorstore(group)._collection.count())
            for group in self._allowed_groups(actor)
        )

    def get_stats(self, actor: dict[str, str]) -> dict[str, int]:
        groups = self._allowed_groups(actor)
        placeholders = ",".join("?" for _ in groups)
        with self._connect() as conn:
            sensitive = conn.execute(
                f"SELECT COALESCE(SUM(sensitive_count), 0) FROM document_checks"
                f" WHERE group_name IN ({placeholders})",
                groups,
            ).fetchone()[0]
            today = datetime.now().astimezone().date().isoformat()
            today_qa = conn.execute(
                "SELECT COUNT(*) FROM qa_records WHERE username = ? AND created_at >= ?",
                (actor["username"], today),
            ).fetchone()[0]
        return {
            "documents": len(self.list_documents(actor)),
            "chunks": self.accessible_chunk_count(actor),
            "sensitive_hits": int(sensitive),
            "today_qa": int(today_qa),
        }

    # ---------- 检索、问答与原文 ----------

    @staticmethod
    def _tokens(text: str) -> list[str]:
        # 修复部分 PDF 在汉字之间插入空格导致的分词断裂。
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
        tokens = []
        for token in jieba.lcut(text.lower()):
            token = token.strip()
            if len(token) >= 2 and token not in STOPWORDS and re.search(r"\w", token):
                tokens.append(token)
        return tokens

    @staticmethod
    def _expanded_query(question: str) -> str:
        additions = [value for key, value in QUERY_EXPANSIONS.items() if key in question]
        return question + (" " + " ".join(additions) if additions else "")

    def _group_chunks(self, group: str) -> list[Document]:
        """读取一个权限组的切片用于 BM25；索引变更时会主动失效缓存。"""
        if group not in self._chunk_cache:
            result = self._vectorstore(group).get(include=["documents", "metadatas"])
            documents = result.get("documents") or []
            metadatas = result.get("metadatas") or []
            self._chunk_cache[group] = [
                Document(page_content=text, metadata=metadata or {})
                for text, metadata in zip(documents, metadatas)
                if text and (metadata or {}).get("group") == group
            ]
        return self._chunk_cache[group]

    def _keyword_candidates(
        self, group: str, question: str, limit: int
    ) -> list[tuple[Document, float]]:
        docs = self._group_chunks(group)
        if not docs:
            return []
        if group not in self._bm25_cache:
            tokenized = [self._tokens(doc.page_content) for doc in docs]
            if not any(tokenized):
                return []
            self._bm25_cache[group] = (BM25Okapi(tokenized), tokenized)
        bm25, _ = self._bm25_cache[group]
        query_tokens = self._tokens(question)
        if not query_tokens:
            return []
        scores = bm25.get_scores(query_tokens)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [
            (docs[index], float(score))
            for index, score in ranked[:limit]
            if score > 0
        ]

    @staticmethod
    def _doc_key(doc: Document) -> str:
        metadata = doc.metadata
        return (
            f"{metadata.get('group')}/{metadata.get('source')}/"
            f"{metadata.get('page')}/{metadata.get('chunk')}"
        )

    def _evidence(self, doc: Document, question: str) -> tuple[str, str, list[str]]:
        """从切片中抽取最关键的 1～2 句，而不是把整段交给用户阅读。"""
        text = re.sub(r"[ \t]+", " ", doc.page_content.strip())
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[。！？；])|\n+", text)
            if part.strip()
        ]
        if not sentences:
            sentences = [text]
        query_tokens = set(self._tokens(question))
        core_terms = [key for key in QUERY_EXPANSIONS if key in question]
        search_terms = {
            synonym
            for term in core_terms
            for synonym in CORE_SYNONYMS.get(term, (term,))
        }

        def score(sentence: str) -> int:
            compact = re.sub(r"\s+", "", sentence)
            value = sum(3 if len(token) > 2 else 2 for token in query_tokens if token in compact)
            value += sum(8 for term in search_terms if term in compact)
            return value

        best_index = max(range(len(sentences)), key=lambda i: score(sentences[i]))
        chosen = {best_index}
        if len(sentences) > 1:
            second_index = max(
                (i for i in range(len(sentences)) if i != best_index),
                key=lambda i: score(sentences[i]),
            )
            if score(sentences[second_index]) > 0:
                chosen.add(second_index)
        selected = [sentences[i] for i in sorted(chosen)]
        evidence = " …… ".join(selected)
        if len(evidence) > 360:
            evidence = sentences[best_index][:357] + "……"
        compact_text = re.sub(r"\s+", "", text)
        matched = sorted(
            {token for token in query_tokens if token in compact_text} |
            {term for term in search_terms if term in compact_text}
        )
        return evidence, sentences[best_index], matched[:6]

    def _rerank(
        self, question: str, entries: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """可选的本地 CrossEncoder 重排，首次使用需下载模型。"""
        if not entries:
            return entries
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "启用 Rerank 需要安装 sentence-transformers。"
                ) from exc
            self._reranker = CrossEncoder(self.reranker_model, device="cpu")
        pairs = [[question, entry["doc"].page_content] for entry in entries]
        scores = self._reranker.predict(pairs)
        for entry, score in zip(entries, scores):
            entry["rerank_score"] = float(score)
        return sorted(entries, key=lambda item: item["rerank_score"], reverse=True)

    @staticmethod
    def clean_answer(answer: str) -> str:
        """清理小模型常见的循环短语、重复行和超长输出，也用于旧记录展示。"""
        text = str(answer).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return "模型未返回有效内容，请重新提问。"

        # 连续重复的短语可能跨越标点，例如“学校最终评审确定。”被循环输出。
        for _ in range(8):
            collapsed = re.sub(r"(.{4,120}?)\1{1,}", r"\1", text, flags=re.S)
            if collapsed == text:
                break
            text = collapsed

        lines: list[str] = []
        previous = ""
        for line in text.split("\n"):
            line = line.strip()
            if line and line == previous:
                continue
            lines.append(line)
            previous = line
        text = "\n".join(lines).strip()

        # 最后一道长度保护，优先在完整句号处结束，避免前端渲染超长异常文本。
        if len(text) > 900:
            shortened = text[:900]
            end = max(shortened.rfind(mark) for mark in ("。", "！", "？", "\n"))
            text = shortened[:end + 1] if end >= 450 else shortened.rstrip() + "……"
        return text.strip()

    @staticmethod
    def _fallback_answer(question: str, sources: list[dict[str, Any]]) -> str:
        """指令模型输出失控时，退回为严格来自证据句的简明摘要。"""
        topic = re.sub(r"\s+", " ", question).strip()[:60]
        points = []
        for source in sources[:4]:
            evidence = CampusRAG.clean_answer(
                source.get("evidence") or source.get("content") or ""
            )
            evidence = re.sub(r"\s+", " ", evidence).strip()
            if len(evidence) > 180:
                shortened = evidence[:180]
                end = max(shortened.rfind(mark) for mark in ("。", "；", "！"))
                evidence = shortened[:end + 1] if end >= 60 else shortened.rstrip() + "……"
            if evidence:
                points.append(f"{len(points) + 1}. {evidence}[资料{source['id']}]")
        if not points:
            return "未从命中文档中提取到可展示的规定，请打开来源原文核对。"
        return (
            f"**一句话结论**：以下是资料中与“{topic}”最直接相关的内容。\n\n"
            "**具体要点**：\n" + "\n".join(points)
        )

    def retrieve(
        self,
        actor: dict[str, str],
        question: str,
        top_k: int = 4,
        retrieval_mode: str = "hybrid",
        use_rerank: bool = False,
    ) -> dict[str, Any]:
        """实际问答与评测共用的检索链路，不调用生成模型。"""
        allowed = self._allowed_groups(actor)
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空。")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError("问题过长，请控制在 500 字以内。")
        if retrieval_mode not in {"vector", "bm25", "hybrid"}:
            raise ValueError("未知检索模式。")
        top_k = max(1, min(int(top_k), 6))
        candidate_limit = max(12, top_k * 4)
        merged: dict[str, dict[str, Any]] = {}

        def add_candidate(doc: Document, rank: int, channel: str, score: float) -> None:
            key = self._doc_key(doc)
            entry = merged.setdefault(key, {
                "doc": doc, "rrf": 0.0, "keyword_score": 0.0,
                "vector_distance": None, "rerank_score": None,
            })
            weight = 1.35 if channel == "keyword" else 1.0
            entry["rrf"] += weight / (60 + rank + 1)
            if channel == "keyword":
                entry["keyword_score"] = max(entry["keyword_score"], score)
            else:
                entry["vector_distance"] = score

        expanded_query = self._expanded_query(question)
        for group in allowed:
            if retrieval_mode in {"vector", "hybrid"}:
                vector_results = self._vectorstore(group).similarity_search_with_score(
                    expanded_query, k=candidate_limit
                )
                for rank, (doc, distance) in enumerate(vector_results):
                    if doc.metadata.get("group") == group:
                        add_candidate(doc, rank, "vector", float(distance))
            if retrieval_mode in {"bm25", "hybrid"}:
                for rank, (doc, score) in enumerate(
                    self._keyword_candidates(group, question, candidate_limit)
                ):
                    add_candidate(doc, rank, "keyword", score)

        candidates = list(merged.values())
        core_terms = [key for key in QUERY_EXPANSIONS if key in question]
        if core_terms:
            search_terms = {
                synonym for term in core_terms
                for synonym in CORE_SYNONYMS.get(term, (term,))
            }
            if retrieval_mode == "hybrid":
                # 混合模式补充全库直接核查，避免双路召回共同漏掉相关页。
                direct_entries: dict[str, dict[str, Any]] = {}
                for group in allowed:
                    for doc in self._group_chunks(group):
                        compact = re.sub(r"\s+", "", doc.page_content)
                        if not any(term in compact for term in search_terms):
                            continue
                        key = self._doc_key(doc)
                        entry = merged.setdefault(key, {
                            "doc": doc, "rrf": 0.0, "keyword_score": 0.0,
                            "vector_distance": None, "rerank_score": None,
                        })
                        entry["rrf"] += 0.04
                        direct_entries[key] = entry
                candidates = list(direct_entries.values())
            else:
                candidates = [
                    entry for entry in candidates
                    if any(term in re.sub(r"\s+", "", entry["doc"].page_content)
                           for term in search_terms)
                ]
        elif retrieval_mode != "vector":
            keyword_hits = [entry for entry in candidates if entry["keyword_score"] > 0]
            if keyword_hits:
                candidates = keyword_hits

        metadata_map = self._document_meta_map()

        def sort_candidates() -> None:
            def sort_key(entry: dict[str, Any]) -> float:
                doc = entry["doc"]
                meta = metadata_map.get(
                    (doc.metadata.get("group"), doc.metadata.get("source")), {}
                )
                rerank_score = entry.get("rerank_score")
                score = float(rerank_score if rerank_score is not None else entry["rrf"])
                # 现行版本只获得适度加分，不能用无关的新文件压过真正相关的旧规定。
                if meta.get("is_current", True):
                    score += 0.5 if rerank_score is not None else 0.003
                return -score

            candidates.sort(key=sort_key)

        sort_candidates()
        rerank_notice = ""
        if use_rerank and candidates:
            try:
                candidates = self._rerank(question, candidates[:30])
            except Exception as exc:
                # 可选增强功能失败不应中断基础问答。
                rerank_notice = f"Rerank 未生效，已回退到当前检索排序：{exc}"
                use_rerank = False
        sort_candidates()

        max_bm25 = max((entry["keyword_score"] for entry in candidates), default=0.0)
        selected_entries = []
        seen_pages = set()
        for entry in candidates:
            doc = entry["doc"]
            page_key = (doc.metadata.get("group"), doc.metadata.get("source"),
                        doc.metadata.get("page"))
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            bm25_norm = entry["keyword_score"] / max_bm25 if max_bm25 > 0 else 0.0
            distance = entry["vector_distance"]
            vector_similarity = 1.0 / (1.0 + max(distance, 0.0)) if distance is not None else 0.0
            if retrieval_mode == "bm25":
                source_confidence = 100.0 * bm25_norm
            elif retrieval_mode == "vector":
                source_confidence = 100.0 * vector_similarity
            else:
                source_confidence = 100.0 * (0.55 * bm25_norm + 0.45 * vector_similarity)
            entry["confidence"] = max(0, min(100, round(source_confidence)))
            selected_entries.append(entry)
            if len(selected_entries) >= top_k:
                break

        return {
            "entries": selected_entries,
            "core_terms": core_terms,
            "rerank_notice": rerank_notice,
            "rerank_used": use_rerank,
        }

    @staticmethod
    def _clarification_needed(question: str, has_history: bool) -> str:
        compact = re.sub(r"[\s，。！？?？]", "", question)
        vague = {"怎么办", "怎么弄", "怎么申请", "如何办理", "需要什么材料", "要什么条件"}
        if compact in vague and not has_history:
            return (
                "请先说明要办理的具体事项，例如“缓考怎么申请”或“奖学金需要什么材料”，"
                "我再从知识库中查找对应规定。"
            )
        return ""

    def _resolve_question(
        self, question: str, history: list[dict[str, str]] | None
    ) -> str:
        """把简短追问补全为独立检索问题；失败时使用保守的原文拼接。"""
        history = (history or [])[-2:]
        if not history:
            return question
        followup_markers = ("那", "它", "这个", "这项", "还", "呢", "材料", "条件", "流程")
        if len(question) > 18 and not any(marker in question for marker in followup_markers):
            return question
        previous = str(history[-1].get("question", "")).strip()
        if not previous:
            return question
        prompt = f"""把最新追问改写成一个可独立检索的完整问题。保留上一问的具体事项，不回答，不解释，只输出一行问题。
上一问：{previous}
最新追问：{question}
完整问题："""
        try:
            candidate = str(self.llm.invoke(prompt)).strip()
            candidate = candidate.split("\n", 1)[0].strip().strip("“”\"'")
            candidate = re.sub(r"^(完整问题|问题|改写结果)[:：]", "", candidate).strip()
            if 3 <= len(candidate) <= 120 and "一句话结论" not in candidate:
                return candidate
        except Exception:
            pass
        return f"{previous}；追问：{question}"

    def _answer_trust(
        self, sources: list[dict[str, Any]], retrieval_confidence: int
    ) -> tuple[int, str]:
        """回答参考可信度：检索匹配、版本有效性和独立资料印证的组合指标。"""
        if not sources:
            return 0, "没有找到可直接使用的资料，因此不计算回答可信度。"
        current_ratio = sum(bool(s.get("is_current", True)) for s in sources) / len(sources)
        unique_docs = {s.get("source") for s in sources}
        corroborated = False
        for i, left in enumerate(sources):
            left_tokens = set(self._tokens(str(left.get("evidence", ""))))
            for right in sources[i + 1:]:
                if left.get("source") == right.get("source"):
                    continue
                right_tokens = set(self._tokens(str(right.get("evidence", ""))))
                union = left_tokens | right_tokens
                overlap = len(left_tokens & right_tokens)
                if union and overlap >= 3 and overlap / len(union) >= 0.12:
                    corroborated = True
                    break
            if corroborated:
                break
        support = 100 if corroborated else (40 if len(unique_docs) > 1 else 0)
        score = round(
            0.55 * max(0, min(100, retrieval_confidence))
            + 0.25 * 100 * current_ratio + 0.20 * support
        )
        notes = [f"资料匹配 {retrieval_confidence}/100"]
        notes.append("来源均为现行版本" if current_ratio == 1 else "包含旧版或未生效资料")
        if corroborated:
            notes.append("不同文档的关键内容有一定重合")
        elif len(unique_docs) > 1:
            notes.append("有多份文档，但内容尚不足以视为相互印证")
        else:
            notes.append("目前只有一份文档支持")
        return max(0, min(100, score)), "；".join(notes)

    def ask(
        self,
        actor: dict[str, str],
        question: str,
        top_k: int = 4,
        retrieval_mode: str = "hybrid",
        use_rerank: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        allowed = self._allowed_groups(actor)
        question = question.strip()
        if not question:
            raise ValueError("问题不能为空。")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError("问题过长，请控制在 500 字以内。")
        resolved_question = self._resolve_question(question, history)
        clarification = self._clarification_needed(question, bool(history))
        if clarification:
            retrieval = {"entries": [], "core_terms": [], "rerank_notice": "", "rerank_used": False}
            use_rerank = False
        else:
            retrieval = self.retrieve(
                actor, resolved_question, top_k=top_k,
                retrieval_mode=retrieval_mode, use_rerank=use_rerank,
            )
        selected_entries = retrieval["entries"]
        core_terms = retrieval["core_terms"]
        rerank_notice = retrieval["rerank_notice"]
        use_rerank = retrieval["rerank_used"]
        generation_notice = ""

        if clarification:
            answer = clarification
            sources: list[dict[str, Any]] = []
            confidence = 0
        elif not selected_entries:
            topic = "、".join(core_terms) if core_terms else resolved_question
            answer = (
                f"未在当前权限范围内的文档中找到与“{topic}”直接相关的规定。"
                "为避免误导，本次不附无关来源。请补充相关制度或换用原文表述。"
            )
            sources: list[dict[str, Any]] = []
            confidence = 0
        else:
            blocks = []
            sources = []
            metadata_map = self._document_meta_map()
            for index, entry in enumerate(selected_entries, start=1):
                doc = entry["doc"]
                page = doc.metadata.get("page")
                location = f"，第 {page} 页" if page else ""
                group = str(doc.metadata["group"])
                evidence, highlight, matched = self._evidence(doc, resolved_question)
                meta = metadata_map.get((group, doc.metadata["source"]), {})
                version_note = meta.get("academic_year", "")
                label = f"{GROUPS[group]}/{doc.metadata['source']}{location}"
                if version_note:
                    label += f"，{version_note}"
                label += f"，{meta.get('status', '现行有效')}"
                blocks.append(
                    f"[资料{index}] 来源：{label}\n"
                    f"关键句：{evidence}\n"
                    f"上下文：{doc.page_content.strip()}"
                )
                sources.append({
                    "id": index, "group": group, "group_name": GROUPS[group],
                    "source": doc.metadata["source"], "page": page,
                    "chunk": doc.metadata.get("chunk"), "content": doc.page_content.strip(),
                    "evidence": evidence, "highlight": highlight, "matched": matched,
                    "confidence": entry["confidence"],
                    "academic_year": meta.get("academic_year", ""),
                    "effective_date": meta.get("effective_date", ""),
                    "expiry_date": meta.get("expiry_date", ""),
                    "is_current": meta.get("is_current", True),
                    "status": meta.get("status", "现行有效"),
                    "replaces": meta.get("replaces", ""),
                })
            prompt = f"""你是“校务通”校园教务问答助手。请阅读每份资料的关键句和上下文，把制度原文总结成普通学生能立即看懂的回答。
回答要求：
1. 必须直接回答问题，优先提炼资料中已有的条件、比例、材料、步骤、期限和负责主体；不能用“请查阅手册”“可在文档中找到”代替答案。
2. 先合并相同含义，再用自己的话简洁表达，不大段照抄，不重复任何句子或短语。
3. 第一行必须写“**一句话结论**：”，直接概括核心答案。
4. 接着必须写“**具体要点**：”，用不超过4条编号短句列出具体信息，并在对应句末标注[资料1]等来源。
5. 如果存在容易误解的限制，最后写“**注意**：”并补充一句；没有则不写。
6. 资料确实没有所需信息时，明确指出缺少的是条件、材料还是流程，不得用相近制度替代或编造。
7. 不重复用户问题，不复述指令，不写“根据以下资料”等套话。通常控制在300字内，信息完整后立即停止。

用户问题：{resolved_question}

资料：
{chr(10).join(blocks)}
"""
            try:
                raw_answer = str(self.llm.invoke(prompt)).strip()
            except Exception as exc:
                raw_answer = ""
                generation_notice = (
                    f"总结模型暂时不可用，本次已改为直接整理证据句：{exc}"
                )
            answer = self.clean_answer(raw_answer)
            severely_repeated = (
                len(raw_answer) >= 160 and len(answer) <= len(raw_answer) * 0.55
            )
            if (
                not raw_answer
                or severely_repeated
                or "一句话结论" not in answer
                or "具体要点" not in answer
            ):
                answer = self._fallback_answer(resolved_question, sources)
            values = [entry["confidence"] for entry in selected_entries]
            confidence = round(0.6 * max(values) + 0.4 * sum(values) / len(values))

        sources_json = json.dumps(sources, ensure_ascii=False)
        trust_score, trust_explanation = self._answer_trust(sources, confidence)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO qa_records (created_at, username, role, question, answer,"
                " sources_json, confidence, model, retrieval_mode, rerank_used, resolved_question,"
                " trust_score, trust_explanation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self._now(), actor["username"], actor["role"], question, answer,
                 sources_json, confidence, self.llm_model, retrieval_mode, int(use_rerank),
                 resolved_question, trust_score, trust_explanation),
            )
            record_id = int(cursor.lastrowid)
        self._audit(
            actor["username"], actor["role"], "query", ",".join(allowed),
            f"问题：{question[:500]}；补全：{resolved_question[:500]}；"
            f"模式：{retrieval_mode}；Rerank：{use_rerank}；"
            f"置信度：{confidence}；命中："
            + "；".join(f"{s['group']}/{s['source']}" for s in sources)
            + (f"；{rerank_notice}" if rerank_notice else "")
            + (f"；{generation_notice}" if generation_notice else ""),
        )
        return {
            "answer": answer, "sources": sources, "record_id": record_id,
            "confidence": confidence, "model": self.llm_model,
            "trust_score": trust_score, "trust_explanation": trust_explanation,
            "retrieval_mode": retrieval_mode, "rerank_used": use_rerank,
            "resolved_question": resolved_question,
            "rerank_notice": rerank_notice,
            "generation_notice": generation_notice,
        }

    # ---------- 引导式事务办理 ----------

    @staticmethod
    def _guide_sentences(source: dict[str, Any]) -> list[str]:
        text = re.sub(r"[ \t]+", " ", str(source.get("content", "")))
        return [
            part.strip() for part in re.split(r"(?<=[。！？；])|\n+", text)
            if 4 <= len(part.strip()) <= 500
        ]

    def build_transaction_guide(
        self,
        actor: dict[str, str],
        topic: str,
        top_k: int = 6,
        retrieval_mode: str = "hybrid",
        use_rerank: bool = False,
    ) -> dict[str, Any]:
        """从真实检索结果归类办理信息；任何类别没有原文依据时保持为空。"""
        self._role(actor)
        topic = topic.strip()
        if not topic:
            raise ValueError("请先填写要办理的事项。")
        if len(topic) > MAX_QUESTION_LENGTH:
            raise ValueError("事项说明过长，请控制在 500 字以内。")
        retrieval = self.retrieve(
            actor, topic, top_k=min(6, max(3, top_k)),
            retrieval_mode=retrieval_mode, use_rerank=use_rerank,
        )
        entries = retrieval["entries"]
        if not entries:
            return {
                "found": False, "topic": topic, "sections": {}, "sources": [],
                "missing": ["条件", "材料", "办理步骤", "截止信息"],
                "message": "当前可访问的资料中没有找到这项事务的规定，请更换表述或联系管理员补充制度。",
                "rerank_notice": retrieval["rerank_notice"],
            }

        metadata_map = self._document_meta_map()
        sources: list[dict[str, Any]] = []
        for index, entry in enumerate(entries, start=1):
            doc = entry["doc"]
            group = str(doc.metadata["group"])
            meta = metadata_map.get((group, doc.metadata["source"]), {})
            evidence, highlight, matched = self._evidence(doc, topic)
            sources.append({
                "id": index, "group": group, "group_name": GROUPS[group],
                "source": doc.metadata["source"], "page": doc.metadata.get("page"),
                "chunk": doc.metadata.get("chunk"), "content": doc.page_content.strip(),
                "evidence": evidence, "highlight": highlight, "matched": matched,
                "confidence": entry["confidence"],
                "academic_year": meta.get("academic_year", ""),
                "effective_date": meta.get("effective_date", ""),
                "expiry_date": meta.get("expiry_date", ""),
                "is_current": meta.get("is_current", True),
                "status": meta.get("status", "现行有效"),
                "replaces": meta.get("replaces", ""),
            })

        category_rules = {
            "conditions": (
                "条件", ("条件", "资格", "符合", "情形", "对象", "范围", "方可", "可以申请", "应当具备"),
            ),
            "materials": (
                "材料", ("材料", "申请表", "证明", "证件", "附件", "提交以下", "原件及复印件"),
            ),
            "steps": (
                "办理步骤", ("流程", "步骤", "提出申请", "提交", "审核", "审批", "办理", "公示", "备案"),
            ),
            "deadlines": (
                "截止信息", ("截止", "日前", "之内", "工作日", "期限", "时间安排", "逾期", "学年内"),
            ),
        }
        sections: dict[str, list[dict[str, Any]]] = {}
        missing = []
        for key, (label, keywords) in category_rules.items():
            candidates = []
            for source in sources:
                for position, sentence in enumerate(self._guide_sentences(source)):
                    compact = re.sub(r"\s+", "", sentence)
                    hits = sum(1 for word in keywords if word in compact)
                    if not hits:
                        continue
                    # 日期本身也是截止信息；其他类别必须出现明确的类别提示词。
                    if key == "deadlines":
                        hits += len(re.findall(
                            r"(?:20\d{2}[年/-]\d{1,2}(?:[月/-]\d{1,2}日?)?|\d+\s*个工作日)", compact
                        ))
                    relevance = sum(1 for token in set(self._tokens(topic)) if token in compact)
                    candidates.append({
                        "text": sentence[:300], "source_ids": [source["id"]],
                        "_score": hits * 4 + relevance, "_source": source["id"],
                        "_position": position,
                    })
            candidates.sort(key=lambda item: (-item["_score"], item["_source"], item["_position"]))
            selected = []
            seen = set()
            for item in candidates:
                normalized = re.sub(r"[\s，。；、]", "", item["text"])
                if normalized in seen:
                    continue
                seen.add(normalized)
                selected.append(item)
                if len(selected) >= (5 if key == "steps" else 4):
                    break
            if key == "steps":
                selected.sort(key=lambda item: (item["_source"], item["_position"]))
            for item in selected:
                item.pop("_score", None)
                item.pop("_source", None)
                item.pop("_position", None)
            sections[key] = selected
            if not selected:
                missing.append(label)

        values = [int(s["confidence"]) for s in sources]
        confidence = round(0.6 * max(values) + 0.4 * sum(values) / len(values))
        trust_score, trust_explanation = self._answer_trust(sources, confidence)
        message = (
            "已从资料中整理出办理信息，请逐项核对来源。"
            if not missing else "资料中没有明确写出：" + "、".join(missing) + "；这些部分不会自动编造。"
        )
        self._audit(
            actor["username"], actor["role"], "transaction_guide", topic[:200],
            f"命中 {len(sources)} 条来源；缺少：{'、'.join(missing) or '无'}",
        )
        return {
            "found": True, "topic": topic, "sections": sections, "sources": sources,
            "missing": missing, "message": message, "confidence": confidence,
            "trust_score": trust_score, "trust_explanation": trust_explanation,
            "created_at": self._now(), "rerank_notice": retrieval["rerank_notice"],
            "rerank_used": retrieval["rerank_used"],
        }

    def export_transaction_guide(
        self, actor: dict[str, str], guide: dict[str, Any], checked_materials: list[int]
    ) -> bytes:
        """导出当前向导和用户勾选状态，不接收任意文件路径或外部内容。"""
        allowed = self._allowed_groups(actor)
        for source in guide.get("sources", []):
            if source.get("group") not in allowed:
                raise PermissionError("当前角色无权导出该向导中的来源。")
        checked = {int(value) for value in checked_materials}
        lines = [
            "校务通事务办理清单",
            f"事项：{guide.get('topic', '')}",
            f"生成时间：{guide.get('created_at', self._now())}",
            "",
        ]
        labels = {"conditions": "一、办理条件", "materials": "二、材料清单",
                  "steps": "三、办理步骤", "deadlines": "四、截止信息"}
        for key, title in labels.items():
            lines.append(title)
            items = guide.get("sections", {}).get(key, [])
            if not items:
                lines.append("资料中未明确说明，请向负责部门核实。")
            for index, item in enumerate(items, start=1):
                refs = "、".join(f"资料{value}" for value in item.get("source_ids", []))
                prefix = f"[{'已勾选' if index - 1 in checked else '未勾选'}] " if key == "materials" else f"{index}. "
                lines.append(f"{prefix}{item.get('text', '')}（{refs}）")
            lines.append("")
        lines.append("五、原文来源")
        for source in guide.get("sources", []):
            page = f"，第 {source['page']} 页" if source.get("page") else ""
            lines.append(
                f"[资料{source['id']}] {source['group_name']}/{source['source']}{page}"
                f"，{source.get('status', '现行有效')}"
            )
        lines.extend(["", "提示：本清单只整理所引资料，不替代负责部门的最终审核。"])
        self._audit(actor["username"], actor["role"], "export_guide", str(guide.get("topic", ""))[:200])
        content = "\n".join(lines) + self._watermark(actor["username"])
        return ("\ufeff" + content).encode("utf-8")

    def evaluate_retrieval(
        self,
        actor: dict[str, str],
        cases: list[dict[str, Any]],
        retrieval_mode: str = "hybrid",
        use_rerank: bool = False,
    ) -> dict[str, Any]:
        """用人工标注的问题与期望来源评测真实检索链路，不调用生成模型。"""
        self._role(actor)
        if retrieval_mode not in {"vector", "bm25", "hybrid"}:
            raise ValueError("未知检索模式。")
        clean_cases = [case for case in cases if str(case.get("question", "")).strip()]
        if not clean_cases:
            raise ValueError("请至少填写一条评测问题。")
        if len(clean_cases) > 100:
            raise ValueError("单次最多评测 100 条问题。")

        details = []
        for case in clean_cases:
            question = str(case["question"]).strip()[:500]
            expected_source = str(case.get("expected_source", "")).strip()
            expected_page_raw = case.get("expected_page")
            try:
                expected_page = int(expected_page_raw) if str(expected_page_raw or "").strip() else None
            except (TypeError, ValueError):
                expected_page = None
            should_answer = bool(case.get("should_answer", True))
            started = time.perf_counter()
            error = ""
            entries = []
            try:
                result = self.retrieve(
                    actor, question, top_k=3,
                    retrieval_mode=retrieval_mode, use_rerank=use_rerank,
                )
                entries = result["entries"]
            except Exception as exc:
                error = str(exc)
            latency = (time.perf_counter() - started) * 1000
            sources = [
                {
                    "source": entry["doc"].metadata.get("source", ""),
                    "page": entry["doc"].metadata.get("page"),
                    "confidence": entry.get("confidence", 0),
                }
                for entry in entries
            ]
            rank = None
            if expected_source:
                for index, source in enumerate(sources, start=1):
                    if source["source"] != expected_source:
                        continue
                    if expected_page is not None and source["page"] != expected_page:
                        continue
                    rank = index
                    break
            refused = not sources
            details.append({
                "question": question,
                "expected_source": expected_source,
                "expected_page": expected_page,
                "should_answer": should_answer,
                "rank": rank,
                "hit_1": rank == 1,
                "hit_3": rank is not None and rank <= 3,
                "reciprocal_rank": 1.0 / rank if rank else 0.0,
                "refusal_correct": (not should_answer and refused),
                "latency_ms": round(latency, 1),
                "sources": sources,
                "error": error,
            })

        answer_cases = [item for item in details if item["should_answer"]]
        refusal_cases = [item for item in details if not item["should_answer"]]

        def average(values: list[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        summary = {
            "case_count": len(details),
            "answer_case_count": len(answer_cases),
            "refusal_case_count": len(refusal_cases),
            "recall_1": average([float(item["hit_1"]) for item in answer_cases]),
            "recall_3": average([float(item["hit_3"]) for item in answer_cases]),
            "mrr": average([float(item["reciprocal_rank"]) for item in answer_cases]),
            "refusal_accuracy": average([
                float(item["refusal_correct"]) for item in refusal_cases
            ]),
            "avg_latency_ms": average([float(item["latency_ms"]) for item in details]),
        }
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO evaluation_runs"
                " (created_at, username, retrieval_mode, rerank_used, case_count,"
                " recall_1, recall_3, mrr, refusal_accuracy, avg_latency_ms, details_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self._now(), actor["username"], retrieval_mode, int(use_rerank),
                 summary["case_count"], summary["recall_1"], summary["recall_3"],
                 summary["mrr"], summary["refusal_accuracy"], summary["avg_latency_ms"],
                 json.dumps(details, ensure_ascii=False)),
            )
            run_id = int(cursor.lastrowid)
        self._audit(actor["username"], actor["role"], "evaluation_run",
                    str(run_id), f"{retrieval_mode}；{len(details)} 条")
        return {"run_id": run_id, **summary, "details": details}

    def get_evaluation_runs(
        self, actor: dict[str, str], limit: int = 30
    ) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluation_runs WHERE username = ? ORDER BY id DESC LIMIT ?",
                (actor["username"], max(1, min(int(limit), 100))),
            ).fetchall()
        return [{
            "id": row["id"], "created_at": row["created_at"],
            "retrieval_mode": row["retrieval_mode"],
            "rerank_used": bool(row["rerank_used"]), "case_count": row["case_count"],
            "recall_1": row["recall_1"], "recall_3": row["recall_3"],
            "mrr": row["mrr"], "refusal_accuracy": row["refusal_accuracy"],
            "avg_latency_ms": row["avg_latency_ms"],
            "details": json.loads(row["details_json"]),
        } for row in rows]

    def run_diagnostics(self, actor: dict[str, str]) -> list[dict[str, str]]:
        """非破坏性检查权限边界、索引元数据、残留向量和两路检索可用性。"""
        self._require_admin(actor)
        checks: list[dict[str, str]] = []

        def add(name: str, status: str, detail: str) -> None:
            checks.append({"检查项": name, "结果": status, "说明": detail})

        expected = {
            "student": ("student",),
            "counselor": ("student", "counselor"),
            "admin": ("student", "counselor", "admin"),
        }
        add("角色权限矩阵", "通过" if ROLE_ACCESS == expected else "失败",
            "学生、辅导员、管理员的知识库边界符合预设。")

        try:
            self._allowed_groups({"username": "invalid", "role": "invalid"})
            add("非法角色拦截", "失败", "非法角色未被拒绝。")
        except PermissionError:
            add("非法角色拦截", "通过", "无效登录角色会被核心层拒绝。")

        documents = self.list_documents(actor)
        protected = next(
            (doc for doc in documents if doc["group"] in {"counselor", "admin"}), None
        )
        if protected:
            try:
                self.open_source(
                    {"username": "permission_probe", "role": "student"},
                    protected["group"], protected["filename"], protected.get("page"),
                )
                add("学生越权读取拦截", "失败", "学生读取了不应访问的文档。")
            except PermissionError:
                add("学生越权读取拦截", "通过",
                    f"已验证学生不能读取{protected['group_name']}。")
            except Exception as exc:
                add("学生越权读取拦截", "失败", f"检查发生异常：{exc}")
        else:
            add("学生越权读取拦截", "跳过", "暂无辅导员或管理员文档可供验证。")

        if protected:
            try:
                protected_chunks = [
                    doc for doc in self._group_chunks(protected["group"])
                    if doc.metadata.get("source") == protected["filename"]
                ]
                probe_tokens = (
                    self._tokens(protected_chunks[0].page_content)[:6]
                    if protected_chunks else []
                )
                if not probe_tokens:
                    add("学生越权检索拦截", "跳过", "受保护文档没有可用的测试关键词。")
                else:
                    probe = " ".join(probe_tokens)
                    result = self.retrieve(
                        {"username": "permission_probe", "role": "student"},
                        probe, top_k=6, retrieval_mode="bm25", use_rerank=False,
                    )
                    leaked = [
                        entry for entry in result["entries"]
                        if entry["doc"].metadata.get("group") in {"counselor", "admin"}
                    ]
                    add("学生越权检索拦截", "失败" if leaked else "通过",
                        "学生检索结果出现受保护分组。" if leaked else
                        "使用受保护文档关键词实测，学生结果中没有受保护分组。")
            except Exception as exc:
                add("学生越权检索拦截", "失败", f"实际检索检查异常：{exc}")

        for group in GROUPS:
            try:
                chunks = self._group_chunks(group)
                wrong_group = [doc for doc in chunks if doc.metadata.get("group") != group]
                missing = sorted({
                    str(doc.metadata.get("source", "")) for doc in chunks
                    if not (self.data_dir / GROUPS[group] / str(doc.metadata.get("source", ""))).is_file()
                })
                if wrong_group:
                    add(f"{GROUPS[group]}分组隔离", "失败", "发现跨分组元数据。")
                elif missing:
                    add(f"{GROUPS[group]}残留向量", "失败",
                        "原文件已缺失：" + "、".join(missing[:5]))
                else:
                    add(f"{GROUPS[group]}索引一致性", "通过",
                        f"{len(chunks)} 个切片，未发现跨组或原文件缺失。")
                if chunks:
                    probe_tokens = self._tokens(chunks[0].page_content)[:6]
                    probe = " ".join(probe_tokens) or chunks[0].page_content[:30]
                    self._vectorstore(group).similarity_search_with_score(probe, k=1)
                    if probe_tokens:
                        self._keyword_candidates(group, probe, 3)
                    add(f"{GROUPS[group]}双路检索", "通过",
                        "已使用当前文档内容实测向量与关键词查找。")
            except Exception as exc:
                add(f"{GROUPS[group]}检索检查", "失败", str(exc))
        self._audit(actor["username"], actor["role"], "diagnostics", "system",
                    f"通过 {sum(c['结果'] == '通过' for c in checks)}/{len(checks)} 项")
        return checks

    def open_source(
        self,
        actor: dict[str, str],
        group: str,
        filename: str,
        page: int | None = None,
    ) -> dict[str, str]:
        if group not in self._allowed_groups(actor):
            self._audit(actor.get("username", "?"), actor.get("role", "?"),
                        "access_denied", f"{group}/{filename}", "越权读取原文")
            raise PermissionError("当前角色无权查看该来源文档。")
        documents = self._load_file(group, filename, use_ocr=True)
        if page is not None:
            pages = [d for d in documents if d.metadata.get("page") == page]
            if not pages:
                raise ValueError("未找到对应 PDF 页面。")
            text = "\n\n".join(d.page_content for d in pages)
            location = f"第 {page} 页"
        else:
            text = "\n\n".join(d.page_content for d in documents)
            location = "DOCX 全文" if Path(filename).suffix.lower() == ".docx" else "文档全文"
        self._audit(
            actor["username"], actor["role"], "view_source",
            f"{group}/{filename}", location,
        )
        return {"text": text, "location": location}

    # ---------- 文档摘要、时间识别与新旧规定治理 ----------

    @staticmethod
    def _governance_sentences(documents: list[Document]) -> list[dict[str, Any]]:
        result = []
        for doc in documents:
            text = re.sub(r"[ \t]+", " ", doc.page_content.strip())
            for part in re.split(r"(?<=[。！？；])|\n+", text):
                sentence = part.strip()
                if 6 <= len(sentence) <= 500:
                    result.append({"text": sentence, "page": doc.metadata.get("page")})
        return result

    @staticmethod
    def _numeric_signature(text: str) -> tuple[str, ...]:
        values = re.findall(
            r"(?<![A-Za-z])\d+(?:\.\d+)?\s*(?:%|％|个?工作日|个?自然日|日|天|学分|元|次|个月|年)?",
            text,
        )
        return tuple(dict.fromkeys(re.sub(r"\s+", "", value) for value in values))

    def _detect_document_conflicts(
        self,
        group: str,
        filename: str,
        documents: list[Document],
    ) -> list[dict[str, Any]]:
        """只报告附有双方原文的疑点，不把模型判断当成制度冲突结论。"""
        all_docs = self.list_documents({"username": "governance", "role": "admin"})
        metadata_map = self._document_meta_map()
        current_meta = metadata_map.get((group, filename), {})
        current_sentences = self._governance_sentences(documents)
        current_text = "\n".join(item["text"] for item in current_sentences)
        current_topics = {key for key in QUERY_EXPANSIONS if key in current_text}
        conflicts: list[dict[str, Any]] = []
        seen_pairs = set()

        for other in all_docs:
            if other["group"] == group and other["filename"] == filename:
                continue
            other_meta = metadata_map.get((other["group"], other["filename"]), {})
            replace_text = str(current_meta.get("replaces", "")) + str(other_meta.get("replaces", ""))
            explicitly_linked = other["filename"] in replace_text or filename in replace_text
            try:
                other_documents = self._load_file(other["group"], other["filename"], use_ocr=False)
            except Exception:
                continue
            other_sentences = self._governance_sentences(other_documents)
            other_text = "\n".join(item["text"] for item in other_sentences)
            shared_topics = current_topics & {key for key in QUERY_EXPANSIONS if key in other_text}
            if not explicitly_linked and not shared_topics:
                continue

            pair_key = (other["group"], other["filename"], "status")
            if (
                explicitly_linked and current_meta.get("is_current", True)
                and other_meta.get("is_current", True) and pair_key not in seen_pairs
            ):
                conflicts.append({
                    "reason": "两份存在替代关系的文件都被标为现行，需要人工确认当前使用版本。",
                    "current_excerpt": current_sentences[0]["text"][:300] if current_sentences else "",
                    "current_page": current_sentences[0].get("page") if current_sentences else None,
                    "other_group": other["group"], "other_filename": other["filename"],
                    "other_group_name": GROUPS[other["group"]],
                    "other_excerpt": other_sentences[0]["text"][:300] if other_sentences else "",
                    "other_page": other_sentences[0].get("page") if other_sentences else None,
                })
                seen_pairs.add(pair_key)

            # 只有同一事项且双方都有数字表述时才提示，避免把无关数字误判为冲突。
            numeric_current = [s for s in current_sentences if self._numeric_signature(s["text"])]
            numeric_other = [s for s in other_sentences if self._numeric_signature(s["text"])]
            for left in numeric_current[:100]:
                left_tokens = set(self._tokens(left["text"]))
                left_numbers = self._numeric_signature(left["text"])
                for right in numeric_other[:100]:
                    right_numbers = self._numeric_signature(right["text"])
                    if left_numbers == right_numbers:
                        continue
                    right_tokens = set(self._tokens(right["text"]))
                    shared = left_tokens & right_tokens
                    sentence_topics = {
                        key for key in shared_topics
                        if key in left["text"] and key in right["text"]
                    }
                    if not sentence_topics and len(shared) < 4:
                        continue
                    pair_key = (other["group"], other["filename"], left["text"], right["text"])
                    if pair_key in seen_pairs:
                        continue
                    conflicts.append({
                        "reason": "同一事项的数字、比例或期限表述不同，需要人工核对适用范围和版本。",
                        "current_values": list(left_numbers), "other_values": list(right_numbers),
                        "current_excerpt": left["text"][:300], "current_page": left.get("page"),
                        "other_group": other["group"], "other_filename": other["filename"],
                        "other_group_name": GROUPS[other["group"]],
                        "other_excerpt": right["text"][:300], "other_page": right.get("page"),
                    })
                    seen_pairs.add(pair_key)
                    if len(conflicts) >= 8:
                        return conflicts
        return conflicts

    def analyze_document_governance(
        self, actor: dict[str, str], group: str, filename: str, use_ocr: bool = False
    ) -> dict[str, Any]:
        self._require_admin(actor)
        if group not in GROUPS:
            raise ValueError("未知文档分组。")
        filename = self._safe_filename(filename)
        documents = self._load_file(group, filename, use_ocr=use_ocr)
        sentences = self._governance_sentences(documents)
        full_text = "\n".join(doc.page_content for doc in documents)
        notices = []
        if len(full_text) > 24000:
            notices.append("文档较长，智能摘要只阅读了前 24000 字；日期和冲突检查仍使用全文。")
        prompt = f"""请只根据下面的制度原文写一份简明说明，不补充原文没有的内容。
第一行写“摘要：”，用100字以内说明这份文件管什么事、适用于谁。
然后写“关键点：”，列出3至5条原文中的条件、材料、流程或期限；每条一行，不超过70字。
不要写建议，不要评价，不要虚构日期或数字。

原文：
{full_text[:24000]}
"""
        raw = ""
        try:
            raw = str(self.llm.invoke(prompt)).strip()
        except Exception as exc:
            notices.append(f"本地模型暂时不可用，摘要已改为原文摘录：{exc}")
        summary_match = re.search(r"摘要[:：]\s*(.+)", raw)
        summary = summary_match.group(1).strip()[:220] if summary_match else ""
        key_points = []
        if "关键点" in raw:
            point_text = raw.split("关键点", 1)[1]
            for line in point_text.splitlines():
                point = re.sub(r"^\s*(?:关键点[:：])?\s*(?:\d+[.、)]|[-•])\s*", "", line).strip()
                if point and "摘要" not in point and len(point) >= 6:
                    key_points.append(point[:180])
                if len(key_points) >= 5:
                    break
        if not summary:
            summary = next((s["text"][:220] for s in sentences if len(s["text"]) >= 20), "未生成摘要，请查看原文。")
            if not notices:
                notices.append("模型摘要格式不完整，当前显示原文摘录。")
        if not key_points:
            key_points = [s["text"][:180] for s in sentences[:4]]
            if not notices:
                notices.append("关键点当前为原文摘录，请结合全文核对。")

        detected_dates = []
        seen_dates = set()
        date_pattern = re.compile(
            r"(?:20\d{2}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|"
            r"20\d{2}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|"
            r"\d{1,2}\s*月\s*\d{1,2}\s*日|\d+\s*个工作日)"
        )
        for sentence in sentences:
            for match in date_pattern.finditer(sentence["text"]):
                value = re.sub(r"\s+", "", match.group(0))
                key = (value, sentence["text"])
                if key in seen_dates:
                    continue
                seen_dates.add(key)
                detected_dates.append({
                    "date": value, "context": sentence["text"][:300], "page": sentence.get("page")
                })
                if len(detected_dates) >= 40:
                    break
            if len(detected_dates) >= 40:
                break
        conflicts = self._detect_document_conflicts(group, filename, documents)
        analyzed_at = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO document_governance (group_name, filename, summary,"
                " key_points_json, detected_dates_json, conflicts_json, analysis_notice, analyzed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (group, filename, summary, json.dumps(key_points, ensure_ascii=False),
                 json.dumps(detected_dates, ensure_ascii=False),
                 json.dumps(conflicts, ensure_ascii=False),
                 "\n".join(notices), analyzed_at),
            )
        self._audit(
            actor["username"], actor["role"], "governance_analysis", f"{group}/{filename}",
            f"关键点 {len(key_points)} 条；时间 {len(detected_dates)} 处；待核对疑点 {len(conflicts)} 条",
        )
        return self.get_document_governance(actor, group, filename) or {}

    def get_document_governance(
        self, actor: dict[str, str], group: str, filename: str
    ) -> dict[str, Any] | None:
        if group not in self._allowed_groups(actor):
            raise PermissionError("当前角色无权查看该文档的治理信息。")
        filename = self._safe_filename(filename)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM document_governance WHERE group_name = ? AND filename = ?",
                (group, filename),
            ).fetchone()
        if not row:
            return None
        return {
            "group": row["group_name"], "filename": row["filename"],
            "summary": row["summary"],
            "key_points": json.loads(row["key_points_json"] or "[]"),
            "detected_dates": json.loads(row["detected_dates_json"] or "[]"),
            "conflicts": json.loads(row["conflicts_json"] or "[]"),
            "analysis_notice": row["analysis_notice"], "analyzed_at": row["analyzed_at"],
        }

    # ---------- 校园社区：通用审核、论坛与内容风控 ----------

    @staticmethod
    def _community_text(value: Any, label: str, limit: int, required: bool = True) -> str:
        text = re.sub(r"\r\n?|\x00", "\n", str(value or "")).strip()
        if required and not text:
            raise ValueError(f"请填写{label}。")
        if len(text) > limit:
            raise ValueError(f"{label}不能超过 {limit} 字。")
        return text

    def _moderate_content(self, text: str, use_ai: bool = True) -> dict[str, Any]:
        """规则兜底＋本地模型辅助审核；模型只能提高风险等级，不能放过规则命中。"""
        compact = re.sub(r"\s+", "", text).lower()
        hard_patterns = {
            "疑似诈骗或刷单": r"刷单兼职|兼职日结|先交保证金|解冻资金|稳赚不赔|代抢课收费",
            "严重辱骂或攻击": r"傻逼|弱智废物|去死吧|nmsl",
            "赌博或色情引流": r"博彩下注|赌场网址|裸聊|色情服务",
        }
        soft_patterns = {
            "包含站外联系方式或引流": r"加我微信|微信群|qq群|扣扣| telegram|whatsapp",
            "包含链接，需要人工确认用途": r"https?://|www\.",
            "包含手机号，请注意个人信息": r"(?<!\d)1[3-9]\d{9}(?!\d)",
        }
        hard_hits = [label for label, pattern in hard_patterns.items() if re.search(pattern, compact, re.I)]
        soft_hits = [label for label, pattern in soft_patterns.items() if re.search(pattern, compact, re.I)]
        rule_status = "blocked" if hard_hits else ("review" if soft_hits else "visible")
        reasons = hard_hits + soft_hits
        status = rule_status
        ai_used = False
        notice = ""
        if use_ai:
            prompt = f"""你是校园内容安全审核员。只根据文本判断风险，不评价观点是否讨喜。
第一行只能输出“通过”“复核”或“拦截”。
第二行用20字以内说明原因。广告、诈骗、严重辱骂、色情赌博和校外引流需要复核或拦截；正常求助、课程讨论和批评意见应通过。
文本：{text[:3000]}
"""
            try:
                raw = str(self.llm.invoke(prompt)).strip()
                first = raw.splitlines()[0] if raw else ""
                ai_status = ""
                if re.search(r"^(?:审核结果[:：]\s*)?拦截", first):
                    ai_status = "blocked"
                elif re.search(r"^(?:审核结果[:：]\s*)?复核", first):
                    ai_status = "review"
                elif re.search(r"^(?:审核结果[:：]\s*)?通过", first):
                    ai_status = "visible"
                if ai_status:
                    ai_used = True
                    rank = {"visible": 0, "review": 1, "blocked": 2}
                    if rank[ai_status] > rank[status]:
                        status = ai_status
                    if len(raw.splitlines()) > 1 and raw.splitlines()[1].strip():
                        reasons.append("本地审核：" + raw.splitlines()[1].strip()[:100])
                else:
                    notice = "本地审核返回格式不完整，已使用规则结果。"
            except Exception as exc:
                notice = f"本地 AI 审核暂不可用，已使用规则结果：{exc}"
        return {
            "status": status, "reason": "；".join(dict.fromkeys(reasons)),
            "ai_used": ai_used, "notice": notice,
        }

    def _save_community_image(self, content: bytes | None, extension: str) -> str:
        if not content:
            return ""
        if len(content) > 5 * 1024 * 1024:
            raise ValueError("图片不能超过 5 MB。")
        ext = extension.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("仅支持 PNG、JPG、JPEG 和 WebP 图片。")
        folder = self.data_dir / "community_images"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}{ext}"
        path.write_bytes(content)
        return str(path)

    def list_user_directory(self, actor: dict[str, str]) -> list[dict[str, str]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT username, role FROM users WHERE username != ? ORDER BY role, username",
                (actor["username"],),
            ).fetchall()
        return [{"username": row["username"], "role": row["role"],
                 "role_name": ROLE_NAMES.get(row["role"], row["role"])} for row in rows]

    def create_forum_post(
        self, actor: dict[str, str], category: str, title: str, content: str,
        image_content: bytes | None = None, image_extension: str = "",
    ) -> dict[str, Any]:
        role = self._role(actor)
        categories = {"求助", "选课交流", "组队", "吐槽", "校园生活", "其他"}
        if category not in categories:
            raise ValueError("未知帖子分类。")
        title = self._community_text(title, "标题", 80)
        content = self._community_text(content, "正文", 5000)
        image_path = self._save_community_image(image_content, image_extension)
        moderation = self._moderate_content(title + "\n" + content)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO forum_posts (username, role, category, title, content, image_path,"
                " status, moderation_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (actor["username"], role, category, title, content, image_path,
                 moderation["status"], moderation["reason"], self._now()),
            )
            post_id = int(cursor.lastrowid)
        self._audit(actor["username"], role, "forum_post", str(post_id), moderation["status"])
        return {"id": post_id, **moderation}

    def get_forum_posts(
        self, actor: dict[str, str], category: str = "全部", sort: str = "latest"
    ) -> list[dict[str, Any]]:
        self._role(actor)
        where = "(p.status = 'visible' OR p.username = ?)"
        if category != "全部":
            where += " AND p.category = ?"
        order = "p.created_at DESC"
        if sort == "hot":
            order = "like_count DESC, comment_count DESC, p.created_at DESC"
        elif sort == "favorite":
            where += " AND EXISTS (SELECT 1 FROM forum_reactions fr WHERE fr.target_type = 'post'"
            where += " AND fr.target_id = p.id AND fr.reaction = 'favorite' AND fr.username = ?)"
        sql = f"""
            SELECT p.*,
              (SELECT COUNT(*) FROM forum_reactions r WHERE r.target_type='post'
               AND r.target_id=p.id AND r.reaction='like') AS like_count,
              (SELECT COUNT(*) FROM forum_comments c WHERE c.post_id=p.id AND c.status='visible') AS comment_count,
              EXISTS(SELECT 1 FROM forum_reactions r WHERE r.target_type='post'
               AND r.target_id=p.id AND r.reaction='like' AND r.username=?) AS liked,
              EXISTS(SELECT 1 FROM forum_reactions r WHERE r.target_type='post'
               AND r.target_id=p.id AND r.reaction='favorite' AND r.username=?) AS favorited
            FROM forum_posts p WHERE {where} ORDER BY {order} LIMIT ?
        """
        # 前三位参数分别对应当前用户可见性、点赞状态和收藏状态；按 SQL 出现顺序重新排列。
        ordered_params: list[Any] = [actor["username"], actor["username"]]
        if category != "全部":
            ordered_params.append(category)
        if sort == "favorite":
            ordered_params.append(actor["username"])
        ordered_params.insert(0, actor["username"])
        ordered_params.append(200)
        with self._connect() as conn:
            rows = conn.execute(sql, ordered_params).fetchall()
        return [dict(row) for row in rows]

    def add_forum_comment(
        self, actor: dict[str, str], post_id: int, content: str, parent_id: int | None = None
    ) -> dict[str, Any]:
        self._role(actor)
        content = self._community_text(content, "评论", 1500)
        with self._connect() as conn:
            post = conn.execute(
                "SELECT id FROM forum_posts WHERE id = ? AND status = 'visible'", (post_id,)
            ).fetchone()
            if not post:
                raise ValueError("帖子不存在或暂不可评论。")
            if parent_id is not None:
                parent = conn.execute(
                    "SELECT id FROM forum_comments WHERE id = ? AND post_id = ? AND status = 'visible'",
                    (parent_id, post_id),
                ).fetchone()
                if not parent:
                    raise ValueError("要回复的评论不存在。")
        moderation = self._moderate_content(content)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO forum_comments (post_id, parent_id, username, content, status,"
                " moderation_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (post_id, parent_id, actor["username"], content, moderation["status"],
                 moderation["reason"], self._now()),
            )
            comment_id = int(cursor.lastrowid)
        self._audit(actor["username"], actor["role"], "forum_comment", str(comment_id), moderation["status"])
        return {"id": comment_id, **moderation}

    def get_forum_comments(self, actor: dict[str, str], post_id: int) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, post_id, parent_id, username, content, created_at FROM forum_comments"
                " WHERE post_id = ? AND status = 'visible' ORDER BY id ASC LIMIT 500", (post_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def toggle_forum_reaction(
        self, actor: dict[str, str], post_id: int, reaction: str
    ) -> bool:
        self._role(actor)
        if reaction not in {"like", "favorite"}:
            raise ValueError("未知操作。")
        with self._connect() as conn:
            if not conn.execute("SELECT 1 FROM forum_posts WHERE id = ? AND status='visible'", (post_id,)).fetchone():
                raise ValueError("帖子不存在。")
            exists = conn.execute(
                "SELECT 1 FROM forum_reactions WHERE username=? AND target_type='post'"
                " AND target_id=? AND reaction=?", (actor["username"], post_id, reaction)
            ).fetchone()
            if exists:
                conn.execute(
                    "DELETE FROM forum_reactions WHERE username=? AND target_type='post'"
                    " AND target_id=? AND reaction=?", (actor["username"], post_id, reaction)
                )
                active = False
            else:
                conn.execute(
                    "INSERT INTO forum_reactions VALUES (?, 'post', ?, ?, ?)",
                    (actor["username"], post_id, reaction, self._now()),
                )
                active = True
        return active

    def get_moderation_queue(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        self._require_admin(actor)
        result = []
        sources = [
            ("forum_posts", "status", "帖子", "title || '：' || content", "username"),
            ("forum_comments", "status", "评论", "content", "username"),
            ("market_items", "risk_status", "二手商品", "title || '：' || description", "username"),
            ("mood_posts", "status", "树洞", "content", "username"),
            ("private_messages", "status", "私信", "content", "sender"),
        ]
        with self._connect() as conn:
            for table, field, kind, content_sql, user_field in sources:
                condition = "<> 'delivered'" if table == "private_messages" else "<> 'visible'"
                reason_field = "moderation_reason" if table in {"forum_posts", "forum_comments", "mood_posts", "private_messages"} else "risk_reason"
                rows = conn.execute(
                    f"SELECT id, {user_field} AS author, {content_sql} AS content,"
                    f" {field} AS status, {reason_field} AS reason, created_at"
                    f" FROM {table} WHERE {field} {condition} ORDER BY id DESC LIMIT 30"
                ).fetchall()
                for row in rows:
                    result.append({"type": kind, "table": table, **dict(row)})
        return sorted(result, key=lambda item: item["created_at"], reverse=True)[:150]

    def review_moderation_item(
        self, actor: dict[str, str], table: str, item_id: int, approve: bool
    ) -> None:
        self._require_admin(actor)
        settings = {
            "forum_posts": ("status", "visible", "hidden"),
            "forum_comments": ("status", "visible", "hidden"),
            "market_items": ("risk_status", "visible", "hidden"),
            "mood_posts": ("status", "visible", "hidden"),
            "private_messages": ("status", "delivered", "blocked"),
        }
        if table not in settings:
            raise ValueError("不支持的审核对象。")
        field, approved, rejected = settings[table]
        value = approved if approve else rejected
        with self._connect() as conn:
            cursor = conn.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (value, item_id))
        if cursor.rowcount == 0:
            raise ValueError("审核对象不存在。")
        self._audit(actor["username"], actor["role"], "moderation_review", f"{table}/{item_id}", value)

    # ---------- 失物招领、二手交易与站内私信 ----------

    def create_lost_found_item(
        self, actor: dict[str, str], kind: str, category: str, title: str,
        description: str, location: str, happened_at: str,
    ) -> int:
        self._role(actor)
        if kind not in {"lost", "found"}:
            raise ValueError("请选择“丢失”或“捡到”。")
        if category not in {"校园卡", "书籍", "雨伞", "电子产品", "证件钥匙", "其他"}:
            raise ValueError("未知物品分类。")
        title = self._community_text(title, "物品名称", 80)
        description = self._community_text(description, "物品描述", 1500)
        location = self._community_text(location, "地点", 120)
        happened_at = self._community_text(happened_at, "日期", 30)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO lost_found_items (username, kind, category, title, description,"
                " location, happened_at, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
                (actor["username"], kind, category, title, description, location,
                 happened_at, self._now()),
            )
            item_id = int(cursor.lastrowid)
        self._audit(actor["username"], actor["role"], "lost_found_create", str(item_id), kind)
        return item_id

    def get_lost_found_items(
        self, actor: dict[str, str], kind: str = "all", include_resolved: bool = False
    ) -> list[dict[str, Any]]:
        self._role(actor)
        sql = "SELECT * FROM lost_found_items WHERE 1=1"
        params: list[Any] = []
        if kind in {"lost", "found"}:
            sql += " AND kind = ?"
            params.append(kind)
        if not include_resolved:
            sql += " AND status = 'open'"
        sql += " ORDER BY created_at DESC LIMIT 300"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def set_lost_found_status(
        self, actor: dict[str, str], item_id: int, status: str
    ) -> None:
        self._role(actor)
        if status not in {"open", "resolved"}:
            raise ValueError("未知物品状态。")
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE lost_found_items SET status=? WHERE id=? AND username=?",
                (status, item_id, actor["username"]),
            )
        if cursor.rowcount == 0:
            raise PermissionError("只能修改自己发布的物品信息。")
        self._audit(actor["username"], actor["role"], "lost_found_status", str(item_id), status)

    def create_market_item(
        self, actor: dict[str, str], title: str, category: str, price: float, description: str
    ) -> dict[str, Any]:
        self._role(actor)
        if category not in {"教材书籍", "数码产品", "交通工具", "生活用品", "其他"}:
            raise ValueError("未知商品分类。")
        title = self._community_text(title, "商品名称", 80)
        description = self._community_text(description, "商品描述", 2000)
        try:
            price_value = round(float(price), 2)
        except (TypeError, ValueError) as exc:
            raise ValueError("价格必须是数字。") from exc
        if not 0 <= price_value <= 1_000_000:
            raise ValueError("价格应在 0 到 1000000 元之间。")
        moderation = self._moderate_content(title + "\n" + description)
        reasons = [moderation["reason"]] if moderation["reason"] else []
        if any(word in title + description for word in ("处方药", "管制刀具", "假证", "代考")):
            moderation["status"] = "blocked"
            reasons.append("疑似违规物品或服务")
        moderation["reason"] = "；".join(reason for reason in reasons if reason)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO market_items (username, title, category, price, description, status,"
                " risk_status, risk_reason, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (actor["username"], title, category, price_value, description,
                 moderation["status"], moderation["reason"], self._now()),
            )
            item_id = int(cursor.lastrowid)
        self._audit(actor["username"], actor["role"], "market_create", str(item_id), moderation["status"])
        return {"id": item_id, **moderation}

    def get_market_items(self, actor: dict[str, str], include_closed: bool = False) -> list[dict[str, Any]]:
        self._role(actor)
        where = "(risk_status='visible' OR username=?)"
        params: list[Any] = [actor["username"]]
        if not include_closed:
            where += " AND (status='active' OR username=?)"
            params.append(actor["username"])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM market_items WHERE {where} ORDER BY created_at DESC LIMIT 300", params
            ).fetchall()
        return [dict(row) for row in rows]

    def set_market_status(self, actor: dict[str, str], item_id: int, status: str) -> None:
        self._role(actor)
        if status not in {"active", "sold", "closed"}:
            raise ValueError("未知商品状态。")
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE market_items SET status=? WHERE id=? AND username=?",
                (status, item_id, actor["username"]),
            )
        if cursor.rowcount == 0:
            raise PermissionError("只能修改自己发布的商品。")
        self._audit(actor["username"], actor["role"], "market_status", str(item_id), status)

    def send_private_message(
        self, actor: dict[str, str], recipient: str, content: str
    ) -> dict[str, Any]:
        self._role(actor)
        recipient = self._community_text(recipient, "收件人", 80)
        content = self._community_text(content, "私信内容", 2000)
        if recipient == actor["username"]:
            raise ValueError("不能给自己发送私信。")
        with self._connect() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE username=?", (recipient,)).fetchone():
                raise ValueError("收件人不存在。")
        # 私信采用实时规则风控，避免把私人内容额外交给生成模型；命中项进入管理员复核队列。
        moderation = self._moderate_content(content, use_ai=False)
        message_status = "delivered" if moderation["status"] == "visible" else moderation["status"]
        moderation["status"] = message_status
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO private_messages (sender, recipient, content, status, moderation_reason,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (actor["username"], recipient, content, message_status,
                 moderation["reason"], self._now()),
            )
            message_id = int(cursor.lastrowid)
        self._audit(actor["username"], actor["role"], "private_message", str(message_id), moderation["status"])
        return {"id": message_id, **moderation}

    def get_private_messages(
        self, actor: dict[str, str], peer: str | None = None
    ) -> list[dict[str, Any]]:
        self._role(actor)
        params: list[Any] = [actor["username"], actor["username"]]
        where = "status='delivered' AND (sender=? OR recipient=?)"
        if peer:
            where += " AND ((sender=? AND recipient=?) OR (sender=? AND recipient=?))"
            params.extend([actor["username"], peer, peer, actor["username"]])
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM private_messages WHERE {where} ORDER BY id ASC LIMIT 500", params
            ).fetchall()
            conn.execute(
                "UPDATE private_messages SET read_at=? WHERE recipient=? AND read_at IS NULL AND status='delivered'",
                (self._now(), actor["username"]),
            )
        return [dict(row) for row in rows]

    def get_message_peers(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT CASE WHEN sender=? THEN recipient ELSE sender END AS peer,"
                " MAX(created_at) AS latest_at, SUM(CASE WHEN recipient=? AND read_at IS NULL THEN 1 ELSE 0 END) AS unread"
                " FROM private_messages WHERE status='delivered' AND (sender=? OR recipient=?)"
                " GROUP BY peer ORDER BY latest_at DESC",
                (actor["username"], actor["username"], actor["username"], actor["username"]),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- 课表、上课提醒与空教室参考 ----------

    @staticmethod
    def _valid_hhmm(value: str, label: str) -> str:
        value = str(value).strip()
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError(f"{label}必须使用 HH:MM 格式。") from exc
        return value

    def add_schedule_entry(
        self, actor: dict[str, str], course_name: str, weekday: int,
        start_time: str, end_time: str, location: str = "", teacher: str = "",
    ) -> int:
        self._role(actor)
        course_name = self._community_text(course_name, "课程名称", 100)
        weekday = int(weekday)
        if weekday not in range(1, 8):
            raise ValueError("星期必须在 1 到 7 之间。")
        start_time = self._valid_hhmm(start_time, "开始时间")
        end_time = self._valid_hhmm(end_time, "结束时间")
        if start_time >= end_time:
            raise ValueError("结束时间必须晚于开始时间。")
        location = self._community_text(location, "上课地点", 100, required=False)
        teacher = self._community_text(teacher, "教师", 60, required=False)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO schedule_entries (username, course_name, weekday, start_time, end_time,"
                " location, teacher, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (actor["username"], course_name, weekday, start_time, end_time,
                 location, teacher, self._now()),
            )
            entry_id = int(cursor.lastrowid)
        return entry_id

    @staticmethod
    def _schedule_day(value: Any) -> int | None:
        """识别表头或单元格中的星期，不把课程编号中的数字当作星期。"""
        text = re.sub(r"\s+", "", str(value or ""))
        if re.fullmatch(r"[1-7]", text):
            return int(text)
        match = re.search(r"(?:星期|周)([一二三四五六日天1-7])", text)
        if not match:
            return None
        token = match.group(1)
        if token.isdigit():
            return int(token)
        return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}[token]

    @classmethod
    def _schedule_day_in_line(cls, line: str) -> int | None:
        day = cls._schedule_day(line)
        if day:
            return day
        match = re.search(r"(?<![\w.])([1-7])(?![\w.])", line)
        return int(match.group(1)) if match else None

    @staticmethod
    def _schedule_times(text: str) -> list[tuple[int, int, str]]:
        result = []
        pattern = r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)"
        for match in re.finditer(pattern, str(text or "")):
            value = f"{int(match.group(1)):02d}:{match.group(2)}"
            result.append((match.start(), match.end(), value))
        return result

    @staticmethod
    def _schedule_course_name(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = re.sub(r"^(?:课程名称|课程名|课程)\s*[:：]", "", text)
        text = re.sub(r"(?:星期|周)[一二三四五六日天1-7]", " ", text)
        text = re.sub(r"第\s*\d+\s*[-—–~至]\s*\d+\s*周", " ", text)
        text = re.sub(r"(?:单周|双周|周次\s*[:：]?\s*[\d\-—–~至]+)", " ", text)
        text = re.sub(r"^\d+\s+(?=[\u4e00-\u9fffA-Za-z])", "", text)
        text = text.strip(" |｜,，;；-—–")
        if not 2 <= len(text) <= 100 or text in {"课程", "课程名称", "课程名", "无", "暂无"}:
            return ""
        if not re.search(r"[\u4e00-\u9fffA-Za-z]", text):
            return ""
        return text

    @classmethod
    def _schedule_cell_details(cls, content: Any) -> tuple[str, str, str]:
        """从周视图单元格提取课程、地点和教师；不确定的可选字段留空。"""
        lines = [re.sub(r"\s+", " ", line).strip() for line in re.split(r"[\n\r]+", str(content or "")) if line.strip()]
        teacher = ""
        location = ""
        course = ""
        for line in lines:
            compact = line.strip()
            if not teacher and re.search(r"教师|老师|教授|讲师", compact):
                candidate = re.sub(r"^(?:任课)?(?:教师|老师)\s*[:：]?", "", compact).strip()
                teacher = candidate[:60]
                continue
            if not location and (
                re.search(r"教室|教学楼|实验楼|图书馆|体育馆|活动中心|中心|[A-Za-z]\d{3,4}", compact)
            ):
                location = compact[:100]
                continue
            if re.search(r"第\s*\d+\s*[-—–~至]?\s*\d*\s*周|单周|双周|周次", compact):
                continue
            if cls._schedule_times(compact) and len(cls._schedule_times(compact)) >= 2:
                continue
            if not course:
                course = cls._schedule_course_name(compact)
        return course, location, teacher

    def _parse_schedule_table(
        self, table: list[list[Any]], page_number: int, table_number: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """解析按课程排列的表格，以及星期按列排列的周视图表格。"""
        rows = [
            [re.sub(r"[ \t]+", " ", str(cell or "")).strip() for cell in row]
            for row in (table or []) if row
        ]
        if len(rows) < 2:
            return [], []
        entries: list[dict[str, Any]] = []
        errors: list[str] = []

        def find_column(headers: list[str], aliases: tuple[str, ...]) -> int | None:
            for index, header in enumerate(headers):
                compact = re.sub(r"\s+", "", header)
                if any(compact == alias or alias in compact for alias in aliases):
                    return index
            return None

        for header_index, headers in enumerate(rows):
            course_col = find_column(headers, ("课程名称", "课程名", "课程"))
            day_col = find_column(headers, ("上课星期", "星期几", "星期"))
            start_col = find_column(headers, ("开始时间", "起始时间", "上课开始"))
            end_col = find_column(headers, ("结束时间", "截止时间", "下课时间"))
            time_col = find_column(headers, ("上课时间", "节次时间", "时间"))
            if course_col is None or day_col is None or (time_col is None and (start_col is None or end_col is None)):
                continue
            location_col = find_column(headers, ("上课地点", "教室", "地点"))
            teacher_col = find_column(headers, ("任课教师", "教师", "老师"))
            last_day = None
            for row_index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
                def cell(index: int | None) -> str:
                    return row[index] if index is not None and index < len(row) else ""

                course = self._schedule_course_name(cell(course_col))
                last_day = self._schedule_day(cell(day_col)) or last_day
                if not course and not any(row):
                    continue
                time_text = (
                    f"{cell(start_col)} {cell(end_col)}"
                    if start_col is not None and end_col is not None else cell(time_col)
                )
                times = self._schedule_times(time_text)
                if not course or not last_day or len(times) < 2:
                    if any(row):
                        errors.append(f"第 {page_number} 页表格 {table_number} 第 {row_index} 行：缺少课程名、星期或具体起止时间。")
                    continue
                entries.append({
                    "course_name": course, "weekday": last_day,
                    "start_time": times[0][2], "end_time": times[1][2],
                    "location": cell(location_col)[:100], "teacher": cell(teacher_col)[:60],
                    "source_page": page_number,
                })
            return entries, errors

        # 周视图：表头包含至少两个“星期X”，每行第一列给出具体时间。
        for header_index, headers in enumerate(rows):
            day_columns = [(index, self._schedule_day(cell)) for index, cell in enumerate(headers)]
            day_columns = [(index, day) for index, day in day_columns if day]
            if len(day_columns) < 2:
                continue
            last_times: list[tuple[int, int, str]] = []
            for row_index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
                first_cell = row[0] if row else ""
                row_times = self._schedule_times(first_cell)
                if len(row_times) >= 2:
                    last_times = row_times[:2]
                elif first_cell:
                    last_times = []
                for column, day in day_columns:
                    content = row[column] if column < len(row) else ""
                    if not content.strip():
                        continue
                    course, location, teacher = self._schedule_cell_details(content)
                    if not course:
                        continue
                    if len(last_times) < 2:
                        message = f"第 {page_number} 页表格 {table_number} 第 {row_index} 行：{course} 缺少具体起止时间。"
                        if message not in errors:
                            errors.append(message)
                        continue
                    entries.append({
                        "course_name": course, "weekday": day,
                        "start_time": last_times[0][2], "end_time": last_times[1][2],
                        "location": location, "teacher": teacher, "source_page": page_number,
                    })
            return entries, errors
        return [], []

    def _parse_schedule_text(self, text: str, page_number: int) -> tuple[list[dict[str, Any]], list[str]]:
        """从普通文字 PDF 或 OCR 结果中识别一行一门课的记录。"""
        entries: list[dict[str, Any]] = []
        errors: list[str] = []
        current_day = None
        pending_lines: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = re.sub(r"[\u00a0\u3000]", " ", raw_line).strip()
            if not line:
                continue
            if "课程" in line and "星期" in line and "时间" in line:
                continue
            explicit_day = self._schedule_day_in_line(line)
            current_day = explicit_day or current_day
            day = explicit_day or current_day
            times = self._schedule_times(line)
            if len(times) < 2:
                if not re.search(r"星期|周[一二三四五六日天]|节次|时间", line):
                    pending_lines = (pending_lines + [line])[-2:]
                continue
            first, second = times[0], times[1]
            before = line[:first[0]]
            after = line[second[1]:]
            before = re.sub(r"(?:星期|周)\s*[一二三四五六日天1-7]", " ", before)
            if not self._schedule_day(line):
                before = re.sub(r"(?<![\w.])[1-7](?![\w.])", " ", before)
            course = self._schedule_course_name(before)
            parts = [part.strip() for part in re.split(r"\s*[|｜]\s*|\t+|\s{2,}", after) if part.strip()]
            if len(parts) <= 1:
                parts = after.split()
            if not course and parts:
                course = self._schedule_course_name(parts.pop(0))
            if not course and pending_lines:
                course = self._schedule_course_name(pending_lines[-1])
            if not course or not day:
                errors.append(f"第 {page_number} 页：一条含时间的记录缺少课程名或星期，未导入。")
                continue
            location = parts[0][:100] if parts else ""
            teacher = parts[1][:60] if len(parts) > 1 else ""
            entries.append({
                "course_name": course, "weekday": day,
                "start_time": first[2], "end_time": second[2],
                "location": location, "teacher": teacher, "source_page": page_number,
            })
            pending_lines = []
        return entries, errors

    def parse_schedule_pdf(
        self, actor: dict[str, str], content: bytes, use_ocr: bool = False
    ) -> dict[str, Any]:
        """本地解析 PDF，仅返回预览；确认后才写入个人课表。"""
        self._role(actor)
        if not content:
            raise ValueError("PDF 文件为空。")
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("课表 PDF 不能超过 20 MB。")
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ValueError("暂不支持加密 PDF，请先解除密码保护。")
            page_count = len(reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("PDF 无法读取，请确认文件未损坏，并且确实是 PDF 格式。") from exc
        if page_count > 30:
            raise ValueError("课表 PDF 最多支持 30 页，请拆分后再导入。")

        try:
            import pdfplumber
        except ImportError:
            pdfplumber = None

        entries: list[dict[str, Any]] = []
        errors: list[str] = []
        warnings: list[str] = []
        ocr_pages: list[int] = []
        text_pages = 0
        if pdfplumber is None:
            warnings.append("未安装 pdfplumber，复杂表格可能无法完整识别；可运行 python -m pip install pdfplumber 增强识别。")

        with tempfile.TemporaryDirectory(prefix="campus_schedule_") as temp_dir:
            temp_pdf = Path(temp_dir) / "schedule.pdf"
            if use_ocr:
                temp_pdf.write_bytes(content)
            for page_index in range(page_count):
                page_number = page_index + 1
                page_entries: list[dict[str, Any]] = []
                text = ""
                if pdfplumber is not None:
                    try:
                        with pdfplumber.open(io.BytesIO(content)) as pdf:
                            page = pdf.pages[page_index]
                            for table_number, table in enumerate(page.extract_tables() or [], start=1):
                                found, table_errors = self._parse_schedule_table(table, page_number, table_number)
                                page_entries.extend(found)
                                errors.extend(table_errors)
                            try:
                                text = page.extract_text(layout=True) or ""
                            except TypeError:
                                text = page.extract_text() or ""
                    except Exception as exc:
                        warnings.append(f"第 {page_number} 页表格读取失败，已尝试普通文字识别：{exc}")
                if not text:
                    try:
                        text = reader.pages[page_index].extract_text(extraction_mode="layout") or ""
                    except (TypeError, ValueError):
                        text = reader.pages[page_index].extract_text() or ""
                    except Exception:
                        text = ""
                if len(re.sub(r"\s+", "", text)) >= 2:
                    text_pages += 1
                if use_ocr and len(re.sub(r"\s+", "", text)) < 20:
                    ocr_text = self._ocr_pdf_page(temp_pdf, page_index).strip()
                    if ocr_text:
                        text = ocr_text
                        page_entries = []
                        ocr_pages.append(page_number)
                if not page_entries and text:
                    page_entries, text_errors = self._parse_schedule_text(text, page_number)
                    errors.extend(text_errors)
                entries.extend(page_entries)
                if not text and not use_ocr:
                    warnings.append(f"第 {page_number} 页没有可读取文字；如果是扫描件，请勾选本地 OCR。")

        # 表格和普通文字可能识别到同一课程，按课程、星期和时间合并。
        merged: dict[tuple[Any, ...], dict[str, Any]] = {}
        for entry in entries:
            key = (entry["course_name"], entry["weekday"], entry["start_time"], entry["end_time"])
            if key not in merged:
                merged[key] = entry
            else:
                for field in ("location", "teacher"):
                    if not merged[key].get(field) and entry.get(field):
                        merged[key][field] = entry[field]
        result_entries = list(merged.values())
        if len(result_entries) > 500:
            result_entries = result_entries[:500]
            warnings.append("最多预览 500 条课程，其余课程未处理。")
        if not result_entries:
            warnings.append("没有识别出完整课程。PDF 需包含课程名、星期和具体起止时间；也可以下载 CSV 模板整理后导入。")
        return {
            "entries": result_entries, "errors": errors[:100], "warnings": list(dict.fromkeys(warnings)),
            "pages": page_count, "text_pages": text_pages, "ocr_pages": ocr_pages,
        }

    def import_schedule_entries(
        self, actor: dict[str, str], entries: list[dict[str, Any]], source: str = "PDF"
    ) -> dict[str, Any]:
        """导入已解析课程，并跳过当前账户已有的同课程、同星期、同时间记录。"""
        self._role(actor)
        success = 0
        duplicates = 0
        errors: list[str] = []
        existing = {
            (row["course_name"], row["weekday"], row["start_time"], row["end_time"])
            for row in self.get_schedule(actor)
        }
        for index, entry in enumerate(entries[:500], start=1):
            try:
                course = str(entry.get("course_name", "")).strip()
                day = int(entry.get("weekday", 0))
                start = self._valid_hhmm(str(entry.get("start_time", "")), "开始时间")
                end = self._valid_hhmm(str(entry.get("end_time", "")), "结束时间")
                key = (course, day, start, end)
                if key in existing:
                    duplicates += 1
                    continue
                self.add_schedule_entry(
                    actor, course, day, start, end,
                    str(entry.get("location", "") or ""), str(entry.get("teacher", "") or ""),
                )
                existing.add(key)
                success += 1
            except Exception as exc:
                errors.append(f"第 {index} 条：{exc}")
        if len(entries) > 500:
            errors.append("最多导入 500 条课程，其余课程未处理。")
        self._audit(
            actor["username"], actor["role"], "schedule_import",
            detail=f"{source}：成功 {success}，重复 {duplicates}，失败 {len(errors)}",
        )
        return {"success": success, "duplicates": duplicates, "errors": errors}

    def import_schedule_pdf(
        self, actor: dict[str, str], content: bytes, use_ocr: bool = False
    ) -> dict[str, Any]:
        preview = self.parse_schedule_pdf(actor, content, use_ocr=use_ocr)
        result = self.import_schedule_entries(actor, preview["entries"], source="PDF")
        result["errors"] = preview["errors"] + result["errors"]
        result["warnings"] = preview["warnings"]
        return result

    def import_schedule_csv(self, actor: dict[str, str], content: bytes) -> dict[str, Any]:
        self._role(actor)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("课表 CSV 不能超过 2 MB。")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("请使用 UTF-8 编码的 CSV 文件。") from exc
        reader = csv.DictReader(io.StringIO(text))
        required = {"课程", "星期", "开始时间", "结束时间"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("CSV 表头必须包含：课程、星期、开始时间、结束时间；地点和教师可选。")
        success = 0
        errors = []
        for index, row in enumerate(reader, start=2):
            if index > 502:
                errors.append("最多导入 500 条课程，其余行未处理。")
                break
            try:
                self.add_schedule_entry(
                    actor, row.get("课程", ""), int(str(row.get("星期", "")).strip()),
                    row.get("开始时间", ""), row.get("结束时间", ""),
                    row.get("地点", "") or "", row.get("教师", "") or "",
                )
                success += 1
            except Exception as exc:
                errors.append(f"第 {index} 行：{exc}")
        self._audit(actor["username"], actor["role"], "schedule_import", detail=f"成功 {success}，失败 {len(errors)}")
        return {"success": success, "errors": errors}

    def get_schedule(self, actor: dict[str, str], weekday: int | None = None) -> list[dict[str, Any]]:
        self._role(actor)
        sql = "SELECT * FROM schedule_entries WHERE username=?"
        params: list[Any] = [actor["username"]]
        if weekday in range(1, 8):
            sql += " AND weekday=?"
            params.append(weekday)
        sql += " ORDER BY weekday, start_time, id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def delete_schedule_entry(self, actor: dict[str, str], entry_id: int) -> None:
        self._role(actor)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM schedule_entries WHERE id=? AND username=?", (entry_id, actor["username"])
            )
        if cursor.rowcount == 0:
            raise PermissionError("只能删除自己的课程。")

    def get_upcoming_classes(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        now = datetime.now()
        today = now.isoweekday()
        current = now.strftime("%H:%M")
        result = []
        for entry in self.get_schedule(actor, today):
            if entry["start_time"] >= current:
                start_dt = datetime.strptime(entry["start_time"], "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                result.append({**entry, "minutes": max(0, int((start_dt - now).total_seconds() // 60))})
        return result

    def find_free_rooms(
        self, actor: dict[str, str], weekday: int, start_time: str, end_time: str
    ) -> dict[str, Any]:
        self._role(actor)
        start_time = self._valid_hhmm(start_time, "开始时间")
        end_time = self._valid_hhmm(end_time, "结束时间")
        if start_time >= end_time:
            raise ValueError("结束时间必须晚于开始时间。")
        if int(weekday) not in range(1, 8):
            raise ValueError("星期无效。")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT location, start_time, end_time FROM schedule_entries"
                " WHERE weekday=? AND location != ''", (int(weekday),)
            ).fetchall()
        rooms = sorted({row["location"] for row in rows})
        occupied = sorted({
            row["location"] for row in rows
            if row["start_time"] < end_time and row["end_time"] > start_time
        })
        return {"rooms": rooms, "occupied": occupied,
                "free": [room for room in rooms if room not in occupied]}

    # ---------- 校园活动报名 ----------

    def create_activity(
        self, actor: dict[str, str], title: str, description: str, location: str,
        starts_at: str, ends_at: str, capacity: int,
    ) -> int:
        self._require_admin(actor)
        title = self._community_text(title, "活动名称", 100)
        description = self._community_text(description, "活动介绍", 3000)
        location = self._community_text(location, "活动地点", 120)
        try:
            start = datetime.fromisoformat(starts_at)
            end = datetime.fromisoformat(ends_at)
        except ValueError as exc:
            raise ValueError("活动时间格式无效。") from exc
        if end <= start:
            raise ValueError("活动结束时间必须晚于开始时间。")
        capacity = int(capacity)
        if not 1 <= capacity <= 100000:
            raise ValueError("活动人数应在 1 到 100000 之间。")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO activities (title, description, location, starts_at, ends_at, capacity,"
                " created_by, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'published', ?)",
                (title, description, location, starts_at, ends_at, capacity,
                 actor["username"], self._now()),
            )
            activity_id = int(cursor.lastrowid)
        self._audit(actor["username"], actor["role"], "activity_create", str(activity_id), title)
        return activity_id

    def get_activities(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.*, COUNT(e.username) AS enrolled_count,"
                " EXISTS(SELECT 1 FROM activity_enrollments x WHERE x.activity_id=a.id AND x.username=?) AS enrolled"
                " FROM activities a LEFT JOIN activity_enrollments e ON e.activity_id=a.id"
                " GROUP BY a.id ORDER BY a.starts_at DESC", (actor["username"],)
            ).fetchall()
        return [dict(row) for row in rows]

    def enroll_activity(self, actor: dict[str, str], activity_id: int) -> None:
        self._role(actor)
        with self._connect() as conn:
            activity = conn.execute(
                "SELECT * FROM activities WHERE id=? AND status='published'", (activity_id,)
            ).fetchone()
            if not activity:
                raise ValueError("活动不存在或已取消。")
            if datetime.fromisoformat(activity["ends_at"]) < datetime.now():
                raise ValueError("活动已结束，不能继续报名。")
            count = conn.execute(
                "SELECT COUNT(*) FROM activity_enrollments WHERE activity_id=?", (activity_id,)
            ).fetchone()[0]
            if count >= activity["capacity"]:
                raise ValueError("活动名额已满。")
            try:
                conn.execute(
                    "INSERT INTO activity_enrollments VALUES (?, ?, ?)",
                    (activity_id, actor["username"], self._now()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("你已经报名过该活动。") from exc
        self._audit(actor["username"], actor["role"], "activity_enroll", str(activity_id))

    def cancel_activity_enrollment(self, actor: dict[str, str], activity_id: int) -> None:
        self._role(actor)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM activity_enrollments WHERE activity_id=? AND username=?",
                (activity_id, actor["username"]),
            )
        if cursor.rowcount == 0:
            raise ValueError("你没有报名该活动。")
        self._audit(actor["username"], actor["role"], "activity_cancel_enrollment", str(activity_id))

    def set_activity_status(self, actor: dict[str, str], activity_id: int, status: str) -> None:
        self._require_admin(actor)
        if status not in {"published", "cancelled"}:
            raise ValueError("未知活动状态。")
        with self._connect() as conn:
            cursor = conn.execute("UPDATE activities SET status=? WHERE id=?", (status, activity_id))
        if cursor.rowcount == 0:
            raise ValueError("活动不存在。")

    def get_activity_participants(self, actor: dict[str, str], activity_id: int) -> list[dict[str, str]]:
        self._require_admin(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT e.username, u.role, e.created_at FROM activity_enrollments e"
                " LEFT JOIN users u ON u.username=e.username WHERE e.activity_id=? ORDER BY e.created_at",
                (activity_id,),
            ).fetchall()
        return [{"username": row["username"], "role": ROLE_NAMES.get(row["role"], row["role"]),
                 "created_at": row["created_at"]} for row in rows]

    # ---------- 本地 AI 学业规划 ----------

    def generate_study_plan(
        self, actor: dict[str, str], grade: str, major: str, goal: str
    ) -> dict[str, Any]:
        self._role(actor)
        grade = self._community_text(grade, "年级", 30)
        major = self._community_text(major, "专业", 80)
        goal = self._community_text(goal, "目标", 80)
        sources = []
        try:
            retrieval = self.retrieve(actor, f"{major} {goal} 培养方案 课程 竞赛 证书 就业", top_k=4)
            for index, entry in enumerate(retrieval["entries"], start=1):
                doc = entry["doc"]
                evidence, _, _ = self._evidence(doc, f"{major} {goal}")
                sources.append({"id": index, "source": doc.metadata.get("source", ""),
                                "page": doc.metadata.get("page"), "evidence": evidence,
                                "content": doc.page_content[:1200]})
        except Exception:
            sources = []
        prompt = f"""请为学生生成一份可执行的学业规划表。通用建议可以基于常识，但涉及本校课程、绩点、证书或竞赛要求时只能引用所给资料，不得编造。
年级：{grade}；专业：{major}；目标：{goal}
请输出 Markdown 表格，列为“阶段｜学习重点｜具体行动｜检查方式”，至少4行；表格后补充3条本学期可执行任务。
不要承诺保研、录取或就业结果，不要把通用建议写成学校硬性规定。
本校资料：
{chr(10).join(f"[资料{s['id']}] {s['content']}" for s in sources) if sources else '暂无本校相关资料，请只给通用建议。'}
"""
        notice = ""
        try:
            plan = str(self.llm.invoke(prompt)).strip()
            if len(plan) < 100 or "|" not in plan:
                raise ValueError("模型没有返回完整规划表")
            plan = plan[:6500]
        except Exception as exc:
            notice = f"本地模型未能生成完整规划，已提供通用模板：{exc}"
            plan = (
                "| 阶段 | 学习重点 | 具体行动 | 检查方式 |\n|---|---|---|---|\n"
                f"| 第1个月 | 明确{goal}目标 | 整理当前课程、能力和时间，确定一个主目标 | 写出一页目标清单 |\n"
                "| 第2—3个月 | 打牢专业基础 | 每周安排固定学习时间，补齐核心课程薄弱点 | 每周复盘一次完成情况 |\n"
                "| 第4—5个月 | 项目或实践 | 完成一个与专业相关的小项目或实践作品 | 保留代码、报告或作品记录 |\n"
                "| 第6个月 | 总结与调整 | 对照目标检查差距，安排下一阶段任务 | 更新一次规划表 |\n\n"
                "本学期可执行：1. 每周固定三次专业学习。2. 每月完成一次成果总结。3. 向教师或辅导员核对本校具体要求。"
            )
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO study_plans (username, grade, major, goal, plan_text, model, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (actor["username"], grade, major, goal, plan, self.llm_model, self._now()),
            )
            plan_id = int(cursor.lastrowid)
        self._audit(actor["username"], actor["role"], "study_plan", str(plan_id), goal)
        return {"id": plan_id, "plan": plan, "sources": sources, "notice": notice}

    def get_study_plans(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM study_plans WHERE username=? ORDER BY id DESC LIMIT 50",
                (actor["username"],),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- 匿名树洞与心情记录（不做医疗诊断） ----------

    def create_mood_post(self, actor: dict[str, str], content: str) -> dict[str, Any]:
        self._role(actor)
        content = self._community_text(content, "树洞内容", 2000)
        moderation = self._moderate_content(content)
        if re.search(r"自杀|不想活|伤害自己|结束生命|自残", content):
            moderation["status"] = "review"
            moderation["reason"] = "；".join(filter(None, [moderation["reason"], "包含可能的自伤内容，暂不公开"]))
            moderation["crisis"] = True
            moderation["support_message"] = (
                "你的安全比发帖更重要。请现在联系一位可信任的人陪着你，并尽快联系学校心理中心或专业医疗机构；"
                "如果有即时危险，请立即拨打当地急救或报警电话（中国大陆可拨打 120 或 110）。"
            )
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO mood_posts (username, content, status, moderation_reason, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (actor["username"], content, moderation["status"], moderation["reason"], self._now()),
            )
            post_id = int(cursor.lastrowid)
        return {"id": post_id, **moderation}

    def get_mood_posts(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, content, created_at FROM mood_posts WHERE status='visible'"
                " ORDER BY id DESC LIMIT 200"
            ).fetchall()
        return [{**dict(row), "alias": f"匿名同学 {row['id']:04d}"} for row in rows]

    def create_mood_checkin(
        self, actor: dict[str, str], mood_score: int, note: str = ""
    ) -> dict[str, Any]:
        self._role(actor)
        mood_score = int(mood_score)
        if mood_score not in range(1, 6):
            raise ValueError("心情分值应在 1 到 5 之间。")
        note = self._community_text(note, "心情记录", 1000, required=False)
        crisis = bool(re.search(r"自杀|不想活|伤害自己|结束生命|自残", note))
        if crisis:
            response = (
                "你刚才的文字可能表示你正处在强烈痛苦中。请现在就联系一位可信任的人陪着你，"
                "并尽快联系学校心理中心或专业医疗机构；如果有即时危险，请立即拨打当地急救或报警电话"
                "（中国大陆可拨打 120 或 110）。这里不能替代专业帮助，也不需要你独自承担。"
            )
        else:
            fallback = (
                "谢谢你记录此刻的感受。可以先做一次缓慢呼吸、喝点水，并把今天最需要完成的一件事缩小到十分钟。"
                if mood_score <= 2 else "谢谢你记录此刻的感受。可以留意今天让你感觉稍好一点的小事，并保持规律作息。"
            )
            prompt = f"""请用中文写一段80字以内的支持性回应，温和、具体、不评判。
不能诊断抑郁、焦虑或任何疾病，不能承诺保密或24小时陪伴，不要替代专业心理服务。
心情评分1到5分，本次为{mood_score}分。记录：{note[:800] or '未填写'}
"""
            try:
                response = str(self.llm.invoke(prompt)).strip()[:600]
                if len(response) < 10:
                    response = fallback
            except Exception:
                response = fallback
            if mood_score <= 2:
                response += " 如果低落持续影响生活，建议联系可信任的人、学校心理中心或专业医疗机构。"
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO mood_checkins (username, mood_score, note, response, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (actor["username"], mood_score, note, response, self._now()),
            )
            checkin_id = int(cursor.lastrowid)
        return {"id": checkin_id, "response": response, "crisis": crisis}

    def get_mood_checkins(self, actor: dict[str, str]) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mood_checkins WHERE username=? ORDER BY id DESC LIMIT 100",
                (actor["username"],),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- 历史、CSV 与审计查询 ----------

    def get_qa_records(self, actor: dict[str, str], limit: int = 30) -> list[dict[str, Any]]:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM qa_records WHERE username = ? ORDER BY id DESC LIMIT ?",
                (actor["username"], max(1, min(limit, 200))),
            ).fetchall()
        records = []
        for row in rows:
            records.append({
                "id": row["id"],
                "created_at": row["created_at"],
                "question": row["question"],
                "resolved_question": row["resolved_question"] or row["question"],
                "answer": row["answer"],
                "sources": json.loads(row["sources_json"]),
                "confidence": int(row["confidence"]),
                "trust_score": int(row["trust_score"]),
                "trust_explanation": row["trust_explanation"],
                "model": row["model"],
                "retrieval_mode": row["retrieval_mode"],
                "rerank_used": bool(row["rerank_used"]),
                "feedback": row["feedback"],
                "feedback_at": row["feedback_at"],
            })
        return records

    def set_feedback(self, actor: dict[str, str], record_id: int, feedback: str) -> None:
        self._role(actor)
        if feedback not in {"useful", "useless"}:
            raise ValueError("未知反馈类型。")
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE qa_records SET feedback = ?, feedback_at = ?"
                " WHERE id = ? AND username = ?",
                (feedback, self._now(), record_id, actor["username"]),
            )
        if cursor.rowcount == 0:
            raise PermissionError("只能评价自己的问答记录。")
        self._audit(
            actor["username"], actor["role"], "answer_feedback",
            str(record_id), "有用" if feedback == "useful" else "无用",
        )

    @staticmethod
    def _csv_safe(value: Any) -> str:
        """避免用户文本在 Excel 中被当作公式执行。"""
        text = str(value)
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    @staticmethod
    def _watermark(username: str) -> str:
        """将当前用户 ID 编码为零宽字符，附加到导出内容中用于溯源。"""
        bits = "".join(f"{byte:08b}" for byte in username.encode("utf-8"))
        return "\u2063" + "".join("\u200b" if bit == "0" else "\u200c" for bit in bits) + "\u2063"

    def export_qa_csv(self, actor: dict[str, str]) -> bytes:
        self._role(actor)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM qa_records WHERE username = ? ORDER BY id ASC",
                (actor["username"],),
            ).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([
            "时间", "用户名", "角色", "问题", "回答", "置信度",
            "模型", "检索模式", "Rerank", "反馈", "原文来源",
        ])
        for row in rows:
            sources = json.loads(row["sources_json"])
            source_text = "\n".join(
                f"[资料{s['id']}] {s['group_name']}/{s['source']}"
                + (f" 第{s['page']}页" if s.get("page") else "")
                + f" 切片{s.get('chunk', '')}\n{s.get('evidence', s['content'])}"
                for s in sources
            )
            writer.writerow([
                self._csv_safe(value) for value in (
                    row["created_at"], row["username"],
                    ROLE_NAMES.get(row["role"], row["role"]),
                    row["question"], row["answer"] + self._watermark(actor["username"]),
                    row["confidence"], row["model"], row["retrieval_mode"],
                    "是" if row["rerank_used"] else "否", row["feedback"], source_text,
                )
            ])
        self._audit(actor["username"], actor["role"], "export_qa_csv", detail=f"{len(rows)} 条")
        # UTF-8 BOM，方便 Windows Excel 直接打开而不乱码。
        return output.getvalue().encode("utf-8-sig")

    def get_audit_logs(
        self, actor: dict[str, str], role: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        self._require_admin(actor)
        limit = max(1, min(int(limit), 1000))
        sql = "SELECT * FROM audit_logs"
        params: list[Any] = []
        if role in ROLE_NAMES:
            sql += " WHERE role = ?"
            params.append(role)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    def get_operations_dashboard(
        self, actor: dict[str, str], days: int = 30
    ) -> dict[str, Any]:
        """聚合问答运营数据；管理员看全校汇总，其他角色只看自己的记录。"""
        role = self._role(actor)
        days = max(1, min(int(days), 365))
        since = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
        with self._connect() as conn:
            if role == "admin":
                rows = conn.execute(
                    "SELECT created_at, question, resolved_question, sources_json, trust_score, feedback"
                    " FROM qa_records WHERE created_at >= ? ORDER BY id DESC LIMIT 5000",
                    (since,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT created_at, question, resolved_question, sources_json, trust_score, feedback"
                    " FROM qa_records WHERE created_at >= ? AND username = ?"
                    " ORDER BY id DESC LIMIT 5000",
                    (since, actor["username"]),
                ).fetchall()

        hot: dict[str, dict[str, Any]] = {}
        unanswered = []
        daily: dict[str, int] = {}
        hourly = {str(hour): 0 for hour in range(24)}
        source_usage: dict[str, dict[str, Any]] = {}
        feedback_counts = {"useful": 0, "useless": 0, "unrated": 0}
        trust_values = []
        answered = 0
        allowed = set(self._allowed_groups(actor))
        for row in rows:
            try:
                sources = json.loads(row["sources_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                sources = []
            question = str(row["resolved_question"] or row["question"]).strip()
            normalized = re.sub(r"[\s，。！？!?？]", "", question).lower()
            if normalized:
                entry = hot.setdefault(normalized, {"question": question, "count": 0})
                entry["count"] += 1
            created = str(row["created_at"])
            daily[created[:10]] = daily.get(created[:10], 0) + 1
            if len(created) >= 13 and created[11:13].isdigit():
                hourly[str(int(created[11:13]))] += 1
            feedback = row["feedback"] if row["feedback"] in {"useful", "useless"} else "unrated"
            feedback_counts[feedback] += 1
            if sources:
                answered += 1
                trust_values.append(int(row["trust_score"] or 0))
            else:
                unanswered.append({
                    "question": self._mask_sensitive(question), "created_at": created
                })
            seen_in_record = set()
            for source in sources:
                group = source.get("group")
                if role != "admin" and group not in allowed:
                    continue
                source_name = str(source.get("source", "未知文档"))
                key = f"{group}/{source_name}"
                if key in seen_in_record:
                    continue
                seen_in_record.add(key)
                item = source_usage.setdefault(key, {
                    "source": source_name, "group_name": source.get("group_name", GROUPS.get(group, group)),
                    "count": 0,
                })
                item["count"] += 1

        start_date = datetime.now().astimezone().date() - timedelta(days=days - 1)
        daily_counts = []
        for offset in range(days):
            day = (start_date + timedelta(days=offset)).isoformat()
            daily_counts.append({"date": day, "count": daily.get(day, 0)})
        result = {
            "scope": "全校汇总（不含用户名）" if role == "admin" else "仅当前账户",
            "days": days, "total_questions": len(rows), "answered": answered,
            "unanswered": len(rows) - answered,
            "answer_rate": answered / len(rows) if rows else 0,
            "average_trust": round(sum(trust_values) / len(trust_values)) if trust_values else 0,
            "hot_questions": sorted(hot.values(), key=lambda item: item["count"], reverse=True)[:10],
            "unanswered_questions": unanswered[:20],
            "daily_counts": daily_counts,
            "hourly_counts": [{"hour": f"{hour}:00", "count": hourly[str(hour)]} for hour in range(24)],
            "source_usage": sorted(source_usage.values(), key=lambda item: item["count"], reverse=True)[:15],
            "feedback_counts": feedback_counts,
        }
        for item in result["hot_questions"]:
            item["question"] = self._mask_sensitive(item["question"])
        self._audit(actor["username"], actor["role"], "view_dashboard", result["scope"], f"{days} 天")
        return result


    @staticmethod
    def _mask_username(username: str) -> str:
        if not username:
            return "***"
        if len(username) == 1:
            return username[0] + "***"
        return username[0] + "***" + username[-1]

    def export_audit_csv(self, actor: dict[str, str]) -> bytes:
        """管理员导出脱敏审计日志，并嵌入当前管理员 ID 水印。"""
        self._require_admin(actor)
        rows = list(reversed(self.get_audit_logs(actor, limit=1000)))
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([
            "脱敏标记", "访问时间", "用户ID（脱敏）", "访问角色",
            "操作", "命中文档/资源", "详情（脱敏）",
        ])
        for row in rows:
            detail = self._mask_sensitive(row["detail"]) + self._watermark(actor["username"])
            writer.writerow([
                self._csv_safe(value) for value in (
                    "已脱敏", row["created_at"], self._mask_username(row["username"]),
                    ROLE_NAMES.get(row["role"], row["role"]), row["action"],
                    self._mask_sensitive(row["resource"]), detail,
                )
            ])
        self._audit(
            actor["username"], actor["role"], "export_audit_csv",
            detail=f"导出 {len(rows)} 条，已脱敏并嵌入水印",
        )
        return output.getvalue().encode("utf-8-sig")