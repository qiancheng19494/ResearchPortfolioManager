"""One connection per operation; versioned schema and data-directory configuration."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
BASE_CONFIG = {
    'name': '示例用户',
    'background': '示例学校 / 示例专业 / 本科',
    'interests': '机器学习、数据挖掘与智能预测',
    'demo': False,
}


def validate_config(values, defaults=None):
    """Merge omitted fields, then validate without coercion or file modification."""
    if not isinstance(values, dict):
        raise ValueError('配置必须为 JSON 对象')
    config = dict(BASE_CONFIG if defaults is None else defaults) | values
    if not isinstance(config.get('name'), str) or not config['name'].strip():
        raise ValueError('配置字段 name（个人姓名）必须为非空文本')
    for field, label in [('background', '学习背景'), ('interests', '研究兴趣')]:
        if not isinstance(config.get(field), str):
            raise ValueError(f'配置字段 {field}（{label}）必须为文本')
    if not isinstance(config.get('demo'), bool):
        raise ValueError('配置字段 demo（演示标记）必须为布尔值 true 或 false')
    return config


DEFAULT_CONFIG = validate_config(json.loads(
    (Path(__file__).resolve().parents[1] / 'config' / 'defaults.json').read_text(encoding='utf-8')
))

SCHEMA = """
CREATE TABLE schema_info(version INTEGER NOT NULL);
INSERT INTO schema_info VALUES(1);
CREATE TABLE projects(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(trim(name))>0),
 category TEXT NOT NULL CHECK(category IN ('研究','软著','竞赛','课程','其他')),
 description TEXT NOT NULL DEFAULT '', leader TEXT NOT NULL DEFAULT '',
 start_date TEXT, end_date TEXT,
 status TEXT NOT NULL CHECK(status IN ('计划中','进行中','已完成','暂停')),
 notes TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN(0,1)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(start_date IS NULL OR end_date IS NULL OR start_date<=end_date)
);
CREATE TABLE tasks(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
 title TEXT NOT NULL CHECK(length(trim(title))>0), description TEXT NOT NULL DEFAULT '', due_date TEXT,
 priority TEXT NOT NULL CHECK(priority IN ('低','中','高')),
 status TEXT NOT NULL CHECK(status IN ('待办','进行中','已完成')), completed_at TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK((status='已完成' AND completed_at IS NOT NULL) OR (status!='已完成' AND completed_at IS NULL))
);
CREATE TABLE achievements(
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
 name TEXT NOT NULL CHECK(length(trim(name))>0), type TEXT NOT NULL, status TEXT NOT NULL,
 related_date TEXT, reference TEXT NOT NULL DEFAULT '', contribution TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(id,project_id),
 CHECK(
 (type='论文' AND status IN ('准备中','已投稿','审稿中','已录用','已发表','退稿')) OR
 (type='软件著作权' AND status IN ('准备中','已提交','已受理','补正中','已登记','未获登记')) OR
 (type='专利' AND status IN ('准备中','已提交','已受理','审查中','已授权','终止')) OR
 (type='竞赛成果' AND status IN ('准备中','已报名','参赛中','已获奖','已结束')) OR
 (type='其他成果' AND status IN ('准备中','进行中','已完成')))
);
CREATE TABLE materials(
 id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
 achievement_id INTEGER, original_name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '其他',
 version_label TEXT NOT NULL DEFAULT 'V1', notes TEXT NOT NULL DEFAULT '',
 size INTEGER NOT NULL CHECK(size>=0), sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 imported_at TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
 FOREIGN KEY(achievement_id,project_id) REFERENCES achievements(id,project_id) ON DELETE RESTRICT
);
CREATE INDEX idx_projects_filter ON projects(archived,category,status);
CREATE INDEX idx_tasks_filter ON tasks(project_id,status,due_date);
CREATE INDEX idx_achievements_filter ON achievements(project_id,type,status,related_date);
CREATE INDEX idx_materials_filter ON materials(project_id,achievement_id,category);
CREATE TRIGGER no_project_delete BEFORE DELETE ON projects BEGIN
 SELECT RAISE(ABORT,'项目仅允许归档，不允许物理删除'); END;
CREATE TRIGGER archived_project_edit BEFORE UPDATE ON projects
 WHEN OLD.archived=1 AND (NEW.name IS NOT OLD.name OR NEW.category IS NOT OLD.category OR
 NEW.description IS NOT OLD.description OR NEW.leader IS NOT OLD.leader OR
 NEW.start_date IS NOT OLD.start_date OR NEW.end_date IS NOT OLD.end_date OR
 NEW.status IS NOT OLD.status OR NEW.notes IS NOT OLD.notes)
 BEGIN SELECT RAISE(ABORT,'归档项目只读，请先恢复'); END;
CREATE TRIGGER no_material_delete BEFORE DELETE ON materials BEGIN
 SELECT RAISE(ABORT,'V1.0 不允许删除材料'); END;
"""


class Store:
    schema_version = SCHEMA_VERSION

    def __init__(self, data_dir):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ('materials', 'config', 'logs'):
            (self.root / name).mkdir(exist_ok=True)
        self.db_path = self.root / 'portfolio.sqlite3'
        self.write_lock = threading.RLock()
        self.config_path = self.root / 'config' / 'settings.json'
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='schema_info'").fetchone():
                existing = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if existing:
                    raise ValueError('资料库缺少版本信息，不能自动覆盖')
                initialization = 'BEGIN IMMEDIATE;\n' + SCHEMA
                for table in ('tasks', 'achievements', 'materials'):
                    for event in ('INSERT', 'UPDATE', 'DELETE'):
                        condition = "(SELECT archived FROM projects WHERE id=NEW.project_id)=1"
                        if event == 'DELETE':
                            condition = "(SELECT archived FROM projects WHERE id=OLD.project_id)=1"
                        elif event == 'UPDATE':
                            condition += " OR (SELECT archived FROM projects WHERE id=OLD.project_id)=1"
                        initialization += f"\nCREATE TRIGGER archived_{table}_{event.lower()} BEFORE {event} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'归档项目的关联记录只读，请先恢复'); END;"
                try:
                    conn.executescript(initialization + '\nCOMMIT;')
                except Exception:
                    conn.rollback()
                    raise
            versions = conn.execute('SELECT version FROM schema_info').fetchall()
            if len(versions) != 1 or versions[0][0] != SCHEMA_VERSION:
                raise ValueError('不支持的数据库版本')
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding='utf-8'))
                self.config = validate_config(loaded, DEFAULT_CONFIG)
            except (OSError, ValueError) as exc:
                raise ValueError(f'配置读取失败，原文件已保留：{exc}') from exc
        else:
            self.config = dict(DEFAULT_CONFIG)
            self.save_config(self.config)

    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=15000')
        return conn

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.write_lock, self.connection() as conn:
            try:
                conn.execute('BEGIN IMMEDIATE')
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def save_config(self, changes):
        with self.write_lock:
            if not isinstance(changes, dict):
                raise ValueError('配置必须为 JSON 对象')
            config = validate_config(dict(getattr(self, 'config', DEFAULT_CONFIG)) | changes, DEFAULT_CONFIG)
            temp = self.config_path.with_suffix('.tmp')
            try:
                temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
                temp.replace(self.config_path)
                self.config = config
            finally:
                temp.unlink(missing_ok=True)
