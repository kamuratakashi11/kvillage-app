import base64
import io
import os

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

import gemini_service
import rpg_data
from image_utils import convert_pdf_to_image, image_files_to_pdf_bytes, build_labeled_pdf
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


def _map_tile_html(icon, name, status_class, badge=""):
    return f"""
    <div class="tile {status_class}">
        <div class="icon">{icon}</div>
        <div class="name">{name}</div>
        {badge}
    </div>"""


_MAP_STYLE = """
<style>
    body { margin:0; padding:0; background: transparent; font-family: 'Hiragino Kaku Gothic ProN','Hiragino Sans',Meiryo,sans-serif; }
    .grid { display:flex; flex-wrap:wrap; gap:14px; padding:10px; }
    .tile { width:120px; height:120px; border-radius:14px; display:flex; flex-direction:column; align-items:center; justify-content:center;
             text-decoration:none; color:#fff; text-align:center; position:relative; box-shadow: 0 4px 10px rgba(0,0,0,0.4); }
    .tile.unlocked { background: linear-gradient(145deg, #7a0d0d, #b21010); border: 2px solid #ff4b4b; }
    .tile.locked { background: #2b2b2b; border: 2px solid #555; color:#888; }
    .tile.boss { width:150px; height:150px; background: linear-gradient(145deg, #3a0303, #7a0d0d); border: 3px solid gold; }
    .tile.boss.defeated { background:#333; border-color:#888; }
    .icon { font-size:36px; }
    .name { font-size:13px; margin-top:6px; font-weight:bold; }
    .badge { font-size:10px; margin-top:4px; background:rgba(0,0,0,0.4); padding:2px 6px; border-radius:8px; }
</style>
"""


def render_map(student_id, student_name):
    st.title("🗺️ 数学冒険マップ")

    selected_category = st.query_params.get("dungeon")
    if selected_category not in rpg_data.CATEGORY_MAP:
        selected_category = None

    if not selected_category:
        _render_dungeon_selector(student_id)
    else:
        _render_dungeon_map(student_id, student_name, selected_category)


def _render_dungeon_selector(student_id):
    st.write("挑戦するダンジョン（出題範囲）を選ぼう！ダンジョンごとに撃破状況・レベル解放は別々に管理されます。")

    student = rpg_data.load_student_with_rpg_fields(student_id)

    tiles_html = ""
    for cat in rpg_data.CATEGORIES:
        dp = student["dungeon_progress"][cat["id"]]
        defeated_units = sum(1 for v in dp["field_progress"].values() if v.get("defeated", 0) > 0)
        total_units = len(cat["units"])
        badge = f'<div class="badge">{defeated_units}/{total_units} 分野撃破</div>'
        if dp["boss_defeated"]:
            badge = '<div class="badge">🏆 制覇済み</div>'
        tiles_html += _map_tile_html(cat["icon"], cat["name"], "unlocked", badge)

    map_html = f"<html><head>{_MAP_STYLE}</head><body><div class=\"grid\">{tiles_html}</div></body></html>"
    components.html(map_html, height=180, scrolling=True)

    st.markdown("---")
    options = {f"{cat['icon']} {cat['name']}": cat["id"] for cat in rpg_data.CATEGORIES}
    choice = st.selectbox("挑戦するダンジョンを選ぶ", list(options.keys()))
    if st.button("このダンジョンに入る", type="primary"):
        st.query_params["dungeon"] = options[choice]
        st.rerun()


