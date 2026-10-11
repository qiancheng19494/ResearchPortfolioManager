"""Reviewed leader/config regressions; every database is isolated temporary data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from database.store import Store, DEFAULT_CONFIG, validate_config
from services.portfolio import PortfolioService


class ReviewedValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='修订校验 中文 ')
        self.base = Path(self.temp.name)
        self.store = Store(self.base / '资料')
        self.portfolio = PortfolioService(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_create_rejects_explicit_blank_whitespace_none_leader_without_record(self):
        for leader in ('', ' \t\n ', None):
            with self.subTest(leader=leader):
                with self.assertRaisesRegex(ValueError, '^负责人不能为空$'):
                    self.portfolio.save_project({'name': '非法负责人', 'leader': leader})
                self.assertEqual(self.portfolio.list_projects(include_archived=True), [])

    def test_edit_rejects_explicit_invalid_leader_and_preserves_entire_record(self):
        pid = self.portfolio.save_project({'name': '有效项目', 'leader': '本人填写'})
        before = self.portfolio.get_project(pid)
        for leader in ('', ' \t\n ', None):
            with self.subTest(leader=leader):
                with self.assertRaisesRegex(ValueError, '^负责人不能为空$'):
                    self.portfolio.save_project(dict(before, name='不应被保存', leader=leader), pid)
                self.assertEqual(self.portfolio.get_project(pid), before)

    def test_omitted_leader_uses_valid_personal_name_on_create_and_edit(self):
        self.store.save_config({'name': '  临时姓名  '})
        pid = self.portfolio.save_project({'name': '默认负责人'})
        self.assertEqual(self.portfolio.get_project(pid)['leader'], '临时姓名')
        self.store.save_config({'name': '第二测试姓名'})
        self.portfolio.save_project({'name': '编辑默认值'}, pid)
        self.assertEqual(self.portfolio.get_project(pid)['leader'], '第二测试姓名')

    def test_default_personal_name_is_validated_not_coerced(self):
        original_config = dict(self.store.config)
        for invalid in ('', '  ', None, 123):
            with self.subTest(name=invalid):
                self.store.config['name'] = invalid
                with self.assertRaisesRegex(ValueError, '^负责人不能为空$'):
                    self.portfolio.save_project({'name': '默认负责人无效'})
                self.assertEqual(self.portfolio.list_projects(include_archived=True), [])
        self.store.config = original_config

    def test_historical_blank_leader_is_readable_not_guessed_and_can_be_edited(self):
        pid = self.portfolio.save_project({'name': '旧版历史项目', 'leader': '原负责人'})
        with self.store.transaction() as connection:
            connection.execute('UPDATE projects SET leader=? WHERE id=?', ('', pid))
        reopened = PortfolioService(Store(self.store.root))
        old = reopened.get_project(pid)
        self.assertEqual(old['leader'], '')
        self.assertEqual(reopened.list_projects()[0]['leader'], '')
        with self.assertRaisesRegex(ValueError, '^负责人不能为空$'):
            reopened.save_project(dict(old), pid)
        self.assertEqual(reopened.get_project(pid), old)
        reopened.save_project(dict(old, leader='本人核实后填写'), pid)
        self.assertEqual(reopened.get_project(pid)['leader'], '本人核实后填写')

    def test_validate_defaults_merge_and_omitted_fields(self):
        merged = validate_config({'name': '测试人'}, DEFAULT_CONFIG)
        self.assertEqual(merged['name'], '测试人')
        for field in ('background', 'interests', 'demo'):
            self.assertEqual(merged[field], DEFAULT_CONFIG[field])
        self.assertIs(type(merged['demo']), bool)
        self.assertEqual(validate_config({}, DEFAULT_CONFIG), DEFAULT_CONFIG)

    def test_config_restart_rejects_semantically_invalid_fields_preserves_bytes(self):
        cases = [('name', ''), ('name', '  \t'), ('name', None), ('name', 123),
                 ('background', 123), ('background', None), ('interests', []),
                 ('interests', None), ('demo', 'false'), ('demo', 'true'),
                 ('demo', 0), ('demo', None)]
        for field, invalid in cases:
            with self.subTest(field=field, invalid=invalid):
                content = json.dumps(dict(DEFAULT_CONFIG, **{field: invalid}), ensure_ascii=False).encode('utf-8')
                self.store.config_path.write_bytes(content)
                with self.assertRaisesRegex(ValueError, field):
                    Store(self.store.root)
                self.assertEqual(self.store.config_path.read_bytes(), content)

    def test_invalid_config_save_preserves_file_and_in_memory_values(self):
        original_bytes = self.store.config_path.read_bytes()
        original_values = dict(self.store.config)
        for field, invalid in [('name', None), ('name', ' '), ('background', 123),
                               ('interests', []), ('demo', 'false')]:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    self.store.save_config({field: invalid})
                self.assertEqual(self.store.config_path.read_bytes(), original_bytes)
                self.assertEqual(self.store.config, original_values)
                self.assertFalse(self.store.config_path.with_suffix('.tmp').exists())

    def test_missing_config_fields_restart_uses_defaults_without_rewriting_source(self):
        content = b'{"name":"fixture person"}\n'
        self.store.config_path.write_bytes(content)
        reopened = Store(self.store.root)
        self.assertEqual(reopened.config['name'], 'fixture person')
        for field in ('background', 'interests', 'demo'):
            self.assertEqual(reopened.config[field], DEFAULT_CONFIG[field])
        self.assertEqual(reopened.config_path.read_bytes(), content)

    def test_valid_config_save_close_and_reopen_real_and_demo_booleans(self):
        for demo in (False, True):
            with self.subTest(demo=demo):
                config = {'name': '临时配置姓名', 'background': '隔离测试背景',
                          'interests': '隔离测试兴趣', 'demo': demo}
                self.store.save_config(config)
                reopened = Store(self.store.root)
                self.assertEqual(reopened.config, config)
                self.assertIs(reopened.config['demo'], demo)

    def test_non_object_config_is_rejected_on_read_and_save(self):
        content = b'["syntactically valid JSON"]'
        self.store.config_path.write_bytes(content)
        with self.assertRaisesRegex(ValueError, 'JSON 对象'):
            Store(self.store.root)
        self.assertEqual(self.store.config_path.read_bytes(), content)
        with self.assertRaisesRegex(ValueError, 'JSON 对象'):
            self.store.save_config([])
        self.assertEqual(self.store.config_path.read_bytes(), content)

    def test_semantically_invalid_config_actual_entry_restart_reports_field_preserves_file(self):
        # Actual startup function executes in its own process; error dialog call is intercepted.
        # This checks startup routing, not visual inspection of the critical-message box.
        script = r'''
import json
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import main
messages = []
with patch('main.QMessageBox.critical', side_effect=lambda *args: messages.append(args[2])):
    result = main.main(['--data-dir', sys.argv[2]])
print(json.dumps({'result':result,'messages':messages,'main_window_loaded':'app.main_window' in sys.modules}, ensure_ascii=False))
'''
        for field, invalid in [('background', 123), ('interests', []), ('demo', 'false')]:
            with self.subTest(field=field):
                content = json.dumps(dict(DEFAULT_CONFIG, **{field: invalid}), ensure_ascii=False).encode('utf-8')
                self.store.config_path.write_bytes(content)
                result = subprocess.run([sys.executable, '-B', '-c', script,
                                         str(Path(__file__).resolve().parents[1]), str(self.store.root)],
                                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'),
                                        text=True, encoding='utf-8', capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                evidence = json.loads(result.stdout)
                self.assertEqual(evidence['result'], 1)
                self.assertIn(field, evidence['messages'][0])
                self.assertFalse(evidence['main_window_loaded'])
                self.assertEqual(self.store.config_path.read_bytes(), content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
