"""运行配置、平台映射和推荐约束常量。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """读取有界整数；空值或错误配置回退默认值，避免服务无法启动。"""
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """读取有界浮点数；部署环境中的空字符串不会造成启动崩溃。"""
    try:
        value = float(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = Path(os.environ.get("MISHU_DATA_DIR", str(BASE_DIR / "runtime-data")))
DB_FILE = DATA_DIR / "mishu.db"
PORT = env_int("PORT", 8080, 1, 65535)
AI_API_URL = os.environ.get("AI_API_URL", "").strip()
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
AI_API_MODEL = os.environ.get("AI_API_MODEL", "").strip()
AI_TIMEOUT = env_float("AI_TIMEOUT", 25.0, 5.0, 60.0)
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "direct").strip().lower()
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
SEARCH_COUNTRY = os.environ.get("SEARCH_COUNTRY", "CN").strip().upper() or "CN"
SEARCH_LANG = os.environ.get("SEARCH_LANG", "zh-hans").strip() or "zh-hans"
SEARCH_TIMEOUT = env_float("SEARCH_TIMEOUT", 10.0, 3.0, 20.0)
MISHU_ACCESS_CODE = os.environ.get("MISHU_ACCESS_CODE", "").strip()
MISHU_SESSION_SECRET = os.environ.get("MISHU_SESSION_SECRET", "").strip() or hashlib.sha256(
    (MISHU_ACCESS_CODE + "|mishu-single-user-session").encode()
).hexdigest()
MISHU_SESSION_DAYS = env_int("MISHU_SESSION_DAYS", 30, 1, 180)
MISHU_SYNC_DAYS = env_int("MISHU_SYNC_DAYS", 180, 7, 365)
AI_CACHE_RETENTION_HOURS = 24
AI_CACHE_LIMIT = 500
RANK_SNAPSHOT_RETENTION_DAYS = 90
QIMAO_GENRES = {
    "玄幻": ("202",),
    "都市": ("203",),
    "仙侠": ("205",),
    "科幻": ("64",),
    "悬疑灵异": ("204",),
    "历史": ("56",),
    "游戏": ("75", "200"),
    "言情": ("1", "2", "4"),
    "N次元": ("207",),
    "现实": ("306", "307"),
}
QIMAO_FEMALE_CATEGORIES = {"1", "2", "4"}
QIMAO_MALE_DEFAULT_CATEGORIES = ("202", "203", "205", "64", "204", "56", "75", "200", "207")
QIMAO_WORD_BUCKETS = {"any": "a", "under30": "1", "30to50": "2", "50to100": "3", "100to200": "4", "over200": "5"}
QIMAO_STATUSES = {"all": "a", "completed": "1", "ongoing": "0"}

DISCOVERY_PLATFORMS = ("起点", "番茄", "书旗", "七猫", "QQ阅读")
PRIMARY_DISCOVERY_PLATFORMS = {"起点", "番茄"}
SOURCE_SCORE_BIAS = {"起点": 5.0, "番茄": 5.0, "书旗": 0.0, "QQ阅读": -1.0, "七猫": -7.0}
QIMAO_SUPPLEMENT_SHARE = 0.15
SYNC_ACTIONS = {"want", "liked", "read", "dislike", "clear", "dislike_reason", "detail", "copy", "source", "dwell"}
FANQIE_FONT_MAP_FILE = BASE_DIR / "data" / "fanqie_font_map.json"


def load_fanqie_font_map() -> tuple[str, dict[str, str]]:
    try:
        payload = json.loads(FANQIE_FONT_MAP_FILE.read_text(encoding="utf-8"))
        font_hash = str(payload.get("font_hash") or "").strip()
        raw_map = payload.get("map") if isinstance(payload, dict) else {}
        if not font_hash or not isinstance(raw_map, dict):
            return "", {}
        mapping = {
            chr(int(codepoint, 16)): str(character)
            for codepoint, character in raw_map.items()
            if isinstance(codepoint, str) and isinstance(character, str) and len(character) == 1
        }
        return font_hash, mapping
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return "", {}


FANQIE_RANK_FONT_HASH, FANQIE_RANK_FONT_MAP = load_fanqie_font_map()
QIDIAN_GENRES = {
    "玄幻": "21", "仙侠": "22", "都市": "4", "现实": "15", "历史": "5",
    "游戏": "7", "科幻": "9", "悬疑灵异": "10", "N次元": "12",
}
QIDIAN_WORD_BUCKETS = {"any": "", "under30": "1", "30to50": "2", "50to100": "3", "100to200": "4", "over200": "5"}
QIDIAN_STATUSES = {"all": "", "completed": "1", "ongoing": "2"}
FANQIE_GENRES = {
    "玄幻": (("1", "258", "传统玄幻"), ("1", "257", "玄幻脑洞"), ("1", "1141", "西方奇幻"), ("0", "248", "玄幻言情")),
    "都市": (("1", "261", "都市日常"), ("1", "124", "都市修真"), ("1", "1014", "都市高武"), ("1", "263", "都市种田"), ("1", "262", "都市脑洞"), ("0", "267", "现言脑洞"), ("0", "750", "职场婚恋"), ("0", "748", "豪门总裁")),
    "仙侠": (("1", "1140", "东方仙侠"), ("1", "124", "都市修真"), ("0", "248", "玄幻言情")),
    "科幻": (("1", "8", "科幻末世"), ("0", "8", "科幻末世")),
    "悬疑灵异": (("1", "539", "悬疑脑洞"), ("1", "751", "悬疑灵异"), ("0", "539", "悬疑脑洞"), ("0", "747", "女频悬疑")),
    "历史": (("1", "273", "历史古代"), ("1", "272", "历史脑洞"), ("1", "504", "抗战谍战"), ("0", "1139", "古风世情"), ("0", "1017", "民国言情")),
    "游戏": (("1", "746", "游戏体育"), ("0", "746", "游戏体育")),
    "言情": (("0", "1139", "古风世情"), ("0", "246", "宫斗宅斗"), ("0", "253", "古言脑洞"), ("0", "24", "快穿"), ("0", "749", "青春甜宠"), ("0", "745", "星光璀璨"), ("0", "750", "职场婚恋"), ("0", "748", "豪门总裁"), ("0", "1017", "民国言情")),
    "N次元": (("1", "718", "动漫衍生"), ("1", "1016", "男频衍生"), ("0", "1015", "女频衍生")),
    "现实": (("1", "261", "都市日常"), ("1", "263", "都市种田"), ("0", "23", "种田"), ("0", "79", "年代"), ("0", "750", "职场婚恋")),
}
FANQIE_WORD_BUCKETS = {"any": "-1", "under30": "0", "30to50": "1", "50to100": "2", "100to200": "3", "over200": "4"}
FANQIE_STATUSES = {"all": "-1", "completed": "0", "ongoing": "1"}
SHUQI_RANKS = {
    "allClick": "点击榜", "allStore": "收藏榜", "allOrder": "订阅榜", "allEnd": "完结榜", "allWords": "字数榜",
    "boyClick": "男频点击榜", "boyStore": "男频收藏榜", "boyOrder": "男频订阅榜", "boyhot": "男频人气榜", "boyEnd": "男频完结榜", "boyUpdate": "男频更新榜",
    "girlClick": "女频点击榜", "girlStore": "女频收藏榜", "girlOrder": "女频订阅榜", "girlhot": "女频人气榜", "girlEnd": "女频完结榜", "girlUpdate": "女频更新榜",
}
SHUQI_STORE_GENRES = {
    # 书旗官方书库的 fc 参数；一个大类可覆盖多个站内分类。
    "玄幻": ("29", "94", "122"),
    "都市": ("7", "15", "76"),
    "仙侠": ("67,98", "58"),
    "科幻": ("34,102",),
    "悬疑灵异": ("41,108",),
    "历史": ("45",),
    "游戏": ("63",),
    "言情": ("76", "86", "94", "122", "127"),
    "N次元": ("71",),
    "现实": ("15",),
}
SHUQI_STORE_WORDS = {
    "any": "10", "under30": "11", "30to50": "12", "50to100": "13",
    "100to200": "14", "over200": "15",
}
SHUQI_STORE_STATUSES = {"all": "0", "ongoing": "1", "completed": "2"}
QQ_RANKS = {"sell": "热门榜", "new": "新书榜", "free": "免费榜", "finish": "完结榜", "god": "封神榜"}
QQ_CATEGORIES = {
    "玄幻": ("20001", "20005"), "仙侠": ("20014", "20010"), "都市": ("20019",),
    "现实": ("20065",), "历史": ("20028", "20032"), "游戏": ("20050",),
    "科幻": ("20042",), "悬疑灵异": ("20037",), "N次元": ("20059", "20109"),
    "言情": ("0",),
}
QQ_WORD_BUCKETS = {
    "any": ("0",), "under30": ("1", "2"), "30to50": ("2",), "50to100": ("3",),
    "100to200": ("4",), "over200": ("5",),
}
QQ_STATUSES = {"all": "0", "ongoing": "1", "completed": "2"}
WORD_LIMITS = {
    "under30": (0, 30), "30to50": (30, 50), "50to100": (50, 100),
    "100to200": (100, 200), "over200": (200, float("inf")),
}
GENRE_ALIASES = {
    "玄幻": ("玄幻", "奇幻", "高武", "东方", "异世"),
    "都市": ("都市", "生活", "职场", "商战", "娱乐圈", "文娱", "华娱", "星光璀璨"),
    "仙侠": ("仙侠", "修真", "武侠", "古武"),
    "科幻": ("科幻", "星际", "末世", "未来"),
    "悬疑灵异": ("悬疑", "灵异", "推理", "恐怖", "奇门"),
    "历史": ("历史", "古代", "秦汉", "两宋", "明清", "军事"),
    "游戏": ("游戏", "网游", "电竞"),
    "言情": ("言情", "甜宠", "婚恋", "总裁", "宫斗", "宅斗", "种田", "星光璀璨"),
    "N次元": ("轻小说", "同人", "诸天", "无限", "二次元"),
    "现实": ("现实", "社会", "生活"),
}

# 内容标签只在“分类或简介”有依据时才能通过严格筛选；书名命中只作为弱提示。
CONTENT_TAG_RULES = {
    "重生": ("重生", "重回", "回到过去", "回到\u4e86"),
    "穿越": ("穿越", "穿到", "魂穿", "穿成"),
    "系统": ("系统", "金手指", "签到", "任务面板"),
    "娱乐圈": ("娱乐圈", "星光璀璨", "演员", "艺人", "明星", "综艺", "经纪人", "剧组", "直播带货"),
    "明星": ("明星", "演员", "歌手", "偶像", "艺人", "娱乐圈", "星光璀璨", "综艺", "影帝", "顶流", "文娱", "华娱", "韩娱", "剧组"),
    "神豪": ("神豪", "消费返利", "百亿", "财富自由", "败家"),
    "商战": ("商战", "商业", "公司", "创业", "投资", "总裁"),
    "校园": ("校园", "高中", "大学", "同桌", "学生"),
    "医术": ("医生", "医院", "医术", "中医", "诊所"),
    "直播": ("直播", "主播", "直播间", "带货"),
    "都市异能": ("异能", "超能力", "灵气复苏", "都市高武"),
    "高武": ("高武", "武道", "武者", "气血", "武馆"),
    "东方玄幻": ("东方玄幻", "玄幻", "修炼", "灵脉", "境界"),
    "御兽": ("御兽", "灵兽", "宠兽", "契约兽"),
    "无敌流": ("无敌", "横推", "碾压", "举世无敌"),
    "宗门": ("宗门", "门派", "掌门", "圣地"),
    "诸天": ("诸天", "万界", "位面", "世界穿梭"),
    "凡人流": ("凡人流", "散修", "资质平庸", "苟道"),
    "剑修": ("剑修", "剑道", "飞剑", "剑仙"),
    "末世": ("末世", "丧尸", "灾变", "废土", "求生"),
    "星际": ("星际", "宇宙", "星舰", "外星", "星球"),
    "机甲": ("机甲", "驾驶舱", "高达", "战甲"),
    "推理破案": ("推理", "破案", "刑侦", "案件", "侦探"),
    "诡异复苏": ("诡异复苏", "诡异", "怪谈", "诡境", "规则"),
    "盗墓": ("盗墓", "古墓", "墓穴", "考古"),
    "无限流": ("无限流", "副本", "轮回", "主神空间"),
    "历史穿越": ("历史穿越", "穿越", "古代", "王朝", "朝堂"),
    "三国": ("三国", "曹操", "刘备", "东汉"),
    "种田经营": ("种田", "经营", "领地", "建设", "农场"),
    "战争争霸": ("战争", "争霸", "行军", "军队", "战场"),
    "电竞": ("电竞", "职业联赛", "战队", "比赛"),
    "网游": ("网游", "游戏", "服务器", "玩家"),
    "模拟器": ("模拟器", "模拟人生", "人生模拟"),
    "豪门": ("豪门", "总裁", "继承人", "财阀"),
    "甜宠": ("甜宠", "甜文", "撒糖", "恋爱"),
    "先婚后爱": ("先婚后爱", "闪婚", "契约婚姻", "结婚后"),
    "综漫": ("综漫", "动漫", "火影", "海贼", "原神"),
    "同人": ("同人", "衍生", "原著"),
    "职场": ("职场", "上班", "公司", "职业"),
    "年代": ("年代", "八零", "九零", "七零", "知青"),
}
CONTENT_TAG_GROUPS = {
    "都市": ("重生", "娱乐圈", "明星", "神豪", "商战", "校园", "医术", "直播", "都市异能", "系统"),
    "玄幻": ("高武", "东方玄幻", "御兽", "无敌流", "宗门", "诸天", "系统", "重生"),
    "仙侠": ("凡人流", "剑修", "宗门", "无敌流", "诸天", "系统", "重生"),
    "科幻": ("末世", "星际", "机甲", "系统", "重生"),
    "悬疑灵异": ("推理破案", "诡异复苏", "盗墓", "无限流", "系统"),
    "历史": ("历史穿越", "三国", "种田经营", "战争争霸", "重生"),
    "游戏": ("电竞", "网游", "模拟器", "系统"),
    "言情": ("重生", "娱乐圈", "明星", "豪门", "甜宠", "先婚后爱", "校园"),
    "N次元": ("综漫", "同人", "无限流", "系统"),
    "现实": ("职场", "年代", "种田经营", "创业"),
}
TAG_NEGATIONS = {
    "系统": ("无系统", "没有系统", "拒绝系统", "系统不存在"),
}
SUBTAG_FANQIE_CATEGORIES = {
    "娱乐圈": (("0", "745", "星光璀璨"),),
    "明星": (("0", "745", "星光璀璨"),),
    "重生": (("1", "262", "都市脑洞"), ("0", "253", "古言脑洞"), ("0", "267", "现言脑洞")),
    "系统": (("1", "257", "玄幻脑洞"), ("1", "262", "都市脑洞"), ("0", "267", "现言脑洞")),
    "神豪": (("1", "262", "都市脑洞"),),
    "校园": (("0", "749", "青春甜宠"),),
    "豪门": (("0", "748", "豪门总裁"),),
    "职场": (("0", "750", "职场婚恋"),),
    "末世": (("1", "8", "科幻末世"), ("0", "8", "科幻末世")),
    "电竞": (("1", "746", "游戏体育"),),
}

# 用户选择的是阅读意图，不要求平台必须使用完全相同的标签名。
# 仍然只接受分类或简介中的高置信依据，书名命中不会因此升级为严格匹配。
SUBTAG_EQUIVALENTS = {
    "明星": {"明星", "娱乐圈"},
    "娱乐圈": {"娱乐圈", "明星"},
    "直播": {"直播", "娱乐圈"},
    "高武": {"高武", "都市异能"},
    "都市异能": {"都市异能", "高武"},
    "电竞": {"电竞", "网游"},
}


PLATFORM_SEARCH = {
    "起点": {
        "domain": "qidian.com",
        "url": "https://www.qidian.com/so/{query}/",
    },
    "番茄": {
        "domain": "fanqienovel.com",
        "url": "https://fanqienovel.com/search/{query}",
    },
    "七猫": {
        "domain": "qimao.com",
        "url": "https://www.qimao.com/search/index/?kw={query}",
    },
    "纵横": {
        "domain": "zongheng.com",
        "url": "https://search.zongheng.com/s?keyword={query}",
    },
    "书旗": {
        "domain": "shuqi.com",
        "url": "https://shuqi.com/search?keyword={query}",
    },
    "QQ阅读": {
        "domain": "book.qq.com",
        "url": "https://book.qq.com/search.html?key={query}",
    },
}
PLATFORM_ORDER = tuple(PLATFORM_SEARCH)
