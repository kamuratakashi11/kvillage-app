import random

from storage import load_json, save_json, STUDENTS_DATA_PATH, DB_PATH, BATTLE_STATE_PATH

# --- 「入試」ダンジョン専用の単元タクソノミー（既存の入試問題データのtopicタグと対応） ---
UNITS = [
    {"id": "suushiki", "name": "数と式", "topic": "数と式", "icon": "⚔️", "enemy_name": "計算スライム", "order": 1},
    {"id": "nijikansuu", "name": "二次関数", "topic": "二次関数", "icon": "🏹", "enemy_name": "放物線ゴブリン", "order": 2},
    {"id": "zukei_seishitsu", "name": "図形の性質", "topic": "図形の性質", "icon": "🛡️", "enemy_name": "図形オーガ", "order": 3},
    {"id": "baai_no_kazu", "name": "場合の数", "topic": "場合の数", "icon": "🎲", "enemy_name": "組合せウルフ", "order": 4},
    {"id": "kakuritsu", "name": "確率", "topic": "確率", "icon": "🎯", "enemy_name": "確率スピリット", "order": 5},
    {"id": "seisuu", "name": "整数", "topic": "整数", "icon": "🔢", "enemy_name": "整数ゴーレム", "order": 6},
    {"id": "zukei_houteishiki", "name": "図形と方程式", "topic": "図形と方程式", "icon": "📐", "enemy_name": "座標ドラゴン", "order": 7},
    {"id": "sankaku_kansuu", "name": "三角関数", "topic": "三角関数", "icon": "🌊", "enemy_name": "波動リザード", "order": 8},
    {"id": "shisuu_taisuu", "name": "指数・対数", "topic": "指数・対数", "icon": "📈", "enemy_name": "指数バット", "order": 9},
    {"id": "bekutoru", "name": "ベクトル", "topic": "ベクトル", "icon": "➡️", "enemy_name": "ベクトルナイト", "order": 10},
    {"id": "suuretsu", "name": "数列", "topic": "数列", "icon": "🔗", "enemy_name": "数列サーペント", "order": 11},
    {"id": "bibun_sekibun", "name": "微分・積分", "topic": "微分・積分", "icon": "📉", "enemy_name": "極限デーモン", "order": 12},
    {"id": "kyokugen", "name": "極限", "topic": "極限", "icon": "♾️", "enemy_name": "無限クラーケン", "order": 13},
    {"id": "fukusosuu_heimen", "name": "複素数平面", "topic": "複素数平面", "icon": "🌀", "enemy_name": "複素数フェアリー", "order": 14},
    {"id": "kyokuza_hyou", "name": "極座標", "topic": "極座標", "icon": "🧭", "enemy_name": "極座標スフィンクス", "order": 15},
    {"id": "suugaku3", "name": "数学Ⅲ", "topic": "数学Ⅲ", "icon": "🌌", "enemy_name": "無限大タイタン", "order": 16},
]

FINAL_BOSS = {"id": "boss", "name": "大魔王ネクロマティカ", "icon": "👑", "title_reward": "数学の勇者"}

