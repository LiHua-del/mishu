"""独立热榜研究：官方列表、按榜单隔离的每日快照与有覆盖说明的趋势。"""
from __future__ import annotations
import gzip
import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .config import DATA_DIR, FANQIE_GENRES
from .sources.common import clean_html_text
from .sources.fanqie import parse_fanqie_rank
from .sources.qidian import parse_qidian_rank
from .sources.qq_read import parse_qq_rank
from .sources.shuqi import parse_shuqi_rank

TZ = ZoneInfo('Asia/Shanghai')
LOCK = threading.Lock()
ROOT = DATA_DIR / 'hotlists'
CATALOG = []

def add(key, platform, audience, category, label, url, kind, note):
    CATALOG.append(dict(id=key, platform=platform, audience=audience, category=category,
                        label=label, url=url, kind=kind, note=note))

for gender, category, label in dict.fromkeys(x for xs in FANQIE_GENRES.values() for x in xs):
    for rank_type, name in [('2', '阅读榜'), ('1', '新书榜')]:
        add(f'fq-{gender}-{category}-{rank_type}', '番茄', 'male' if gender == '1' else 'female', label,
            name, f'https://fanqienovel.com/rank/{gender}_{rank_type}_{category}', 'fanqie', '官方分类榜；仅采集入口当前公开条目')
add('qd-month', '起点', 'male', '全部', '月票榜（本月）',
    'https://m.qidian.com/rank/yuepiao/{month}/', 'qidian', '自然月累计，不是滚动30天；女频暂未接入')
for audience, gender in [('male', 'boy'), ('female', 'girl')]:
    for period, name in [('date', '大热榜（日榜）'), ('month', '大热榜（官方月榜）')]:
        add(f'qm-{gender}-{period}', '七猫', audience, '全部', name,
            f'https://www.qimao.com/paihang/{gender}/hot/{period}/', 'qimao', '统计月份或日期以页面说明为准')
    for suffix, name in [('Click', '点击榜'), ('Store', '收藏榜'), ('Order', '订阅榜')]:
        add(f'sq-{gender}-{suffix}', '书旗', audience, '全部', name,
            f'https://ognv.shuqi.com/ranklist?rank={gender}{suffix}&page=1', 'shuqi', '统计周期未确认；仅第一页')
    add(f'qq-{audience}', 'QQ阅读', audience, '全部', '热门榜（全部书籍）',
        f'https://book.qq.com/book-rank/{audience}-sell/cycle-5', 'qq', 'cycle-5表示全部上架时长，不是周/月榜；仅第一页')
BOARDS = {x['id']: x for x in CATALOG}

def complete_font(books, body):
    supplement = Path(__file__).resolve().parents[1] / 'data/hotlists_font_supplement.json'
    if not supplement.exists():
        return
    data = json.loads(supplement.read_text(encoding='utf-8'))
    if data['font_hash'] not in body:
        return
    mapping = {int(k, 16):v for k,v in data['map'].items()}
    for book in books:
        for field in ('title', 'author', 'description'):
            book[field] = str(book.get(field, '')).translate(mapping)
        if any('\ue000' <= c <= '\uf8ff' for c in book['description']):
            book['description'] = re.sub('[\ue000-\uf8ff]', '□', book['description']) + '（□为未能还原的字符，请以官方详情为准）'

def now():
    return datetime.now(TZ)

@contextmanager
def connect():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'snapshots.db', timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

def init():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS snapshots (board TEXT, day TEXT, payload TEXT NOT NULL, PRIMARY KEY(board,day))')
        db.execute('CREATE TABLE IF NOT EXISTS attempts (board TEXT PRIMARY KEY, at TEXT, error TEXT)')

