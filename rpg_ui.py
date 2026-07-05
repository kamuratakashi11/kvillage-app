import base64
import io
import os

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

import gemini_service
import rpg_data
from image_utils import convert_pdf_to_image
from storage import IMG_DIR
from student_state import consume_tickets, update_student_exp


def render_copy_prompt_box(prompt_text, key):
    """コピー用プロンプトをテキストエリア＋ワンクリックコピーボタンで表示する"""
    st.text_area("コピー用プロンプト（下のボタンでもコピーできます）", prompt_text, height=260, key=f"prompt_area_{key}")
    b64 = base64.b64encode(prompt_text.encode("utf-8")).decode("ascii")
    components.html(f"""
    <div style="font-family: sans-serif;">
      <button id="copy_btn_{key}" style="background:#b21010;color:#fff;border:none;border-radius:8px;padding:10px 18px;font-size:14px;cursor:pointer;">📋 プロンプトをコピーする</button>
      <span id="copied_msg_{key}" style="margin-left:10px;color:#4caf50;"></span>
    </div>
    <script>
      function b64DecodeUnicode_{key}(str) {{
        return decodeURIComponent(atob(str).split('').map(function(c) {{
          return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }}).join(''));
      }}
      document.getElementById("copy_btn_{key}").addEventListener("click", function() {{
        const text = b64DecodeUnicode_{key}("{b64}");
        navigator.clipboard.writeText(text).then(function() {{
          document.getElementById("copied_msg_{key}").innerText = "コピーしました！";
        }}, function() {{
          document.getElementById("copied_msg_{key}").innerText = "コピーできませんでした。上のテキストを手動で選択してコピーしてください。";
        }});
      }});
    </script>
    """, height=60)


def _map_tile_html(unit, unlocked, defeated):
    status_class = "unlocked" if unlocked else "locked"
    icon = unit["icon"] if unlocked else "🔒"
    badge = f'<div class="badge">撃破 {defeated}回</div>' if unlocked and defeated > 0 else ""
    return f"""
    <div class="tile {status_class}">
        <div class="icon">{icon}</div>
        <div class="name">{unit['name']}</div>
        {badge}
    </div>"""


def render_map(student_id, student_name):
    st.title("🗺️ 数学冒険マップ")
    st.write("フィールドを選んで敵と戦い、経験値を稼ごう！撃破すると隣のフィールドが解放されます。")

    student = rpg_data.load_student_with_rpg_fields(student_id)
    field_progress = student["field_progress"]
    boss_unlocked = rpg_data.is_boss_unlocked(field_progress)
    boss_defeated = student.get("boss_defeated", False)
    title = student.get("title")

    if title:
        st.success(f"🏆 称号「{title}」を獲得しています！")

    tiles_html = "".join(
        _map_tile_html(unit, rpg_data.is_unit_unlocked(unit, field_progress), field_progress.get(unit["id"], {}).get("defeated", 0))
        for unit in rpg_data.UNITS
    )

    boss = rpg_data.FINAL_BOSS
    if boss_defeated:
        tiles_html += f"""
        <div class="tile boss defeated">
            <div class="icon">{boss['icon']}</div>
            <div class="name">{boss['name']}</div>
            <div class="badge">撃破済み</div>
        </div>"""
    elif boss_unlocked:
        tiles_html += f"""
        <div class="tile boss unlocked">
            <div class="icon">{boss['icon']}</div>
            <div class="name">{boss['name']}</div>
        </div>"""
    else:
        tiles_html += """
        <div class="tile boss locked">
            <div class="icon">🔒</div>
            <div class="name">???</div>
        </div>"""

    map_html = f"""
    <html><head><style>
        body {{ margin:0; padding:0; background: transparent; font-family: 'Hiragino Kaku Gothic ProN','Hiragino Sans',Meiryo,sans-serif; }}
        .grid {{ display:flex; flex-wrap:wrap; gap:14px; padding:10px; }}
        .tile {{ width:120px; height:120px; border-radius:14px; display:flex; flex-direction:column; align-items:center; justify-content:center;
                 text-decoration:none; color:#fff; text-align:center; position:relative; box-shadow: 0 4px 10px rgba(0,0,0,0.4); }}
        .tile.unlocked {{ background: linear-gradient(145deg, #7a0d0d, #b21010); border: 2px solid #ff4b4b; }}
        .tile.locked {{ background: #2b2b2b; border: 2px solid #555; color:#888; }}
        .tile.boss {{ width:150px; height:150px; background: linear-gradient(145deg, #3a0303, #7a0d0d); border: 3px solid gold; }}
        .tile.boss.defeated {{ background:#333; border-color:#888; }}
        .icon {{ font-size:36px; }}
        .name {{ font-size:13px; margin-top:6px; font-weight:bold; }}
        .badge {{ font-size:10px; margin-top:4px; background:rgba(0,0,0,0.4); padding:2px 6px; border-radius:8px; }}
    </style></head>
    <body><div class="grid">{tiles_html}</div></body></html>
    """
    components.html(map_html, height=340, scrolling=True)

    st.markdown("---")
    st.caption("赤く輝くフィールドが挑戦できる場所です。下のメニューから選んで挑みましょう。")
    unlocked_units = [u for u in rpg_data.UNITS if rpg_data.is_unit_unlocked(u, field_progress)]
    options = {f"{u['icon']} {u['name']}（{u['enemy_name']}）": u["id"] for u in unlocked_units}
    if boss_unlocked and not boss_defeated:
        options[f"{boss['icon']} {boss['name']}（ラスボス）"] = "boss"

    if options:
        choice = st.selectbox("挑戦するフィールドを選ぶ", list(options.keys()))
        if st.button("このフィールドに挑む", type="primary"):
            st.query_params["page"] = "rpg_battle"
            st.query_params["field"] = options[choice]
            st.rerun()


