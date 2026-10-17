"""V1.1 due filters and recovery guidance, using isolated temporary databases.

Widget tests create native Qt objects without showing or capturing the desktop.
They do not verify interaction with Windows file dialogs or external programs.
"""
from datetime import date, timedelta
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from app.main_window import MainWindow
from database.store import Store
from services.portfolio import PortfolioService


class DueFilterTests(unittest.TestCase):
    today = date(2026, 10, 10)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='V11 筛选 ')
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / '资料')
        self.service = PortfolioService(self.store)
        self.pid = self.service.save_project({'name': '活跃项目', 'leader': '隔离测试人'})
        self.other = self.service.save_project({'name': '其他项目', 'leader': '隔离测试人'})
        self.archived = self.service.save_project({'name': '归档项目', 'leader': '隔离测试人'})
        self.ids = {}
        for title, offset in [('昨天', -1), ('今天', 0), ('明天', 1), ('第七天', 7), ('第八天', 8)]:
            self.ids[title] = self.task(self.pid, title, offset)
        self.ids['无日期'] = self.task(self.pid, '无日期', None)
        self.ids['完成任务'] = self.task(self.pid, '完成任务', 0, status='已完成')
        self.ids['归档任务'] = self.task(self.archived, '归档任务', 0)
        self.service.archive_project(self.archived)

    def task(self, project_id, title, offset, **changes):
        values = {'project_id': project_id, 'title': title,
                  'due_date': (self.today + timedelta(days=offset)).isoformat() if offset is not None else '',
                  'status': '待办'}
        values.update(changes)
        return self.service.save_task(values)

    def selected(self, due_filter, **conditions):
        return {row['id'] for row in self.service.list_tasks(due_filter=due_filter, today=self.today, **conditions)}

    def test_due_boundaries_and_exclusions(self):
        self.assertEqual(self.selected('overdue'), {self.ids['昨天']})
        self.assertEqual(self.selected('today'), {self.ids['今天']})
        self.assertEqual(self.selected('upcoming'), {self.ids['明天'], self.ids['第七天']})
        self.assertEqual(len(self.selected('')), 8)

    def test_default_and_positional_api_still_include_complete_and_archived(self):
        records = self.service.list_tasks('', None, '', False)
        self.assertEqual({row['id'] for row in records}, set(self.ids.values()))
        self.assertNotIn(self.ids['归档任务'], {row['id'] for row in self.service.list_tasks(active_only=True)})
        self.assertIn(self.ids['完成任务'], {row['id'] for row in self.service.list_tasks(active_only=True)})

    def test_keyword_project_status_intersection_and_literal_wildcards(self):
        match = self.task(self.pid, '检查 %_ 目标', 0, status='进行中')
        self.task(self.pid, '检查任意目标', 0, status='进行中')
        self.task(self.other, '检查 %_ 目标', 0, status='进行中')
        self.task(self.pid, '检查 %_ 目标', 0)
        self.assertEqual(self.selected('today', keyword='%_', project_id=self.pid, status='进行中'), {match})
        self.assertEqual(self.selected('today', status='已完成'), set())
        self.assertEqual(self.selected('today', project_id=self.archived), set())

    def test_dashboard_and_task_filters_share_date_groups(self):
        dashboard = self.service.dashboard(self.today.isoformat())
        for due_filter, key in [('overdue', 'overdue_tasks'), ('today', 'today_tasks'), ('upcoming', 'upcoming_tasks')]:
            with self.subTest(due_filter=due_filter):
                self.assertEqual(self.selected(due_filter), {row['id'] for row in dashboard[key]})
        self.assertEqual(dashboard['tasks_count'], 6)

    def test_leap_day_and_year_transition_boundaries(self):
        for current in (date(2028, 2, 28), date(2026, 12, 28)):
            with self.subTest(today=current):
                pid = self.service.save_project({'name': current.isoformat(), 'leader': '隔离测试人'})
                ids = {}
                for offset in (0, 1, 7, 8):
                    ids[offset] = self.service.save_task({'project_id': pid, 'title': str(offset),
                                                        'due_date': (current + timedelta(days=offset)).isoformat()})
                actual = self.service.list_tasks(project_id=pid, due_filter='upcoming', today=current.isoformat())
                self.assertEqual({row['id'] for row in actual}, {ids[1], ids[7]})

    def test_invalid_filter_or_reference_date_does_not_change_records(self):
        original = self.service.list_tasks()
        for invalid in ('tomorrow', 'today OR 1=1', None, 1):
            with self.subTest(filter=invalid), self.assertRaisesRegex(ValueError, '任务到期筛选选项无效'):
                self.service.list_tasks(due_filter=invalid, today=self.today)
        for invalid in ('2026-02-30', '2026-1-2', 123):
            with self.subTest(today=invalid), self.assertRaises(ValueError):
                self.service.list_tasks(due_filter='today', today=invalid)
        self.assertEqual(self.service.list_tasks(), original)


class FilterAndReportWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='V11 提示 ')
        self.base = Path(self.temp.name)
        self.store = Store(self.base / '资料')
        self.window = MainWindow(self.store)
        self.errors, self.infos = [], []
        self.error_patch = patch.object(self.window, 'show_error', side_effect=lambda *args: self.errors.append(args))
        self.info_patch = patch.object(self.window, 'show_info', side_effect=lambda *args: self.infos.append(args))
        self.error_patch.start()
        self.info_patch.start()

    def tearDown(self):
        self.wait_job()
        self.error_patch.stop()
        self.info_patch.stop()
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(30)
        self.temp.cleanup()

    def wait_job(self):
        deadline = time.monotonic() + 15
        while self.window.busy and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertFalse(self.window.busy, '后台任务未结束')

    def add_tasks(self):
        service = self.window.portfolio
        pid = service.save_project({'name': '筛选项目', 'leader': '隔离人'})
        match = service.save_task({'project_id': pid, 'title': '目标关键词', 'status': '进行中', 'due_date': date.today().isoformat()})
        service.save_task({'project_id': pid, 'title': '未完成无日期'})
        service.save_task({'project_id': pid, 'title': '目标关键词 已完成', 'status': '已完成', 'due_date': date.today().isoformat()})
        return pid, match

    def test_task_controls_intersect_and_reset_all_filters(self):
        pid, match = self.add_tasks()
        page = self.window.pages['tasks']
        page.refresh()
        self.assertEqual(page.table.rowCount(), 3)
        page.search.setText('目标关键词')
        page.project.setCurrentIndex(page.project.findData(pid))
        page.status.setCurrentIndex(page.status.findData('进行中'))
        page.due_filter.setCurrentIndex(page.due_filter.findData('today'))
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 0).text(), '目标关键词')
        page.reset()
        self.assertEqual((page.search.text(), page.project.currentData(), page.status.currentData(), page.due_filter.currentData()), ('', None, '', ''))
        self.assertEqual(page.table.rowCount(), 3)
        self.assertEqual(self.errors, [])

    def test_recovery_guidance_keeps_complete_escaped_command_and_checklist(self):
        page = self.window.pages['reports']
        guidance = page.findChild(QLabel, 'reports_backup_guidance').text()
        for phrase in ('空目录', '关闭软件', '核对', '不会切换或覆盖当前资料库'):
            self.assertIn(phrase, guidance)
        target = self.base / "恢复 中文 空格 '$目录"
        page.restored(target)
        result = page.result.text()
        for phrase in ('恢复与完整性校验成功', '--data-dir', 'main.py', '未自动切换', '□ 项目', '□ 任务', '□ 成果', '□ 材料', '□ 真实／演示标记'):
            self.assertIn(phrase, result)
        self.assertIn("''$目录'", result)
        self.assertEqual(page.result_path, target)
        self.assertEqual(len(self.infos), 1)

    def test_backup_success_includes_independent_restore_advice(self):
        page = self.window.pages['reports']
        archive = self.base / '备份.zip'
        with patch('app.pages.QFileDialog.getSaveFileName', return_value=(str(archive), '')):
            page.backup()
        self.wait_job()
        self.assertTrue(archive.is_file())
        self.assertIn('完整备份成功', page.result.text())
        self.assertIn('独立空目录', page.result.text())
        self.assertEqual(self.errors, [])

    def test_frozen_restore_command_uses_executable_without_source_entry(self):
        page = self.window.pages['reports']
        with patch('runtime_paths.sys.frozen', True, create=True), \
                patch('runtime_paths.sys.executable', str(self.base / "程序 空格'" / 'ResearchPortfolioManager.exe')):
            page.restored(self.base / '恢复目录')
        self.assertIn('ResearchPortfolioManager.exe', page.result.text())
        self.assertIn('--data-dir', page.result.text())
        self.assertNotIn('main.py', page.result.text())
        self.assertIn("空格''", page.result.text())

    def test_restore_success_retains_current_store_and_includes_restart_checklist(self):
        self.add_tasks()
        page = self.window.pages['reports']
        archive = self.window.exports.backup(self.base / '备份.zip')
        target = self.base / '空的恢复目录'
        target.mkdir()
        with patch('app.pages.QFileDialog.getOpenFileName', return_value=(str(archive), '')), \
                patch('app.pages.QFileDialog.getExistingDirectory', return_value=str(target)), \
                patch('app.pages.QMessageBox.question', return_value=QMessageBox.Yes):
            page.restore()
        self.wait_job()
        self.assertEqual(self.window.store.root, self.store.root)
        self.assertEqual(len(PortfolioService(Store(target)).list_tasks()), 3)
        self.assertIn('恢复与完整性校验成功', page.result.text())
        self.assertIn('□ 真实／演示标记', page.result.text())
        self.assertEqual(self.errors, [])

    def test_failed_restore_clears_stale_success_and_keeps_nonempty_target(self):
        page = self.window.pages['reports']
        archive = self.window.exports.backup(self.base / '备份.zip')
        target = self.base / '已有资料'
        target.mkdir()
        sentinel = target / '保留.txt'
        sentinel.write_text('不得覆盖', encoding='utf-8')
        page.saved('恢复与完整性校验成功', self.base / '过去成功的目录')
        with patch('app.pages.QFileDialog.getOpenFileName', return_value=(str(archive), '')), \
                patch('app.pages.QFileDialog.getExistingDirectory', return_value=str(target)), \
                patch('app.pages.QMessageBox.question', return_value=QMessageBox.Yes):
            page.restore()
        self.wait_job()
        self.assertTrue(self.errors)
        self.assertEqual(self.infos, [])
        self.assertNotIn('恢复与完整性校验成功', page.result.text())
        self.assertIsNone(page.result_path)
        self.assertFalse(page.open_result_button.isEnabled())
        self.assertEqual(sentinel.read_text(encoding='utf-8'), '不得覆盖')

    def test_failed_backup_does_not_keep_old_success(self):
        page = self.window.pages['reports']
        old = self.base / '旧备份.zip'
        page.saved('完整备份成功', old)
        destination = self.base / '失败备份.zip'
        with patch('app.pages.QFileDialog.getSaveFileName', return_value=(str(destination), '')), \
                patch.object(self.window.exports, 'backup', side_effect=OSError('隔离模拟写入失败')):
            page.backup()
            self.wait_job()
        self.assertTrue(self.errors)
        self.assertNotIn('完整备份成功', page.result.text())
        self.assertIsNone(page.result_path)
        self.assertFalse(destination.exists())
        self.assertEqual(self.infos, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
