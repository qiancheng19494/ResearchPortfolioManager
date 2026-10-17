"""受管理材料副本与关联。文件先复制并校验，再保存记录。"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
from datetime import datetime
from uuid import uuid4

LOGGER = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = frozenset({
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.tsv', '.txt',
    '.md', '.rtf', '.ppt', '.pptx', '.png', '.jpg', '.jpeg', '.gif',
    '.bmp', '.webp', '.zip',
})
WINDOWS_DEVICE_NAMES = frozenset(
    {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} |
    {f'{prefix}{number}' for prefix in ('COM', 'LPT') for number in '123456789\u00b9\u00b2\u00b3'}
)


def _unsafe_windows_component(part: str) -> bool:
    """Reject Win32 aliases as well as characters with device/path semantics."""
    return (part.endswith((' ', '.')) or
            any(ord(char) < 32 or char in '<>:"|?*' for char in part) or
            part.split('.', 1)[0].rstrip(' ').upper() in WINDOWS_DEVICE_NAMES)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(root: Path, relative: str, *, materials_only: bool = False) -> Path:
    """限制规范相对路径，拒绝 Windows 文件名别名、重解析点和硬链接。"""
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('归档路径无效。')
    parts = PurePosixPath(relative).parts
    if (PurePosixPath(relative).is_absolute() or not parts or
            any(part in {'.', '..'} or _unsafe_windows_component(part) for part in parts) or
            str(PurePosixPath(relative)) != relative):
        raise ValueError('归档路径必须是规范的安全相对路径。')
    if materials_only and (len(parts) < 3 or parts[0] != 'materials'):
        raise ValueError('材料必须位于受管理材料目录。')
    base = Path(root).resolve()
    path = base.joinpath(*parts)
    probe = base
    for part in parts:
        probe /= part
        try:
            info = probe.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('归档路径不能经过符号链接或 Windows 重解析点。')
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise ValueError('归档路径不能使用硬链接文件。')
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
        if (not isinstance(category, str) or not category.strip() or
                not isinstance(version_label, str) or not version_label.strip()):
            raise ValueError('材料类别和版本标签不能为空。')
        if not isinstance(notes, str):
            raise ValueError('材料备注必须为文本。')
        return category.strip(), version_label.strip(), notes

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

    def audit_materials(self):
        """只读检查全部材料；单个材料异常不会阻止后续项目的检查。

        大文件按块计算 SHA-256，调用方应使用后台任务。报告反映读取期间
        的结果；不更改数据库、旧哈希或文件，不创建预览，不尝试修复内容。
        """
        report = {'checked_at': datetime.now().isoformat(timespec='seconds'),
                  'total': 0, 'passed': 0, 'failed': 0, 'items': []}
        with self.store.write_lock:
            for record in self.list_materials():
                item = {key: record[key] for key in
                        ('id', 'original_name', 'project_name', 'version_label', 'relative_path')}
                item.update(project_archived=bool(record['project_archived']),
                            expected_size=record['size'], expected_sha256=record['sha256'],
                            actual_size=None, actual_sha256=None, status='error', reason='')
                try:
                    path = safe_relative_path(self.store.root, record['relative_path'],
                                              materials_only=True)
                    info = path.stat()
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('受管理材料路径不是普通文件。')
                    item['actual_size'] = info.st_size
                    item['actual_sha256'] = sha256_file(path)
                    if (item['actual_size'] == item['expected_size'] and
                            item['actual_sha256'] == item['expected_sha256']):
                        item.update(status='passed', reason='大小和 SHA-256 与归档记录一致。')
                    else:
                        item.update(status='changed', reason='大小或 SHA-256 与归档记录不符；哈希不能重建原内容，请从完好备份恢复或重新导入新版本。')
                except FileNotFoundError:
                    item.update(status='missing', reason='受管理材料副本缺失；哈希不能重建文件，请从完好备份恢复或重新导入新版本。')
                except ValueError as exc:
                    item.update(status='unsafe_path', reason=str(exc))
                except (OSError, TypeError) as exc:
                    item.update(status='error', reason=f'材料无法读取：{exc}')
                report['items'].append(item)
        report['total'] = len(report['items'])
        report['passed'] = sum(item['status'] == 'passed' for item in report['items'])
        report['failed'] = report['total'] - report['passed']
        return report

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
