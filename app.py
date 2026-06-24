import streamlit as st
import json
import os
import random
import fitz  # PyMuPDF
from PIL import Image
import google.generativeai as genai
import tempfile
from datetime import datetime, timedelta
import re
import html
import hashlib
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

# 共通設定 (Kvillage先生仕様)
st.set_page_config(page_title="Kvillage先生の数学演習システム", page_icon="🎓", layout="wide")

import zipfile
import glob

# パス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db.json")
IMG_DIR = os.path.join(BASE_DIR, "pdf_images")
USERS_PATH = os.path.join(BASE_DIR, "users.json")
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")
STUDENTS_DATA_PATH = os.path.join(BASE_DIR, "students_data.json")
ANSWER_CACHE_PATH = os.path.join(BASE_DIR, "answer_cache.json")
BG_IMG_PATH = os.path.join(BASE_DIR, "bg.png")

# クラウド用：分割ZIPがあれば解凍して画像を復元
if not os.path.exists(IMG_DIR):
    zip_files = glob.glob(os.path.join(BASE_DIR, "images_part*.zip"))
    if zip_files:
        for zf in zip_files:
            with zipfile.ZipFile(zf, 'r') as zip_ref:
                zip_ref.extractall(BASE_DIR)

# マスターパスワード（先生専用）
MASTER_PASSWORD = "kvillage_master"
SECRET_WORD = "kvillage2026" # 教室の合言葉

from PIL import Image, ImageOps, ImageEnhance
import io
import base64

