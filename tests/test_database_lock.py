"""Independent persistence safeguards and cross-process Qt locking."""
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from database.store import Store
from services.portfolio import PortfolioService


class DatabaseSafeguardsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='科研锁测试 ')
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / '中文 资料')
        self.service = PortfolioService(self.store)
        self.project = self.service.save_project({'name': '研究项目'})

    def test_foreign_keys_and_database_type_state_constraint(self):
        with self.store.connection() as conn:
            self.assertEqual(conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO achievements(project_id,name,type,status,created_at,updated_at) VALUES(?,?,'论文','已授权','x','x')", (self.project, '非法状态'))
            conn.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO tasks(project_id,title,priority,status,created_at,updated_at) VALUES(999,'不存在','中','待办','x','x')")
            conn.rollback()

    def test_archive_guard_prevents_raw_update_and_delete(self):
        task = self.service.save_task({'project_id': self.project, 'title': '保留任务'})
        self.service.archive_project(self.project)
        with self.store.connection() as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute('UPDATE tasks SET title=? WHERE id=?', ('非法修改', task))
            conn.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute('DELETE FROM projects WHERE id=?', (self.project,))
            conn.rollback()
        self.service.archive_project(self.project, False)
        self.service.save_task({'project_id': self.project, 'title': '恢复后可改'}, task)
        self.assertEqual(self.service.get_task(task)['title'], '恢复后可改')

    def test_config_reopen_and_unknown_schema_preserved(self):
        self.store.save_config({'name': '可编辑姓名', 'interests': '本地保存'})
        reopened = Store(self.store.root)
        self.assertEqual(reopened.config['name'], '可编辑姓名')
        with self.store.transaction() as conn:
            conn.execute('UPDATE schema_info SET version=999')
        with self.assertRaisesRegex(ValueError, '版本'):
            Store(self.store.root)
        with self.store.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM projects').fetchone()[0], 1)

    def test_null_required_name_rejected(self):
        with self.assertRaises(ValueError):
            self.service.save_project({'name': None})
        with self.assertRaises(ValueError):
            self.service.save_task({'project_id': self.project, 'title': None})
        with self.assertRaises(ValueError):
            self.service.save_achievement({'project_id': self.project, 'name': None})

    def test_single_directory_lock_rejected_by_second_process(self):
        from PySide6.QtCore import QLockFile
        lock_path = self.store.root / '.instance.lock'
        lock = QLockFile(str(lock_path))
        lock.setStaleLockTime(0)
        self.assertTrue(lock.tryLock(0))
        self.addCleanup(lock.unlock)
        code = 'from PySide6.QtCore import QLockFile; import sys; lock=QLockFile(sys.argv[1]); lock.setStaleLockTime(0); sys.exit(0 if lock.tryLock(0) else 2)'
        same = subprocess.run([sys.executable, '-c', code, str(lock_path)], timeout=15, capture_output=True)
        other = subprocess.run([sys.executable, '-c', code, str(self.store.root / 'different.lock')], timeout=15, capture_output=True)
        self.assertEqual(same.returncode, 2, same.stderr)
        self.assertEqual(other.returncode, 0, other.stderr)


if __name__ == '__main__':
    unittest.main()
