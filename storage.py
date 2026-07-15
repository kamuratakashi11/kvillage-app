import os
import json
import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from google.cloud.firestore_v1.field_path import FieldPath

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db.json")
IMG_DIR = os.path.join(BASE_DIR, "pdf_images")
USERS_PATH = os.path.join(BASE_DIR, "users.json")
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")
STUDENTS_DATA_PATH = os.path.join(BASE_DIR, "students_data.json")
ANSWER_CACHE_PATH = os.path.join(BASE_DIR, "answer_cache.json")
BATTLE_STATE_PATH = os.path.join(BASE_DIR, "battle_state.json")
SESSIONS_PATH = os.path.join(BASE_DIR, "sessions.json")
BG_IMG_PATH = os.path.join(BASE_DIR, "bg.png")


def init_firestore():
    try:
        if not firebase_admin._apps:
            if "FIREBASE_KEY" not in st.secrets:
                return None, "Secretsに [FIREBASE_KEY] が見つかりません。TOMLの形式を確認してください。"

            cert_dict = dict(st.secrets["FIREBASE_KEY"])
            if "private_key" not in cert_dict:
                return None, "FIREBASE_KEY の中に private_key が見つかりません。"

            # JSONからTOMLへの変換時の改行文字を元に戻す
            if "\\n" in cert_dict["private_key"]:
                cert_dict["private_key"] = cert_dict["private_key"].replace("\\n", "\n")

            cred = credentials.Certificate(cert_dict)
            firebase_admin.initialize_app(cred)
        return firestore.client(), None
    except Exception as e:
        return None, f"Firestore初期化エラー: {e}"


db_client, db_error = init_firestore()


def _load_db_fallback(default_val):
    """Firestoreにdb.jsonがまだ保存されていない場合、リポジトリ同梱のファイルを初期データとして使う"""
    if not os.path.exists(DB_PATH):
        return default_val
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json(path, default_val):
    # db.jsonもFirestoreで永続化する（Reboot・再デプロイのたびに進捗が消えるのを防ぐため）
    if db_client is None:
        if path == DB_PATH:
            return _load_db_fallback(default_val)
        return default_val

    doc_name = os.path.basename(path).replace(".json", "")
    try:
        doc_ref = db_client.collection("kvillage_data").document(doc_name)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("data", default_val)
        elif path == DB_PATH:
            return _load_db_fallback(default_val)
        else:
            return default_val
    except Exception as e:
        st.error(f"🚨 **DB読み込みエラー ({doc_name})**: {e}")
        return default_val


def save_json(path, data):
    if db_client is None:
        st.session_state["_pending_storage_error"] = f"🚨 **DB保存エラー**: Firestoreが初期化されていません（{db_error}）"
        return

    doc_name = os.path.basename(path).replace(".json", "")
    try:
        doc_ref = db_client.collection("kvillage_data").document(doc_name)
        doc_ref.set({"data": data})
    except Exception as e:
        message = f"🚨 **DB保存エラー ({doc_name})**: {e}"
        # st.rerun()が直後に呼ばれる呼び出し元だとst.error()の表示が一瞬で消えてしまうため、
        # 次の再描画でも表示できるようセッションに保持しておく
        st.session_state["_pending_storage_error"] = message
        st.error(message)


def update_student_field(path, student_id, *sub_keys, value):
    """load_json→（生徒ごとのキーだけ書き換え）→save_jsonという流れだと、
    全生徒共有の1ドキュメントを丸ごと読み書きするため、他の生徒が同時に保存すると
    お互いの更新を古い内容で上書きしてしまう（例: バトル中に倒したはずの敵のHPが巻き戻る）。
    Firestoreのネストフィールド指定updateを使い、この生徒のこのフィールドだけを
    サーバー側でアトミックに更新することで、この競合を避ける。"""
    if db_client is None:
        st.session_state["_pending_storage_error"] = f"🚨 **DB保存エラー**: Firestoreが初期化されていません（{db_error}）"
        return

    doc_name = os.path.basename(path).replace(".json", "")
    doc_ref = db_client.collection("kvillage_data").document(doc_name)
    field_path = FieldPath("data", student_id, *sub_keys)
    try:
        doc_ref.update({field_path: value})
    except Exception:
        # ドキュメント自体がまだ存在しない場合はここで作成してから再試行する
        try:
            doc_ref.set({}, merge=True)
            doc_ref.update({field_path: value})
        except Exception as e:
            message = f"🚨 **DB保存エラー ({doc_name})**: {e}"
            st.session_state["_pending_storage_error"] = message
            st.error(message)


def delete_student_field(path, student_id, *sub_keys):
    """update_student_fieldの削除版。指定フィールドが元々無い場合は何もしない。"""
    if db_client is None:
        return

    doc_name = os.path.basename(path).replace(".json", "")
    doc_ref = db_client.collection("kvillage_data").document(doc_name)
    field_path = FieldPath("data", student_id, *sub_keys)
    try:
        doc_ref.update({field_path: firestore.DELETE_FIELD})
    except Exception:
        pass
