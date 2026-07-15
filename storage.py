import os
import json
import glob
import zipfile
import streamlit as st
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from firebase_admin import storage as fb_storage
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
            # 過去問画像のバックアップ保存先（Firebase Storage）。プロジェクトのデフォルト
            # バケット名は通常 <project_id>.appspot.com だが、異なる場合はSecretsの
            # FIREBASE_STORAGE_BUCKET で明示的に上書きできるようにしておく
            storage_bucket = st.secrets.get("FIREBASE_STORAGE_BUCKET", f"{cert_dict['project_id']}.appspot.com")
            firebase_admin.initialize_app(cred, {"storageBucket": storage_bucket})
        return firestore.client(), None
    except Exception as e:
        return None, f"Firestore初期化エラー: {e}"


db_client, db_error = init_firestore()


def get_storage_bucket():
    """過去問画像のバックアップ用Firebase Storageバケットを返す。未設定・初期化失敗時はNone。"""
    if db_client is None:
        return None
    try:
        return fb_storage.bucket()
    except Exception:
        return None


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
    # update()に渡す辞書のキーはFieldPathオブジェクトそのものではなく、
    # to_api_repr()で変換した文字列（例: "data.stu1.exp"）である必要がある。
    # FieldPathオブジェクトを直接キーにすると、SDK内部で文字列として扱おうとして
    # AttributeError: 'FieldPath' object has no attribute 'strip' になる。
    field_path_str = FieldPath("data", student_id, *sub_keys).to_api_repr()
    try:
        doc_ref.update({field_path_str: value})
    except Exception:
        # ドキュメント自体がまだ存在しない場合はここで作成してから再試行する
        try:
            doc_ref.set({}, merge=True)
            doc_ref.update({field_path_str: value})
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
    field_path_str = FieldPath("data", student_id, *sub_keys).to_api_repr()
    try:
        doc_ref.update({field_path_str: firestore.DELETE_FIELD})
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
    field_path_str = FieldPath("data", student_id, field_name).to_api_repr()

    @firestore.transactional
    def _consume(transaction):
        snapshot = doc_ref.get(transaction=transaction)
        doc_data = snapshot.to_dict() or {}
        current = doc_data.get("data", {}).get(student_id, {}).get(field_name, 0)
        if current < amount:
            return False
        transaction.update(doc_ref, {field_path_str: current - amount})
        return True

    try:
        transaction = db_client.transaction()
        return _consume(transaction)
    except Exception as e:
        message = f"🚨 **DB保存エラー ({doc_name})**: {e}"
        st.session_state["_pending_storage_error"] = message
        st.error(message)
        return False


IMAGES_ARCHIVE_BLOB_PREFIX = "pdf_images/"


def upload_images_archive():
    """リポジトリ同梱のimages_part*.zip（過去問の生スキャン画像）をそのままFirebase Storageの
    バケットへアップロードする。このリポジトリはPublic設定のため、画像をgit管理から外して
    ここに退避させるための1回限りの移行用関数（管理画面のボタンから呼ばれる想定）。
    戻り値: (成功したか, メッセージ)"""
    bucket = get_storage_bucket()
    if bucket is None:
        return False, f"Firebase Storageバケットが取得できませんでした（{db_error}）。FIREBASE_KEYの設定と、Firebase ConsoleでStorageが有効になっているか確認してください。"

    zip_files = sorted(glob.glob(os.path.join(BASE_DIR, "images_part*.zip")))
    if not zip_files:
        return False, "images_part*.zip がこの環境に見つかりませんでした。"

    uploaded = []
    try:
        for zf in zip_files:
            blob_name = IMAGES_ARCHIVE_BLOB_PREFIX + os.path.basename(zf)
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(zf)
            uploaded.append(f"{os.path.basename(zf)}（{os.path.getsize(zf)/1024/1024:.1f}MB）")
        return True, "アップロード完了: " + "、".join(uploaded)
    except Exception as e:
        return False, f"アップロードに失敗しました: {e}"


