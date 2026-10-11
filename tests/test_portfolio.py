"""Core and end-to-end checks. Every database lives in a TemporaryDirectory."""

import csv
from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from database.store import Store
from services.portfolio import PortfolioService
from services.materials import MaterialService
from services.export_backup import ExportBackupService


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="科研测试 中文 空格 ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = Store(self.base / "资料 中文")
        self.service = PortfolioService(self.store)
        self.materials = MaterialService(self.store)
        self.exports = ExportBackupService(self.store)

    def project(self, name="测试项目", **changes):
        data = dict(name=name, category="研究", description="项目说明", leader="示例用户",
                    start_date="2026-10-01", end_date="2026-12-01", status="进行中", notes="")
        data.update(changes)
        return self.service.save_project(data)

    def task(self, pid, title="测试任务", **changes):
        data = dict(project_id=pid, title=title, description="任务说明", due_date="2026-10-10",
                    priority="中", status="待办")
        data.update(changes)
        return self.service.save_task(data)

    def achievement(self, pid, name="测试成果", **changes):
        data = dict(project_id=pid, name=name, type="论文", status="准备中", related_date="2026-10-10",
                    reference="", contribution="测试贡献", notes="示例，不是真实履历")
        data.update(changes)
        return self.service.save_achievement(data)

    def source(self, name="演示.txt", text="测试材料，不是真实科研成果"):
        p = self.base / "原文件" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_empty_initialization_and_config_persistence(self):
        self.assertEqual(self.service.list_projects(), [])
        self.assertEqual(self.service.list_tasks(), [])
        self.assertEqual(self.service.list_achievements(), [])
        self.assertEqual(self.materials.list_materials(), [])
        self.assertFalse(self.store.config.get("demo", False))
        self.assertEqual(self.service.dashboard(date(2026, 10, 10))["tasks_count"], 0)
        cfg = dict(self.store.config, name="测试姓名", interests="修改后兴趣")
        self.store.save_config(cfg)
        reopened = Store(self.store.root)
        self.assertEqual(reopened.config["name"], "测试姓名")
        self.assertEqual(reopened.config["interests"], "修改后兴趣")

    def test_persistence_edits_and_project_detail(self):
        pid = self.project()
        tid = self.task(pid)
        aid = self.achievement(pid)
        mid = self.materials.import_file(self.source(), pid, aid)
        p = self.service.get_project(pid)
        self.service.save_project(dict(p, name="修改后的项目"), pid)
        t = self.service.get_task(tid)
        self.service.save_task(dict(t, title="修改后的任务"), tid)
        a = self.service.get_achievement(aid)
        self.service.save_achievement(dict(a, notes="已修改备注"), aid)
        svc = PortfolioService(Store(self.store.root))
        self.assertEqual(svc.get_project(pid)["name"], "修改后的项目")
        self.assertEqual(svc.get_task(tid)["title"], "修改后的任务")
        self.assertEqual(svc.get_achievement(aid)["notes"], "已修改备注")
        detail = svc.project_detail(pid)
        self.assertEqual(len(detail["tasks"]), 1)
        self.assertEqual(len(detail["achievements"]), 1)
        self.assertEqual(detail["materials"][0]["id"], mid)

    def test_required_fields_dates_and_enums(self):
        for changes in ({"name": " "}, {"category": "不存在"}, {"status": "不存在"},
                        {"start_date": "2026-02-30"}, {"end_date": "2026-09-30"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.project(**changes)
        pid = self.project()
        for changes in ({"title": " "}, {"due_date": "2026-13-01"},
                        {"status": "不存在"}, {"priority": "不存在"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.task(pid, **changes)
        for changes in ({"name": " "}, {"related_date": "2026-02-30"},
                        {"type": "不存在"}, {"status": "已授权"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.achievement(pid, **changes)

    def test_illegal_associations_and_foreign_keys(self):
        pid = self.project()
        other = self.project("第二项目")
        aid = self.achievement(pid)
        with self.assertRaises(ValueError):
            self.task(999999)
        with self.assertRaises(ValueError):
            self.achievement(999999)
        with self.assertRaises(ValueError):
            self.materials.import_file(self.source(), other, aid)
        with self.assertRaises(ValueError):
            self.materials.import_file(self.source(), pid, 999999)
        with self.store.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE achievements SET project_id=999999 WHERE id=?", (aid,))

    def test_type_status_constraints_and_change(self):
        pid = self.project()
        aid = self.achievement(pid, status="已发表")
        record = self.service.get_achievement(aid)
        with self.assertRaises(ValueError):
            self.service.save_achievement(dict(record, type="软件著作权"), aid)
        self.service.save_achievement(dict(record, type="软件著作权", status="准备中"), aid)
        self.assertEqual(self.service.get_achievement(aid)["type"], "软件著作权")
        self.assertEqual(self.service.get_achievement(aid)["status"], "准备中")

    def test_fixed_date_dashboard_boundaries(self):
        pid = self.project()
        yesterday = self.task(pid, "昨天", due_date="2026-10-09")
        today = self.task(pid, "今天", due_date="2026-10-10")
        tomorrow = self.task(pid, "明天", due_date="2026-10-11")
        seventh = self.task(pid, "第七天", due_date="2026-10-17")
        self.task(pid, "第八天", due_date="2026-10-18")
        self.task(pid, "没有日期", due_date="")
        self.task(pid, "已经完成", due_date="2026-10-09", status="已完成")
        self.achievement(pid)
        self.materials.import_file(self.source(), pid)
        dashboard = self.service.dashboard("2026-10-10")
        self.assertEqual(dashboard["projects_count"], 1)
        self.assertEqual(dashboard["tasks_count"], 6)
        self.assertEqual(dashboard["overdue_count"], 1)
        self.assertEqual(dashboard["achievements_count"], 1)
        self.assertEqual(dashboard["materials_count"], 1)
        self.assertEqual([x["id"] for x in dashboard["overdue_tasks"]], [yesterday])
        self.assertEqual([x["id"] for x in dashboard["today_tasks"]], [today])
        self.assertEqual({x["id"] for x in dashboard["upcoming_tasks"]}, {tomorrow, seventh})

    def test_completed_time_tracks_status(self):
        pid = self.project()
        tid = self.task(pid)
        task = self.service.get_task(tid)
        self.assertFalse(task["completed_at"])
        self.service.save_task(dict(task, status="已完成"), tid)
        complete = self.service.get_task(tid)
        self.assertTrue(complete["completed_at"])
        self.service.save_task(dict(complete, status="已完成", title="保留完成时间"), tid)
        self.assertEqual(self.service.get_task(tid)["completed_at"], complete["completed_at"])
        self.service.save_task(dict(complete, status="进行中"), tid)
        self.assertFalse(self.service.get_task(tid)["completed_at"])

    def test_archive_preserves_and_freezes_all_associations(self):
        pid = self.project()
        tid = self.task(pid, due_date="2026-10-09")
        aid = self.achievement(pid)
        mid = self.materials.import_file(self.source(), pid, aid)
        self.service.archive_project(pid)
        self.assertEqual(self.service.list_projects(), [])
        self.assertEqual(len(self.service.list_projects(include_archived=True)), 1)
        self.assertEqual(len(self.service.list_tasks(project_id=pid)), 1)
        self.assertEqual(self.service.list_tasks(active_only=True), [])
        dashboard = self.service.dashboard("2026-10-10")
        self.assertEqual(dashboard["projects_count"], 0)
        self.assertEqual(dashboard["tasks_count"], 0)
        self.assertEqual(dashboard["overdue_count"], 0)
        operations = [lambda: self.service.save_project(self.service.get_project(pid), pid),
                      lambda: self.task(pid),
                      lambda: self.service.save_task(self.service.get_task(tid), tid),
                      lambda: self.service.delete_task(tid),
                      lambda: self.achievement(pid),
                      lambda: self.service.save_achievement(self.service.get_achievement(aid), aid),
                      lambda: self.service.delete_achievement(aid),
                      lambda: self.materials.import_file(self.source("新文件.txt"), pid),
                      lambda: self.materials.update_material(mid, aid)]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation()
        self.assertTrue(self.materials.file_path(mid, verify=True).is_file())
        self.service.archive_project(pid, False)
        self.service.save_task(dict(self.service.get_task(tid), status="进行中"), tid)
        self.assertEqual(len(self.service.project_detail(pid)["materials"]), 1)

    def test_achievement_delete_requires_unlink_and_task_delete_is_local(self):
        pid = self.project()
        tid = self.task(pid)
        aid = self.achievement(pid)
        mid = self.materials.import_file(self.source(), pid, aid)
        with self.assertRaises(ValueError):
            self.service.delete_achievement(aid)
        self.materials.update_material(mid, achievement_id=None)
        self.service.delete_achievement(aid)
        self.service.delete_task(tid)
        self.assertEqual(self.service.list_achievements(), [])
        self.assertEqual(self.service.list_tasks(), [])
        self.assertIsNotNone(self.service.get_project(pid))
        self.assertTrue(self.materials.file_path(mid, verify=True).is_file())

    def test_filters_include_literal_wildcards(self):
        pid = self.project("特殊 % 项目")
        other = self.project("其他课程", category="课程", status="计划中")
        a = self.achievement(pid, "特定论文", related_date="2026-10-01")
        self.achievement(other, "特定其他", type="其他成果", status="进行中", related_date="2026-10-20")
        self.task(pid, "需要查找")
        self.task(other, "完成查找", status="已完成")
        self.assertEqual(len(self.service.list_projects(keyword="%")), 1)
        self.assertEqual(len(self.service.list_projects(category="课程", status="计划中")), 1)
        self.assertEqual(len(self.service.list_tasks(keyword="查找", project_id=pid, status="待办")), 1)
        records = self.service.list_achievements(keyword="特定", project_id=pid, type="论文", status="准备中",
                                                 date_from="2026-10-01", date_to="2026-10-10")
        self.assertEqual([x["id"] for x in records], [a])
        with self.assertRaises(ValueError):
            self.service.list_achievements(date_from="2026-10-10", date_to="2026-10-01")

    def test_material_versions_hashes_and_source_unchanged(self):
        pid = self.project()
        aid = self.achievement(pid)
        first = self.source(text="第一版内容")
        old_hash = hashlib.sha256(first.read_bytes()).hexdigest()
        first_id = self.materials.import_file(first, pid, aid, version_label="V1")
        second = self.base / "另一 原目录" / first.name
        second.parent.mkdir()
        second.write_text("第二版内容", encoding="utf-8")
        second_id = self.materials.import_file(second, pid, aid, version_label="V2")
        self.assertNotEqual(first_id, second_id)
        a, b = self.materials.get_material(first_id), self.materials.get_material(second_id)
        self.assertNotEqual(a["relative_path"], b["relative_path"])
        self.assertEqual(a["sha256"], old_hash)
        self.assertEqual(first.read_text(encoding="utf-8"), "第一版内容")
        self.assertEqual(second.read_text(encoding="utf-8"), "第二版内容")
        for mid, original in ((first_id, first), (second_id, second)):
            material = self.materials.get_material(mid)
            managed = self.materials.file_path(mid, verify=True)
            self.assertEqual(managed.read_bytes(), original.read_bytes())
            self.assertEqual(material["size"], len(original.read_bytes()))
            self.assertEqual(material["sha256"], hashlib.sha256(managed.read_bytes()).hexdigest())
        self.assertEqual(len(self.materials.list_materials(keyword="演示", project_id=pid, achievement_id=aid)), 2)

    def test_material_copy_failure_has_no_record_or_leftover(self):
        pid = self.project()
        source = self.source()
        # Both standard copy entry points are blocked, without touching the source.
        with patch("services.materials.shutil.copy2", side_effect=OSError("测试复制失败")), \
                patch("services.materials.shutil.copyfile", side_effect=OSError("测试复制失败")):
            with self.assertRaises(Exception):
                self.materials.import_file(source, pid)
        self.assertEqual(self.materials.list_materials(), [])
        self.assertEqual(source.read_text(encoding="utf-8"), "测试材料，不是真实科研成果")
        self.assertEqual([p for p in (self.store.root / "materials").rglob("*") if p.is_file()], [])

    def test_missing_material_and_unsupported_import(self):
        pid = self.project()
        mid = self.materials.import_file(self.source(), pid)
        path = self.materials.file_path(mid)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.materials.file_path(mid)
        self.assertEqual(len(self.materials.list_materials()), 1)
        for name in ("危险.py", "程序.exe", "无类型"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.materials.import_file(self.source(name), pid)

    def test_csv_filter_bom_formula_neutralization_and_html_escape(self):
        pid = self.project("项目 <标题> & 测试", description='说明 <script>alert("x")</script>')
        aid = self.achievement(pid, "=1+1", reference="+SUM(A1:A2)", contribution="@测试", notes="-备注")
        self.achievement(pid, "另一成果", type="其他成果", status="进行中")
        self.achievement(self.project("其他项目"), "其他论文")
        path = self.exports.export_csv(self.base / "筛选成果.csv", pid, "论文", "准备中")
        self.assertEqual(path.read_bytes()[:3], b"\xef\xbb\xbf")
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))
        self.assertEqual(len(rows), 2)
        combined = "|".join(rows[1])
        self.assertIn("'=1+1", combined)
        self.assertIn("'+SUM(A1:A2)", combined)
        self.assertIn("'@测试", combined)
        self.assertIn("'-备注", combined)
        self.assertEqual(self.service.get_achievement(aid)["name"], "=1+1")
        report = self.exports.export_html(self.base / "摘要.html", pid).read_text(encoding="utf-8")
        self.assertIn("&lt;标题&gt;", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertNotIn('<script>alert("x")</script>', report)

    def test_end_to_end_export_backup_restore(self):
        pid = self.project("端到端 演示项目")
        tid = self.task(pid, "完成端到端流程")
        aid = self.achievement(pid, "端到端 示例论文")
        mid1 = self.materials.import_file(self.source(text="端到端第一版"), pid, aid, version_label="V1")
        mid2 = self.materials.import_file(self.source("演示 V2.txt", text="端到端第二版"), pid, aid, version_label="V2")
        self.assertEqual(len(self.service.list_projects(keyword="端到端")), 1)
        self.assertEqual(len(self.materials.list_materials(project_id=pid, achievement_id=aid)), 2)
        self.assertTrue(self.exports.export_csv(self.base / "台账.csv", project_id=pid).is_file())
        self.assertTrue(self.exports.export_html(self.base / "摘要.html", pid).is_file())
        archive = self.exports.backup(self.base / "完整备份.zip")
        with zipfile.ZipFile(archive) as file:
            names = file.namelist()
            self.assertIn("manifest.json", names)
            self.assertFalse(any(name.endswith(".zip") for name in names))
            self.assertTrue(json.loads(file.read("manifest.json")))
        target = self.base / "恢复 中文 目录"
        result = self.exports.restore(archive, target)
        self.assertEqual(Path(result).resolve(), target.resolve())
        restored = Store(target)
        svc = PortfolioService(restored)
        mats = MaterialService(restored)
        self.assertEqual(svc.get_project(pid), self.service.get_project(pid))
        self.assertEqual(svc.get_task(tid), self.service.get_task(tid))
        self.assertEqual(svc.get_achievement(aid), self.service.get_achievement(aid))
        for mid in (mid1, mid2):
            self.assertEqual(mats.get_material(mid), self.materials.get_material(mid))
            self.assertEqual(mats.file_path(mid, verify=True).read_bytes(), self.materials.file_path(mid, verify=True).read_bytes())
        with restored.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_restore_rejects_corruption_path_escape_nonempty_and_unsupported(self):
        pid = self.project()
        self.materials.import_file(self.source(), pid)
        good = self.exports.backup(self.base / "好备份.zip")
        nonempty = self.base / "非空"
        nonempty.mkdir()
        sentinel = nonempty / "保留.txt"
        sentinel.write_text("保留", encoding="utf-8")
        with self.assertRaises(Exception):
            self.exports.restore(good, nonempty)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "保留")
        corrupt = self.base / "损坏.zip"
        corrupt.write_bytes(b"not a zip archive")
        with self.assertRaises(Exception):
            self.exports.restore(corrupt, self.base / "损坏恢复")
        for dangerous in ("../escape.txt", "/absolute.txt", "C:/drive.txt", "a/../../escape.txt"):
            bad = self.base / ("危险" + str(len(dangerous)) + ".zip")
            with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
                for member in src.infolist():
                    dst.writestr(member, src.read(member.filename))
                dst.writestr(dangerous, "危险内容")
            with self.subTest(path=dangerous), self.assertRaises(Exception):
                self.exports.restore(bad, self.base / ("危险恢复" + str(len(dangerous))))
        unsupported = self.base / "不支持.zip"
        with zipfile.ZipFile(unsupported, "w") as dst:
            dst.writestr("manifest.json", json.dumps({"format_version": 999, "schema_version": 999, "files": {}}))
        with self.assertRaises(Exception):
            self.exports.restore(unsupported, self.base / "不支持恢复")
        with zipfile.ZipFile(good) as src, zipfile.ZipFile(self.base / "哈希损坏.zip", "w") as dst:
            changed = False
            for member in src.infolist():
                data = src.read(member.filename)
                if member.filename != "manifest.json" and not changed:
                    data = bytes([data[0] ^ 1]) + data[1:]
                    changed = True
                dst.writestr(member, data)
        with self.assertRaises(Exception):
            self.exports.restore(self.base / "哈希损坏.zip", self.base / "哈希恢复")
        self.assertEqual(len(self.service.list_projects()), 1)
        self.assertTrue(self.materials.file_path(self.materials.list_materials()[0]["id"], verify=True).is_file())

    def test_restore_rejects_rehashed_database_and_missing_material_reference(self):
        """Valid ZIP hashes do not replace schema/relational/reference validation."""
        pid = self.project()
        self.materials.import_file(self.source(), pid)
        good = self.exports.backup(self.base / "结构备份.zip")
        for case in ("schema", "reference", "foreign_key"):
            stage = self.base / ("变更 " + case)
            stage.mkdir()
            with zipfile.ZipFile(good) as package:
                package.extractall(stage)  # Known locally generated safe package, never user input.
            manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
            db = stage / "portfolio.sqlite3"
            with closing(sqlite3.connect(db)) as connection:
                with connection:
                    if case == "schema":
                        connection.execute("UPDATE schema_info SET version=999")
                    elif case == "reference":
                        connection.execute("UPDATE materials SET relative_path='materials/absent/missing.txt'")
                    else:
                        connection.execute("UPDATE materials SET project_id=999999")
            manifest["files"]["portfolio.sqlite3"] = {
                "size": db.stat().st_size, "sha256": hashlib.sha256(db.read_bytes()).hexdigest()}
            (stage / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            bad = self.base / (case + ".zip")
            with zipfile.ZipFile(bad, "w") as package:
                for item in stage.rglob("*"):
                    if item.is_file():
                        package.write(item, item.relative_to(stage).as_posix())
            with self.subTest(case=case), self.assertRaises(Exception):
                self.exports.restore(bad, self.base / ("拒绝 " + case))

    def test_demo_is_labelled_and_refuses_populated_directory(self):
        from demo import create_demo
        target = self.base / "演示资料"
        create_demo(target)
        demo_store = Store(target)
        self.assertTrue(demo_store.config["demo"])
        svc = PortfolioService(demo_store)
        self.assertEqual(len(svc.list_projects()), 2)
        self.assertTrue(all(p["name"].startswith("【演示】") for p in svc.list_projects()))
        materials = MaterialService(demo_store)
        self.assertEqual(len(materials.list_materials()), 4)
        self.assertTrue(all(m["original_name"].endswith(".txt") for m in materials.list_materials()))
        with self.assertRaises(ValueError):
            create_demo(target)
        self.assertEqual(len(svc.list_projects()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