def qimao(body):
    books = []
    for item in re.findall(r'<li\b[^>]*class="rank-list-item"[^>]*>(.*?)</li>', body, re.S):
        def field(cls):
            m = re.search(r'<(?:span|a|em)[^>]*class="' + cls + r'(?: [^"]*)?"[^>]*>(.*?)</(?:span|a|em)>', item, re.S)
            return clean_html_text(m.group(1)) if m else ''
        bid = re.search(r'/shuku/(\d+)/', item)
        title, rank = field('s-book-title'), field('rank-number')
        if not bid or not title or not rank.isdigit():
            continue
        author = re.search(r'<a[^>]*href="[^"]*/zuozhe/[^"]*"[^>]*>(.*?)</a>', item, re.S)
        categories = re.findall(r'<a[^>]*href="[^"]*/shuku/a-[^"]*"[^>]*>(.*?)</a>', item, re.S)
        books.append(dict(id='qimao-' + bid[1], title=title, rank=int(rank),
            author=clean_html_text(author[1]) if author else '未知作者',
            genres=[clean_html_text(x) for x in categories], description=field('s-book-intro'),
            url=f'https://www.qimao.com/shuku/{bid[1]}/',
            metric='热度 ' + field('rank-num') + field('rank-unit')))
    return books

def collect(board_id, fetch_html):
    board = BOARDS[board_id]
    # 序列化采集，防止手动刷新与每日任务重叠访问同一站点。
    with LOCK:
        stamp = now()
        url = board['url'].format(month=stamp.strftime('%Y%m'))
        try:
            body = fetch_html(url)
            raw = ROOT / 'raw' / stamp.strftime('%Y-%m-%d')
            raw.mkdir(parents=True, exist_ok=True)
            path = raw / (board_id + '-' + stamp.strftime('%H%M%S%f') + '.html.gz')
            with gzip.open(path, 'wt', encoding='utf-8') as output:
                output.write(body)
            kind = board['kind']
            cutoff = ''
            period_key = 'current'
            if kind == 'fanqie':
                marker = 'window.__INITIAL_STATE__='
                head, state = body.split(marker, 1)
                # 官方内嵌状态偶尔包含 JS undefined；只替换字符串外的 token。
                state = re.sub(r'"(?:\\.|[^"\\])*"|\bundefined\b',
                               lambda m: 'null' if m[0] == 'undefined' else m[0], state)
                parsed_body = head + marker + state
                books = parse_fanqie_rank(parsed_body, url, board['category'])
                complete_font(books, body)
                payload = json.JSONDecoder().raw_decode(state)[0]
                counts = {str(x.get('bookId')): str(x.get('read_count') or '') for x in payload['rank']['book_list']}
                for book in books:
                    count = counts.get(book['id'].removeprefix('fanqie-'), '')
                    book['metric'] = ('在读 ' + count) if count else '未提供'
                m = re.search(r'统计时间截止至(.*?)</p>', body, re.S)
                cutoff = clean_html_text(m[1]) if m else ''
            elif kind == 'qimao':
                books = qimao(body)
                m = re.search(r'<span class="rule-txt"[^>]*>(.*?)</span></span>', body, re.S)
                cutoff = clean_html_text(m[1]) if m else ''
                if '昨日' in cutoff:
                    cutoff += '（' + (stamp - timedelta(days=1)).strftime('%Y-%m-%d') + '）'
                if board_id.endswith('month'):
                    # 以网页明确月份隔离官方月榜，避免跨月比较排名。
                    month = re.search(r'(\d+)月', cutoff)
                    if not month:
                        raise ValueError('月榜统计月份未识别，停止写入以免混合周期')
                    mnum = int(month[1]); year = stamp.year - (mnum > stamp.month)
                    period_key = f'{year}-{mnum:02d}'
                    cutoff += f'（统计月份：{period_key}）'
            elif kind == 'qidian':
                books = parse_qidian_rank(body, url)
                period_key = stamp.strftime('%Y-%m')
                cutoff = '本月累计：' + period_key + '；平台更新时间未提供'
                for book in books:
                    book['metric'] = book.get('popularityText', '')
            elif kind == 'shuqi':
                books = parse_shuqi_rank(body, url, board_id.split('-')[1] + board_id.split('-')[2])
            else:
                books = parse_qq_rank(body, url, 'sell')
            if not books or len({x['id'] for x in books}) != len(books):
                raise ValueError('没有可解析榜单或出现重复条目，保留历史快照')
            if any(not b.get('title') or any('\ue000' <= c <= '\uf8ff' for c in b['title'] + b.get('author', '')) for b in books):
                raise ValueError('书名或作者含无法解码字符，停止写入以免误认作品')
            for book in books:
                for key in ('popularityScore', 'popularityText'):
                    book.pop(key, None)
                book.setdefault('metric', '未提供官方数值')
            result = dict(board=board, source_url=url, captured_at=stamp.isoformat(),
                platform_cutoff=cutoff or '平台未提供可确认的统计截止时间',
                period_key=period_key, books=books, raw_file=str(path.relative_to(ROOT)),
                scope='仅当前入口公开列表；不代表全站完整书库', count=len(books))
            with connect() as db:
                db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?,?)',
                           (board_id, stamp.date().isoformat(), json.dumps(result, ensure_ascii=False)))
                db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)', (board_id, stamp.isoformat(), ''))
            return dict(ok=True, **result)
        except Exception as error:
            message = f'{type(error).__name__}: {error}'[:300]
            with connect() as db:
                db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)', (board_id, stamp.isoformat(), message))
            return dict(ok=False, error=message, board=board)