def _safe_folder_name(name):
    """大学名などをFirebase Storageのフォルダ名として使えるよう軽くサニタイズする。"""
    name = (name or "").strip() or "未分類"
    return name.replace("/", "_").replace("\\", "_")


def _filename_to_university_map():
    """db.json内の全問題について、image_file→university（無ければ"未分類"）の対応表を作る。"""
    db_items = load_json(DB_PATH, [])
    mapping = {}
    for item in db_items:
        img_file = item.get("image_file")
        if img_file:
            mapping[img_file] = _safe_folder_name(item.get("university"))
    return mapping


def backup_pdf_images(filenames=None, subfolder=None, skip_existing=False):
    """pdf_images/内の画像をFirebase Storageに1ファイル=1オブジェクトとして個別にアップロードする。
    大学・模試ごとにFirebase Storage上でフォルダ分けされるよう、
    pdf_images/<大学名>/<ファイル名> というオブジェクト名にする。
    模試PDFの自動取り込み等で新しく追加された問題画像は、upload_images_archive()（同梱の
    images_part*.zipのみが対象）ではバックアップされず、ローカルディスクにしか存在しない。
    Streamlit Cloudはコンテナ再起動でローカルディスクの内容がリセットされるため、新規取り込みの
    保存が完了するたびにこの関数を呼ぶ必要がある。

    以前はpdf_images/フォルダ全体を毎回まるごとzip化して再アップロードしていたが、
    取り込み件数が増えるほど転送量が際限なく膨らむため、個別ファイルの差分アップロード方式に変更した。

    filenames: バックアップ対象のファイル名リスト（pdf_images/直下）。Noneならフォルダ内の
               全ファイルを対象にする。
    subfolder: 指定すれば、対象ファイル全てをこの大学名（フォルダ）の下にアップロードする
               （新規取り込み直後の自動呼び出しで、その取り込みの大学名を渡す想定）。
               省略時はdb.jsonのuniversityフィールドを参照し、ファイルごとに適切な大学名フォルダを判定する。
    skip_existing: Trueなら、バケットに同名のオブジェクトが既に存在するファイルはアップロードを
                   スキップする（「今すぐ全画像をバックアップする」ボタンでの重複アップロードを防ぐ）。
                   新規取り込み直後の自動呼び出しでは、対象は確実に新規ファイルなのでFalseのままでよい。
    戻り値: (成功したか, メッセージ)"""
    bucket = get_storage_bucket()
    if bucket is None:
        return False, f"Firebase Storageバケットが取得できませんでした（{db_error}）。"

    if not os.path.exists(IMG_DIR):
        return False, "pdf_images/ が見つかりませんでした。"

    if filenames is None:
        filenames = os.listdir(IMG_DIR)

    filename_to_university = None
    if subfolder is None:
        filename_to_university = _filename_to_university_map()

    uploaded_count = 0
    skipped_count = 0
    try:
        for filename in filenames:
            file_path = os.path.join(IMG_DIR, filename)
            if not os.path.isfile(file_path):
                continue

            folder = subfolder if subfolder is not None else filename_to_university.get(filename, "未分類")
            blob = bucket.blob(f"{IMAGES_ARCHIVE_BLOB_PREFIX}{_safe_folder_name(folder)}/{filename}")
            if skip_existing:
                try:
                    if blob.exists():
                        skipped_count += 1
                        continue
                except Exception:
                    pass  # 存在確認に失敗しても、念のためアップロードは試みる

            blob.upload_from_filename(file_path)
            uploaded_count += 1
        return True, f"{uploaded_count}件の画像をバックアップしました（{skipped_count}件は既存のためスキップ）。"
    except Exception as e:
        return False, f"バックアップに失敗しました: {e}"


