import base64
import io
import os

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

import gemini_service
import rpg_data
import theme
from image_utils import convert_pdf_to_image, image_files_to_pdf_bytes, build_labeled_pdf
from storage import IMG_DIR
from student_state import consume_tickets, update_student_exp


def render_copy_prompt_box(prompt_text, key):
    """コピー用プロンプトをテキストエリア＋ワンクリックコピーボタンで表示する"""
    st.text_area("コピー用プロンプト（下のボタンでもコピーできます）", prompt_text, height=260, key=f"prompt_area_{key}")
    b64 = base64.b64encode(prompt_text.encode("utf-8")).decode("ascii")
    c = theme.COLORS
    components.html(f"""
    <div style="font-family: sans-serif;">
      <button id="copy_btn_{key}" style="background:{c['accent']};color:#fff;border:none;border-radius:8px;padding:10px 18px;font-size:14px;cursor:pointer;">📋 プロンプトをコピーする</button>
      <span id="copied_msg_{key}" style="margin-left:10px;color:{c['success']};"></span>
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


def render_map(student_id, student_name):
    st.title("🗺️ 数学冒険マップ")

    selected_category = st.query_params.get("dungeon")
    if selected_category not in rpg_data.CATEGORY_MAP:
        selected_category = None

    if not selected_category:
        _render_dungeon_selector(student_id)
    else:
        _render_dungeon_map(student_id, student_name, selected_category)


def _dungeon_button_css(index):
    c = theme.COLORS
    container_selector = (
        f'div[data-testid="stElementContainer"]:has(div.dungeon-mk-{index}) '
        f'+ div[data-testid="stElementContainer"]'
    )
    button_selector = f'{container_selector} div[data-testid="stButton"] button'
    return f"""
    {container_selector} {{
        width: 100% !important;
    }}
    {container_selector} div[data-testid="stButton"] {{
        width: 100% !important;
    }}
    {button_selector} {{
        width: 100% !important;
        height: 100px !important;
        border-radius: 14px !important;
        background: {c['accent_bg']} !important;
        border: 2px solid {c['accent']} !important;
        font-size: 40px !important;
    }}
    """


def _render_dungeon_selector(student_id):
    st.write("挑戦するダンジョン（出題範囲）を選ぼう！ダンジョンごとに撃破状況・レベル解放は別々に管理されます。カードをクリックすると挑戦できます。")

    student = rpg_data.load_student_with_rpg_fields(student_id)

    clicked_dungeon_id = None
    button_css_rules = []
    cols = st.columns(len(rpg_data.CATEGORIES))
    for idx, (col, cat) in enumerate(zip(cols, rpg_data.CATEGORIES)):
        dp = student["dungeon_progress"][cat["id"]]
        defeated_units = sum(1 for v in dp["field_progress"].values() if v.get("defeated", 0) > 0)
        total_units = len(cat["units"])
        badge_text = f"{defeated_units}/{total_units} 分野撃破"
        if dp["boss_defeated"]:
            badge_text = "🏆 制覇済み"

        with col:
            st.markdown(f'<div class="dungeon-name">{cat["name"]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="dungeon-mk dungeon-mk-{idx}"></div>', unsafe_allow_html=True)
            if st.button(cat["icon"], key=f"dungeon_btn_{cat['id']}"):
                clicked_dungeon_id = cat["id"]
            st.markdown(f'<div class="dungeon-badge">{badge_text}</div>', unsafe_allow_html=True)
        button_css_rules.append(_dungeon_button_css(idx))

    st.markdown(
        f"""
        <style>
            {''.join(button_css_rules)}
            .dungeon-name {{ text-align:center; font-size:15px; font-weight:bold;
                             color:{theme.COLORS['text_primary']}; margin-bottom:6px; }}
            .dungeon-badge {{ text-align:center; font-size:12px; color:{theme.COLORS['text_secondary']};
                              margin-top:6px; }}
            div[data-testid="stButton"] {{ display:flex; justify-content:center; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    if clicked_dungeon_id:
        st.query_params["dungeon"] = clicked_dungeon_id
        st.rerun()


_SUGOROKU_COLUMNS = 4


def _sugoroku_node_style(state, is_boss):
    c = theme.COLORS
    if state == "cleared":
        return {"bg": c["success_bg"], "border": c["success"], "text": c["success_text"],
                "label": "撃破済み" if is_boss else "クリア"}
    if state == "current":
        return {"bg": c["amber_bg"], "border": c["amber"], "text": c["amber_text"], "label": "挑戦中"}
    return {"bg": c["accent_bg"], "border": c["accent"], "text": c["accent_text"], "label": "挑戦できます"}


def _sugoroku_button_css(index, style, is_current):
    """st.button直前に置いたマーカー要素との隣接関係を利用して、そのボタン1つだけを丸いマス目風に着色する"""
    ring = f"box-shadow:0 0 0 4px {style['bg']}, inset 0 0 0 1px {style['border']} !important;" if is_current else ""
    selector = (
        f'div[data-testid="stElementContainer"]:has(div.sg-mk-{index}) '
        f'+ div[data-testid="stElementContainer"] div[data-testid="stButton"] button'
    )
    return f"""
    {selector} {{
        border-radius: 50% !important;
        width: 64px !important;
        height: 64px !important;
        padding: 0 !important;
        background: {style['bg']} !important;
        border: 2px solid {style['border']} !important;
        color: {style['text']} !important;
        font-weight: bold !important;
        font-size: 20px !important;
        {ring}
    }}
    """


_SUGOROKU_LOCKED_CSS = f"""
div[data-testid="stElementContainer"]:has(div.sg-mk-locked)
+ div[data-testid="stElementContainer"] div[data-testid="stButton"] button {{
    border-radius: 50% !important;
    width: 64px !important;
    height: 64px !important;
    padding: 0 !important;
    background: {theme.COLORS['locked_bg']} !important;
    border: 2px dashed {theme.COLORS['locked']} !important;
    opacity: 0.75 !important;
}}
"""


def _render_sugoroku_map(category_id, cat, field_progress, boss_unlocked, boss_defeated):
    """すごろく状マップを、4列ボウストロフェドン（折り返し）でst.columns+st.buttonを使って描画する。
    戻り値: クリックされたユニットid（'boss'含む）。何もクリックされなければNone。"""
    c = theme.COLORS
    units = sorted(cat["units"], key=lambda u: u["order"])
    states = rpg_data.compute_unit_states(category_id, field_progress)

    nodes = [
        {"id": u["id"], "name": u["name"], "order": u["order"], "state": states[u["id"]], "is_boss": False}
        for u in units
    ]
    boss = cat["final_boss"]
    boss_state = "cleared" if boss_defeated else ("current" if boss_unlocked else "locked")
    nodes.append({"id": "boss", "name": boss["name"], "order": len(units) + 1, "state": boss_state, "is_boss": True})

    clicked_unit_id = None
    marker_index = 0
    button_css_rules = [_SUGOROKU_LOCKED_CSS]

    for row_start in range(0, len(nodes), _SUGOROKU_COLUMNS):
        row_nodes = nodes[row_start:row_start + _SUGOROKU_COLUMNS]
        row_index = row_start // _SUGOROKU_COLUMNS
        visual_row = row_nodes if row_index % 2 == 0 else list(reversed(row_nodes))

        cols = st.columns(len(visual_row))
        for col, node in zip(cols, visual_row):
            with col:
                st.markdown(f'<div class="sg-name">{node["name"]}</div>', unsafe_allow_html=True)
                state = node["state"]
                if state == "locked":
                    st.markdown('<div class="sg-mk sg-mk-locked"></div>', unsafe_allow_html=True)
                    st.button("🔒", key=f"sgbtn_{category_id}_{node['id']}", disabled=True)
                    status_text, status_color = "ロック中", c["text_muted"]
                else:
                    style = _sugoroku_node_style(state, node["is_boss"])
                    st.markdown(f'<div class="sg-mk sg-mk-{marker_index}"></div>', unsafe_allow_html=True)
                    button_css_rules.append(_sugoroku_button_css(marker_index, style, state == "current"))
                    label = "👑" if node["is_boss"] else str(node["order"])
                    if st.button(label, key=f"sgbtn_{category_id}_{node['id']}"):
                        clicked_unit_id = node["id"]
                    status_text, status_color = style["label"], style["text"]
                    marker_index += 1
                st.markdown(
                    f'<div class="sg-status" style="color:{status_color};">{status_text}</div>',
                    unsafe_allow_html=True,
                )

        if row_start + _SUGOROKU_COLUMNS < len(nodes) and len(row_nodes) == _SUGOROKU_COLUMNS:
            # 次の行の先頭ノードは、この行の折り返し位置（偶数行なら右端／奇数行なら左端）の真下に来る
            connector_cols = st.columns(len(visual_row))
            turn_index = len(visual_row) - 1 if row_index % 2 == 0 else 0
            with connector_cols[turn_index]:
                st.markdown('<div class="sg-arrow-down">↓</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <style>
            {''.join(button_css_rules)}
            .sg-name {{ text-align:center; font-size:13px; font-weight:bold; color:{c['text_primary']};
                        margin-bottom:6px; }}
            .sg-status {{ text-align:center; font-size:11px; margin-top:4px; }}
            .sg-arrow-down {{ text-align:center; font-size:20px; color:{c['border_strong']}; margin:2px 0; }}
            div[data-testid="stButton"] {{ display:flex; justify-content:center; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    return clicked_unit_id


def _render_dungeon_map(student_id, student_name, category_id):
    cat = rpg_data.CATEGORY_MAP[category_id]

    if st.button("⬅️ ダンジョン選択に戻る"):
        del st.query_params["dungeon"]
        st.rerun()

    st.subheader(f"{cat['icon']} {cat['name']}")
    st.write("マスを選んで敵と戦い、経験値を稼ごう！クリアすると次のマスが解放されます。")

    student = rpg_data.load_student_with_rpg_fields(student_id)
    dp = student["dungeon_progress"][category_id]
    field_progress = dp["field_progress"]
    boss_unlocked = rpg_data.is_boss_unlocked(category_id, field_progress)
    boss_defeated = dp["boss_defeated"]
    title = dp["title"]

    if title:
        st.success(f"🏆 称号「{title}」を獲得しています！")

    st.caption("色のついたマスをクリックすると挑戦できます。ロック中のマスは、手前のマスをクリアすると解放されます。")
    clicked_unit_id = _render_sugoroku_map(category_id, cat, field_progress, boss_unlocked, boss_defeated)

    if clicked_unit_id:
        st.query_params["page"] = "rpg_battle"
        st.query_params["dungeon"] = category_id
        st.query_params["field"] = clicked_unit_id
        st.rerun()


def _battle_unit_info(category_id, unit_id):
    """戦闘対象（通常フィールド or ボス）の情報を返す。存在しなければNoneを返す。"""
    cat = rpg_data.CATEGORY_MAP.get(category_id)
    if not cat:
        return None, None, None
    is_boss = (unit_id == "boss")
    if is_boss:
        unit = cat["final_boss"]
        enemy_max_hp = rpg_data.BOSS_ENEMY_MAX_HP
    else:
        unit = rpg_data.get_unit(category_id, unit_id)
        if not unit:
            return cat, None, None
        enemy_max_hp = rpg_data.ENEMY_MAX_HP
    return cat, unit, enemy_max_hp


def _pop_battle_setup_keys(battle_key):
    st.session_state.pop(f"battle_num_questions_{battle_key}", None)
    st.session_state.pop(f"battle_universities_{battle_key}", None)


def _render_battle_setup(category_id, unit_id, student_id):
    cat, unit, _ = _battle_unit_info(category_id, unit_id)
    if not cat:
        st.error("ダンジョンが見つかりません。")
        return
    if not unit:
        st.error("フィールドが見つかりません。")
        return

    battle_key = f"{category_id}_{unit_id}"
    unit_topic_name = unit["name"]
    enemy_label = unit.get("enemy_name", unit["name"])

    if st.button("🗺️ マップに戻る", key=f"setup_back_{battle_key}"):
        _pop_battle_setup_keys(battle_key)
        if "field" in st.query_params:
            del st.query_params["field"]
        st.rerun()

    st.title(f"{cat['icon']} {cat['name']} － ⚔️ {enemy_label} に挑む")

    total_available = rpg_data.count_available_battle_problems(category_id, unit_topic_name)
    if total_available == 0:
        st.warning("この分野にはまだバトル用に準備された問題がありません。先生に「🏷️ 問題のタグ付け作業」ページで、バトル用データ（難易度・正解）を生成してもらってください。")
        return

    universities = rpg_data.get_available_universities(category_id, unit_topic_name)
    selected_universities = []
    if len(universities) >= 2:
        label_to_name = {f"{name}（{n}問）": name for name, n in universities}
        chosen_labels = st.multiselect(
            "出題範囲を選ぼう（複数選択できます。大学・模試ごとに難易度が違うよ。何も選ばなければ全体から出題）",
            list(label_to_name.keys()),
            key=f"battle_univ_select_{battle_key}",
        )
        selected_universities = [label_to_name[label] for label in chosen_labels]

    available = rpg_data.count_available_battle_problems(category_id, unit_topic_name, universities=selected_universities or None)
    if selected_universities and available == 0:
        st.warning(f"選択した出題範囲（{'、'.join(selected_universities)}）の問題は、この分野ではまだ準備されていません。別の出題範囲を選ぶか、選択を解除してください。")
        return
    if selected_universities and available < 5:
        st.info(f"選択した出題範囲（{'、'.join(selected_universities)}）の問題は、この分野では現在 **{available}問** しかありません。出題内容が偏る可能性があります。")

    st.write(f"この分野で挑戦できる問題は最大 **{available}問** あります。何問挑戦するか選ぼう。")
    max_count = min(10, available)
    default_count = min(5, max_count)
    count = st.slider("出題数", min_value=1, max_value=max_count, value=default_count, key=f"battle_num_q_slider_{battle_key}")

    if st.button("⚔️ 挑戦をはじめる", type="primary", key=f"start_battle_{battle_key}"):
        st.session_state[f"battle_num_questions_{battle_key}"] = count
        st.session_state[f"battle_universities_{battle_key}"] = selected_universities
        st.rerun()


def render_battle_entry(unit_id, student_id, student_name, api_key, category_id):
    """マップのフィールドリンク経由の入口。出題数が未選択なら選択画面を、選択済みならバトル画面を表示する。"""
    battle_key = f"{category_id}_{unit_id}"
    problems_key = f"battle_problems_{battle_key}"
    num_q_key = f"battle_num_questions_{battle_key}"

    already_started = problems_key in st.session_state or bool(rpg_data.load_battle_state(student_id, battle_key))

    if num_q_key not in st.session_state and not already_started:
        _render_battle_setup(category_id, unit_id, student_id)
        return

    render_battle(unit_id, student_id, student_name, api_key, category_id, st.session_state.get(num_q_key))


def render_battle(unit_id, student_id, student_name, api_key, category_id, num_questions=None):
    cat, unit, enemy_max_hp = _battle_unit_info(category_id, unit_id)
    if not cat:
        st.error("ダンジョンが見つかりません。")
        return
    if not unit:
        st.error("フィールドが見つかりません。")
        return

    is_boss = (unit_id == "boss")
    unit_topic_name = unit["name"]
    enemy_label = unit.get("enemy_name", unit["name"])

    battle_key = f"{category_id}_{unit_id}"

    if st.button("🗺️ マップに戻る"):
        _pop_battle_setup_keys(battle_key)
        if "field" in st.query_params:
            del st.query_params["field"]
        st.rerun()

    st.title(f"{cat['icon']} {cat['name']} － ⚔️ {enemy_label} とのバトル")

    if st.session_state.get("_pending_storage_error"):
        st.error(st.session_state.pop("_pending_storage_error"))

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
        _pop_battle_setup_keys(battle_key)
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
        selected_universities = st.session_state.get(f"battle_universities_{battle_key}") or None
        available = rpg_data.count_available_battle_problems(category_id, unit_topic_name, universities=selected_universities)
        if available == 0:
            st.warning("この分野にはまだバトル用に準備された問題がありません。先生に「🏷️ 問題のタグ付け作業」ページで、バトル用データ（難易度・正解）を生成してもらってください。")
            return

        count = min(num_questions or 5, available)
        st.session_state[problems_key] = rpg_data.pick_battle_problems(category_id, unit_topic_name, count, universities=selected_universities)
        st.session_state.pop(results_key, None)
        _persist_battle_state()

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