# --- 「教科書」「問題集」「模試」ダンジョン共通の単元タクソノミー（pdf_ingestion.pyの分野・単元と対応） ---
NEW_TAXONOMY_UNITS = [
    {"id": "nt_suushiki", "name": "数と式", "topic": "数と式", "icon": "⚔️", "enemy_name": "計算スライム", "order": 1},
    {"id": "nt_shuugou_meidai", "name": "集合と命題", "topic": "集合と命題", "icon": "🧩", "enemy_name": "論理パズラー", "order": 2},
    {"id": "nt_2jikansuu", "name": "2次関数", "topic": "2次関数", "icon": "🏹", "enemy_name": "放物線ゴブリン", "order": 3},
    {"id": "nt_zukei_keiryou", "name": "図形と計量", "topic": "図形と計量", "icon": "📏", "enemy_name": "三角比レンジャー", "order": 4},
    {"id": "nt_data_bunseki", "name": "データの分析", "topic": "データの分析", "icon": "📊", "enemy_name": "統計スパイダー", "order": 5},
    {"id": "nt_baai_kakuritsu", "name": "場合の数と確率", "topic": "場合の数と確率", "icon": "🎲", "enemy_name": "組合せウルフ", "order": 6},
    {"id": "nt_seisuu_seishitsu", "name": "整数の性質", "topic": "整数の性質", "icon": "🔢", "enemy_name": "整数ゴーレム", "order": 7},
    {"id": "nt_zukei_seishitsu", "name": "図形の性質", "topic": "図形の性質", "icon": "🛡️", "enemy_name": "図形オーガ", "order": 8},
    {"id": "nt_shiki_shoumei", "name": "式と証明", "topic": "式と証明", "icon": "📜", "enemy_name": "恒等式スケルトン", "order": 9},
    {"id": "nt_fukusosuu_houteishiki", "name": "複素数と方程式", "topic": "複素数と方程式", "icon": "🔮", "enemy_name": "虚数フェアリー", "order": 10},
    {"id": "nt_zukei_houteishiki", "name": "図形と方程式", "topic": "図形と方程式", "icon": "📐", "enemy_name": "座標ドラゴン", "order": 11},
    {"id": "nt_sankaku_kansuu", "name": "三角関数", "topic": "三角関数", "icon": "🌊", "enemy_name": "波動リザード", "order": 12},
    {"id": "nt_shisuu_taisuu_kansuu", "name": "指数関数・対数関数", "topic": "指数関数・対数関数", "icon": "📈", "enemy_name": "指数バット", "order": 13},
    {"id": "nt_bibun_sekibun_kangae", "name": "微分・積分の考え", "topic": "微分・積分の考え", "icon": "📉", "enemy_name": "増減表ドラゴン", "order": 14},
    {"id": "nt_suuretsu", "name": "数列", "topic": "数列", "icon": "🔗", "enemy_name": "数列サーペント", "order": 15},
    {"id": "nt_toukei_suisoku", "name": "統計的な推測", "topic": "統計的な推測", "icon": "🎯", "enemy_name": "母集団スピリット", "order": 16},
    {"id": "nt_bekutoru", "name": "ベクトル", "topic": "ベクトル", "icon": "➡️", "enemy_name": "ベクトルナイト", "order": 17},
    {"id": "nt_heimen_kyokusen_fukusosuu", "name": "平面上の曲線と複素数平面", "topic": "平面上の曲線と複素数平面", "icon": "🌀", "enemy_name": "複素数フェアリー", "order": 18},
    {"id": "nt_kyokugen", "name": "極限", "topic": "極限", "icon": "♾️", "enemy_name": "無限クラーケン", "order": 19},
    {"id": "nt_bibunhou", "name": "微分法", "topic": "微分法", "icon": "🌌", "enemy_name": "接線タイタン", "order": 20},
    {"id": "nt_sekibunhou", "name": "積分法", "topic": "積分法", "icon": "🪐", "enemy_name": "回転体タイタン", "order": 21},
]

# --- 出題範囲（ダンジョン）の定義 ---
CATEGORIES = [
    {
        "id": "教科書", "name": "教科書の草原", "icon": "🌾",
        "units": NEW_TAXONOMY_UNITS,
        "final_boss": {"id": "boss", "name": "草原の守護者", "icon": "🌳", "title_reward": "基礎の達人"},
    },
    {
        "id": "問題集", "name": "問題集の海", "icon": "🌊",
        "units": NEW_TAXONOMY_UNITS,
        "final_boss": {"id": "boss", "name": "深海の主", "icon": "🐙", "title_reward": "演習の達人"},
    },
    {
        "id": "模試", "name": "模試の山", "icon": "⛰️",
        "units": NEW_TAXONOMY_UNITS,
        "final_boss": {"id": "boss", "name": "山嶺の巨神", "icon": "🗻", "title_reward": "模試の覇者"},
    },
    {
        "id": "入試", "name": "入試の塔", "icon": "🗼",
        "units": UNITS,
        "final_boss": FINAL_BOSS,
    },
]
CATEGORY_MAP = {cat["id"]: cat for cat in CATEGORIES}
DEFAULT_CATEGORY = "入試"  # カテゴリ未設定の既存問題データは「入試」として扱う

