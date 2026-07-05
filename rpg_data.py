import random

from storage import load_json, save_json, STUDENTS_DATA_PATH, DB_PATH

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

ENEMY_MAX_HP = 100
DAMAGE_PER_CORRECT_MULTIPLIER = 2
PLAYER_MAX_HP = 100
DAMAGE_ON_WRONG = 20

BOSS_ENEMY_MAX_HP = 250

DIFFICULTY_EXP = {"易しい": 15, "普通": 25, "難しい": 40}


def get_unit(unit_id):
    for unit in UNITS:
        if unit["id"] == unit_id:
            return unit
    return None


def _default_field_progress():
    return {unit["id"]: {"defeated": 0} for unit in UNITS}


def ensure_rpg_fields(student):
    """students_data内の1生徒分の辞書にRPG関連フィールドが無ければ追加する（破壊的更新）"""
    changed = False
    if "field_progress" not in student:
        student["field_progress"] = _default_field_progress()
        changed = True
    else:
        for unit in UNITS:
            if unit["id"] not in student["field_progress"]:
                student["field_progress"][unit["id"]] = {"defeated": 0}
                changed = True
    if "boss_defeated" not in student:
        student["boss_defeated"] = False
        changed = True
    if "title" not in student:
        student["title"] = None
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


def is_unit_unlocked(unit, field_progress):
    if unit["order"] == 1:
        return True
    prev_units = [u for u in UNITS if u["order"] == unit["order"] - 1]
    if not prev_units:
        return True
    prev_unit = prev_units[0]
    return field_progress.get(prev_unit["id"], {}).get("defeated", 0) > 0


def is_boss_unlocked(field_progress):
    return all(field_progress.get(unit["id"], {}).get("defeated", 0) > 0 for unit in UNITS)


def record_unit_win(student_id, unit_id):
    data = load_json(STUDENTS_DATA_PATH, {})
    student = data.get(student_id, {})
    student, _ = ensure_rpg_fields(student)
    student["field_progress"].setdefault(unit_id, {"defeated": 0})
    student["field_progress"][unit_id]["defeated"] += 1
    data[student_id] = student
    save_json(STUDENTS_DATA_PATH, data)
    return student


def record_boss_win(student_id):
    data = load_json(STUDENTS_DATA_PATH, {})
    student = data.get(student_id, {})
    student, _ = ensure_rpg_fields(student)
    student["boss_defeated"] = True
    student["title"] = FINAL_BOSS["title_reward"]
    data[student_id] = student
    save_json(STUDENTS_DATA_PATH, data)
    return student


def pick_battle_problem(topic):
    """db.json（既存の問題バンク）から、指定分野で正解が登録済みの問題をランダムに1問選ぶ"""
    db = load_json(DB_PATH, [])

    pool = []
    for item in db:
        item_topics = item.get("topic", [])
        if isinstance(item_topics, str):
            item_topics = [item_topics]
        if topic in item_topics and str(item.get("correct_answer", "")).strip():
            pool.append(item)

    if not pool:
        return None

    item = random.choice(pool)
    difficulty = item.get("difficulty", "普通")
    return {
        "image_file": item["image_file"],
        "correct_answer": item["correct_answer"],
        "difficulty": difficulty,
        "exp_value": DIFFICULTY_EXP.get(difficulty, 25),
    }