def reorganize_flat_pdf_images():
    """以前のバージョンでpdf_images/直下（大学フォルダ分けなし）にアップロードされてしまった
    画像を、db.jsonのuniversityフィールドを見て pdf_images/<大学名>/<ファイル名> に
    移動する（コピー後に元オブジェクトを削除）。1回限りの整理用。
    戻り値: (成功したか, メッセージ)"""
    bucket = get_storage_bucket()
    if bucket is None:
        return False, f"Firebase Storageバケットが取得できませんでした（{db_error}）。"

    try:
        blobs = list(bucket.list_blobs(prefix=IMAGES_ARCHIVE_BLOB_PREFIX))
    except Exception as e:
        return False, f"バケット内のファイル一覧取得に失敗しました: {e}"

    filename_to_university = _filename_to_university_map()

    moved_count = 0
    try:
        for blob in blobs:
            rest = blob.name[len(IMAGES_ARCHIVE_BLOB_PREFIX):]
            if not rest or "/" in rest or rest.endswith(".zip"):
                continue  # すでにフォルダ分けされている or zipアーカイブは対象外

            filename = rest
            folder = filename_to_university.get(filename, "未分類")
            new_name = f"{IMAGES_ARCHIVE_BLOB_PREFIX}{_safe_folder_name(folder)}/{filename}"
            bucket.copy_blob(blob, bucket, new_name=new_name)
            blob.delete()
            moved_count += 1
        return True, f"{moved_count}件の画像を大学ごとのフォルダに整理しました。"
    except Exception as e:
        return False, f"フォルダ整理に失敗しました: {e}"


def ensure_pdf_images_extracted():
    """pdf_images/ が無ければ、まずFirebase Storageに退避済みのバックアップから復元を試みる。
    バケットに無ければ、リポジトリ同梱のimages_part*.zip（移行完了後は削除される想定の
    互換フォールバック）から復元する。

    Firebase Storage上には2種類のオブジェクトが混在しうる:
    - 過去の移行・一括バックアップで作られたzipアーカイブ（拡張子.zip）→ダウンロードして展開する
    - 新規取り込みのたびに個別アップロードされた画像ファイル→pdf_images/直下にそのままダウンロードする
    """
    if os.path.exists(IMG_DIR):
        return

    restored_any = False

    bucket = get_storage_bucket()
    if bucket is not None:
        try:
            blobs = list(bucket.list_blobs(prefix=IMAGES_ARCHIVE_BLOB_PREFIX))
        except Exception as e:
            blobs = []
            st.session_state["_pending_storage_error"] = f"🚨 **画像復元エラー**: Firebase Storageの一覧取得に失敗しました（{e}）。同梱の画像データがあればそちらを使用します。"

        os.makedirs(IMG_DIR, exist_ok=True)
        for blob in blobs:
            try:
                if blob.name.endswith(".zip"):
                    tmp_zip = os.path.join(BASE_DIR, "_" + os.path.basename(blob.name))
                    blob.download_to_filename(tmp_zip)
                    with zipfile.ZipFile(tmp_zip, "r") as zip_ref:
                        zip_ref.extractall(BASE_DIR)
                    os.remove(tmp_zip)
                else:
                    filename = os.path.basename(blob.name)
                    if filename:
                        blob.download_to_filename(os.path.join(IMG_DIR, filename))
                restored_any = True
            except Exception as e:
                st.session_state["_pending_storage_error"] = f"🚨 **画像復元エラー**: Firebase Storageからのダウンロードに失敗しました（{blob.name}: {e}）。他のファイルの復元は続行します。"

    if restored_any:
        return

    # フォールバック: リポジトリ同梱のzip（Firebase Storageへの移行・確認が済んだらgit履歴から削除する想定）
    zip_files = glob.glob(os.path.join(BASE_DIR, "images_part*.zip"))
    for zf in zip_files:
        with zipfile.ZipFile(zf, "r") as zip_ref:
            zip_ref.extractall(BASE_DIR)