ENEMY_MAX_HP = 100
DAMAGE_PER_CORRECT_MULTIPLIER = 2
PLAYER_MAX_HP = 100
DAMAGE_ON_WRONG = 20

BOSS_ENEMY_MAX_HP = 250

DIFFICULTY_EXP = {"易しい": 15, "普通": 25, "難しい": 40}


def get_category(category_id):
    return CATEGORY_MAP.get(category_id)


def get_unit(category_id, unit_id):
    cat = get_category(category_id)
    if not cat:
        return None
    for unit in cat["units"]:
        if unit["id"] == unit_id:
            return unit
    return None


def _default_dungeon_progress(category_id):
    cat = CATEGORY_MAP[category_id]
    return {
        "field_progress": {unit["id"]: {"defeated": 0} for unit in cat["units"]},
        "boss_defeated": False,
        "title": None,
    }


def _default_all_dungeon_progress():
    return {cat["id"]: _default_dungeon_progress(cat["id"]) for cat in CATEGORIES}


def ensure_rpg_fields(student):
    """students_data内の1生徒分の辞書にRPG関連フィールド（ダンジョンごとの進捗）が無ければ追加する（破壊的更新）。
    カテゴリ分け前の旧形式データ（field_progress/boss_defeated/titleが生徒直下にあるもの）は
    「入試の塔」の進捗としてそのまま引き継ぐ。"""
    changed = False

    if "dungeon_progress" not in student:
        student["dungeon_progress"] = _default_all_dungeon_progress()
        if "field_progress" in student:
            old_field_progress = student.pop("field_progress")
            entrance_progress = student["dungeon_progress"][DEFAULT_CATEGORY]["field_progress"]
            for unit_id, prog in old_field_progress.items():
                if unit_id in entrance_progress:
                    entrance_progress[unit_id] = prog
            student["dungeon_progress"][DEFAULT_CATEGORY]["boss_defeated"] = student.pop("boss_defeated", False)
            student["dungeon_progress"][DEFAULT_CATEGORY]["title"] = student.pop("title", None)
        changed = True
    else:
        for cat in CATEGORIES:
            cid = cat["id"]
            if cid not in student["dungeon_progress"]:
                student["dungeon_progress"][cid] = _default_dungeon_progress(cid)
                changed = True
                continue
            dp = student["dungeon_progress"][cid]
            if "field_progress" not in dp:
                dp["field_progress"] = {unit["id"]: {"defeated": 0} for unit in cat["units"]}
                changed = True
            else:
                for unit in cat["units"]:
                    if unit["id"] not in dp["field_progress"]:
                        dp["field_progress"][unit["id"]] = {"defeated": 0}
                        changed = True
            if "boss_defeated" not in dp:
                dp["boss_defeated"] = False
                changed = True
            if "title" not in dp:
                dp["title"] = None
                changed = True

    return student, changed


def load_student_with_rpg_fields(student_id):
    data = load_json(STUDENTS_DATA_PATH, {})
    student = data.get(student_id, {})
    student, changed = ensure_rpg_fields(student)
    if changed:
        data[student_id] = student
        save_json(STUDENTS_DATA_PATH, data)
    return student


def get_earned_titles(student):
    """全ダンジョンで獲得済みの称号一覧を返す（生徒サイドバー表示用）"""
    dungeon_progress = student.get("dungeon_progress", {})
    return [dp["title"] for dp in dungeon_progress.values() if dp.get("title")]