def view(board_id, days=0):
    if board_id not in BOARDS or days not in (0, 7, 30):
        raise ValueError('无效榜单或时间范围')
    with connect() as db:
        rows = db.execute('SELECT day,payload FROM snapshots WHERE board=? ORDER BY day DESC', (board_id,)).fetchall()
        attempt = db.execute('SELECT at,error FROM attempts WHERE board=?', (board_id,)).fetchone()
    last = dict(attempt) if attempt else None
    if not rows:
        return dict(ok=True, snapshot=None, attempt=last, books=[], covered_days=0, requested_days=days)
    latest = json.loads(rows[0]['payload'])
    result = dict(ok=True, snapshot={k:v for k,v in latest.items() if k != 'books'},
                  attempt=last, books=latest['books'], requested_days=days, covered_days=1)
    if not days:
        return result
    start = (now().date() - timedelta(days=days-1)).isoformat()
    samples = [json.loads(row['payload']) for row in reversed(rows) if start <= row['day'] <= now().date().isoformat()]
    samples = [s for s in samples if s['period_key'] == latest['period_key']]
    result.update(covered_days=len(samples), window_start=start, window_end=now().date().isoformat(),
                  coverage_dates=[s['captured_at'][:10] for s in samples])
    aggregate = {}
    for sample in samples:
        for b in sample['books']:
            item = aggregate.setdefault(b['id'], dict(book=b, ranks=[], dates=[]))
            item['book'] = b
            item['ranks'].append(b['rank']); item['dates'].append(sample['captured_at'][:10])
    books = []
    latest_ids = {b['id'] for b in samples[-1]['books']} if samples else set()
    for item in aggregate.values():
        ranks = item['ranks']
        books.append(dict(item['book'], observed_days=len(ranks), avg_rank=round(sum(ranks)/len(ranks),2),
            rank_change=ranks[0]-ranks[-1] if len(ranks)>1 else None,
            last_seen=item['dates'][-1], in_latest=item['book']['id'] in latest_ids))
    result['books'] = sorted(books, key=lambda x: (-x['observed_days'],x['avg_rank']))
    return result

def start_daily(fetch_html):
    """服务运行时每天16点后更新；启动补采空榜；失败至多每小时重试。"""
    def run():
        while True:
            for board in CATALOG:
                state = view(board['id'])
                stamp = now()
                scheduled = stamp.replace(hour=16, minute=0, second=0, microsecond=0)
                if stamp < scheduled:
                    scheduled -= timedelta(days=1)
                captured = state['snapshot']['captured_at'] if state['snapshot'] else ''
                attempt = state['attempt']
                recent_failure = attempt and attempt['error'] and (stamp-datetime.fromisoformat(attempt['at'])).total_seconds()<3600
                if (not captured or datetime.fromisoformat(captured)<scheduled) and not recent_failure:
                    result = collect(board['id'], fetch_html)
                    print('热榜快照', board['id'], '成功' if result['ok'] else result['error'], flush=True)
                    time.sleep(0.5)
            time.sleep(60)
    threading.Thread(target=run, name='hotlist-daily', daemon=True).start()