def _render_dungeon_map(student_id, student_name, category_id):
    cat = rpg_data.CATEGORY_MAP[category_id]

    if st.button("⬅️ ダンジョン選択に戻る"):
        del st.query_params["dungeon"]
        st.rerun()

    st.subheader(f"{cat['icon']} {cat['name']}")
    st.write("フィールドを選んで敵と戦い、経験値を稼ごう！撃破すると隣のフィールドが解放されます。")

    student = rpg_data.load_student_with_rpg_fields(student_id)
    dp = student["dungeon_progress"][category_id]
    field_progress = dp["field_progress"]
    boss_unlocked = rpg_data.is_boss_unlocked(category_id, field_progress)
    boss_defeated = dp["boss_defeated"]
    title = dp["title"]

    if title:
        st.success(f"🏆 称号「{title}」を獲得しています！")

    tiles_html = "".join(
        _map_tile_html(
            unit["icon"] if rpg_data.is_unit_unlocked(category_id, unit, field_progress) else "🔒",
            unit["name"],
            "unlocked" if rpg_data.is_unit_unlocked(category_id, unit, field_progress) else "locked",
            f'<div class="badge">撃破 {field_progress.get(unit["id"], {}).get("defeated", 0)}回</div>'
            if rpg_data.is_unit_unlocked(category_id, unit, field_progress) and field_progress.get(unit["id"], {}).get("defeated", 0) > 0
            else "",
        )
        for unit in cat["units"]
    )

    boss = cat["final_boss"]
    if boss_defeated:
        tiles_html += _map_tile_html(boss["icon"], boss["name"], "boss defeated", '<div class="badge">撃破済み</div>')
    elif boss_unlocked:
        tiles_html += _map_tile_html(boss["icon"], boss["name"], "boss unlocked")
    else:
        tiles_html += _map_tile_html("🔒", "???", "boss locked")

    map_html = f"<html><head>{_MAP_STYLE}</head><body><div class=\"grid\">{tiles_html}</div></body></html>"
    components.html(map_html, height=340, scrolling=True)

    st.markdown("---")
    st.caption("赤く輝くフィールドが挑戦できる場所です。下のメニューから選んで挑みましょう。")
    unlocked_units = [u for u in cat["units"] if rpg_data.is_unit_unlocked(category_id, u, field_progress)]
    options = {f"{u['icon']} {u['name']}（{u['enemy_name']}）": u["id"] for u in unlocked_units}
    if boss_unlocked and not boss_defeated:
        options[f"{boss['icon']} {boss['name']}（ラスボス）"] = "boss"

    if options:
        choice = st.selectbox("挑戦するフィールドを選ぶ", list(options.keys()))
        if st.button("このフィールドに挑む", type="primary"):
            st.query_params["page"] = "rpg_battle"
            st.query_params["field"] = options[choice]
            st.rerun()


