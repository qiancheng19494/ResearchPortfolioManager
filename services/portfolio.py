"""Projects, tasks, achievements and date-aware reminders."""
from __future__ import annotations

from datetime import date, datetime, timedelta

PROJECT_CATEGORIES = ['研究', '软著', '竞赛', '课程', '其他']
PROJECT_STATUSES = ['计划中', '进行中', '已完成', '暂停']
TASK_STATUSES = ['待办', '进行中', '已完成']
PRIORITIES = ['低', '中', '高']
ACHIEVEMENT_STATUSES = {
    '论文': ['准备中', '已投稿', '审稿中', '已录用', '已发表', '退稿'],
    '软件著作权': ['准备中', '已提交', '已受理', '补正中', '已登记', '未获登记'],
    '专利': ['准备中', '已提交', '已受理', '审查中', '已授权', '终止'],
    '竞赛成果': ['准备中', '已报名', '参赛中', '已获奖', '已结束'],
    '其他成果': ['准备中', '进行中', '已完成'],
}


def now():
    return datetime.now().isoformat(timespec='seconds')


def clean_date(value):
    if value is None or value == '':
        return None
    value = str(value)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('日期必须为合法的 YYYY-MM-DD') from exc
    if parsed.isoformat() != value:
        raise ValueError('日期必须为 YYYY-MM-DD')
    return value


def required(data, key, label):
    raw = data.get(key)
    value = '' if raw is None else str(raw).strip()
    if not value:
        raise ValueError(f'{label}不能为空')
    return value


def choice(value, options, label):
    if value not in options:
        raise ValueError(f'{label}选项无效')
    return value


def like_pattern(value):
    return '%' + str(value).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


