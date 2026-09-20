import re
from urllib.parse import urlparse

# 主要小学校・塾のドメインおよびURLキーワードと名称のマップ
DOMAIN_SCHOOL_MAP = {
    "rikkyo.ac.jp": "立教小学校",
    "primary.rikkyo.ac.jp": "立教小学校",
    "aoyama.ac.jp": "青山学院初等部",
    "keio.ac.jp": "慶應義塾幼稚舎",
    "youchisha.keio.ac.jp": "慶應義塾幼稚舎",
    "yokohama.keio.ac.jp": "慶應義塾横浜初等部",
    "toho.ac.jp": "桐朋学園小学校",
    "toho-e.ed.jp": "桐朋小学校",
    "tamagawa.ac.jp": "玉川学園小学部",
    "tamagawa.ed.jp": "玉川学園小学部",
    "seikei.ac.jp": "成蹊小学校",
    "shirayuri-e.ed.jp": "白百合学園小学校",
    "shirayuri.ed.jp": "白百合学園",
    "futaba-ed.jp": "雙葉小学校",
    "tfutaba.ed.jp": "田園調布雙葉小学校",
    "sfutaba.ed.jp": "横浜雙葉小学校",
    "gakushuin.ac.jp": "学習院初等科",
    "waseda.jp": "早稲田実業学校初等部",
    "waseda.ed.jp": "早稲田実業学校初等部",
    "hosen.ed.jp": "宝仙学園小学校",
    "kokuritsu.ed.jp": "国立学園小学校",
    "toyoeiwa.ac.jp": "東洋英和女学院小学部",
    "rikkyoniyo.ed.jp": "立教女学院小学校",
    "seishin-e.ed.jp": "聖心女子学院初等科",
    "denenchofu-futaba.ed.jp": "田園調布雙葉小学校",
    "showa.ac.jp": "昭和女子大学附属昭和小学校",
    "showa-e.ed.jp": "昭和小学校",
    "tokyo-urban.ed.jp": "東京都市大学付属小学校",

    # 塾・幼児教室
    "rieikai.com": "理英会",
    "jack.ne.jp": "ジャック幼児教育研究所",
    "kogumakai.co.jp": "こぐま会",
    "shingakai.co.jp": "伸芽会",
    "singa.or.jp": "伸芽会",
    "pygma.jp": "ピグマリオン",
    "tamagawa-okujuken.com": "玉川幼児教室",
    "keio-youchisha.jp": "お受験専門教室"
}

# ソース名にこれらが含まれていれば学校名・塾名が判明しているとみなすキーワード
KNOWN_SCHOOL_KEYWORDS = [
    "青山", "立教", "慶應", "慶応", "桐朋", "玉川", "成蹊", "白百合", "雙葉", "学習院",
    "早稲田", "宝仙", "国立", "東洋英和", "聖心", "昭和", "都市大", "理英会", "ジャック",
    "こぐま", "伸芽会", "ピグマリオン", "小学校", "初等部", "初等科", "幼稚舎", "幼児教室",
    "塾", "研究所", "学園", "学院"
]

# ソース名として不十分な（学校名が欠落している可能性が高い）汎用キーワード
GENERIC_NAME_KEYWORDS = [
    "入学試験概要", "入学案内", "入試説明", "説明会", "お知らせ", "ニュース", "TOP", "トップページ",
    "イベント", "募集要項", "出願", "願書", "更新情報", "インフォメーション", "Exam", "News", "Notice"
]

def infer_school_name_from_url(url: str) -> str:
    """
    URLのドメインおよびパス情報から学校名・塾名を自動推論
    """
    if not url:
        return ""
    
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()
    full_str = f"{netloc}{path}"

    # 1. 完全一致/後方一致ドメイン検索
    for domain, school_name in DOMAIN_SCHOOL_MAP.items():
        if netloc == domain or netloc.endswith("." + domain):
            return school_name

    # 2. サブドメインやURL内のキーワード検索
    if "rikkyo" in full_str:
        return "立教小学校"
    if "aoyama" in full_str:
        return "青山学院初等部"
    if "keio" in full_str:
        return "慶應義塾"
    if "toho" in full_str:
        return "桐朋学園"
    if "tamagawa" in full_str:
        return "玉川学園"
    if "seikei" in full_str:
        return "成蹊小学校"
    if "shirayuri" in full_str:
        return "白百合学園"
    if "futaba" in full_str:
        return "雙葉小学校"
    if "gakushuin" in full_str:
        return "学習院初等科"
    if "waseda" in full_str:
        return "早稲田実業"
    if "rieikai" in full_str:
        return "理英会"
    if "jack" in full_str:
        return "ジャック幼児教育研究所"
    if "koguma" in full_str:
        return "こぐま会"
    if "shinga" in full_str:
        return "伸芽会"

    # ドメインの第1サブドメイン/ドメイン名をフォールバックとして整形
    parts = netloc.split(".")
    if len(parts) >= 2:
        main_name = parts[-2] if parts[-1] in ["jp", "com", "net", "org"] else parts[0]
        if main_name not in ["www", "primary", "entrance", "exam"]:
            return main_name.capitalize()

    return ""

def clean_and_enhance_source_name(source_name: str, target_url: str = "") -> str:
    """
    Source.name が『入学試験概要』などのように学校名が抜けている場合、
    URLから推論した学校名・塾名を補完して見やすい名称に整形します。
    """
    s_name = (source_name or "").strip()
    
    # 既に学校名・塾名キーワードが含まれているか判定
    has_known_school = any(kw in s_name for kw in KNOWN_SCHOOL_KEYWORDS)
    
    # 汎用的な名前か判定
    is_generic = any(kw in s_name for kw in GENERIC_NAME_KEYWORDS) or len(s_name) < 4

    if not has_known_school or is_generic:
        inferred = infer_school_name_from_url(target_url)
        if inferred:
            if not s_name:
                return inferred
            if inferred in s_name:
                return s_name
            return f"[{inferred}] {s_name}"
            
    return s_name if s_name else "学校・塾公式"

def extract_group_name(source_name: str, target_url: str = "") -> str:
    """ソース名から親の「学校・塾グループ名」を抽出 (例: '青山学院初等部 - お知らせ' -> '青山学院初等部')"""
    enhanced = clean_and_enhance_source_name(source_name, target_url)
    name = re.sub(r'\s*[\(\（].*?[\)\）]', '', enhanced)  # カッコ表記の除去
    if ' - ' in name:
        name = name.split(' - ')[0]
    return name.strip()