def set_custom_design():
    if not os.path.exists(BG_IMG_PATH):
        return
        
    # タブレットでも爆速で表示させるため、メモリ上で画像を軽量JPEGに圧縮してBase64化
    try:
        img = Image.open(BG_IMG_PATH)
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        # ナインボールカラーの画像を強調（全体は落ち着いた状態をキープ）
        enhancer_contrast = ImageEnhance.Contrast(img)
        img = enhancer_contrast.enhance(2.0)  
        
        enhancer_brightness = ImageEnhance.Brightness(img)
        img = enhancer_brightness.enhance(1.2)  
        
        # 【追加】文字や線（ある程度明るいピクセル）だけをさらに白く発光させるトーンカーブ補正
        # ピクセルの明るさが100以上の部分だけを1.8倍明るくし、暗い図形部分はそのままにする
        img = img.point(lambda x: min(255, int(x * 1.8)) if x > 100 else x)
        
        buffer = io.BytesIO()
        # 画質を少し落としてファイルサイズを極限まで小さくする
        img.save(buffer, format="JPEG", quality=50, optimize=True)
        b64_str = base64.b64encode(buffer.getvalue()).decode()
    except Exception as e:
        return
        
    custom_css = f"""
    <style>
    /* 軽量化した数式背景画像 ＋ ダークオーバーレイ（薄めの黒い幕）で黒基調にする */
    .stApp {{
        background-color: #0a0a0a;
        background-image: 
            linear-gradient(rgba(0, 0, 0, 0.4), rgba(0, 0, 0, 0.4)),
            url("data:image/jpeg;base64,{b64_str}");
        background-size: cover;
        background-position: center center;
        background-attachment: fixed;
    }}
    
    /* ダークテーマ用のガラス調（グラスモーフィズム）パネル */
    .block-container {{
        background: rgba(20, 20, 20, 0.85);
        border-radius: 15px;
        padding: 2rem 3rem;
        box-shadow: 0 8px 32px 0 rgba(178, 16, 16, 0.3);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(178, 16, 16, 0.2);
        margin-top: 2rem;
        margin-bottom: 2rem;
    }}
    
    /* ----------------------------------------------------
       ここから文字色を強制的に白（明るい色）にするCSS
    ---------------------------------------------------- */
    html, body, [class*="css"] {{
        color: #ffffff !important;
    }}
    p, h1, h2, h3, h4, h5, h6, span, div, label, li {{
        color: #f0f0f0 !important;
    }}
    a {{
        color: #ff4b4b !important;
    }}
    .stButton > button {{
        color: #ffffff !important;
        background-color: #333333 !important;
        border-color: #555555 !important;
    }}
    .stButton > button:hover {{
        border-color: #ff4b4b !important;
        color: #ff4b4b !important;
    }}
    .stTextInput > div > div > input {{
        color: #ffffff !important;
        background-color: rgba(0, 0, 0, 0.5) !important;
    }}

    /* -------------------------------------------------------------------
       【追加】不要なメニュー（右上のForkボタンや右下のアプリ一覧）を非表示にする
       ------------------------------------------------------------------- */
    #MainMenu {{visibility: hidden;}}
    header {{visibility: hidden !important;}}
    [data-testid="stHeader"] {{display: none !important;}}
    [data-testid="stToolbar"] {{display: none !important;}}
    .stDeployButton {{display: none !important;}}
    footer {{visibility: hidden;}}
    
    div[data-testid="stDecoration"] {{display: none !important;}}
    div[class^="viewerBadge_"] {{display: none !important;}}
    div[class^="styles_viewerBadge"] {{display: none !important;}}
    #viewerBadge_link__1SllNM {{display: none !important;}}
    .viewerBadge_container__1JCIV {{display: none !important;}}
    
    /* 画像のフルスクリーンボタンを隠す（あらゆる環境・言語に対応した最強のセレクタ） */
    button[title="View fullscreen"], 
    button[title="全画面表示"], 
    [data-testid="StyledFullScreenButton"], 
    [data-testid="stImageFullScreenButton"],
    [data-testid="stImage"] button,
    .stImage button {{
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }}
    
    /* 【最重要】入力フォーム（テキスト入力、セレクトボックス等）の視認性アップ */
    .stTextInput input, .stSelectbox > div > div {{
        background-color: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 8px !important;
        color: white !important;
    }}
    /* 入力フォームにフォーカスした時（枠を深紅に光らせる） */
    .stTextInput input:focus, .stSelectbox > div > div:focus {{
        border: 2px solid #b21010 !important;
        box-shadow: 0 0 8px rgba(178, 16, 16, 0.6) !important;
        background-color: rgba(255, 255, 255, 0.1) !important;
    }}
    
    /* ボタンのモダン化（丸みとホバーアニメーション） */
    .stButton>button {{
        border-radius: 30px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.5);
        font-weight: bold;
    }}
    .stButton>button:hover {{
        transform: translateY(-3px);
        box-shadow: 0 6px 15px rgba(178, 16, 16, 0.4);
    }}
    
    /* プライマリボタンの色調調整（ナインボール・クリムゾンレッド） */
    .stButton>button[data-baseweb="button"]:not([disabled]) {{
        background-color: #b21010;
        color: white;
        border: none;
    }}
    .stButton>button[data-baseweb="button"]:hover:not([disabled]) {{
        background-color: #8b0000;
    }}
    
    /* サイドバーの背景もダークトーンに調整 */
    [data-testid="stSidebar"] {{
        background-color: rgba(15, 15, 15, 0.95);
        border-right: 1px solid rgba(178, 16, 16, 0.2);
    }}
    </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)

# --- 💡【追加】Firestoreデータベースの初期化 ---
@st.cache_resource
def init_firestore():
    try:
        if not firebase_admin._apps:
            # Streamlit SecretsからFirebaseの鍵を読み込む
            cert_dict = dict(st.secrets["FIREBASE_KEY"])
            # JSONからTOMLへの変換時の改行文字を元に戻す
            cert_dict["private_key"] = cert_dict["private_key"].replace("\\n", "\n")
            cred = credentials.Certificate(cert_dict)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"Firestore初期化エラー: {e}")
        return None

db_client = init_firestore()

def load_json(path, default_val):
    # db.json（先生がアップロードする問題データ）はそのままローカルのファイルを読む
    if path == DB_PATH:
        if not os.path.exists(path):
            return default_val
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    # それ以外の生徒データはFirestoreから読む
    if db_client is None:
        return default_val
        
    doc_name = os.path.basename(path).replace(".json", "")
    try:
        doc_ref = db_client.collection("kvillage_data").document(doc_name)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("data", default_val)
        else:
            return default_val
    except Exception as e:
        print(f"DB読み込みエラー ({doc_name}): {e}")
        return default_val

def save_json(path, data):
    # db.json はローカルに上書きする（※通常アプリ稼働中はタグ付け以外で書き換えない）
    if path == DB_PATH:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return
        
    # 生徒データの書き込みはすべてFirestoreへ送る
    if db_client is None:
        return
        
    doc_name = os.path.basename(path).replace(".json", "")
    try:
        doc_ref = db_client.collection("kvillage_data").document(doc_name)
        doc_ref.set({"data": data})
    except Exception as e:
        print(f"DB保存エラー ({doc_name}): {e}")

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
        except:
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
    
    student = data[student_id]
    old_level, _, _ = get_level_info(student.get("exp", 0))
    
    student["exp"] = student.get("exp", 0) + exp_gain
    
    new_level, _, _ = get_level_info(student["exp"])
    leveled_up = False
    
    if new_level > old_level:
        student["level"] = new_level
        leveled_up = True
        
    data[student_id] = student
    save_json(STUDENTS_DATA_PATH, data)
    return leveled_up

def consume_tickets(student_id, amount):
    if student_id == "master":
        return True
    data = load_json(STUDENTS_DATA_PATH, {})
    if student_id not in data:
        return False
    
    student = data[student_id]
    if student.get("tickets", 0) >= amount:
        student["tickets"] -= amount
        data[student_id] = student
        save_json(STUDENTS_DATA_PATH, data)
        return True
    return False

def check_password_and_login():
    """3つの入り口（ログイン・新規登録・ゲスト）を持つ認証機能"""
    users = load_json(USERS_PATH, {})
    
    # URLパラメータからの自動復元
    query_params = st.query_params
    if "token" in query_params:
        token = query_params["token"]
        if token == MASTER_PASSWORD:
            if not st.session_state.get("logged_in"):
                st.session_state["logged_in"] = True
                st.session_state["student_id"] = "master"
                st.session_state["student_name"] = "Kvillage先生"
                st.session_state["is_guest"] = False
                st.session_state["is_master"] = True
        elif token in users and not st.session_state.get("logged_in"):
            st.session_state["logged_in"] = True
            st.session_state["student_id"] = token
            st.session_state["student_name"] = users[token]
            st.session_state["is_guest"] = False
            st.session_state["is_master"] = False
            process_daily_login(token)
            
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
        
    if not st.session_state["logged_in"]:
        st.title("🎓 Kvillage先生の数学ルームへようこそ！")
        
        tab1, tab2 = st.tabs(["🔒 会員ログイン", "✨ 新規会員登録（要合言葉）"])
        
        # 既存会員ログイン (マスターログイン兼用)
        with tab1:
            st.markdown("### 登録済みのパスワードでログイン")
            login_pass = st.text_input("パスワード", type="password", key="login_pass")
            if st.button("ログイン", key="btn_login"):
                if login_pass == MASTER_PASSWORD:
                    st.session_state["logged_in"] = True
                    st.session_state["student_id"] = "master"
                    st.session_state["student_name"] = "Kvillage先生"
                    st.session_state["is_guest"] = False
                    st.session_state["is_master"] = True
                    st.query_params.token = MASTER_PASSWORD
                    st.rerun()
                elif login_pass in users:
                    st.session_state["logged_in"] = True
                    st.session_state["student_id"] = login_pass
                    st.session_state["student_name"] = users[login_pass]
                    st.session_state["is_guest"] = False
                    st.session_state["is_master"] = False
                    st.query_params.token = login_pass
                    process_daily_login(login_pass)
                    st.rerun()
                else:
                    st.error("パスワードが違います。")
                    
        # 新規登録
        with tab2:
            st.markdown("### 自分専用のアカウントを作ろう！")
            st.info("💡 先生から教わった「教室の合言葉」が必要です。")
            new_name = st.text_input("あなたの名前（ニックネーム可）", key="reg_name")
            new_pass = st.text_input("好きなパスワード（6文字以上、英字と数字を必ず含めること）", type="password", key="reg_pass")
            secret_word = st.text_input("教室の合言葉", type="password", key="reg_secret")
            
            if st.button("登録してはじめる", key="btn_register"):
                if not new_name or not new_pass or not secret_word:
                    st.error("すべての項目を入力してください。")
                elif secret_word != SECRET_WORD:
                    st.error("合言葉が間違っています。先生に確認してください。")
                elif len(new_pass) < 6:
                    st.error("パスワードは6文字以上にしてください。")
                elif not (re.search(r'[A-Za-z]', new_pass) and re.search(r'[0-9]', new_pass)):
                    st.error("パスワードには、アルファベット（英字）と数字を両方とも含めてください。")
                elif new_pass in users or new_pass == MASTER_PASSWORD:
                    st.error("そのパスワードは既に使われています。別のパスワードを考えてね！")
                else:
                    # 登録処理
                    users[new_pass] = new_name
                    save_json(USERS_PATH, users)
                    init_student_data(new_pass, new_name)
                    st.success("登録が完了しました！さっそく始めましょう！")
                    st.session_state["logged_in"] = True
                    st.session_state["student_id"] = new_pass
                    st.session_state["student_name"] = new_name
                    st.session_state["is_guest"] = False
                    st.session_state["is_master"] = False
                    st.query_params.token = new_pass
                    process_daily_login(new_pass)
                    st.rerun()
                
        return False
    return True

def generate_pdf(selected_univs, num_questions, student_id, is_review=False, review_target_ids=None, topic_filter="all"):
    db = load_json(DB_PATH, [])
    history_db = load_json(HISTORY_PATH, {})
    
    is_guest = (student_id == "guest")
    
    if is_guest:
        # ゲストモード：履歴を一切考慮せず、指定大学から完全ランダムに抽出
        pool = [item for item in db if item.get("university") in selected_univs]
    else:
        # 正規会員モード
        student_history = history_db.get(student_id, [])
        if is_review:
            # 復習プリント
            pool = [item for item in db if item.get("image_file") in review_target_ids]
        else:
            # 新規演習（履歴除外）
            used_ids = [record.get("id") for record in student_history]
            pool = [item for item in db if item.get("university") in selected_univs and item.get("image_file") not in used_ids]
            
    if topic_filter == "1a2bc":
        pool = [item for item in pool if item.get("topic") != "数学Ⅲ" or item.get("university") == "東京海洋大"]
    
    if not pool:
        return None, 0
        
    count = min(num_questions, len(pool))
    selected_items = random.sample(pool, count)
    
    out_doc = fitz.open()
    for item in selected_items:
        img_path = os.path.join(IMG_DIR, item.get("image_file", ""))
        if os.path.exists(img_path):
            img_doc = fitz.open(img_path)
            pdf_bytes = img_doc.convert_to_pdf()
            img_pdf = fitz.open("pdf", pdf_bytes)
            out_doc.insert_pdf(img_pdf)
            
    pdf_data = out_doc.write()
    
    # 履歴の更新（ゲストは保存しない）
    if not is_guest:
        today = datetime.today().strftime('%Y-%m-%d')
        for item in selected_items:
            student_history.append({
                "id": item.get("image_file"),
                "date_issued": today,
                "status": "issued"
            })
        history_db[student_id] = student_history
        save_json(HISTORY_PATH, history_db)
    
    return pdf_data, count

def convert_pdf_to_image(uploaded_file):
    import tempfile
    import os
    
    # PDFの中身がストリームだと正常に全ページ読み込めない場合があるため、一度一時ファイルに保存する
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
        
    doc = None
    try:
        doc = fitz.open(tmp_path)
        images = []
        mat = fitz.Matrix(2.0, 2.0)
        for i in range(len(doc)):
            page = doc[i]
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data)).convert("RGB")
            # 一括送信時にデータ容量オーバー（Payload Too Large等）で弾かれるのを防ぐため画像サイズを圧縮
            img.thumbnail((1500, 1500))
            images.append(img)
        return images
    except Exception as e:
        return []
    finally:
        # Windowsエラー対策: 削除する前に必ずファイルを閉じる
        if doc is not None:
            doc.close()
        # 処理が終わったら確実に一時ファイルを削除
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@st.cache_data(ttl=3600, show_spinner=False)
def get_flash_model_name(api_key):
    """APIキーに紐づく利用可能なFlashモデルの名前を1回だけ取得し、キャッシュする"""
    try:
        genai.configure(api_key=api_key)
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # まず gemini-1.5-flash が名前に含まれるものを探す
        for m in models:
            if 'gemini-1.5-flash' in m.name:
                return m.name
                
        # なければ flash が含まれるものを探す
        for m in models:
            if 'flash' in m.name:
                return m.name
                
        # それでもなければフォールバック
        return "gemini-1.5-flash-latest"
    except Exception:
        return "gemini-1.5-flash"

def analyze_with_gemini(img_or_imgs, api_key, mode, student_name, student_id, is_batch=False):
    images_for_hash = img_or_imgs if isinstance(img_or_imgs, list) else [img_or_imgs]
    
    # 画像ハッシュ化（キャッシュ用）
    h = hashlib.md5()
    for img in images_for_hash:
        h.update(img.tobytes())
    img_hash = h.hexdigest()

    is_answer_mode = (mode == "解答・解説をもらう（答え合わせしたい時 / チケット消費0枚）")
    is_hint_mode = (mode == "ヒントだけもらう（行き詰まった時 / チケット消費0枚）")
    is_correction_mode = (mode == "添削してもらう（解き終わった時 / チケット消費1枚）")
    
    if is_answer_mode:
        cache_data = load_json(ANSWER_CACHE_PATH, {})
        if img_hash in cache_data:
            greeting = f"**{student_name}さん、こんにちは！**\n\n"
            return greeting + cache_data[img_hash] + "\n\n*(※データベースから一瞬で解答を取得しました！チケット消費0枚)*"

    # チケット消費チェック
    required_tickets = 1 if is_correction_mode else 0
    if is_batch:
        required_tickets += 1  # 一括送信のペナルティとして+1枚消費

    if required_tickets > 0:
        if not consume_tickets(student_id, required_tickets):
            return f"⚠️ **チケットが足りません！**\n\n今回の送信にはチケットが {required_tickets}枚 必要です。明日ログインしてボーナスチケットを受け取ってください！"

    genai.configure(api_key=api_key)
    
    # キャッシュされた関数から確実に存在するモデル名を取得（APIの無駄打ちは発生しない）
    best_model_name = get_flash_model_name(api_key)
    
    try:
        model = genai.GenerativeModel(best_model_name)
    except Exception as e:
        return f"モデルの初期化中にエラーが発生しました: {e}"
    
    if is_hint_mode:
        instruction = "問題文と生徒の書き込みを読み取り、解き方の『最初のヒント』や『アプローチ方法』だけを教えてください。絶対に最終的な答えや完全な数式は教えないでください。"
    elif is_answer_mode:
        instruction = "問題文を読み取り、この問題に対する『完全な模範解答と丁寧な解説』を作成してください。\n【重要】今回は生徒が答え合わせを希望しているため、教育的な配慮（ヒントで止めるなど）は一切不要です。出し惜しみせず、最後の結論（答えの数値や証明の完了）まで全ての数式と論理展開を省略せずに最後まで書き切ってください。"
    else:
        instruction = "問題文と生徒の手書き解答の両方を読み取ってください。\n生徒の解答が合っているか判定し、間違っている場合は『どこで計算ミスをしたか』『どの公式を間違えたか』などを具体的に指摘して添削してください。\n白紙の場合は、「まずはここから考えてみよう」と優しくヒントを出してください。"

    # 生徒のステータス取得
    student_data = load_json(STUDENTS_DATA_PATH, {}).get(student_id, {})
    level = student_data.get("level", 1)
    streak = student_data.get("login_streak", 1)
        
    if is_answer_mode:
        prompt = f"""