def render_battle(unit_id, student_id, student_name, api_key):
    is_boss = (unit_id == "boss")
    if is_boss:
        unit = rpg_data.FINAL_BOSS
        enemy_max_hp = rpg_data.BOSS_ENEMY_MAX_HP
    else:
        unit = rpg_data.get_unit(unit_id)
        if not unit:
            st.error("フィールドが見つかりません。")
            return
        enemy_max_hp = rpg_data.ENEMY_MAX_HP

    unit_topic_name = unit["name"]
    enemy_label = unit.get("enemy_name", unit["name"])

    if st.button("🗺️ マップに戻る"):
        if "field" in st.query_params:
            del st.query_params["field"]
        st.rerun()

    st.title(f"⚔️ {enemy_label} とのバトル")

    hp_key = f"battle_enemy_hp_{unit_id}"
    player_hp_key = f"battle_player_hp_{unit_id}"
    problem_key = f"battle_problem_{unit_id}"
    result_key = f"battle_result_{unit_id}"
    review_key = f"battle_review_prompt_{unit_id}"

    if hp_key not in st.session_state:
        st.session_state[hp_key] = enemy_max_hp
    if player_hp_key not in st.session_state:
        st.session_state[player_hp_key] = rpg_data.PLAYER_MAX_HP

    enemy_hp = st.session_state[hp_key]
    player_hp = st.session_state[player_hp_key]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**{enemy_label}** HP: {max(0, enemy_hp)} / {enemy_max_hp}")
        st.progress(max(0.0, enemy_hp / enemy_max_hp))
    with col2:
        st.markdown(f"**{student_name}さん** HP: {max(0, player_hp)} / {rpg_data.PLAYER_MAX_HP}")
        st.progress(max(0.0, player_hp / rpg_data.PLAYER_MAX_HP))

    def _reset_battle_session():
        for k in (hp_key, player_hp_key, problem_key, result_key, review_key):
            st.session_state.pop(k, None)

    if enemy_hp <= 0:
        st.success(f"🎉 {enemy_label} を倒しました！")
        if is_boss:
            reward_flag = f"boss_reward_given_{student_id}"
            if not st.session_state.get(reward_flag, False):
                rpg_data.record_boss_win(student_id)
                st.session_state[reward_flag] = True
                st.balloons()
            st.success(f"🏆 称号「{rpg_data.FINAL_BOSS['title_reward']}」を獲得しました！")
        else:
            win_flag = f"win_recorded_{unit_id}"
            if not st.session_state.get(win_flag, False):
                rpg_data.record_unit_win(student_id, unit_id)
                st.session_state[win_flag] = True
        if st.button("🗺️ マップに戻ってさらに冒険する", type="primary"):
            _reset_battle_session()
            if "field" in st.query_params:
                del st.query_params["field"]
            st.rerun()
        return

    if player_hp <= 0:
        st.error("💥 やられてしまった...もう一度チケットを使って挑み直そう！")
        if st.button("🔄 最初からやり直す"):
            st.session_state[player_hp_key] = rpg_data.PLAYER_MAX_HP
            st.session_state[hp_key] = enemy_max_hp
            st.session_state.pop(problem_key, None)
            st.session_state.pop(result_key, None)
            st.session_state.pop(review_key, None)
            st.rerun()
        return

    st.markdown("---")

    if problem_key not in st.session_state:
        st.write("チケットを1枚使って問題を呼び出そう。")
        if st.button("⚔️ 問題を呼び出す（チケット1枚消費）", type="primary"):
            problem = rpg_data.pick_battle_problem(unit_topic_name)
            if problem is None:
                st.warning("この分野にはまだバトル用に準備された問題がありません。先生に「🏷️ 問題のタグ付け作業」ページで、バトル用データ（難易度・正解）を生成してもらってください。")
            elif not consume_tickets(student_id, 1):
                st.error("⚠️ チケットが足りません！明日ログインしてボーナスチケットを受け取ってください。")
            else:
                st.session_state[problem_key] = problem
                st.session_state.pop(result_key, None)
                st.rerun()
        return

    problem = st.session_state[problem_key]
    st.subheader(f"📜 出題（難易度: {problem.get('difficulty', '普通')} / 正解でEXP {problem['exp_value']}）")
    problem_img_path = os.path.join(IMG_DIR, problem["image_file"])
    if os.path.exists(problem_img_path):
        problem_img = Image.open(problem_img_path)
        buffered = io.BytesIO()
        problem_img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        st.markdown(f'<img src="data:image/png;base64,{img_str}" style="width:100%; max-width:600px; border-radius:8px; border:1px solid rgba(255,255,255,0.2);">', unsafe_allow_html=True)
    else:
        st.error("問題画像が見つかりませんでした。")

    st.subheader("✍️ 手書きで解いて、写真かPDFをアップロード")
    uploaded_file = st.file_uploader("画像(JPG/PNG)またはPDF", type=["png", "jpg", "jpeg", "pdf"], key=f"battle_upload_{unit_id}")

    if uploaded_file and result_key not in st.session_state:
        if uploaded_file.name.lower().endswith(".pdf"):
            images = convert_pdf_to_image(uploaded_file)
            image = images[0] if images else None
        else:
            image = Image.open(uploaded_file)

        if image is None:
            st.error("画像の読み込みに失敗しました。")
        elif st.button("🎯 採点する", type="primary"):
            if not api_key:
                st.error("システムエラー: 裏側のAI設定（APIキー）が完了していません。Kvillage先生に報告してください。")
            else:
                try:
                    with st.spinner("敵が解答を確認中..."):
                        result = gemini_service.judge_battle_answer(image, problem["correct_answer"], api_key)
                    st.session_state[result_key] = result

                    if result["is_correct"]:
                        damage = problem["exp_value"] * rpg_data.DAMAGE_PER_CORRECT_MULTIPLIER
                        st.session_state[hp_key] = max(0, enemy_hp - damage)
                        update_student_exp(student_id, problem["exp_value"])
                    else:
                        st.session_state[player_hp_key] = max(0, player_hp - rpg_data.DAMAGE_ON_WRONG)
                    st.rerun()
                except Exception as e:
                    st.error(gemini_service.describe_gemini_error(e))

    if result_key in st.session_state:
        result = st.session_state[result_key]
        if result["is_correct"]:
            st.success(f"⚔️ 正解！ {enemy_label} に会心の一撃！ (+{problem['exp_value']} EXP)")
        else:
            st.warning(f"😣 不正解...反撃を受けてしまった！ (読み取った解答: {result.get('extracted_answer') or '読み取れませんでした'})")

        if st.button("📖 くわしく添削してほしい"):
            st.session_state[review_key] = gemini_service.generate_battle_review_prompt(
                unit_topic_name, problem["correct_answer"]
            )

        if review_key in st.session_state:
            st.info("①下の「問題の画像を保存する」ボタンで問題画像を保存 → ②Gemini (gemini.google.com) を開く → ③保存した問題画像とあなたの解答の写真の両方を添付 → ④下のプロンプトをコピーして貼り付けて送信してください。")
            if os.path.exists(problem_img_path):
                with open(problem_img_path, "rb") as f:
                    st.download_button(
                        "📥 問題の画像を保存する",
                        data=f.read(),
                        file_name=problem["image_file"],
                        mime="image/png",
                        key=f"dl_problem_{unit_id}",
                    )
            render_copy_prompt_box(st.session_state[review_key], key=f"review_{unit_id}")

        if st.button("⚔️ 次の問題に挑む（チケット1枚消費）", type="primary"):
            st.session_state.pop(problem_key, None)
            st.session_state.pop(result_key, None)
            st.session_state.pop(review_key, None)
            st.rerun()