def is_unit_unlocked(category_id, unit, field_progress):
    if unit["order"] == 1:
        return True
    cat = CATEGORY_MAP[category_id]
    prev_units = [u for u in cat["units"] if u["order"] == unit["order"] - 1]
    if not prev_units:
        return True
    prev_unit = prev_units[0]
    return field_progress.get(prev_unit["id"], {}).get("defeated", 0) > 0


def is_boss_unlocked(category_id, field_progress):
    cat = CATEGORY_MAP[category_id]
    return all(field_progress.get(unit["id"], {}).get("defeated", 0) > 0 for unit in cat["units"])


def record_unit_win(student_id, category_id, unit_id):
    data = load_json(STUDENTS_DATA_PATH, {})
    student = data.get(student_id, {})
    student, _ = ensure_rpg_fields(student)
    dp = student["dungeon_progress"][category_id]
    dp["field_progress"].setdefault(unit_id, {"defeated": 0})
    dp["field_progress"][unit_id]["defeated"] += 1
    data[student_id] = student
    save_json(STUDENTS_DATA_PATH, data)
    return student


def record_boss_win(student_id, category_id):
    data = load_json(STUDENTS_DATA_PATH, {})
    student = data.get(student_id, {})
    student, _ = ensure_rpg_fields(student)
    dp = student["dungeon_progress"][category_id]
    dp["boss_defeated"] = True
    dp["title"] = CATEGORY_MAP[category_id]["final_boss"]["title_reward"]
    data[student_id] = student
    save_json(STUDENTS_DATA_PATH, data)
    return student


def _battle_ready_pool(category_id, topic):
    """db.json（既存の問題バンク）から、指定ダンジョン・指定分野で正解が登録済みの問題一覧を返す"""
    db = load_json(DB_PATH, [])
    pool = []
    for item in db:
        if item.get("category", DEFAULT_CATEGORY) != category_id:
            continue
        item_topics = item.get("topic", [])
        if isinstance(item_topics, str):
            item_topics = [item_topics]
        if topic in item_topics and str(item.get("correct_answer", "")).strip():
            pool.append(item)
    return pool


def count_available_battle_problems(category_id, topic):
    """指定ダンジョン・指定分野でバトルに出題可能な（正解登録済みの）問題数を返す"""
    return len(_battle_ready_pool(category_id, topic))


def _to_battle_problem(item):
    difficulty = item.get("difficulty", "普通")
    return {
        "image_file": item["image_file"],
        "correct_answer": item["correct_answer"],
        "answer_type": item.get("answer_type", "value"),
        "difficulty": difficulty,
        "exp_value": DIFFICULTY_EXP.get(difficulty, 25),
    }


def pick_battle_problems(category_id, topic, count):
    """指定ダンジョン・指定分野で正解が登録済みの問題を、重複無しで最大count問ランダムに選ぶ"""
    pool = _battle_ready_pool(category_id, topic)
    if not pool:
        return []
    count = min(count, len(pool))
    return [_to_battle_problem(item) for item in random.sample(pool, count)]


def load_battle_state(student_id, battle_key):
    """ブラウザを閉じても再開できるよう、進行中のバトル（出題内容・HP・採点結果）を取得する"""
    data = load_json(BATTLE_STATE_PATH, {})
    return data.get(student_id, {}).get(battle_key)


def save_battle_state(student_id, battle_key, state):
    data = load_json(BATTLE_STATE_PATH, {})
    data.setdefault(student_id, {})[battle_key] = state
    save_json(BATTLE_STATE_PATH, data)


def clear_battle_state(student_id, battle_key):
    data = load_json(BATTLE_STATE_PATH, {})
    if student_id in data and battle_key in data[student_id]:
        del data[student_id][battle_key]
        save_json(BATTLE_STATE_PATH, data)