def render_battle(unit_id, student_id, student_name, api_key, category_id):
    cat = rpg_data.CATEGORY_MAP.get(category_id)
    if not cat:
        st.error("ダンジョンが見つかりません。")
        return

    is_boss = (unit_id == "boss")
    if is_boss:
        unit = cat["final_boss"]
        enemy_max_hp = rpg_data.BOSS_ENEMY_MAX_HP
    else:
        unit = rpg_data.get_unit(category_id, unit_id)
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

    st.title(f"{cat['icon']} {cat['name']} － ⚔️ {enemy_label} とのバトル")

    if st.session_state.get("_pending_storage_error"):
        st.error(st.session_state.pop("_pending_storage_error"))

    battle_key = f"{category_id}_{unit_id}"
    hp_key = f"battle_enemy_hp_{battle_key}"
    player_hp_key = f"battle_player_hp_{battle_key}"
    problems_key = f"battle_problems_{battle_key}"
    results_key = f"battle_results_{battle_key}"
    reviews_prefix = f"battle_review_{battle_key}_"

    if problems_key not in st.session_state:
        persisted = rpg_data.load_battle_state(student_id, battle_key)
        if persisted:
            st.session_state[hp_key] = persisted.get("enemy_hp", enemy_max_hp)
            st.session_state[player_hp_key] = persisted.get("player_hp", rpg_data.PLAYER_MAX_HP)
            st.session_state[problems_key] = persisted.get("problems", [])
            if persisted.get("results") is not None:
                st.session_state[results_key] = persisted["results"]

    if hp_key not in st.session_state:
        st.session_state[hp_key] = enemy_max_hp
    if player_hp_key not in st.session_state:
        st.session_state[player_hp_key] = rpg_data.PLAYER_MAX_HP

    enemy_hp = st.session_state[hp_key]
    player_hp = st.session_state[player_hp_key]

    def _persist_battle_state():
        rpg_data.save_battle_state(student_id, battle_key, {
            "problems": st.session_state.get(problems_key, []),
            "enemy_hp": st.session_state.get(hp_key),
            "player_hp": st.session_state.get(player_hp_key),
            "results": st.session_state.get(results_key),
        })

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**{enemy_label}** HP: {max(0, enemy_hp)} / {enemy_max_hp}")
        st.progress(max(0.0, enemy_hp / enemy_max_hp))
    with col2:
        st.markdown(f"**{student_name}さん** HP: {max(0, player_hp)} / {rpg_data.PLAYER_MAX_HP}")
        st.progress(max(0.0, player_hp / rpg_data.PLAYER_MAX_HP))

    def _reset_battle_session():
        keys_to_remove = [
            k for k in list(st.session_state.keys())
            if k in (hp_key, player_hp_key, problems_key, results_key) or k.startswith(reviews_prefix)
        ]
        for k in keys_to_remove:
            del st.session_state[k]
        rpg_data.clear_battle_state(student_id, battle_key)

    if enemy_hp <= 0:
        st.success(f"🎉 {enemy_label} を倒しました！")
        if is_boss:
            reward_flag = f"boss_reward_given_{student_id}_{battle_key}"
            if not st.session_state.get(reward_flag, False):
                rpg_data.record_boss_win(student_id, category_id)
                st.session_state[reward_flag] = True
                st.balloons()
            st.success(f"🏆 称号「{cat['final_boss']['title_reward']}」を獲得しました！")
        else:
            win_flag = f"win_recorded_{battle_key}"
            if not st.session_state.get(win_flag, False):
                rpg_data.record_unit_win(student_id, category_id, unit_id)
                st.session_state[win_flag] = True
        if st.button("🗺️ マップに戻ってさらに冒険する", type="primary"):
            _reset_battle_session()
            if "field" in st.query_params:
                del st.query_params["field"]
            st.rerun()
        return

    if player_hp <= 0:
        st.error("💥 やられてしまった...最初からやり直して挑み直そう！")
        if st.button("🔄 最初からやり直す"):
            _reset_battle_session()
            st.session_state[player_hp_key] = rpg_data.PLAYER_MAX_HP
            st.session_state[hp_key] = enemy_max_hp
            st.rerun()
        return

    st.markdown("---")

    if problems_key not in st.session_state:
        available = rpg_data.count_available_battle_problems(category_id, unit_topic_name)
        if available == 0:
            st.warning("この分野にはまだバトル用に準備された問題がありません。先生に「🏷️ 問題のタグ付け作業」ページで、バトル用データ（難易度・正解）を生成してもらってください。")
            return

        st.write(f"この分野で挑戦できる問題は最大 **{available}問** あります。まとめて何問挑戦するか選んで、問題を呼び出そう。")
        max_count = min(10, available)
        count = st.number_input("挑戦する問題数", min_value=1, max_value=max_count, value=min(3, max_count), step=1, key=f"battle_count_{battle_key}")

        if st.button("⚔️ 問題を呼び出す", type="primary"):
            st.session_state[problems_key] = rpg_data.pick_battle_problems(category_id, unit_topic_name, int(count))
            st.session_state.pop(results_key, None)
            _persist_battle_state()
            st.rerun()
        return

    problems = st.session_state[problems_key]
    n = len(problems)
    problem_img_paths = [os.path.join(IMG_DIR, p["image_file"]) for p in problems]

    st.subheader(f"📜 出題（全{n}問）")
    for i, (problem, img_path) in enumerate(zip(problems, problem_img_paths)):
        st.markdown(f"**第{i+1}問**（難易度: {problem.get('difficulty', '普通')} / 正解でEXP {problem['exp_value']}）")
        if os.path.exists(img_path):
            problem_img = Image.open(img_path)
            buffered = io.BytesIO()
            problem_img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            st.markdown(f'<img src="data:image/png;base64,{img_str}" style="width:100%; max-width:600px; border-radius:8px; border:1px solid rgba(255,255,255,0.2);">', unsafe_allow_html=True)
        else:
            st.error(f"第{i+1}問の画像が見つかりませんでした。")

    existing_paths = [p for p in problem_img_paths if os.path.exists(p)]
    if existing_paths:
        st.download_button(
            f"📥 全{n}問をまとめてPDFでダウンロード（GoodNotes等に貼り付け可）",
            data=image_files_to_pdf_bytes(existing_paths),
            file_name="battle_mondai.pdf",
            mime="application/pdf",
            key=f"dl_batch_pdf_{battle_key}",
        )
    st.caption("💡 印刷不要！ダウンロード後、共有メニューから「GoodNotesにコピー」を選べば、そのままApple Pencilで全問書き込めます。書き終わったら、ページ順そのままでPDFまたは画像でエクスポートして、下のアップロード欄に送信してください。")

    st.subheader("✍️ 手書きで解いて、写真かPDFをアップロード")
    uploaded_files = st.file_uploader(
        "解答のPDF（複数ページ可）または画像を、問題の順番通りにアップロードしてください",
        type=["png", "jpg", "jpeg", "pdf"],
        accept_multiple_files=True,
        key=f"battle_upload_{battle_key}",
    )

    if uploaded_files and results_key not in st.session_state:
        answer_images = []
        for uf in uploaded_files:
            if uf.name.lower().endswith(".pdf"):
                answer_images.extend(convert_pdf_to_image(uf))
            else:
                answer_images.append(Image.open(uf))

        if not answer_images:
            st.error("画像の読み込みに失敗しました。")
        else:
            if len(answer_images) < n:
                st.warning(f"アップロードされたページ数（{len(answer_images)}）が問題数（{n}）より少ないため、{len(answer_images)}問しか採点できません。")
            elif len(answer_images) > n:
                st.info(f"アップロードされたページ数（{len(answer_images)}）が問題数（{n}）より多いため、最初の{n}ページのみ採点に使います。")

            grade_count = min(n, len(answer_images))
            if st.button(f"🎯 まとめて採点する（チケット{grade_count}枚消費）", type="primary"):
                if not api_key:
                    st.error("システムエラー: 裏側のAI設定（APIキー）が完了していません。Kvillage先生に報告してください。")
                elif not consume_tickets(student_id, grade_count):
                    st.error("⚠️ チケットが足りません！明日ログインしてボーナスチケットを受け取ってください。")
                else:
                    pairs = list(zip(problems, answer_images))
                    try:
                        results = []
                        with st.spinner(f"敵が{len(pairs)}問の解答を確認中..."):
                            for problem, image in pairs:
                                results.append(gemini_service.judge_battle_answer(image, problem["correct_answer"], api_key, problem.get("answer_type", "value")))
                        st.session_state[results_key] = results

                        total_damage = sum(
                            p["exp_value"] * rpg_data.DAMAGE_PER_CORRECT_MULTIPLIER
                            for p, r in zip(problems, results) if r["is_correct"]
                        )
                        total_exp = sum(p["exp_value"] for p, r in zip(problems, results) if r["is_correct"])
                        total_player_damage = sum(rpg_data.DAMAGE_ON_WRONG for r in results if not r["is_correct"])

                        st.session_state[hp_key] = max(0, enemy_hp - total_damage)
                        st.session_state[player_hp_key] = max(0, player_hp - total_player_damage)
                        if total_exp > 0:
                            update_student_exp(student_id, total_exp)
                        _persist_battle_state()
                        st.rerun()
                    except Exception as e:
                        st.error(gemini_service.describe_gemini_error(e))

    if results_key in st.session_state:
        results = st.session_state[results_key]
        correct_count = sum(1 for r in results if r["is_correct"])
        st.subheader(f"📊 採点結果: {correct_count} / {len(results)} 問正解")

        for i, result in enumerate(results):
            problem = problems[i]
            if result["is_correct"]:
                st.success(f"第{i+1}問: ⚔️ 正解！ (+{problem['exp_value']} EXP)")
            else:
                st.warning(f"第{i+1}問: 😣 不正解 (読み取った解答: {result.get('extracted_answer') or '読み取れませんでした'})")

                review_flag_key = f"{reviews_prefix}{i}"
                if st.button(f"📖 第{i+1}問をくわしく添削してほしい", key=f"review_btn_{battle_key}_{i}"):
                    st.session_state[review_flag_key] = gemini_service.generate_battle_review_prompt(
                        unit_topic_name, problem["correct_answer"], problem.get("answer_type", "value")
                    )

                if review_flag_key in st.session_state:
                    st.info("①下の「問題の画像を保存する」ボタンで問題画像を保存 → ②Gemini (gemini.google.com) を開く → ③保存した問題画像とあなたの解答の写真の両方を添付 → ④下のプロンプトをコピーして貼り付けて送信してください。")
                    img_path = problem_img_paths[i]
                    if os.path.exists(img_path):
                        with open(img_path, "rb") as f:
                            st.download_button(
                                f"📥 第{i+1}問の画像を保存する",
                                data=f.read(),
                                file_name=problem["image_file"],
                                mime="image/png",
                                key=f"dl_problem_{battle_key}_{i}",
                            )
                    render_copy_prompt_box(st.session_state[review_flag_key], key=f"review_{battle_key}_{i}")

        st.markdown("---")
        st.subheader("🧠 NotebookLMで弱点を分析してもらおう")
        st.write("今回解いた問題と正誤結果をまとめたPDFを作りました。NotebookLMに読み込ませて、自分の弱点を分析してもらいましょう。")

        karute_entries = [
            (problem_img_paths[i], f"第{i+1}問（難易度: {problems[i].get('difficulty', '普通')}）: {'正解' if r['is_correct'] else '不正解'}")
            for i, r in enumerate(results)
            if os.path.exists(problem_img_paths[i])
        ]
        if karute_entries:
            st.download_button(
                "📥 学習カルテPDFをダウンロード",
                data=build_labeled_pdf(karute_entries),
                file_name="gakushu_karute.pdf",
                mime="application/pdf",
                key=f"dl_karute_{battle_key}",
            )
            st.info("①NotebookLM (notebooklm.google.com) を開く → ②「ソースを追加」でこのPDFをアップロード → ③下の質問をコピーして貼り付けて聞いてみよう")
            render_copy_prompt_box(
                gemini_service.generate_notebooklm_analysis_prompt(unit_topic_name, correct_count, len(results)),
                key=f"notebooklm_{battle_key}",
            )

        if st.button("⚔️ 次のバトルに挑む", type="primary"):
            _reset_battle_session()
            st.rerun()
