from datetime import datetime
from storage import (
    load_json, save_json, update_student_field, increment_student_field,
    consume_student_resource, STUDENTS_DATA_PATH, USERS_PATH,
)


def init_student_data(student_id, name):
    data = load_json(STUDENTS_DATA_PATH, {})
    if student_id not in data:
        data[student_id] = {
            "name": name,
            "tickets": 3,
            "exp": 0,
            "level": 1,
            "login_streak": 1,
            "last_login_date": datetime.now().strftime("%Y-%m-%d")
        }
        save_json(STUDENTS_DATA_PATH, data)
    return data[student_id]


def process_daily_login(student_id):
    import streamlit as st

    if student_id == "master":
        return
    data = load_json(STUDENTS_DATA_PATH, {})
    if student_id not in data:
        # 古いアカウントなどでデータがない場合は初期化してボーナスを付与する
        users = load_json(USERS_PATH, {})
        name = users.get(student_id, "名無し")
        data[student_id] = {
            "name": name,
            "tickets": 3,
            "exp": 0,
            "level": 1,
            "login_streak": 1,
            "last_login_date": datetime.now().strftime("%Y-%m-%d")
        }
        save_json(STUDENTS_DATA_PATH, data)
        st.toast(f"🎉 ログインボーナス！チケットを3枚獲得しました！ (現在: 3枚)", icon="🎟️")
        return

    student = data[student_id]
    today = datetime.now().strftime("%Y-%m-%d")
    last_login = student.get("last_login_date", "")

    if today != last_login:
        student["tickets"] = min(10, student.get("tickets", 0) + 3)
        try:
            last_date = datetime.strptime(last_login, "%Y-%m-%d")
            curr_date = datetime.strptime(today, "%Y-%m-%d")
            if (curr_date - last_date).days == 1:
                student["login_streak"] = student.get("login_streak", 0) + 1
            else:
                student["login_streak"] = 1
        except Exception:
            student["login_streak"] = 1

        student["last_login_date"] = today
        data[student_id] = student
        save_json(STUDENTS_DATA_PATH, data)
        st.toast(f"🎉 ログインボーナス！チケットを3枚獲得しました！ (現在: {student['tickets']}枚)", icon="🎟️")


def get_level_info(total_exp):
    """累計EXPから、現在のレベル、そのレベル内での獲得EXP、次のレベルへの必要EXPを計算する"""
    level = 1
    required_exp_for_next = 50
    current_tier_exp = total_exp

    while current_tier_exp >= required_exp_for_next:
        current_tier_exp -= required_exp_for_next
        level += 1
        required_exp_for_next += 50

    return level, current_tier_exp, required_exp_for_next


def update_student_exp(student_id, exp_gain):
    if student_id == "master":
        return False
    data = load_json(STUDENTS_DATA_PATH, {})
    if student_id not in data:
        return False

    old_level, _, _ = get_level_info(data[student_id].get("exp", 0))

    # expはFirestoreのアトミックIncrementで加算する。load→加算→save_jsonの
    # 丸ごと書き戻し方式だと、他の生徒の保存とほぼ同時に行われた際に
    # 加算分がまるごと消えてしまうことがあるため。
    increment_student_field(STUDENTS_DATA_PATH, student_id, "exp", exp_gain)

    fallback_exp = data[student_id].get("exp", 0) + exp_gain
    refreshed_exp = load_json(STUDENTS_DATA_PATH, {}).get(student_id, {}).get("exp", fallback_exp)
    new_level, _, _ = get_level_info(refreshed_exp)
    leveled_up = new_level > old_level

    if leveled_up:
        update_student_field(STUDENTS_DATA_PATH, student_id, "level", value=new_level)

    return leveled_up


def consume_tickets(student_id, amount):
    if student_id == "master":
        return True
    # 「残高確認→減算→保存」を1つのFirestoreトランザクションにまとめることで、
    # ほぼ同時に来た複数のチケット消費リクエストが両方とも「足りている」と
    # 誤判定して二重に消費してしまう競合を避ける。
    return consume_student_resource(STUDENTS_DATA_PATH, student_id, "tickets", amount)