あなたは優秀で、生徒に寄り添う親切な高校の数学教師「Kvillage先生」です。

【生徒からの要望】
{instruction}

【ルール】
1. 口調は「です・ます」調で、生徒を温かく励ますトーンにしてください。ただし、特定の生徒名や個別の挨拶は書かないでください。（システム側で後から付与します）
2. 【重要】解答を教える際、ただ公式を当てはめるだけでなく、「なぜここでその公式を使うのか（発想の動機）」を必ず語ってください。
3. 【超重要: 読みやすさとレイアウト（余白）】
   相手は高校生です。文字や数式が密集していると読む気を無くしてしまいます。
   - 文章は1〜2文ごとに必ず「空行（改行2回）」を挟み、たっぷりと余白を取ってください。
   - 長い文章を絶対に1つの段落に詰め込まないでください。
4. 【超重要: 数式の表示について（絶対に守ること）】
   - シグマ記号（∑）、極限（lim）、積分（∫）、分数などを出力する際、**添え字や分母分子が必ず文字の「上下」に配置されるようにしてください**。
   - 数式（特に方程式や式の変形）を書く際は、必ず改行して独立した行となる「ブロック数式（`$$` で囲む形式）」で記述してください。
     (良い例): 「...を以下のように変形します。\n\n$$ a_n = \sum_{{k=1}}^n \frac{{1}}{{k}} $$\n\nこの式から...」
   - 文中（インライン）に短い変数や数式（例: x や \alpha など）を書く場合は、バッククォート（`）ではなく、**必ず `$x$` や `$\alpha$` のように `$` で囲んでください**。
   - インラインでシグマや分数など縦に長い数式を書く場合にのみ、`$ \displaystyle \sum $` のように `\displaystyle` を付けてください。単なる変数には不要です。
   - 【厳禁】数式や変数を記述する際、絶対にバッククォート（`）で囲まないでください。緑色の文字（コードブロック）になってしまい、数式として表示されなくなります。
