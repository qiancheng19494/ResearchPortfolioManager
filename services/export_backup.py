"""可复核的台账导出，以及清单校验、暂存验证后恢复的完整备份。"""
from __future__ import annotations

import csv
from datetime import datetime, date
import hashlib
import html
import json
import logging
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from uuid import UUID

from database.store import Store, SCHEMA_VERSION, DEFAULT_CONFIG, validate_config
from services.materials import MaterialService, ALLOWED_EXTENSIONS, safe_relative_path, sha256_file
from services.portfolio import PortfolioService

LOGGER = logging.getLogger(__name__)
FORMAT_NAME = 'ResearchPortfolioManager.backup'
BACKUP_FORMAT_VERSION = 1
DB_ENTRY = 'portfolio.sqlite3'
CONFIG_ENTRY = 'config/settings.json'
HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')
WINDOWS_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                    *(f'LPT{i}' for i in range(1, 10))}


def csv_safe(value):
    """在导出副本前加文本前缀，数据库中的原始文字保持不变。"""
    text = '' if value is None else str(value)
    stripped = text.lstrip()
    if (stripped[:1] in {'=', '+', '-', '@'} or text[:1] in {'\t', '\r', '\n'}):
        return "'" + text
    return text


def _html_table(headers, rows):
    escaped = lambda value: html.escape('' if value is None else str(value), quote=True)
    heading = ''.join(f'<th>{escaped(value)}</th>' for value in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{escaped(value)}</td>' for value in row) + '</tr>'
                   for row in rows)
    if not body:
        body = f'<tr><td colspan="{len(headers)}">暂无记录</td></tr>'
    return f'<table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table>'


class ExportBackupService:
    def __init__(self, store):
        self.store = store

    def _destination(self, destination):
        path = Path(destination).expanduser().resolve()
        if path.exists() and not path.is_file():
            raise ValueError('保存位置必须是文件。')
        if not path.parent.is_dir():
            raise ValueError('保存位置的父目录不存在。')
        protected = [self.store.db_path.resolve(), self.store.root / '.instance.lock',
                     *(Path(str(self.store.db_path) + suffix) for suffix in ('-journal', '-wal', '-shm')),
                     self.store.root / 'materials',
                     self.store.root / 'config', self.store.root / 'logs', self.store.root / 'preview_cache']
        if any(path == item or path.is_relative_to(item) for item in protected):
            raise ValueError('不能将导出或备份写入数据库、配置、日志、预览缓存或受管理材料位置。')
        return path

    def export_csv(self, destination, project_id=None, type='', status='') -> Path:
        path = self._destination(destination)
        with self.store.write_lock:
            records = PortfolioService(self.store).list_achievements(project_id=project_id,
                                                                    type=type, status=status)
        headers = ['成果ID', '所属项目', '成果名称', '成果类型', '成果状态', '相关日期',
                   '编号或链接', '贡献说明', '备注', '创建时间', '更新时间']
        fields = ['id', 'project_name', 'name', 'type', 'status', 'related_date', 'reference',
                  'contribution', 'notes', 'created_at', 'updated_at']
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                                             dir=path.parent, prefix='.export-', suffix='.tmp',
                                             delete=False) as stream:
                temporary = Path(stream.name)
                writer = csv.writer(stream)
                writer.writerow(headers)
                writer.writerows([csv_safe(record.get(field)) for field in fields]
                                  for record in records)
            temporary.replace(path)
            return path
        except Exception:
            LOGGER.exception('成果台账导出失败')
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def export_html(self, destination, project_id) -> Path:
        path = self._destination(destination)
        with self.store.write_lock:
            detail = PortfolioService(self.store).project_detail(project_id)
        project = detail['project']
        escaped = lambda value: html.escape('' if value is None else str(value), quote=True)
        fields = [('类别', 'category'), ('状态', 'status'), ('负责人', 'leader'),
                  ('开始日期', 'start_date'), ('计划结束日期', 'end_date'),
                  ('创建时间', 'created_at'), ('更新时间', 'updated_at')]
        metadata = ''.join(f'<dt>{label}</dt><dd>{escaped(project.get(key))}</dd>'
                           for label, key in fields)
        tables = [
            ('任务', ['标题', '说明', '截止日期', '优先级', '状态', '完成时间'],
             [[r.get(f) for f in ('title', 'description', 'due_date', 'priority', 'status', 'completed_at')]
              for r in detail['tasks']]),
            ('成果', ['名称', '类型', '状态', '相关日期', '编号或链接', '贡献说明', '备注'],
             [[r.get(f) for f in ('name', 'type', 'status', 'related_date', 'reference', 'contribution', 'notes')]
              for r in detail['achievements']]),
            ('材料目录', ['原文件名', '类别', '版本', '关联成果', '大小（字节）', 'SHA-256', '导入时间', '受管理相对路径', '备注'],
             [[r.get(f) for f in ('original_name', 'category', 'version_label', 'achievement_name', 'size', 'sha256', 'imported_at', 'relative_path', 'notes')]
              for r in detail['materials']]),
        ]
        sections = ''.join(f'<h2>{title}</h2>{_html_table(headers, rows)}'
                           for title, headers, rows in tables)
        demo = '<p class="notice">演示数据：本报告仅用于软件演示。</p>' if self.store.config.get('demo') else ''
        output = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{escaped(project['name'])} — 项目摘要</title>
