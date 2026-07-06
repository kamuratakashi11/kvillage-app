import streamlit as st
import json
import os
import random
import fitz  # PyMuPDF
from PIL import Image
from datetime import datetime, timedelta
import re

from storage import (
    BASE_DIR, DB_PATH, IMG_DIR, USERS_PATH, HISTORY_PATH,
    STUDENTS_DATA_PATH, BG_IMG_PATH, db_error, load_json, save_json,
)
from student_state import (
    init_student_data, process_daily_login, get_level_info,
)
import gemini_service
import rpg_data
import rpg_ui

# 共通設定 (Kvillage先生仕様)
st.set_page_config(
    page_title="Kvillage先生の数学演習システム",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"  # 追加：サイドバーを最初から開いた状態に固定
)

import zipfile
import glob

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
       【修正】不要な上部メニューとサイドバー開閉機能を完全に非表示にする
       ------------------------------------------------------------------- */
    #MainMenu {{visibility: hidden;}}
    header {{visibility: hidden !important;}}
    [data-testid="stHeader"] {{display: none !important;}}
    [data-testid="stToolbar"] {{display: none !important;}}
    .stDeployButton {{display: none !important;}}
    footer {{visibility: hidden;}}
    
    /* サイドバー開閉ボタン（「＞」や「✕」アイコン）を完全に消去 */
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarHeader"] button,
    section[data-testid="stSidebar"] button[kind="header"] {{
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }}
    
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
            
            # --- 💡【追加】新規登録の受付状態チェック ---
            app_settings = load_json("app_settings.json", {"allow_registration": True})
            
            if not app_settings.get("allow_registration", True):
                st.warning("🙏 **現在、新規会員登録は締め切っています。**\n\n登録に関するお問い合わせはKvillage先生に直接ご連絡ください。")
            else:
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

def auto_tag_problem_with_ai(image_path, api_key):
    if not os.path.exists(image_path):
        return []

    try:
        prompt = """
        この数学の入試問題の画像を見て、以下の分野リストの中から、この問題に当てはまるものをすべて選び、JSON形式の配列（文字列のリスト）として出力してください。
        必ず以下のリストにある完全一致する文字列のみを使用し、その他の言葉は含めないでください。

        【分野リスト】
        "確率", "ベクトル", "数列", "微分・積分", "図形と方程式", "複素数平面", "極座標", "整数", "数と式", "三角関数", "指数・対数", "二次関数", "図形の性質", "場合の数", "極限", "その他", "数学Ⅲ"

        出力例:
        ["ベクトル", "数列"]
        """
        img = Image.open(image_path)
        # APIのトークン削減と高速化のためリサイズ
        img.thumbnail((1024, 1024))

        response = gemini_service.generate_with_fallback(
            api_key, [prompt, img], {"response_mime_type": "application/json"}
        )
        result = gemini_service.parse_json_lenient(response.text)
        if isinstance(result, list):
            # リストに含まれる無効な文字列を除外
            valid_tags = ["確率", "ベクトル", "数列", "微分・積分", "図形と方程式", "複素数平面", "極座標", "整数", "数と式", "三角関数", "指数・対数", "二次関数", "図形の性質", "場合の数", "極限", "その他", "数学Ⅲ"]
            filtered_result = [tag for tag in result if tag in valid_tags]
            return filtered_result if filtered_result else ["未分類"]
        return ["未分類"]
    except Exception as e:
        print(f"AI Tagging Error: {e}")
        return ["未分類"]