5. 【超重要: 複数行の数式ブロックについて】
   - 複数行の数式を書く場合は、**必ず `\begin{{aligned}}` と `\end{{aligned}}` を使用し、その外側を `$$` で囲んでください。**
   - 絶対に `\begin{{align*}}` は使わないでください。（表示エラーになるため、必ず aligned を使用すること）
   - 【厳格なルール】`\begin{{aligned}}` 環境内で等号（`&=`）を続ける場合は、**絶対に1行に複数書かず、必ず `\\` （バックスラッシュ2つ）を使って改行してください**。
   - 例:
     $$
     \begin{{aligned}}
     y &= x^2 + 2x + 1 \\
       &= (x + 1)^2
     \end{{aligned}}
     $$
"""
    else:
        prompt = f"""
あなたは優秀で、生徒に寄り添う親切な高校の数学教師「Kvillage先生」です。
目の前にいる生徒の名前は「{student_name}」さんです。

【生徒の裏情報（※機械的に言わず、自然な励ましに変換して文中に含めること）】
- 現在の数学レベル: {level}
- 連続学習日数: {streak}日

【生徒からの要望】
{instruction}

【ルール】
1. 必ず最初に「{student_name}さん、こんにちは！」など、名前を呼んで温かく接し、生徒の学習の継続（{streak}日連続）やレベル（レベル{level}）を褒めてあげてください。
2. 口調は「です・ます」調で、生徒を温かく励ますトーンにしてください。
3. 【重要】解答を教える際、ただ公式を当てはめるだけでなく、「なぜここでその公式を使うのか（発想の動機）」を必ず語ってください。
4. 【超重要: 読みやすさとレイアウト（余白）】
   相手は高校生です。文字や数式が密集していると読む気を無くしてしまいます。
   - 文章は1〜2文ごとに必ず「空行（改行2回）」を挟み、たっぷりと余白を取ってください。
   - 長い文章を絶対に1つの段落に詰め込まないでください。
5. 【超重要: 数式の表示について（絶対に守ること）】
   - シグマ記号（∑）、極限（lim）、積分（∫）、分数などを出力する際、**添え字や分母分子が必ず文字の「上下」に配置されるようにしてください**。
   - 数式（特に方程式や式の変形）を書く際は、必ず改行して独立した行となる「ブロック数式（`$$` で囲む形式）」で記述してください。
     (良い例): 「...を以下のように変形します。\n\n$$ a_n = \sum_{{k=1}}^n \frac{{1}}{{k}} $$\n\nこの式から...」
   - 文中（インライン）に短い変数や数式（例: x や \alpha など）を書く場合は、バッククォート（`）ではなく、**必ず `$x$` や `$\alpha$` のように `$` で囲んでください**。
   - インラインでシグマや分数など縦に長い数式を書く場合にのみ、`$ \displaystyle \sum $` のように `\displaystyle` を付けてください。単なる変数には不要です。
   - 【厳禁】数式や変数を記述する際、絶対にバッククォート（`）で囲まないでください。緑色の文字（コードブロック）になってしまい、数式として表示されなくなります。
5. 【超重要: 複数行の数式ブロックについて】
   - 複数行の数式を書く場合は、**必ず `\begin{{aligned}}` と `\end{{aligned}}` を使用し、その外側を `$$` で囲んでください。**
   - 絶対に `\begin{{align*}}` は使わないでください。（表示エラーになるため、必ず aligned を使用すること）
   - 【厳格なルール】`\begin{{aligned}}` 環境内で等号（`&=`）を続ける場合は、**絶対に1行に複数書かず、必ず `\\` （バックスラッシュ2つ）を使って改行してください**。
   - 例:
     $$
     \begin{{aligned}}
     y &= x^2 + 2x + 1 \\
       &= (x + 1)^2
     \end{{aligned}}
     $$
