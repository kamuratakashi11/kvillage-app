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


def increment_student_field(path, student_id, field_name, delta):
    """指定フィールド（数値）にdeltaを加算する。Firestoreのアトミックな
    Incrementを使うため、複数の保存がほぼ同時に行われても加算分が
    互いに上書きされて消えることがない（例: EXP加算の取りこぼし防止）。"""
    update_student_field(path, student_id, field_name, value=firestore.Increment(delta))


def consume_student_resource(path, student_id, field_name, amount):
    """指定フィールド（チケットのような残高数値）がamount以上あれば、
    Firestoreのトランザクションで「残高チェック」と「アトミックな減算」を
    1つの不可分な操作として行う。read-modify-write（読み込み→減算→
    書き戻し）だと、ほぼ同時に来た複数のリクエストがどちらも「まだ残高が
    足りる」という古い状態を見て両方通ってしまい、合計の消費量が実際の
    残高を超えてしまうことがある。
    戻り値: 消費できればTrue、残高不足（またはFirestore未初期化）ならFalse。"""
    if db_client is None:
        st.session_state["_pending_storage_error"] = f"🚨 **DB保存エラー**: Firestoreが初期化されていません（{db_error}）"
        return False

    doc_name = os.path.basename(path).replace(".json", "")
    doc_ref = db_client.collection("kvillage_data").document(doc_name)
    field_path = FieldPath("data", student_id, field_name)

    @firestore.transactional
    def _consume(transaction):
        snapshot = doc_ref.get(transaction=transaction)
        doc_data = snapshot.to_dict() or {}
        current = doc_data.get("data", {}).get(student_id, {}).get(field_name, 0)
        if current < amount:
            return False
        transaction.update(doc_ref, {field_path: current - amount})
        return True

    try:
        transaction = db_client.transaction()
        return _consume(transaction)
    except Exception as e:
        message = f"🚨 **DB保存エラー ({doc_name})**: {e}"
        st.session_state["_pending_storage_error"] = message
        st.error(message)
        return False