class PortfolioService:
    def __init__(self, store):
        self.store = store

    def _get(self, table, record_id):
        with self.store.connection() as conn:
            row = conn.execute(f'SELECT * FROM {table} WHERE id=?', (record_id,)).fetchone()
        if row is None:
            raise ValueError('记录不存在')
        return dict(row)

    def get_project(self, record_id):
        return self._get('projects', record_id)

    def get_task(self, record_id):
        return self._get('tasks', record_id)

    def get_achievement(self, record_id):
        return self._get('achievements', record_id)

    def require_project(self, project_id, writable=False):
        result = self.get_project(project_id)
        if writable and result['archived']:
            raise ValueError('归档项目及其关联记录只读，请先恢复项目')
        return result

    def _save(self, table, values, record_id=None, conn=None):
        fields = list(values)
        if record_id is None:
            columns = ','.join(fields)
            placeholders = ','.join('?' for _ in fields)
            return conn.execute(f'INSERT INTO {table}({columns}) VALUES({placeholders})', tuple(values.values())).lastrowid
        setters = ','.join(f'{field}=?' for field in fields)
        if conn.execute(f'UPDATE {table} SET {setters} WHERE id=?', (*values.values(), record_id)).rowcount != 1:
            raise ValueError('记录不存在')
        return record_id

    def save_project(self, data, project_id=None):
        leader = data['leader'] if 'leader' in data else self.store.config.get('name')
        if not isinstance(leader, str) or not leader.strip():
            raise ValueError('负责人不能为空')
        values = {
            'name': required(data, 'name', '项目名称'),
            'category': choice(data.get('category', '研究'), PROJECT_CATEGORIES, '项目类别'),
            'description': str(data.get('description', '')).strip(),
            'leader': leader.strip(),
            'start_date': clean_date(data.get('start_date')),
            'end_date': clean_date(data.get('end_date')),
            'status': choice(data.get('status', '计划中'), PROJECT_STATUSES, '项目状态'),
            'notes': str(data.get('notes', '')).strip(),
            'updated_at': now(),
        }
        if values['start_date'] and values['end_date'] and values['start_date'] > values['end_date']:
            raise ValueError('计划结束日期不能早于开始日期')
        with self.store.transaction() as conn:
            if project_id is None:
                values['created_at'] = values['updated_at']
            else:
                self.require_project(project_id, writable=True)
            return self._save('projects', values, project_id, conn)

    def archive_project(self, project_id, archived=True):
        with self.store.transaction() as conn:
            self.require_project(project_id)
            conn.execute('UPDATE projects SET archived=?,updated_at=? WHERE id=?', (int(bool(archived)), now(), project_id))

    def save_task(self, data, task_id=None):
        state = choice(data.get('status', '待办'), TASK_STATUSES, '任务状态')
        values = {
            'project_id': data.get('project_id'),
            'title': required(data, 'title', '任务标题'),
            'description': str(data.get('description', '')).strip(),
            'due_date': clean_date(data.get('due_date')),
            'priority': choice(data.get('priority', '中'), PRIORITIES, '任务优先级'),
            'status': state, 'updated_at': now(),
        }
        with self.store.transaction() as conn:
            self.require_project(values['project_id'], writable=True)
            old = self.get_task(task_id) if task_id is not None else None
            if old:
                self.require_project(old['project_id'], writable=True)
            values['completed_at'] = (old['completed_at'] if old and old['status'] == '已完成' else values['updated_at']) if state == '已完成' else None
            if not old:
                values['created_at'] = values['updated_at']
            return self._save('tasks', values, task_id, conn)

    def delete_task(self, task_id):
        with self.store.transaction() as conn:
            self.require_project(self.get_task(task_id)['project_id'], writable=True)
            conn.execute('DELETE FROM tasks WHERE id=?', (task_id,))

    def save_achievement(self, data, achievement_id=None):
        kind = choice(data.get('type', '其他成果'), ACHIEVEMENT_STATUSES, '成果类型')
        values = {
            'project_id': data.get('project_id'), 'name': required(data, 'name', '成果名称'),
            'type': kind, 'status': choice(data.get('status', '准备中'), ACHIEVEMENT_STATUSES[kind], '成果状态与类型组合'),
            'related_date': clean_date(data.get('related_date')),
            'reference': str(data.get('reference', '')).strip(),
            'contribution': str(data.get('contribution', '')).strip(),
            'notes': str(data.get('notes', '')).strip(), 'updated_at': now(),
        }
        with self.store.transaction() as conn:
            self.require_project(values['project_id'], writable=True)
            if achievement_id is None:
                values['created_at'] = values['updated_at']
            else:
                old = self.get_achievement(achievement_id)
                self.require_project(old['project_id'], writable=True)
                if old['project_id'] != values['project_id'] and conn.execute('SELECT 1 FROM materials WHERE achievement_id=?', (achievement_id,)).fetchone():
                    raise ValueError('成果有关联材料，请先解除材料关联再更改项目')
            return self._save('achievements', values, achievement_id, conn)

    def delete_achievement(self, achievement_id):
        with self.store.transaction() as conn:
            self.require_project(self.get_achievement(achievement_id)['project_id'], writable=True)
            if conn.execute('SELECT 1 FROM materials WHERE achievement_id=?', (achievement_id,)).fetchone():
                raise ValueError('成果有关联材料，请先在材料归档中解除关联')
            conn.execute('DELETE FROM achievements WHERE id=?', (achievement_id,))

    def list_projects(self, keyword='', category='', status='', include_archived=False):
        clauses, args = [], []
        if not include_archived:
            clauses.append('archived=0')
        if keyword:
            clauses.append("(name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR leader LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\')")
            args.extend([like_pattern(keyword)] * 4)
        for key, value in [('category', category), ('status', status)]:
            if value:
                clauses.append(f'{key}=?')
                args.append(value)
        sql = 'SELECT * FROM projects' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY updated_at DESC,id DESC'
        with self.store.connection() as conn:
            return [dict(row) for row in conn.execute(sql, args)]

    def _list_related(self, table, keyword='', project_id=None, status='', type='', date_from='', date_to='', active_only=False):
        clauses, args = [], []
        if keyword:
            columns = ['title', 'description'] if table == 'tasks' else ['name', 'reference', 'contribution', 'notes']
            clauses.append('(' + ' OR '.join(f"r.{col} LIKE ? ESCAPE '\\'" for col in columns) + ')')
            args.extend([like_pattern(keyword)] * len(columns))
        for key, value in [('project_id', project_id), ('status', status), ('type', type)]:
            if value is not None and value != '':
                clauses.append(f'r.{key}=?')
                args.append(value)
        for operator, value in [('>=', date_from), ('<=', date_to)]:
            if value:
                clauses.append(f'r.related_date{operator}?')
                args.append(clean_date(value))
        if date_from and date_to and date_from > date_to:
            raise ValueError('日期范围起点不能晚于终点')
        if active_only:
            clauses.append('p.archived=0')
        sql = f'SELECT r.*,p.name AS project_name,p.archived AS project_archived FROM {table} r JOIN projects p ON p.id=r.project_id'
        sql += (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY r.updated_at DESC,r.id DESC'
        with self.store.connection() as conn:
            return [dict(row) for row in conn.execute(sql, args)]

    def list_tasks(self, keyword='', project_id=None, status='', active_only=False):
        return self._list_related('tasks', keyword, project_id, status, active_only=active_only)

    def list_achievements(self, keyword='', project_id=None, type='', status='', date_from='', date_to=''):
        return self._list_related('achievements', keyword, project_id, status, type, date_from, date_to)

    def dashboard(self, today=None):
        if today is None:
            today = date.today()
        elif isinstance(today, str):
            today = date.fromisoformat(clean_date(today))
        end = (today + timedelta(days=7)).isoformat()
        current = today.isoformat()
        unfinished = [t for t in self.list_tasks(active_only=True) if t['status'] != '已完成']
        overdue = sorted([t for t in unfinished if t['due_date'] and t['due_date'] < current], key=lambda t: t['due_date'])
        today_tasks = [t for t in unfinished if t['due_date'] == current]
        upcoming = sorted([t for t in unfinished if t['due_date'] and current < t['due_date'] <= end], key=lambda t: t['due_date'])
        with self.store.connection() as conn:
            counts = {key: conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for key, table in [('achievements_count', 'achievements'), ('materials_count', 'materials')]}
        projects = self.list_projects()
        return counts | {'projects_count': len(projects), 'tasks_count': len(unfinished), 'overdue_count': len(overdue),
                         'today_tasks': today_tasks, 'upcoming_tasks': upcoming, 'overdue_tasks': overdue, 'recent_projects': projects[:8]}

    def project_detail(self, project_id):
        from services.materials import MaterialService
        return {'project': self.get_project(project_id), 'tasks': self.list_tasks(project_id=project_id),
                'achievements': self.list_achievements(project_id=project_id),
                'materials': MaterialService(self.store).list_materials(project_id=project_id)}