"""
    try:
        contents = [prompt]
        # 複数画像の場合は縦長に連結して「1枚の画像」として送ることで、画像の枚数制限によるAPIエラーを回避する
        if isinstance(img_or_imgs, list) and len(img_or_imgs) > 0:
            if len(img_or_imgs) == 1:
                contents.append(img_or_imgs[0])
            else:
                # 幅は最大のもの、高さは合計
                widths, heights = zip(*(i.size for i in img_or_imgs))
                max_width = max(widths)
                total_height = sum(heights)
                
                # 縦長の空キャンバスを作成
                new_im = Image.new('RGB', (max_width, total_height), (255, 255, 255))
                y_offset = 0
                for im in img_or_imgs:
                    new_im.paste(im, (0, y_offset))
                    y_offset += im.size[1]
                
                # 巨大すぎる場合はリサイズ（高さ最大4000px程度に制限）
                if new_im.height > 4000:
                    ratio = 4000.0 / new_im.height
                    new_width = int(new_im.width * ratio)
                    new_height = int(new_im.height * ratio)
                    new_im = new_im.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                contents.append(new_im)
        elif not isinstance(img_or_imgs, list):
            contents.append(img_or_imgs)
            
        response = model.generate_content(contents)
        
        result_text = response.text
        
        # AIが癖で出力してしまうMarkdownのコードブロックタグを削除（これがあると数式としてレンダリングされないため）
        result_text = result_text.replace("```latex\n", "").replace("```math\n", "").replace("```\n", "").replace("```", "")
        result_text = result_text.replace("`$$", "$$").replace("$$`", "$$").replace("`$", "$").replace("$`", "$")
        
        # さらに、インラインのバッククォート（緑文字の原因）を剥がす
        # 例: `$(-2, 5)$` -> $(-2, 5)$ (この後Streamlitが$を認識して数式化する)
        import re
        result_text = re.sub(r'`([^`\n]+)`', r'\1', result_text)
        # 成功時にEXP付与 (先生アカウント以外)
        leveled_up = False
        if is_correction_mode:
            leveled_up = update_student_exp(student_id, 50)
        elif is_hint_mode or is_answer_mode:
            pass # チケット消費なしの行動ではEXPは増えない
        
        # キャッシュの保存と、解答モード時の挨拶の付与
        if is_answer_mode:
            cache_data = load_json(ANSWER_CACHE_PATH, {})
            cache_data[img_hash] = result_text
            save_json(ANSWER_CACHE_PATH, cache_data)
            greeting = f"**{student_name}さん、こんにちは！**\n\n"
            result_text = greeting + result_text
        
        if leveled_up:
            st.toast(f"🎉 レベルアップしました！👑", icon="🎉")
        
        return result_text + f"\n\n*(使用モデル: {best_model_name})*"
    except Exception as e:
        error_msg = str(e).lower()
        if "429" in error_msg or "resource exhausted" in error_msg or "quota" in error_msg:
            # 1日あたりの上限に達しているかチェック
            if "generaterequestsperday" in error_msg or "perday" in error_msg or "limit: 200" in error_msg or "limit: 20" in error_msg:
                return f"🙏 **本日のAI利用枠（1日あたりの上限回数）を使い切ってしまいました！**\n\n先生が設定した1日の上限回数に達したため、本日はこれ以上送信できません。明日の朝にリセットされるまでお待ちください。\n\n*(デバッグ用内部エラー: {e})*"
            
            # 待機秒数が含まれている場合は抽出する
            wait_time = "1分ほど"
            import re
            match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_msg)
            if match:
                seconds = int(float(match.group(1)))
                wait_time = f"あと **{seconds}秒** ほど"
                
            return f"🙏 **現在Kvillage先生は他の生徒の質問に答えていて大忙しです！**\n\nごめんね、{wait_time}待ってからもう一度「Kvillage先生に送信する」ボタンを押してみてね！\n\n*(※通信制限のため一時的にお待ちいただいています)*"
        else:
            return f"エラーが発生しました: {e}"

def main():
    set_custom_design()
    
    if not check_password_and_login():
        return
        
    student_id = st.session_state["student_id"]
    student_name = st.session_state["student_name"]
    is_guest = st.session_state.get("is_guest", False)
    is_master = st.session_state.get("is_master", False)
        
    st.sidebar.title(f"ようこそ、{student_name}さん！")
    
    if not is_master:
        student_data = load_json(STUDENTS_DATA_PATH, {}).get(student_id, {})
        tickets = student_data.get("tickets", 0)
        level = student_data.get("level", 1)
        exp = student_data.get("exp", 0)
        streak = student_data.get("login_streak", 1)
        
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"<h2 style='text-align: center; color: #ffcccc; margin-bottom: 0;'>👑 レベル: {level}</h2>", unsafe_allow_html=True)
        
        _, current_tier_exp, required_exp = get_level_info(exp)
        progress_val = min(1.0, max(0.0, current_tier_exp / required_exp))
        st.sidebar.progress(progress_val, text=f"次のレベルまで: {required_exp - current_tier_exp} EXP")
        st.sidebar.markdown(f"**🎟️ 所持チケット**: {tickets} 枚")
        st.sidebar.markdown(f"**🔥 連続学習**: {streak} 日目")
        st.sidebar.markdown("---")
    
    # 権限に応じたメニューの切り替え
    if is_master:
        menu_options = ["⚙️ 先生専用管理ダッシュボード", "🏷️ 問題のタグ付け作業", "提出＆Kvillage先生の添削"]
    else:
        menu_options = ["演習プリント作成", "復習プリント作成", "提出＆Kvillage先生の添削"]
        
    page = st.sidebar.radio("メニュー", menu_options)
    
    # ログアウトボタン
    if st.sidebar.button("ログアウト"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()
    
    db = load_json(DB_PATH, [])
    history_db = load_json(HISTORY_PATH, {})
    student_history = history_db.get(student_id, [])
    
    if page == "⚙️ 先生専用管理ダッシュボード":
        st.title("⚙️ Kvillage先生専用 管理ダッシュボード")
        st.write("ここでは登録されている生徒のパスワードの確認、変更、学習状況の確認が行えます。")
        
        users = load_json(USERS_PATH, {})
        
        if not users:
            st.info("まだ登録している生徒はいません。")
        else:
            # データの整形
            student_data = []
            for pwd, name in users.items():
                h = history_db.get(pwd, [])
                student_data.append({
                    "名前": name,
                    "パスワード": pwd,
                    "総プリント出力数": len(h)
                })
                
            st.subheader("👥 生徒一覧と学習状況")
            st.dataframe(student_data, use_container_width=True)
            
            st.subheader("🔑 パスワードの強制リセット")
            st.write("「パスワードを忘れた」という生徒のパスワードを新しいものに変更します。")
            
            target_user_pwd = st.selectbox("リセットする生徒を選択", options=list(users.keys()), format_func=lambda x: f"{users[x]} (現在のパスワード: {x})")
            new_pwd = st.text_input("新しいパスワード（6文字以上・英数字含む）", type="password")
            
            if st.button("パスワードを上書き変更する", type="primary"):
                if not new_pwd:
                    st.error("新しいパスワードを入力してください。")
                elif len(new_pwd) < 6:
                    st.error("パスワードは6文字以上にしてください。")
                elif not (re.search(r'[A-Za-z]', new_pwd) and re.search(r'[0-9]', new_pwd)):
                    st.error("パスワードには、アルファベット（英字）と数字を両方とも含めてください。")
                elif new_pwd in users or new_pwd == "guest" or new_pwd == MASTER_PASSWORD:
                    st.error("そのパスワードは既に別の人が使っています。")
                else:
                    # usersの変更
                    name = users[target_user_pwd]
                    del users[target_user_pwd]
                    users[new_pwd] = name
                    save_json(USERS_PATH, users)
                    
                    # historyの引き継ぎ
                    if target_user_pwd in history_db:
                        history_db[new_pwd] = history_db[target_user_pwd]
                        del history_db[target_user_pwd]
                        save_json(HISTORY_PATH, history_db)
                        
                    st.success(f"{name}さんのパスワードを「{new_pwd}」に変更し、学習履歴も引き継ぎました！")
                    st.rerun()

    elif page == "🏷️ 問題のタグ付け作業":
        st.title("🏷️ 問題のタグ付け（手動分類）作業")
        st.write("自動分類で「未分類」となった問題や、分類を修正したい問題にタグを付けます。")
        
        # セッションステートの初期化
        if "tagging_index" not in st.session_state:
            st.session_state["tagging_index"] = 0
            
        # 未分類を含む、またはフィルタに合致する問題のリストアップ
        filter_type = st.radio("表示する問題", ["未分類の問題のみ", "すべての問題"], index=0, horizontal=True)
        
        if filter_type == "未分類の問題のみ":
            target_items = [item for item in db if "未分類" in item.get("topic", [])]
        else:
            target_items = db
            
        if not target_items:
            st.success("対象となる問題はありません！すべて分類済みです 🎉")
        else:
            st.write(f"対象問題: **{len(target_items)}問** (現在のインデックス: {st.session_state['tagging_index'] + 1} / {len(target_items)})")
            
            # インデックスが範囲外になったらリセット
            if st.session_state["tagging_index"] >= len(target_items):
                st.session_state["tagging_index"] = 0
                
            current_item = target_items[st.session_state["tagging_index"]]
            
            # 問題の情報を表示
            st.markdown(f"**大学**: {current_item.get('university')}　**ファイル**: {current_item.get('source_pdf')}　**ページ**: {current_item.get('page')}")
            
            # 画像の表示
            img_path = os.path.join(IMG_DIR, current_item.get("image_file", ""))
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path)
                    buffered = io.BytesIO()
                    img.save(buffered, format="PNG")
                    img_str = base64.b64encode(buffered.getvalue()).decode()
                    st.markdown(f'<img src="data:image/png;base64,{img_str}" style="width:100%; max-width:800px; border-radius:8px; border:1px solid rgba(255,255,255,0.2);">', unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"画像の表示に失敗しました: {e}")
            else:
                st.error("画像ファイルが見つかりません。")
                
            # タグ選択UI
            all_topics = ["確率", "ベクトル", "数列", "微分・積分", "図形と方程式", "複素数平面", "極座標", "整数", "数と式", "三角関数", "指数・対数", "二次関数", "図形の性質", "場合の数", "極限", "その他", "未分類", "数学Ⅲ"]
            current_topics = current_item.get("topic", [])
            if isinstance(current_topics, str):
                current_topics = [current_topics]
                
            new_topics = st.multiselect("この問題の分野（複数選択可）", all_topics, default=current_topics)
            
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button("💾 保存して次へ", type="primary"):
                    # DBを更新
                    for idx, item in enumerate(db):
                        if item.get("image_file") == current_item.get("image_file"):
                            # 未分類以外のタグが選ばれた場合、自動的に「未分類」を外す
                            if "未分類" in new_topics and len(new_topics) > 1:
                                new_topics.remove("未分類")
                            db[idx]["topic"] = new_topics
                            break
                    save_json(DB_PATH, db)
                    st.session_state["tagging_index"] += 1
                    st.rerun()
            with col2:
                if st.button("⏭️ スキップ（次へ）"):
                    st.session_state["tagging_index"] += 1
                    st.rerun()
            with col3:
                if st.button("⏮️ 1つ戻る"):
                    st.session_state["tagging_index"] = max(0, st.session_state["tagging_index"] - 1)
                    st.rerun()

    elif page == "演習プリント作成":
        st.title("📚 オリジナル演習プリント作成")
        if is_guest:
            st.write("志望する大学を選んで、演習プリントを作ろう！（※ゲストモードでは同じ問題が何度も出ることがあります）")
        else:
            st.write("志望する大学を選んで、君だけの新しい演習プリントを作ろう！")
        
        if not db:
            st.error("データベースが見つかりません。")
            return
            
        univ_counts = {}
        for item in db:
            u = item.get("university")
            if u:
                univ_counts[u] = univ_counts.get(u, 0) + 1
        
        univ_list = sorted(univ_counts.keys())
        
        st.subheader("1. 大学を選ぶ")
        selected_univs = st.multiselect("大学を選択（複数可）", univ_list, default=None)
        
        st.subheader("2. 出題範囲を選ぶ")
        topic_choice = st.radio("数学Ⅲを含めますか？", ["数学ⅠA・ⅡBC のみ出題", "数学ⅠA・ⅡBC・Ⅲ すべて出題"], index=0)
        topic_filter = "1a2bc" if topic_choice == "数学ⅠA・ⅡBC のみ出題" else "all"
        
        if selected_univs:
            if is_guest:
                pool_count = sum(1 for item in db if item.get("university") in selected_univs and (topic_filter == "all" or item.get("topic") != "数学Ⅲ" or item.get("university") == "東京海洋大"))
                st.write(f"※対象となる問題数: **{pool_count}問**")
            else:
                used_ids = [record.get("id") for record in student_history]
                pool_count = sum(1 for item in db if item.get("university") in selected_univs and item.get("image_file") not in used_ids and (topic_filter == "all" or item.get("topic") != "数学Ⅲ" or item.get("university") == "東京海洋大"))
                st.write(f"※現在、あなたが挑戦できる新しい問題数: **{pool_count}問**")
            
            if pool_count == 0:
                if is_guest:
                    st.warning("選択した大学の問題はありません。")
                else:
                    st.warning("選択した大学の新しい問題はすべて解き終わりました！別の大学を選ぶか、「復習プリント作成」メニューへ進みましょう。")
            elif pool_count == 1:
                st.subheader("3. 問題数を決める")
                st.write("作成できる新しい問題は残り **1問** です。")
                num_q = 1
                
                if st.button("プリントを作成する（無料）", type="primary"):
                    with st.spinner("PDFを生成中..."):
                        pdf_data, count = generate_pdf(selected_univs, num_q, student_id, topic_filter=topic_filter)
                        if pdf_data:
                            msg = f"ランダムに {count}問 選んでプリントを作成しました！" if is_guest else f"新しい問題から {count}問 のプリントを作成し、履歴に記録しました！"
                            st.success(msg)
                            st.download_button(
                                label="📥 PDFをダウンロード",
                                data=pdf_data,
                                file_name=f"演習プリント_{student_name}.pdf",
                                mime="application/pdf"
                            )
                        else:
                            st.error("プリントの作成に失敗しました。")
            else:
                st.subheader("3. 問題数を決める")
                # カラムを使ってスライダーの横幅を短く制限する
                col1, col2 = st.columns([1, 2])
                with col1:
                    num_q = st.slider("作成する問題数", min_value=1, max_value=min(5, pool_count), value=min(3, pool_count))
                
                if st.button("プリントを作成する（無料）", type="primary"):
                    with st.spinner("PDFを生成中..."):
                        pdf_data, count = generate_pdf(selected_univs, num_q, student_id, topic_filter=topic_filter)
                        if pdf_data:
                            msg = f"ランダムに {count}問 選んでプリントを作成しました！" if is_guest else f"新しい問題から {count}問 のプリントを作成し、履歴に記録しました！"
                            st.success(msg)
                            st.download_button(
                                label="📥 PDFをダウンロード",
                                data=pdf_data,
                                file_name=f"演習プリント_{student_name}.pdf",
                                mime="application/pdf"
                            )
                        else:
                            st.error("プリントの作成に失敗しました。")
                            
    elif page == "復習プリント作成":
        st.title("🔄 復習プリント作成")
        
        if is_guest:
            st.warning("⚠️ この機能は無料の会員登録をした生徒のみが使えます！")
            st.info("💡 **会員登録のメリット**\n- 過去に解いた問題が保存され、新しい問題だけを出題できるようになります。\n- エビングハウスの忘却曲線に合わせて、忘れた頃に復習プリントを作れます。\n\n**左側の「ログアウト」ボタンを押して、最初の画面から「新規会員登録」を行ってみてください！**")
        else:
            st.write("エビングハウスの忘却曲線を意識して、最適なタイミングで復習しよう！")
            
            if not student_history:
                st.info("まだ演習の履歴がありません。まずは「演習プリント作成」から新しい問題に挑戦しましょう！")
            else:
                st.subheader("1. 復習する範囲を決める")
                days_ago = st.slider("何日以上前に解いた問題を復習しますか？", min_value=0, max_value=30, value=7, help="0日にすると、過去に解いたすべての問題から抽出します。")
                
                topic_choice_rev = st.radio("数学Ⅲを含めますか？ ", ["数学ⅠA・ⅡBC のみ出題", "数学ⅠA・ⅡBC・Ⅲ すべて出題"], index=0)
                topic_filter_rev = "1a2bc" if topic_choice_rev == "数学ⅠA・ⅡBC のみ出題" else "all"
                
                target_date_threshold = datetime.today() - timedelta(days=days_ago)
                
                review_target_ids = set()
                for record in student_history:
                    try:
                        record_date = datetime.strptime(record["date_issued"], '%Y-%m-%d')
                        if record_date <= target_date_threshold:
                            review_target_ids.add(record["id"])
                    except:
                        pass
                
                if topic_filter_rev == "1a2bc":
                    valid_ids = {item.get("image_file") for item in db if item.get("topic") != "数学Ⅲ" or item.get("university") == "東京海洋大"}
                    review_target_ids = review_target_ids.intersection(valid_ids)
                
                if not review_target_ids:
                    if days_ago == 0:
                        st.warning("過去に出題された履歴が見つかりません。")
                    else:
                        st.warning(f"現在、{days_ago}日以上前に解いた問題はありません。日数を短くして試してみてください。")
                else:
                    st.write(f"※対象となる復習問題のストック: **{len(review_target_ids)}問**")
                    if len(review_target_ids) == 1:
                        st.subheader("2. 問題数を決める")
                        st.write("復習できる問題は **1問** です。")
                        num_q = 1
                        
                        if st.button("復習プリントを作成する（無料）", type="primary"):
                            with st.spinner("PDFを生成中..."):
                                pdf_data, count = generate_pdf([], num_q, student_id, is_review=True, review_target_ids=review_target_ids, topic_filter=topic_filter_rev)
                                if pdf_data:
                                    st.success(f"復習用ストックから {count}問 を選んでプリントを作成しました！")
                                    st.download_button(
                                        label="📥 復習プリントをダウンロード",
                                        data=pdf_data,
                                        file_name=f"復習プリント_{student_name}.pdf",
                                        mime="application/pdf"
                                    )
                                else:
                                    st.error("プリントの作成に失敗しました。")
                    else:
                        st.subheader("2. 問題数を決める")
                        # カラムを使ってスライダーの横幅を短く制限する
                        col1, col2 = st.columns([1, 2])
                        with col1:
                            num_q = st.slider("作成する問題数", min_value=1, max_value=min(5, len(review_target_ids)), value=min(3, len(review_target_ids)), key="review_slider")
                        
                        if st.button("復習プリントを作成する（無料）", type="primary"):
                            with st.spinner("PDFを生成中..."):
                                pdf_data, count = generate_pdf([], num_q, student_id, is_review=True, review_target_ids=review_target_ids, topic_filter=topic_filter_rev)
                                if pdf_data:
                                    st.success(f"復習用ストックから {count}問 をランダムに選んでプリントを作成しました！")
                                    st.download_button(
                                        label="📥 復習プリントをダウンロード",
                                        data=pdf_data,
                                        file_name=f"復習プリント_{student_name}.pdf",
                                        mime="application/pdf"
                                    )
                                else:
                                    st.error("プリントの作成に失敗しました。")
                        
    elif page == "提出＆Kvillage先生の添削":
        st.title("📝 解答提出 ＆ Kvillage先生の添削アシスタント")
        st.write("解き終わったプリント（書き込み済みのもの）を写真かPDFでアップロードしよう。Kvillage先生がチェックしてくれるよ！")
        
        try:
            api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        except:
            api_key = os.environ.get("GEMINI_API_KEY")
            
        if not api_key or api_key == "ここにコピーしたAPIキーを貼り付けます":
            st.error("システムエラー: 裏側のAI設定（APIキー）が完了していません。Kvillage先生に報告してください。")
            
        with st.expander("📸 【重要】Kvillage先生に正しく見てもらうための写真の撮り方", expanded=True):
            st.markdown("""
            AIのKvillage先生に正しく添削してもらうためには、**文字の大きさと写真の撮り方**がとても重要です！
            
            **✅ 推奨する書き方と撮り方（OK例）**
            *   **文字の大きさ**: 普通のノートの「1行」に1文字をしっかり書く普通のサイズ（小さすぎる文字は読めません！）
            *   **余白を取る**: 数式と数式の間は少し空白を空ける
            *   **1枚の目安**: ノート1ページ分を、スマホ画面いっぱいに大きく撮影する
            
            **❌ 避けてほしい書き方（NG例）**
            *   **見開き撮影**: ノートの右と左を「1枚の写真」に収めようと遠くから撮影したもの（文字が小さすぎて読めません）
            *   **ミミズ字**: 余白に小さく詰め込んだ計算メモ
            *   **影やブレ**: スマホの影で真っ暗になっていたり、ピンボケしている写真
            
            👉 **「スマホの画面上で拡大せずに読める文字」** を意識して撮影してください！
            """)
            
        st.subheader("1. ファイルのアップロード")
        uploaded_file = st.file_uploader("画像(JPG/PNG)またはPDFを選んでください", type=["png", "jpg", "jpeg", "pdf"])
        
        st.subheader("2. Kvillage先生へのお願い（モード選択）")
        mode = st.radio("どのように教えてほしいですか？", [
            "ヒントだけもらう（行き詰まった時 / チケット消費0枚）",
            "添削してもらう（解き終わった時 / チケット消費1枚）",
            "解答・解説をもらう（答え合わせしたい時 / チケット消費0枚）"
        ], index=1)
        
        if uploaded_file and api_key and api_key != "ここにコピーしたAPIキーを貼り付けます":
            images = []
            
            # 画像の抽出
            if uploaded_file.name.lower().endswith(".pdf"):
                images = convert_pdf_to_image(uploaded_file)
            else:
                img = Image.open(uploaded_file)
                images = [img]
                
            if not images:
                st.error("画像の読み込みに失敗しました。")
            elif len(images) > 4:
                st.error(f"⚠️ **画像枚数オーバー（現在 {len(images)}枚）**\n\n一度にまとめて送信・処理できるのは **最大 4枚 まで** です。ページ数を絞ってアップロードし直してください。")
            else:
                if len(images) > 1:
                    st.write(f"※全 **{len(images)}** ページを読み込みました。下の各タブから1ページずつ個別に送信するか、まとめて一括送信できます。")
                    
                    st.markdown("---")
                    st.subheader("📦 まとめて一括送信")
                    st.write("すべての画像を1回の送信としてまとめてAIに添削してもらいます。（※チケット消費量が通常の +1 枚になります）")
                    
                    required_tickets = 1 if "添削" in mode else 0
                    required_tickets += 1
                    
                    if st.button(f"すべてのページをまとめて送信する（チケット {required_tickets}枚 消費）", type="primary", use_container_width=True):
                        with st.spinner(f"Kvillage先生が全 {len(images)} ページをまとめて確認中です...（約20〜40秒かかります）"):
                            result_text = analyze_with_gemini(images, api_key, mode, student_name, student_id, is_batch=True)
                            st.session_state["batch_result"] = result_text

                    if "batch_result" in st.session_state:
                        result_text = st.session_state["batch_result"]
                        st.subheader("👨‍🏫 Kvillage先生からの返信 (全ページまとめ)")
                        st.markdown(result_text)
                        
                        safe_text = html.escape(result_text).replace("\\", "\\\\")
                        html_template = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>Kvillage先生からの解説 - まとめ</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
      MathJax = {{
        tex: {{ inlineMath: [['$', '$']], displayMath: [['$$', '$$']] }}
      }};
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
    <style>
        body {{ font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif; line-height: 1.6; padding: 40px; max-width: 800px; margin: 0 auto; color: #333; background: #fff; }}
        h1 {{ border-bottom: 2px solid #b21010; padding-bottom: 10px; font-size: 1.5em; }}
        .header-info {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 30px; border-left: 5px solid #b21010; }}
        @media print {{
            body {{ padding: 0; }}
            .no-print {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="no-print" style="background:#fff3f3; padding:15px; text-align:center; margin-bottom:30px; border:1px solid #ffcccc; border-radius:8px;">
        💡 <strong>印刷する場合:</strong> キーボードの「Ctrl + P」（Macは Cmd + P）を押してください。<br>
        この上部のメッセージは印刷時には自動的に消えます。
    </div>
    <div class="header-info">
        <strong>👨‍🏫 Kvillage先生からの解説</strong><br>
        生徒名: {student_name} さん<br>
        対象ページ: 全ページまとめ
    </div>
    <div id="source" style="display:none;">{safe_text}</div>
    <div id="content"></div>
    <script>
        const text = document.getElementById('source').textContent;
        document.getElementById('content').innerHTML = marked.parse(text);
        MathJax.typesetPromise();
    </script>
</body>
</html>"""
                        st.download_button(
                            label="📥 このまとめ解説を専用Webページ（印刷用）として保存",
                            data=html_template,
                            file_name=f"{student_name}さん_Kvillage先生の解説_まとめ.html",
                            mime="text/html",
                            key="dl_btn_batch",
                            type="secondary"
                        )
                    
                    st.markdown("---")
                    st.subheader("📄 個別送信（1ページずつ送る場合）")

                
                # タブの動的生成
                if len(images) == 1:
                    tabs = [st.container()]
                    tab_names = ["1ページ目"]
                else:
                    tab_names = [f"第{i+1}問（{i+1}ページ）" for i in range(len(images))]
                    tabs = st.tabs(tab_names)
                
                # 各タブごとの処理
                for i, tab in enumerate(tabs):
                    with tab:
                        # 画像が巨大にならないよう、画面を4分割して左の1/4に表示する
                        col_img, col_space = st.columns([1, 3])
                        with col_img:
                            # Streamlit標準のst.imageだとフルスクリーン機能が残るバグを回避するため、純粋なHTML画像として描画する
                            buffered = io.BytesIO()
                            images[i].save(buffered, format="PNG")
                            img_str = base64.b64encode(buffered.getvalue()).decode()
                            st.markdown(f'<img src="data:image/png;base64,{img_str}" style="width:100%; border-radius:8px; border:1px solid rgba(255,255,255,0.2);">', unsafe_allow_html=True)
                            st.caption(tab_names[i])
                        
                        # タブごとに独立した送信ボタンを配置（キーで一意にする）
                        btn_label = "このページをKvillage先生に送信する" if len(images) > 1 else "Kvillage先生に送信する"
                        if st.button(btn_label, key=f"btn_analyze_{i}", type="primary"):
                            with st.spinner(f"Kvillage先生が {tab_names[i]} を確認中です...（約10〜30秒かかります）"):
                                result_text = analyze_with_gemini(images[i], api_key, mode, student_name, student_id)
                                st.session_state[f"result_{i}"] = result_text

                        if f"result_{i}" in st.session_state:
                            result_text = st.session_state[f"result_{i}"]
                            st.subheader(f"👨‍🏫 Kvillage先生からの返信 ({tab_names[i]})")
                            st.markdown(result_text)
                            
                            # --- HTMLファイルとしてのダウンロード機能 ---
                            safe_text = html.escape(result_text).replace("\\", "\\\\")
                            html_template = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <title>Kvillage先生からの解説 - {tab_names[i]}</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
      MathJax = {{
        tex: {{ inlineMath: [['$', '$']], displayMath: [['$$', '$$']] }}
      }};
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
    <style>
        body {{ font-family: 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Hiragino Sans', Meiryo, sans-serif; line-height: 1.6; padding: 40px; max-width: 800px; margin: 0 auto; color: #333; background: #fff; }}
        h1 {{ border-bottom: 2px solid #b21010; padding-bottom: 10px; font-size: 1.5em; }}
        .header-info {{ background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 30px; border-left: 5px solid #b21010; }}
        @media print {{
            body {{ padding: 0; }}
            .no-print {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="no-print" style="background:#fff3f3; padding:15px; text-align:center; margin-bottom:30px; border:1px solid #ffcccc; border-radius:8px;">
        💡 <strong>印刷する場合:</strong> キーボードの「Ctrl + P」（Macは Cmd + P）を押してください。<br>
        この上部のメッセージは印刷時には自動的に消えます。
    </div>
    
    <div class="header-info">
        <strong>👨‍🏫 Kvillage先生からの解説</strong><br>
        生徒名: {student_name} さん<br>
        対象ページ: {tab_names[i]}
    </div>

    <div id="source" style="display:none;">{safe_text}</div>
    <div id="content"></div>
    
    <script>
        const text = document.getElementById('source').textContent;
        document.getElementById('content').innerHTML = marked.parse(text);
        MathJax.typesetPromise();
    </script>
</body>
</html>"""
                            
                            st.download_button(
                                label="📥 この解説を専用Webページ（印刷用）として保存",
                                data=html_template,
                                file_name=f"{student_name}さん_Kvillage先生の解説_{tab_names[i]}.html",
                                mime="text/html",
                                key=f"dl_btn_{i}",
                                type="secondary"
                            )

if __name__ == "__main__":
    main()