def main():
    set_custom_design()
    
    if db_error:
        st.error(f"🚨 **データベース接続エラー**\n\nデータベース（Firestore）に正しく接続できていません。以下のエラーメッセージをコピーして開発者にお知らせください。\n\n`{db_error}`")
    
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
        st.sidebar.markdown(f"**🎟️ バトル挑戦チケット**: {tickets} 枚")
        st.sidebar.markdown(f"**🔥 連続学習**: {streak} 日目")
        rpg_title = load_json(STUDENTS_DATA_PATH, {}).get(student_id, {}).get("title")
        if rpg_title:
            st.sidebar.markdown(f"**🏆 称号**: {rpg_title}")
        st.sidebar.markdown("---")

    # 権限に応じたメニューの切り替え
    if is_master:
        menu_options = ["⚙️ 先生専用管理ダッシュボード", "🏷️ 問題のタグ付け作業", "🗺️ 数学冒険マップ", "提出＆Kvillage先生に質問する"]
    else:
        menu_options = ["演習プリント作成", "復習プリント作成", "🗺️ 数学冒険マップ", "提出＆Kvillage先生に質問する"]

    # マップのフィールドリンク経由でページ全体が再読み込みされた場合、メニューの初期選択もマップに合わせる
    default_menu_index = 0
    if st.query_params.get("page") == "rpg_battle" and "🗺️ 数学冒険マップ" in menu_options:
        default_menu_index = menu_options.index("🗺️ 数学冒険マップ")

    page = st.sidebar.radio("メニュー", menu_options, index=default_menu_index)

    # ログアウトボタン
    if st.sidebar.button("ログアウト"):
        st.session_state.clear()
        st.query_params.clear()
        st.rerun()

    db = load_json(DB_PATH, [])
    history_db = load_json(HISTORY_PATH, {})
    student_history = history_db.get(student_id, [])

    rpg_field_from_url = st.query_params.get("field") if st.query_params.get("page") == "rpg_battle" else None

    if rpg_field_from_url:
        # マップ上のフィールドをクリックして遷移してきた場合は、サイドバーの選択に関わらずバトル画面を直接表示する
        try:
            rpg_api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        except Exception:
            rpg_api_key = os.environ.get("GEMINI_API_KEY")
        if not rpg_api_key or rpg_api_key == "ここにコピーしたAPIキーを貼り付けます":
            rpg_api_key = None
        rpg_ui.render_battle(rpg_field_from_url, student_id, student_name, rpg_api_key)
    elif page == "⚙️ 先生専用管理ダッシュボード":
        st.title("⚙️ Kvillage先生専用 管理ダッシュボード")
        
        # --- 💡【追加】システム設定（新規登録の受付切り替え） ---
        st.subheader("⚙️ システム設定")
        app_settings = load_json("app_settings.json", {"allow_registration": True})
        
        current_allow_reg = app_settings.get("allow_registration", True)
        new_allow_reg = st.toggle("✨ 新規会員登録の受付を許可する", value=current_allow_reg)
        
        if new_allow_reg != current_allow_reg:
            app_settings["allow_registration"] = new_allow_reg
            save_json("app_settings.json", app_settings)
            st.toast("システム設定を更新しました！", icon="✅")
            st.rerun()
            
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
            
            # --- 💡【追加】生徒アカウントの削除 ---
            st.markdown("---")
            st.subheader("🗑️ 生徒アカウントの削除")
            st.write("卒業した生徒や、間違って登録した生徒のデータをすべて削除します。（※一度消すと復元できません）")
            
            delete_target_pwd = st.selectbox("削除する生徒を選択", options=list(users.keys()), format_func=lambda x: f"{users[x]} (現在のパスワード: {x})", key="del_select")
            
            # 誤操作防止のための確認チェックボックス
            confirm_delete = st.checkbox("本当に削除してもよろしいですか？", key="del_check")
            
            if st.button("🚫 この生徒を完全に削除する", type="primary"):
                if not confirm_delete:
                    st.error("削除する場合は「本当に削除してもよろしいですか？」にチェックを入れてください。")
                else:
                    name = users[delete_target_pwd]
                    
                    # 1. usersから削除
                    del users[delete_target_pwd]
                    save_json(USERS_PATH, users)
                    
                    # 2. historyから削除
                    if delete_target_pwd in history_db:
                        del history_db[delete_target_pwd]
                        save_json(HISTORY_PATH, history_db)
                        
                    # 3. students_dataから削除
                    students_data = load_json(STUDENTS_DATA_PATH, {})
                    if delete_target_pwd in students_data:
                        del students_data[delete_target_pwd]
                        save_json(STUDENTS_DATA_PATH, students_data)
                        
                    st.success(f"「{name}」さんのアカウントとすべてのデータを完全に削除しました。")
                    st.rerun()

    elif page == "🏷️ 問題のタグ付け作業":
        st.title("🏷️ 問題のタグ付け（手動＆AI分類）作業")
        st.write("自動分類で「未分類」となった問題や、分類を修正したい問題にタグを付けます。")
        
        # --- 💡【追加】AIによる自動一括分類 ---
        st.markdown("---")
        st.subheader("🤖 AIによる自動一括タグ付け")
        st.write("有料版のGemini APIを使い、現在「未分類」となっている問題をすべて自動で判別しタグ付けします。（※1000問あたり約5.5円のコストがかかります）")
        
        unclassified_items = [item for item in db if "未分類" in item.get("topic", [])]
        BATCH_LIMIT = 100

        st.caption(f"💡 暴走・想定外の課金を防ぐため、1回のクリックで最大{BATCH_LIMIT}問までしか処理しません。続きをやりたい場合は、完了後にもう一度このボタンを押してください。")

        if st.button(f"🚀 未分類の問題（残り {len(unclassified_items)} 問 / 今回は最大{min(BATCH_LIMIT, len(unclassified_items))}問処理）をAIで自動分類する", type="primary", disabled=len(unclassified_items) == 0):
            gemini_key = st.secrets.get("GEMINI_API_KEY", "")
            if not gemini_key:
                st.error("APIキーが設定されていません。")
            else:
                items_to_process = unclassified_items[:BATCH_LIMIT]
                progress_bar = st.progress(0)
                status_text = st.empty()

                SAVE_EVERY = 20
                success_count = 0
                total_to_process = len(items_to_process)

                for idx, current_item in enumerate(items_to_process):
                    status_text.text(f"処理中 ({idx+1}/{total_to_process}): {current_item.get('university')} の問題をAIが確認中...")
                    img_path = os.path.join(IMG_DIR, current_item.get("image_file", ""))

                    new_tags = auto_tag_problem_with_ai(img_path, gemini_key)

                    if new_tags and new_tags != ["未分類"]:
                        # dbの該当アイテムを更新
                        for db_idx, db_item in enumerate(db):
                            if db_item.get("image_file") == current_item.get("image_file"):
                                db[db_idx]["topic"] = new_tags
                                success_count += 1
                                break

                    progress_bar.progress((idx + 1) / total_to_process)

                    # 途中経過をこまめに保存し、中断してもここまでの結果が失われないようにする
                    if (idx + 1) % SAVE_EVERY == 0:
                        save_json(DB_PATH, db)

                # 最後に必ず保存する
                save_json(DB_PATH, db)
                remaining = len(unclassified_items) - len(items_to_process)
                status_text.success(f"🎉 今回の分類が完了しました！ ({success_count}問を新しく分類しました / 残り{remaining}問。続ける場合はもう一度ボタンを押してください)")
                st.toast("AIによる自動分類が完了しました！", icon="🤖")
                st.rerun()

        # --- 💡【追加】RPGバトル用データ（難易度・正解）の自動生成 ---
        st.markdown("---")
        st.subheader("🎮 バトル用データの自動生成（難易度・正解）")
        st.write("有料版のGemini APIを使い、まだ「正解」が登録されていない問題にAIが実際に解答し、「難易度」と「正解」を自動生成します。RPGバトル機能で出題するために必要な作業です。（※証明問題の場合は、証明で示すべき結論と採点基準をAIがまとめて登録し、それをもとに手書きの証明を採点します）")

        not_enriched_items = [item for item in db if not item.get("correct_answer")]
        BATCH_LIMIT_BATTLE = 100

        st.caption(f"💡 暴走・想定外の課金を防ぐため、1回のクリックで最大{BATCH_LIMIT_BATTLE}問までしか処理しません。続きをやりたい場合は、完了後にもう一度このボタンを押してください。")

        if st.button(f"🚀 未対応の問題（残り {len(not_enriched_items)} 問 / 今回は最大{min(BATCH_LIMIT_BATTLE, len(not_enriched_items))}問処理）をAIに解かせる", type="primary", disabled=len(not_enriched_items) == 0, key="btn_enrich_battle"):
            gemini_key = st.secrets.get("GEMINI_API_KEY", "")
            if not gemini_key:
                st.error("APIキーが設定されていません。")
            else:
                items_to_process = not_enriched_items[:BATCH_LIMIT_BATTLE]
                progress_bar = st.progress(0)
                status_text = st.empty()
                error_box = st.empty()

                SAVE_EVERY = 20
                success_count = 0
                skipped_count = 0
                error_count = 0
                last_error = None
                total_to_process = len(items_to_process)

                for idx, current_item in enumerate(items_to_process):
                    status_text.text(f"処理中 ({idx+1}/{total_to_process}): {current_item.get('university')} の問題をAIが解答中... (成功: {success_count}件 / スキップ: {skipped_count}件 / エラー: {error_count}件)")
                    img_path = os.path.join(IMG_DIR, current_item.get("image_file", ""))

                    try:
                        result = gemini_service.enrich_problem_for_battle(img_path, gemini_key)
                    except Exception as e:
                        result = None
                        error_count += 1
                        last_error = str(e)
                        error_box.error(f"直近のエラー: {last_error}")
                    else:
                        if result is None:
                            skipped_count += 1

                    if result:
                        for db_idx, db_item in enumerate(db):
                            if db_item.get("image_file") == current_item.get("image_file"):
                                db[db_idx]["difficulty"] = result["difficulty"]
                                db[db_idx]["correct_answer"] = result["correct_answer"]
                                db[db_idx]["answer_type"] = result["answer_type"]
                                db[db_idx]["method_summary"] = result["method_summary"]
                                success_count += 1
                                break

                    progress_bar.progress((idx + 1) / total_to_process)

                    # 途中経過をこまめに保存し、中断してもここまでの結果が失われないようにする
                    if (idx + 1) % SAVE_EVERY == 0:
                        save_json(DB_PATH, db)

                # 最後に必ず保存する
                save_json(DB_PATH, db)
                remaining = len(not_enriched_items) - len(items_to_process)
                status_text.success(f"🎉 今回のバトル用データ生成が完了しました！ (成功: {success_count}問 / スキップ: {skipped_count}問 / エラー: {error_count}件 / 残り{remaining}問。続ける場合はもう一度ボタンを押してください)")
                if error_count > 0:
                    st.error(f"⚠️ {error_count}件でエラーが発生しました。直近のエラー内容: {last_error}")
                st.toast("バトル用データの生成が完了しました！", icon="🎮")
                st.rerun()

        # --- 💡【追加】先生用：単元演習検索のためのキーワード抽出 ---
        st.markdown("---")
        st.subheader("🔍 検索用キーワードの自動生成（単元演習作成用）")
        st.write("有料版のGemini APIを使い、まだキーワードが登録されていない問題にAIが具体的なテーマ（例: 最大値・最小値、軌跡など）を判定して登録します。解かせるわけではないので、タグ付けと同程度の低コストです。（※1000問あたり約5.5円のコストがかかります）")

        no_keyword_items = [item for item in db if not item.get("keywords")]
        BATCH_LIMIT_KEYWORDS = 100

        st.caption(f"💡 暴走・想定外の課金を防ぐため、1回のクリックで最大{BATCH_LIMIT_KEYWORDS}問までしか処理しません。続きをやりたい場合は、完了後にもう一度このボタンを押してください。")

        if st.button(f"🚀 未対応の問題（残り {len(no_keyword_items)} 問 / 今回は最大{min(BATCH_LIMIT_KEYWORDS, len(no_keyword_items))}問処理）にキーワードを自動生成する", type="primary", disabled=len(no_keyword_items) == 0, key="btn_gen_keywords"):
            gemini_key = st.secrets.get("GEMINI_API_KEY", "")
            if not gemini_key:
                st.error("APIキーが設定されていません。")
            else:
                items_to_process = no_keyword_items[:BATCH_LIMIT_KEYWORDS]
                progress_bar = st.progress(0)
                status_text = st.empty()
                error_box = st.empty()

                SAVE_EVERY = 20
                success_count = 0
                error_count = 0
                last_error = None
                total_to_process = len(items_to_process)

                for idx, current_item in enumerate(items_to_process):
                    status_text.text(f"処理中 ({idx+1}/{total_to_process}): {current_item.get('university')} の問題をAIが確認中... (成功: {success_count}件 / エラー: {error_count}件)")
                    img_path = os.path.join(IMG_DIR, current_item.get("image_file", ""))

                    try:
                        keywords = gemini_service.generate_search_keywords(img_path, gemini_key)
                    except Exception as e:
                        keywords = []
                        error_count += 1
                        last_error = str(e)
                        error_box.error(f"直近のエラー: {last_error}")

                    if keywords:
                        for db_idx, db_item in enumerate(db):
                            if db_item.get("image_file") == current_item.get("image_file"):
                                db[db_idx]["keywords"] = keywords
                                success_count += 1
                                break

                    progress_bar.progress((idx + 1) / total_to_process)

                    # 途中経過をこまめに保存し、中断してもここまでの結果が失われないようにする
                    if (idx + 1) % SAVE_EVERY == 0:
                        save_json(DB_PATH, db)

                # 最後に必ず保存する
                save_json(DB_PATH, db)
                remaining = len(no_keyword_items) - len(items_to_process)
                status_text.success(f"🎉 今回のキーワード生成が完了しました！ ({success_count}問に登録しました / 残り{remaining}問。続ける場合はもう一度ボタンを押してください)")
                if error_count > 0:
                    st.error(f"⚠️ {error_count}件でエラーが発生しました。直近のエラー内容: {last_error}")
                st.toast("キーワード生成が完了しました！", icon="🔍")
                st.rerun()

        # --- 💡【追加】生成したキーワードで問題を検索し、単元演習プリントを作成 ---
        st.markdown("---")
        st.subheader("📖 キーワードで単元演習プリントを作成")
        st.write("登録済みのキーワードでテーマ（例: 最大値・最小値、軌跡など）を検索し、大学を問わず同じテーマの問題だけを集めたプリントを作成できます。")

        all_keywords = sorted({kw for item in db for kw in item.get("keywords", [])})

        if not all_keywords:
            st.info("まだキーワードが登録された問題がありません。上のボタンでキーワードを自動生成してください。")
        else:
            selected_keywords = st.multiselect("検索するテーマ（キーワード）を選択（複数可）", all_keywords, key="keyword_search_select")

            if selected_keywords:
                matched_items = [item for item in db if any(kw in item.get("keywords", []) for kw in selected_keywords)]
                st.write(f"※該当する問題数: **{len(matched_items)}問**")

                if not matched_items:
                    st.warning("該当する問題が見つかりませんでした。")
                else:
                    max_num = len(matched_items)
                    num_q_kw = st.slider("プリントに含める問題数", min_value=1, max_value=max_num, value=min(10, max_num), key="keyword_search_num")

                    if st.button("📄 このテーマでプリントを作成する", type="primary", key="btn_gen_keyword_pdf"):
                        with st.spinner("PDFを生成中..."):
                            selected_items = random.sample(matched_items, num_q_kw)
                            out_doc = fitz.open()
                            for item in selected_items:
                                img_path = os.path.join(IMG_DIR, item.get("image_file", ""))
                                if os.path.exists(img_path):
                                    img_doc = fitz.open(img_path)
                                    pdf_bytes = img_doc.convert_to_pdf()
                                    img_pdf = fitz.open("pdf", pdf_bytes)
                                    out_doc.insert_pdf(img_pdf)
                            pdf_data = out_doc.write()

                        st.success(f"「{'、'.join(selected_keywords)}」の問題を {num_q_kw}問 集めたプリントを作成しました！")
                        st.download_button(
                            label="📥 PDFをダウンロード",
                            data=pdf_data,
                            file_name=f"単元演習_{'_'.join(selected_keywords)}.pdf",
                            mime="application/pdf",
                            key="dl_keyword_pdf"
                        )

        st.markdown("---")
        st.subheader("✍️ 個別での確認・修正")
        
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
            
            # --- 💡【追加】個別のAI自動判定ボタン ---
            if st.button("🤖 AIに判定させて自動保存し、次へ進む", type="secondary"):
                gemini_key = st.secrets.get("GEMINI_API_KEY", "")
                with st.spinner("AIが画像から分野を判定中..."):
                    suggested_tags = auto_tag_problem_with_ai(img_path, gemini_key)
                    if suggested_tags and suggested_tags != ["未分類"]:
                        # データベースを更新して次へ
                        for idx, item in enumerate(db):
                            if item.get("image_file") == current_item.get("image_file"):
                                db[idx]["topic"] = suggested_tags
                                break
                        save_json(DB_PATH, db)
                        st.session_state["tagging_index"] += 1
                        st.toast(f"AI判定: {', '.join(suggested_tags)}", icon="🤖")
                        st.rerun()
                    else:
                        st.error("AIによる判定ができませんでした（判定不能）。")
            
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
                        
    elif page == "🗺️ 数学冒険マップ":
        rpg_ui.render_map(student_id, student_name)

    elif page == "提出＆Kvillage先生に質問する":
        st.title("📝 解答提出 ＆ Kvillage先生に質問しよう")
        st.write("Geminiにそのまま貼り付けて使える専用プロンプトを作成します。自分のGeminiアプリを開いて、解いた問題の写真を直接添付し、このプロンプトを貼り付ければ、会話を続けながら気になることを何度でも質問できます！")

        with st.expander("📸 【重要】Geminiに正しく読み取ってもらうための写真の撮り方", expanded=True):
            st.markdown("""
            AIに正しく読み取ってもらうためには、**文字の大きさと写真の撮り方**がとても重要です！

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

        st.subheader("1. Kvillage先生へのお願い（モード選択）")
        mode_labels = {
            "hint": "ヒントだけもらう（行き詰まった時）",
            "correction": "添削してもらう（解き終わった時）",
            "answer": "解答・解説をもらう（答え合わせしたい時）",
        }
        mode_choice_label = st.radio("どのように教えてほしいですか？", list(mode_labels.values()), index=1)
        mode_key = next(k for k, v in mode_labels.items() if v == mode_choice_label)

        student_data = load_json(STUDENTS_DATA_PATH, {}).get(student_id, {})
        level = student_data.get("level", 1)
        streak = student_data.get("login_streak", 1)

        st.warning("⚠️ 学校のGoogleアカウントではGeminiが制限されているため、必ず個人のGoogleアカウントでログインして使ってね！")

        st.subheader("2. コピー用プロンプト")
        st.info("①下のプロンプトをコピー → ②Gemini (gemini.google.com) を開く → ③解いた問題の写真をGeminiに直接添付（このアプリへのアップロードは不要です） → ④プロンプトを貼り付けて送信 → ⑤気になる点はそのまま追加で質問できます！")
        prompt_text = gemini_service.generate_copy_prompt(mode_key, student_name, level, streak)
        rpg_ui.render_copy_prompt_box(prompt_text, key="submission")

        if mode_key == "correction":
            st.markdown("""💡 **添削が終わったら…**
Geminiから最後に出力される『【日付】〜【今後の学習方針】』の記録をコピーして、自分の分析ノートに貼り付けよう！データが溜まると専用の復習テストが作れるようになります。""")
            st.link_button("📋 自分の分析ノート（Google Docs）を開く", "https://docs.google.com/document/u/0/")

        with st.expander("📚 【マニュアル】NotebookLMで自分専用の復習テストを作る方法"):
            st.markdown("""**【初回のみ】NotebookLMとの連携設定**
まずはあなたの学習記録を読み込ませる初期設定を行います。最初の1回だけでOKです！

1. **NotebookLM**（ https://notebooklm.google.com/ ）を開き、必ず**個人のGoogleアカウント**でログインします。
2. 「新しいノートブック」を作成し、名前に「数学 弱点分析ノート」などと入力します。
3. 「ソースを追加」の画面が出るので、**「Google ドライブ」**を選びます。
4. Kvillageからデータを貼り付けた「自分の分析ノート（Google Docs）」を選択して追加します。
5. ノートブックの設定（右上の設定ボタン等）から、「カスタムのノートブックの概要を設定」を開き、以下の指示をコピーして貼り付け、保存します。

> `蓄積されたデータを分析し、私の『現在の弱点』『数学的な直観力を養うためのアドバイス』『弱点克服のための記述式テスト3問』を出力してください。`

---

**【週末のルーティン】テストの自動生成**
毎日の学習では、GeminiからDocsへデータを貼り付けるだけでOKです。NotebookLMを開くのは週末やテスト前です！

1. 自分が作ったNotebookLMの「数学 弱点分析ノート」を開きます。
2. 左側のソース一覧にある自分のGoogle Docsの横の**「同期（Sync）」ボタン**を押します。（これで最新の記録が読み込まれます！）
3. 下のチャット欄に、**「今週のテストを作って」**とだけ入力して送信します。
4. 丸暗記ではなく、本質的な理解ができているかを確認できる、あなただけのオリジナルテストが完成します！""")

if __name__ == "__main__":
    main()
