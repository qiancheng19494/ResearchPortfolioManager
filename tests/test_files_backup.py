"""文件复制补偿、台账编码及严格备份恢复的独立临时目录验证。"""
import csv
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from database.store import Store
from services.portfolio import PortfolioService
from services.materials import MaterialService, sha256_file
from services.export_backup import ExportBackupService, csv_safe


class FilesBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='科研文件验证 空格 ')
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / '资料 中文')
        self.portfolio = PortfolioService(self.store)
        self.materials = MaterialService(self.store)
        self.exports = ExportBackupService(self.store)
        self.project = self.portfolio.save_project({'name': '研究 <项目>&"', 'description': '<script>原始文本</script>'})
        self.achievement = self.portfolio.save_achievement({'project_id': self.project,
            'name': '=SUM(1,1)', 'type': '论文', 'status': '准备中', 'reference': '@测试', 'notes': '<证明>&"'})
        self.source = self.root / '证明 材料.txt'
        self.source.write_text('独立生成的测试材料：版本一', encoding='utf-8')

    def tearDown(self):
        self.temporary.cleanup()

    def import_one(self):
        return self.materials.import_file(self.source, self.project, self.achievement)

    def archive(self):
        self.import_one()
        destination = self.root / '完整备份.zip'
        self.exports.backup(destination)
        return destination

    def rewrite_archive(self, source, change):
        with zipfile.ZipFile(source) as package:
            entries = {info.filename: package.read(info.filename) for info in package.infolist()}
        change(entries)
        destination = self.root / '修改测试备份.zip'
        with zipfile.ZipFile(destination, 'w') as package:
            for name, content in entries.items():
                package.writestr(name, content)
        return destination

    def test_same_name_and_version_isolation_original_preserved(self):
        original = self.source.read_bytes()
        first = self.import_one()
        other = self.root / '另一个目录'
        other.mkdir()
        second_source = other / self.source.name
        second_source.write_text('版本二', encoding='utf-8')
        second = self.materials.import_file(second_source, self.project, self.achievement, version_label='V2')
        self.assertNotEqual(first, second)
        first_path = self.materials.file_path(first, verify=True)
        second_path = self.materials.file_path(second, verify=True)
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first_path.read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(sha256_file(second_path), sha256_file(second_source))
        reopened = MaterialService(Store(self.store.root))
        self.assertEqual(len(reopened.list_materials()), 2)

    def test_copy_failure_and_partial_file_cleanup(self):
        original = self.source.read_bytes()
        def partial_then_fail(source, destination):
            Path(destination).write_bytes(b'partial')
            raise OSError('模拟复制中断')
        with patch('services.materials.shutil.copyfile', side_effect=partial_then_fail):
            with self.assertRaisesRegex(OSError, '复制中断'):
                self.import_one()
        self.assertEqual(self.materials.list_materials(), [])
        self.assertEqual(list((self.store.root / 'materials').iterdir()), [])
        self.assertEqual(self.source.read_bytes(), original)

    def test_silent_copy_corruption_rejected(self):
        def corrupt_copy(source, destination):
            Path(destination).write_bytes(b'corrupted')
        with patch('services.materials.shutil.copyfile', side_effect=corrupt_copy):
            with self.assertRaisesRegex(OSError, '校验失败'):
                self.import_one()
        self.assertEqual(self.materials.list_materials(), [])

    def test_transaction_failure_compensates_copy(self):
        with self.store.connection() as connection:
            connection.execute("CREATE TRIGGER test_reject BEFORE INSERT ON materials BEGIN SELECT RAISE(ABORT,'模拟写入失败'); END")
            connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.import_one()
        self.assertEqual(self.materials.list_materials(), [])
        self.assertEqual(list((self.store.root / 'materials').iterdir()), [])

    def test_missing_material_and_modified_material_detected(self):
        material = self.import_one()
        path = self.materials.file_path(material)
        path.write_text('修改过', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.materials.file_path(material, verify=True)
        path.unlink()
        with self.assertRaisesRegex(FileNotFoundError, '缺失'):
            self.materials.file_path(material)

    def test_archived_project_readonly_and_link_rules(self):
        other = self.portfolio.save_project({'name': '另一个项目'})
        wrong_achievement = self.portfolio.save_achievement({'project_id': other, 'name': '其他成果'})
        with self.assertRaisesRegex(ValueError, '同一个项目'):
            self.materials.import_file(self.source, self.project, wrong_achievement)
        material = self.import_one()
        self.portfolio.archive_project(self.project)
        self.assertTrue(self.materials.file_path(material, verify=True).exists())
        with self.assertRaisesRegex(ValueError, '只读'):
            self.import_one()
        with self.assertRaisesRegex(ValueError, '只读'):
            self.materials.update_material(material, notes='不应更新')
        self.portfolio.archive_project(self.project, False)
        self.materials.update_material(material, achievement_id=None, version_label='保留原副本')
        self.assertIsNone(self.materials.get_material(material)['achievement_id'])

    def test_scripts_rejected_and_literal_keyword_search(self):
        script = self.root / '不会执行.py'
        script.write_text('raise RuntimeError()', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '脚本'):
            self.materials.import_file(script, self.project)
        material = self.import_one()
        self.materials.update_material(material, notes='包含 %_ 文本')
        self.assertEqual(len(self.materials.list_materials(keyword='%_')), 1)
        self.assertEqual(self.materials.list_materials(keyword='不存在%_'), [])

    def test_csv_filters_bom_and_formula_defense_preserve_database(self):
        self.portfolio.save_achievement({'project_id': self.project, 'name': '另一个类型', 'type': '专利', 'status': '已提交'})
        destination = self.exports.export_csv(self.root / '成果.csv', self.project, '论文', '准备中')
        self.assertTrue(destination.read_bytes().startswith(b'\xef\xbb\xbf'))
        with destination.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['成果名称'], "'=SUM(1,1)")
        self.assertEqual(rows[0]['编号或链接'], "'@测试")
        self.assertEqual(self.portfolio.get_achievement(self.achievement)['name'], '=SUM(1,1)')
        for malicious in ['=1', ' +1', '-1', '@SUM(A1)', '\t=1', '\r=1', '\n=1']:
            self.assertTrue(csv_safe(malicious).startswith("'"))

    def test_html_escapes_all_user_text_and_includes_material(self):
        material = self.import_one()
        output = self.exports.export_html(self.root / '摘要.html', self.project).read_text(encoding='utf-8')
        self.assertIn('&lt;script&gt;原始文本&lt;/script&gt;', output)
        self.assertIn('研究 &lt;项目&gt;&amp;&quot;', output)
        self.assertNotIn('<script>', output)
        self.assertIn(self.materials.get_material(material)['relative_path'], output)
        self.assertIn('证明 材料.txt', output)

    def test_backup_snapshot_restore_and_no_recursive_package(self):
        material = self.import_one()
        self.portfolio.save_task({'project_id': self.project, 'title': '核验任务'})
        self.store.save_config({'background': '保存的自定义背景'})
        unrelated = self.store.root / '旧备份.zip'
        unrelated.write_bytes('不应进入备份'.encode('utf-8'))
        archive = self.exports.backup(self.store.root / '本次备份.zip')
        with zipfile.ZipFile(archive) as package:
            self.assertNotIn('本次备份.zip', package.namelist())
            self.assertNotIn('旧备份.zip', package.namelist())
            manifest = json.loads(package.read('manifest.json'))
            self.assertEqual(manifest['format_version'], 1)
            for name, descriptor in manifest['files'].items():
                self.assertEqual(hashlib.sha256(package.read(name)).hexdigest(), descriptor['sha256'])
        target = self.root / '恢复 空目录'
        target.mkdir()
        self.assertEqual(self.exports.restore(archive, target), target.resolve())
        restored = Store(target)
        self.assertEqual(restored.config['background'], '保存的自定义背景')
        self.assertEqual(PortfolioService(restored).get_project(self.project), self.portfolio.get_project(self.project))
        self.assertEqual(PortfolioService(restored).list_tasks(), self.portfolio.list_tasks())
        restored_materials = MaterialService(restored)
        self.assertEqual(restored_materials.get_material(material), self.materials.get_material(material))
        self.assertEqual(sha256_file(restored_materials.file_path(material, verify=True)), sha256_file(self.source))

    def test_corrupt_backup_and_unknown_version_rejected(self):
        archive = self.archive()
        corrupted = self.rewrite_archive(archive, lambda entries: entries.__setitem__('config/settings.json', b'{}'))
        target = self.root / '恢复失败'
        with self.assertRaisesRegex(ValueError, '长度|校验描述|校验失败'):
            self.exports.restore(corrupted, target)
        self.assertFalse(target.exists())
        def incompatible(entries):
            manifest = json.loads(entries['manifest.json'])
            manifest['format_version'] = 999
            entries['manifest.json'] = json.dumps(manifest).encode('utf-8')
        incompatible_archive = self.rewrite_archive(archive, incompatible)
        with self.assertRaisesRegex(ValueError, '不支持'):
            self.exports.restore(incompatible_archive, target)
        self.assertEqual(len(self.materials.list_materials()), 1)

    def test_dangerous_paths_unlisted_files_and_nonempty_target_rejected(self):
        archive = self.archive()
        for name in ['../escape.txt', '/absolute.txt', 'C:/absolute.txt', 'materials/a/../../escape.txt', 'materials/a/CON.txt', 'materials/a/x\\y.txt']:
            with self.subTest(name=name):
                dangerous = self.rewrite_archive(archive, lambda entries: entries.__setitem__(name, b'danger'))
                with self.assertRaises(ValueError):
                    self.exports.restore(dangerous, self.root / '危险恢复')
                self.assertFalse((self.root / '危险恢复').exists())
        unlisted = self.rewrite_archive(archive, lambda entries: entries.__setitem__('extra.txt', b'extra'))
        with self.assertRaisesRegex(ValueError, '清单'):
            self.exports.restore(unlisted, self.root / '未列出')
        nonempty = self.root / '非空'
        nonempty.mkdir()
        protected = nonempty / '保留.txt'
        protected.write_text('保留', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '空目录'):
            self.exports.restore(archive, nonempty)
        self.assertEqual(protected.read_text(encoding='utf-8'), '保留')

    def test_forged_database_schema_rejected_even_when_hash_updated(self):
        archive = self.archive()
        def forge(entries):
            database = self.root / '待修改数据库.sqlite3'
            database.write_bytes(entries['portfolio.sqlite3'])
            with closing(sqlite3.connect(database)) as connection:
                connection.execute('DROP TRIGGER no_material_delete')
                connection.commit()
            content = database.read_bytes()
            entries['portfolio.sqlite3'] = content
            manifest = json.loads(entries['manifest.json'])
            manifest['files']['portfolio.sqlite3'] = {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
            entries['manifest.json'] = json.dumps(manifest).encode('utf-8')
        forged = self.rewrite_archive(archive, forge)
        with self.assertRaisesRegex(ValueError, '结构'):
            self.exports.restore(forged, self.root / '伪造结构恢复')

    def test_backup_rejects_missing_material_and_preserves_previous_archive(self):
        archive = self.archive()
        previous = archive.read_bytes()
        material = self.materials.list_materials()[0]
        self.materials.file_path(material['id']).unlink()
        with self.assertRaisesRegex(FileNotFoundError, '缺失'):
            self.exports.backup(archive)
        self.assertEqual(archive.read_bytes(), previous)

    def test_export_cannot_overwrite_managed_data(self):
        original = self.store.db_path.read_bytes()
        with self.assertRaisesRegex(ValueError, '数据库'):
            self.exports.export_csv(self.store.db_path)
        self.assertEqual(self.store.db_path.read_bytes(), original)

    def test_backup_holds_write_lock_and_snapshot_precedes_waiting_write(self):
        entered, release, writer_finished = threading.Event(), threading.Event(), threading.Event()
        errors = []
        original_copy = shutil.copyfile
        archive = self.root / '并发快照.zip'
        def slow_copy(source, destination):
            if Path(source) == self.store.config_path:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('测试等待超时')
            return original_copy(source, destination)
        def backup_worker():
            try:
                self.exports.backup(archive)
            except Exception as error:
                errors.append(error)
        def writer_worker():
            try:
                self.portfolio.save_task({'project_id': self.project, 'title': '快照完成后写入'})
            except Exception as error:
                errors.append(error)
            finally:
                writer_finished.set()
        with patch('services.export_backup.shutil.copyfile', side_effect=slow_copy):
            backup_thread = threading.Thread(target=backup_worker)
            backup_thread.start()
            try:
                self.assertTrue(entered.wait(3), '备份未进入复制阶段')
                writer_thread = threading.Thread(target=writer_worker)
                writer_thread.start()
                self.assertFalse(writer_finished.wait(0.1), '备份期间发生了写入')
            finally:
                release.set()
                backup_thread.join(5)
                if 'writer_thread' in locals():
                    writer_thread.join(5)
        self.assertFalse(errors, errors)
        self.assertTrue(writer_finished.is_set())
        restored = Store(self.exports.restore(archive, self.root / '并发恢复'))
        self.assertEqual(PortfolioService(restored).list_tasks(), [])
        self.assertEqual(len(self.portfolio.list_tasks()), 1)

    def test_managed_zip_is_copied_opaquely_and_symlink_archive_rejected(self):
        material_zip = self.root / '示例附件.zip'
        with zipfile.ZipFile(material_zip, 'w') as package:
            package.writestr('仅作为文本.txt', '不解包、不执行')
        material = self.materials.import_file(material_zip, self.project)
        archive = self.exports.backup(self.root / 'ZIP材料备份.zip')
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            self.assertEqual(len([name for name in names if name.startswith('materials/')]), 1)
            self.assertEqual(package.read(self.materials.get_material(material)['relative_path']), material_zip.read_bytes())
        linked = self.root / '链接伪造.zip'
        with zipfile.ZipFile(archive) as original, zipfile.ZipFile(linked, 'w') as package:
            for name in original.namelist():
                package.writestr(name, original.read(name))
            entry = zipfile.ZipInfo('materials/link.txt')
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(entry, '../outside.txt')
        with self.assertRaisesRegex(ValueError, '链接'):
            self.exports.restore(linked, self.root / '链接恢复')


if __name__ == '__main__':
    unittest.main()