<style>body{{font-family:"Microsoft YaHei",sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#24334b}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border:1px solid #cbd5e1;padding:9px;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}}th{{background:#edf3fa}}dt{{font-weight:bold;float:left;width:110px}}dd{{margin-left:120px;margin-bottom:8px}}p{{white-space:pre-wrap}}.notice{{background:#fff0b3;padding:12px}}</style></head>
<body><h1>{escaped(project['name'])}</h1>{demo}<p>本科科研项目与成果档案管理系统 V1.0 · 项目摘要</p>
<p>归档状态：{'已归档' if project['archived'] else '未归档'}</p><dl>{metadata}</dl>
<h2>项目简介</h2><p>{escaped(project.get('description'))}</p>
<h2>项目备注</h2><p>{escaped(project.get('notes'))}</p>{sections}
<p>导出时间：{escaped(datetime.now().isoformat(timespec='seconds'))}。报告仅包含数据库中实际保存的资料，成果状态由用户录入。</p></body></html>'''
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix='.export-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(output)
            temporary.replace(path)
            return path
        except Exception:
            LOGGER.exception('项目摘要导出失败')
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def backup(self, destination) -> Path:
        path = self._destination(destination)
        try:
            with self.store.write_lock, tempfile.TemporaryDirectory(prefix='.backup-', dir=path.parent) as temporary:
                stage = Path(temporary)
                snapshot = stage / DB_ENTRY
                source = self.store.connect()
                snapshot_connection = sqlite3.connect(snapshot)
                try:
                    source.backup(snapshot_connection)
                    snapshot_connection.row_factory = sqlite3.Row
                    materials = [dict(row) for row in snapshot_connection.execute('SELECT * FROM materials')]
                    versions = snapshot_connection.execute('SELECT version FROM schema_info').fetchall()
                    if len(versions) != 1 or versions[0][0] != SCHEMA_VERSION:
                        raise ValueError('数据库版本不支持备份。')
                finally:
                    snapshot_connection.close()
                    source.close()
                files = {DB_ENTRY: snapshot}
                config_destination = stage / CONFIG_ENTRY
                config_destination.parent.mkdir(parents=True)
                shutil.copyfile(self.store.config_path, config_destination)
                validate_config(json.loads(config_destination.read_text(encoding='utf-8')), DEFAULT_CONFIG)
                files[CONFIG_ENTRY] = config_destination
                for record in materials:
                    material_source = safe_relative_path(self.store.root, record['relative_path'], materials_only=True)
                    if not material_source.is_file():
                        raise FileNotFoundError(f"材料副本缺失，备份已取消：{record['original_name']}")
                    material_destination = safe_relative_path(stage, record['relative_path'], materials_only=True)
                    material_destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(material_source, material_destination)
                    if (material_destination.stat().st_size != record['size'] or
                            sha256_file(material_destination) != record['sha256']):
                        raise ValueError(f"材料副本校验失败，备份已取消：{record['original_name']}")
                    files[record['relative_path']] = material_destination
                manifest = {'format': FORMAT_NAME, 'format_version': BACKUP_FORMAT_VERSION,
                            'schema_version': SCHEMA_VERSION,
                            'created_at': datetime.now().isoformat(timespec='seconds'),
                            'files': {name: {'size': item.stat().st_size, 'sha256': sha256_file(item)}
                                      for name, item in files.items()}}
                self._validate_database(stage, manifest)
                archive = stage / 'backup.zip'
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as package:
                    for name, item in files.items():
                        package.write(item, name)
                    package.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                archive.replace(path)
            return path
        except Exception:
            LOGGER.exception('完整备份失败')
            raise

    @staticmethod
    def _zip_path(name):
        if not isinstance(name, str) or not name or '\\' in name:
            raise ValueError('备份包含危险路径。')
        parts = PurePosixPath(name).parts
        if (PurePosixPath(name).is_absolute() or not parts or str(PurePosixPath(name)) != name or
                any(part in {'.', '..'} or ':' in part or '\x00' in part or
                    any(ch in part for ch in '<>"|?*') or part.endswith((' ', '.')) or
                    part.split('.')[0].upper() in WINDOWS_RESERVED for part in parts)):
            raise ValueError('备份包含危险或不兼容的归档路径。')
        return name

    @staticmethod
    def _schema_signature(connection):
        return [(row[0], row[1], row[2], ' '.join(row[3].split()).rstrip(';'))
                for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")]

    def _validate_database(self, stage, manifest):
        database = stage / DB_ENTRY
        connection = sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            if connection.execute('PRAGMA integrity_check').fetchall()[0][0] != 'ok':
                raise ValueError('备份数据库完整性检查失败。')
            if connection.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('备份数据库存在无效关联。')
            versions = connection.execute('SELECT version FROM schema_info').fetchall()
            if len(versions) != 1 or versions[0][0] != SCHEMA_VERSION:
                raise ValueError('备份数据库版本不支持。')
            # 与本版真实初始化的结构比较，不能靠伪造版本号接受未知表结构。
            with tempfile.TemporaryDirectory(prefix='.schema-', dir=stage.parent) as expected_dir:
                expected = Store(expected_dir)
                with expected.connection() as expected_connection:
                    if self._schema_signature(connection) != self._schema_signature(expected_connection):
                        raise ValueError('备份数据库结构不属于本软件支持的 V1.0。')
            for table, fields in [('projects', ['start_date', 'end_date']), ('tasks', ['due_date']),
                                  ('achievements', ['related_date'])]:
                for row in connection.execute(f"SELECT {','.join(fields)} FROM {table}"):
                    for value in row:
                        if value is not None and (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value):
                            raise ValueError('备份数据库包含非法日期。')
            materials = [dict(row) for row in connection.execute('SELECT * FROM materials')]
            required = {DB_ENTRY, CONFIG_ENTRY}
            for record in materials:
                if str(UUID(record['id'])) != record['id']:
                    raise ValueError('备份中材料 ID 无效。')
                if record['relative_path'] != f"materials/{record['id']}/{record['original_name']}":
                    raise ValueError('备份材料引用与独立存储路径不一致。')
                if Path(record['original_name']).suffix.lower() not in ALLOWED_EXTENSIONS:
                    raise ValueError('备份包含不支持的材料类型。')
                material_path = safe_relative_path(stage, record['relative_path'], materials_only=True)
                if not material_path.is_file():
                    raise ValueError('备份缺少数据库引用的材料。')
                descriptor = manifest['files'].get(record['relative_path'])
                if (not descriptor or descriptor['size'] != record['size'] or
                        descriptor['sha256'] != record['sha256']):
                    raise ValueError('数据库材料记录与清单校验信息不一致。')
                required.add(record['relative_path'])
            if required != set(manifest['files']):
                raise ValueError('备份清单与数据库实际引用文件不一致。')
        finally:
            connection.close()
        configuration = json.loads((stage / CONFIG_ENTRY).read_text(encoding='utf-8'))
        validate_config(configuration, DEFAULT_CONFIG)

    def restore(self, archive, target) -> Path:
        archive = Path(archive).expanduser().resolve(strict=True)
        requested = Path(target).expanduser()
        if requested.is_symlink():
            raise ValueError('恢复目标不能是符号链接。')
        target = requested.resolve()
        if target == self.store.root or any(target.is_relative_to(self.store.root / part)
                                            for part in ('materials', 'config', 'logs', 'preview_cache')):
            raise ValueError('不能恢复到当前资料库或其受管理目录。')
        if not target.parent.is_dir():
            raise ValueError('恢复目标的父目录必须存在。')
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError('恢复只允许新建或空目录，不能覆盖已有资料。')
        try:
            with tempfile.TemporaryDirectory(prefix='.restore-', dir=target.parent) as temporary:
                stage = Path(temporary) / 'validated_data'
                stage.mkdir()
                with zipfile.ZipFile(archive, 'r') as package:
                    infos = package.infolist()
                    if len(infos) > 100000:
                        raise ValueError('备份包含过多文件。')
                    names, folded = set(), set()
                    for info in infos:
                        name = self._zip_path(info.filename)
                        if (info.orig_filename != info.filename or name in names or name.casefold() in folded or info.is_dir() or
                                stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                            raise ValueError('备份包含重复路径、链接、目录项或加密文件。')
                        names.add(name)
                        folded.add(name.casefold())
                    if 'manifest.json' not in names or package.getinfo('manifest.json').file_size > 5 * 1024 * 1024:
                        raise ValueError('备份缺少有效清单。')
                    manifest = json.loads(package.read('manifest.json').decode('utf-8'))
                    if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT_NAME or
                            type(manifest.get('format_version')) is not int or manifest['format_version'] != BACKUP_FORMAT_VERSION or
                            type(manifest.get('schema_version')) is not int or manifest['schema_version'] != SCHEMA_VERSION or
                            not isinstance(manifest.get('files'), dict)):
                        raise ValueError('不支持的备份格式或数据库版本。')
                    files = manifest['files']
                    if not {DB_ENTRY, CONFIG_ENTRY}.issubset(files) or set(files) | {'manifest.json'} != names:
                        raise ValueError('备份文件与必要清单不一致。')
                    total_size = 0
                    for name, descriptor in files.items():
                        self._zip_path(name)
                        if name not in {DB_ENTRY, CONFIG_ENTRY} and not name.startswith('materials/'):
                            raise ValueError('备份包含不支持的文件。')
                        if (not isinstance(descriptor, dict) or type(descriptor.get('size')) is not int or
                                descriptor['size'] < 0 or not isinstance(descriptor.get('sha256'), str) or
                                not HASH_PATTERN.fullmatch(descriptor['sha256']) or
                                package.getinfo(name).file_size != descriptor['size']):
                            raise ValueError('备份文件校验描述无效。')
                        total_size += descriptor['size']
                    if total_size + 16 * 1024 * 1024 > shutil.disk_usage(target.parent).free:
                        raise OSError('磁盘空间不足以暂存并验证备份。')
                    for name, descriptor in files.items():
                        destination = safe_relative_path(stage, name, materials_only=name.startswith('materials/'))
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        digest, copied = hashlib.sha256(), 0
                        with package.open(name, 'r') as source, destination.open('xb') as output:
                            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                                copied += len(chunk)
                                if copied > descriptor['size']:
                                    raise ValueError('备份文件超出清单长度。')
                                digest.update(chunk)
                                output.write(chunk)
                        if copied != descriptor['size'] or digest.hexdigest() != descriptor['sha256']:
                            raise ValueError('备份文件损坏，SHA-256 校验失败。')
                self._validate_database(stage, manifest)
                (stage / 'materials').mkdir(exist_ok=True)
                (stage / 'logs').mkdir(exist_ok=True)
                removed_empty_target = False
                if target.exists():
                    if not target.is_dir() or any(target.iterdir()):
                        raise ValueError('恢复目标已变为非空目录，已取消恢复。')
                    target.rmdir()
                    removed_empty_target = True
                try:
                    stage.rename(target)
                except Exception:
                    if removed_empty_target and not target.exists():
                        target.mkdir()
                    raise
            # 检查实际恢复位置；每个材料可解析并与记录哈希一致。
            restored = Store(target)
            material_service = MaterialService(restored)
            for material in material_service.list_materials():
                material_service.file_path(material['id'], verify=True)
            return target
        except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeError, sqlite3.DatabaseError) as exc:
            LOGGER.exception('备份恢复失败')
            raise ValueError(f'备份格式或内容无效：{exc}') from exc
        except Exception:
            LOGGER.exception('备份恢复失败')
            raise
