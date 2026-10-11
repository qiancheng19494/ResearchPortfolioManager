"""Build explicitly labelled demo data, never modifying a populated directory."""

import argparse
from pathlib import Path
import tempfile

from database.store import Store
from services.portfolio import PortfolioService
from services.materials import MaterialService


def create_demo(data_dir):
    root = Path(data_dir).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("演示目录必须不存在或为空；不会覆盖已有资料。")
    store = Store(root)
    store.save_config(dict(store.config, demo=True))
    svc = PortfolioService(store)
    mats = MaterialService(store)
    projects = [
        ("【演示】局域网安全监测管理系统", "研究", "示例项目，用于体验项目、任务、成果与材料关联。"),
        ("【演示】航空航班延误智能预测与决策分析系统", "研究", "示例项目，用于体验检索和摘要报告。"),
    ]
    with tempfile.TemporaryDirectory(prefix="ResearchPortfolioDemo_") as tmp:
        for index, (name, category, description) in enumerate(projects, 1):
            pid = svc.save_project(dict(name=name, category=category, description=description,
                                       leader="示例用户（演示资料）", start_date="2026-10-01", end_date="2026-12-01",
                                       status="进行中", notes="全部状态、日期和材料均为软件演示，不代表真实履历。"))
            svc.save_task(dict(project_id=pid, title="【演示】整理需求与材料", description="仅用于展示操作。",
                               due_date="2026-10-10", priority="中", status="待办"))
            svc.save_task(dict(project_id=pid, title="【演示】复核项目摘要", description="仅用于展示操作。",
                               due_date="2026-10-15", priority="高", status="进行中"))
            aid = svc.save_achievement(dict(project_id=pid, name="【演示】成果准备记录", type="其他成果", status="准备中",
                                           related_date="2026-10-10", reference="", contribution="演示贡献说明",
                                           notes="没有登记号、奖项、论文录用或授权声明。"))
            for version in (1, 2):
                source = Path(tmp) / f"项目{index}" / "演示材料.txt"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(f"演示数据\n{name}\n版本 V{version}\n此附件由演示生成器新建，不是真实科研成果证明。\n", encoding="utf-8")
                mats.import_file(source, pid, aid, category="其他", version_label=f"V{version}", notes="新生成的演示文本附件")
    return root


def main():
    parser = argparse.ArgumentParser(description="创建独立演示资料目录；非空目录会被拒绝。")
    parser.add_argument("--data-dir", default=str(Path(__file__).parent / "demo_data"))
    args = parser.parse_args()
    try:
        root = create_demo(args.data_dir)
    except Exception as exc:
        parser.exit(1, f"演示资料创建失败：{exc}\n")
    print(f"演示数据已创建：{root}")
    print('使用 main.py --data-dir "上述目录" 启动。界面将标注“演示数据”。')


if __name__ == "__main__":
    main()
