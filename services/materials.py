"""受管理材料副本与关联。文件先复制并校验，再保存记录。"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
from datetime import datetime
from uuid import uuid4

LOGGER = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = frozenset({
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.tsv', '.txt',
    '.md', '.rtf', '.ppt', '.pptx', '.png', '.jpg', '.jpeg', '.gif',
    '.bmp', '.webp', '.zip',
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(root: Path, relative: str, *, materials_only: bool = False) -> Path:
    """将数据库/清单相对路径限制在资料根目录内，拒绝符号链接。"""
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('归档路径无效。')
    parts = PurePosixPath(relative).parts
    if (PurePosixPath(relative).is_absolute() or not parts or
            any(part in {'.', '..'} or ':' in part or '\x00' in part for part in parts) or
            str(PurePosixPath(relative)) != relative):
        raise ValueError('归档路径必须是规范的安全相对路径。')
    if materials_only and (len(parts) < 3 or parts[0] != 'materials'):
        raise ValueError('材料必须位于受管理材料目录。')
    base = Path(root).resolve()
    path = base.joinpath(*parts)
    probe = base
    for part in parts:
        probe /= part
        if probe.is_symlink():
            raise ValueError('归档路径不能经过符号链接。')
    if not path.resolve().is_relative_to(base):
        raise ValueError('归档路径超出资料目录。')
    return path


class MaterialService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _check_link(connection, project_id, achievement_id=None, writable=False):
        project = connection.execute('SELECT id, archived FROM projects WHERE id=?',
                                     (project_id,)).fetchone()
        if project is None:
            raise ValueError('所属项目不存在。')
        if writable and project['archived']:
            raise ValueError('归档项目及关联记录为只读，请先恢复项目。')
        if achievement_id is not None:
            achievement = connection.execute('SELECT project_id FROM achievements WHERE id=?',
                                             (achievement_id,)).fetchone()
            if achievement is None or achievement['project_id'] != project_id:
                raise ValueError('关联成果必须存在且属于同一个项目。')

    @staticmethod
    def _metadata(category, version_label, notes):
        category = str(category).strip()
        version_label = str(version_label).strip()
        if not category or not version_label:
            raise ValueError('材料类别和版本标签不能为空。')
        return category, version_label, str(notes)

    def import_file(self, source, project_id, achievement_id=None, category='其他',
                    version_label='V1', notes='') -> str:
        category, version_label, notes = self._metadata(category, version_label, notes)
        source = Path(source).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError('请选择普通文件。')
        if source.suffix.lower() not in ALLOWED_EXTENSIONS:
            raise ValueError('不支持该文件类型；禁止导入脚本和可执行文件。')
        material_id = str(uuid4())
        relative = f'materials/{material_id}/{source.name}'
        destination = safe_relative_path(self.store.root, relative, materials_only=True)
        directory = destination.parent
        temporary = directory / '.import.part'
        with self.store.write_lock:
            connection = self.store.connect()
            try:
                self._check_link(connection, project_id, achievement_id, writable=True)
            finally:
                connection.close()
            directory.mkdir(parents=True, exist_ok=False)
            try:
                size = source.stat().st_size
                source_hash = sha256_file(source)
                shutil.copyfile(source, temporary)
                with temporary.open('rb+') as stream:
                    os.fsync(stream.fileno())
                if temporary.stat().st_size != size or sha256_file(temporary) != source_hash:
                    raise OSError('材料副本校验失败，源文件可能在导入过程中发生变化。')
                temporary.replace(destination)
                connection = self.store.connect()
                try:
                    with connection:
                        self._check_link(connection, project_id, achievement_id, writable=True)
                        connection.execute('''INSERT INTO materials
                            (id,project_id,achievement_id,original_name,category,version_label,
                             notes,size,sha256,imported_at,relative_path)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                            (material_id, project_id, achievement_id, source.name, category,
                             version_label, notes, size, source_hash,
                             datetime.now().isoformat(timespec='seconds'), relative))
                finally:
                    connection.close()
                return material_id
            except Exception:
                # 仅清理本次 UUID 独立目录；从不操作用户源文件。
                shutil.rmtree(directory, ignore_errors=True)
                LOGGER.exception('导入材料失败: %s', source.name)
                raise

    def list_materials(self, keyword='', project_id=None, achievement_id=None, category=''):
        clauses, values = [], []
        if keyword:
            escaped = str(keyword).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            clauses.append("(m.original_name LIKE ? ESCAPE '\\' OR m.notes LIKE ? ESCAPE '\\' OR m.version_label LIKE ? ESCAPE '\\')")
            values.extend([f'%{escaped}%'] * 3)
        for field, value in [('project_id', project_id), ('achievement_id', achievement_id),
                             ('category', category)]:
            if value is not None and value != '':
                clauses.append(f'm.{field}=?')
                values.append(value)
        query = '''SELECT m.*, p.name AS project_name, p.archived AS project_archived,
                   a.name AS achievement_name FROM materials m
                   JOIN projects p ON p.id=m.project_id
                   LEFT JOIN achievements a ON a.id=m.achievement_id'''
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        query += ' ORDER BY m.imported_at DESC, m.id'
        connection = self.store.connect()
        try:
            return [dict(row) for row in connection.execute(query, values)]
        finally:
            connection.close()

    def get_material(self, material_id):
        connection = self.store.connect()
        try:
            row = connection.execute('''SELECT m.*, p.name AS project_name,
                p.archived AS project_archived, a.name AS achievement_name
                FROM materials m JOIN projects p ON p.id=m.project_id
                LEFT JOIN achievements a ON a.id=m.achievement_id WHERE m.id=?''',
                (material_id,)).fetchone()
            if row is None:
                raise ValueError('材料记录不存在。')
            return dict(row)
        finally:
            connection.close()

    def file_path(self, material_id, verify=False) -> Path:
        record = self.get_material(material_id)
        path = safe_relative_path(self.store.root, record['relative_path'], materials_only=True)
        if not path.is_file():
            raise FileNotFoundError(f"受管理材料副本缺失：{record['original_name']}。哈希不能重建文件；请从早期完整备份恢复到新资料目录，或找到原文件并重新导入新版本。")
        if verify and (path.stat().st_size != record['size'] or sha256_file(path) != record['sha256']):
            raise ValueError(f"受管理材料副本校验失败，大小或 SHA-256 已变化：{record['original_name']}。哈希不能重建原内容；请从早期完整备份恢复到新资料目录，或找到完好的原文件并重新导入新版本。旧记录不会改写。")
        return path

    def prepare_preview(self, material_id) -> Path:
        """校验归档原副本后生成独立预览；交付给外部应用的副本不自动清理。

        每次打开使用新 UUID，避免复用已由编辑器修改的预览。失败时仅清理
        尚未返回、尚未交给外部应用的本次目录；不清理历史预览或终止编辑器。
        此方法包含复制和哈希，应由界面的后台任务调用。
        """
        with self.store.write_lock:
            original = self.file_path(material_id, verify=True)
            record = self.get_material(material_id)
            if original.suffix.lower() not in ALLOWED_EXTENSIONS:
                raise ValueError('不支持预览该文件类型；禁止打开脚本和可执行文件。')
            relative = f'preview_cache/{uuid4()}/{original.name}'
            preview = safe_relative_path(self.store.root, relative)
            directory = preview.parent
            directory.mkdir(parents=True, exist_ok=False)
            try:
                shutil.copyfile(original, preview)
                with preview.open('rb+') as stream:
                    os.fsync(stream.fileno())
                if preview.stat().st_size != record['size'] or sha256_file(preview) != record['sha256']:
                    raise ValueError('预览副本校验失败，原文件可能在复制时变化；未打开文件。')
                # 外部程序可能同时编辑原副本，复制成功后再核对源文件。
                self.file_path(material_id, verify=True)
                return preview
            except Exception:
                # 此目录尚未暴露给外部程序，安全补偿仅限本次新建 UUID。
                shutil.rmtree(directory, ignore_errors=True)
                LOGGER.exception('准备材料预览失败: %s', record['original_name'])
                raise

    def update_material(self, material_id, achievement_id=None, category='其他',
                        version_label='V1', notes=''):
        category, version_label, notes = self._metadata(category, version_label, notes)
        with self.store.write_lock:
            connection = self.store.connect()
            try:
                with connection:
                    record = connection.execute('SELECT project_id FROM materials WHERE id=?',
                                                (material_id,)).fetchone()
                    if record is None:
                        raise ValueError('材料记录不存在。')
                    self._check_link(connection, record['project_id'], achievement_id, writable=True)
                    connection.execute('''UPDATE materials SET achievement_id=?, category=?,
                        version_label=?, notes=? WHERE id=?''',
                        (achievement_id, category, version_label, notes, material_id))
            finally:
                connection.close()
