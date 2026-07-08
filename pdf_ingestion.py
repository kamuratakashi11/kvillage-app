# -*- coding: utf-8 -*-
"""
pdf_ingestion.py
=================
模試などのPDFから大問ごとに画像を自動切り出し、「分野」「単元」「キーワード」を
自動タグ付けして db.json に登録するための取り込みパイプライン。

【重要】分野・単元の判定は既定でAPIを一切使わない「ルールベース（キーワード照合）」
で行います。数学の問題文には sin/cos/log/ベクトル/漸化式 のような分野特有の
語句・記号が高い確率で出現するため、これだけでも実用的な精度が出ます。
判定に自信が持てない問題だけ、Gemini APIに判定させるオプション（fallback）も
用意していますが、api_key を渡さなければ一切APIは呼ばれません＝無料です。

kvillage-app (app.py) の既存資産をそのまま利用する前提:
  - storage.load_json / save_json
  - gemini_service.generate_with_fallback / parse_json_lenient （AI fallbackを使う場合のみ）
  - DB_PATH, IMG_DIR (storage.py で定義済み)

使い方の全体像:
  1. detect_markers()        : PDFの指定ページ範囲から大問見出し（例:「X 3」）を検出
  2. render_problem_images() : 大問ごとにPDFページをクロップし、1枚のPNG画像として書き出す
                                （抽出済みテキストも一緒に返す）
  3. classify_problem_by_rules() : キーワード照合で「分野」「単元」「キーワード」を判定（無料）
  4. classify_problem_hybrid()   : ルールベースで自信が無い問題だけAI判定にフォールバック（任意）
  5. ingest_pdf()             : 上記を全部つなげて db.json に新しい問題として追記する

app.py 側では「⚙️ 先生専用管理ダッシュボード」に取り込み用のUIセクションを
追加するだけで、既存の演習プリント作成・復習プリント作成・単元検索の
仕組みにそのまま乗ります（本ファイル末尾の STREAMLIT_UI_SNIPPET 参照）。
"""

import os
import re
import uuid

import pdfplumber
from PIL import Image


# ---------------------------------------------------------------------------
# 分野・単元のタクソノミー（学習指導要領ベース。学校・塾の方針に応じて調整可）
# ---------------------------------------------------------------------------
SUBJECT_UNIT_MAP = {
    "数学I":   ["数と式", "集合と命題", "2次関数", "図形と計量", "データの分析"],
    "数学A":   ["場合の数と確率", "整数の性質", "図形の性質"],
    "数学II":  ["式と証明", "複素数と方程式", "図形と方程式", "三角関数",
                "指数関数・対数関数", "微分・積分の考え"],
    "数学B":   ["数列", "統計的な推測"],
    "数学C":   ["ベクトル", "平面上の曲線と複素数平面"],
    "数学III": ["極限", "微分法", "積分法"],
}

ALL_SUBJECTS = list(SUBJECT_UNIT_MAP.keys())

UNIT_TO_SUBJECT = {
    unit: subj for subj, units in SUBJECT_UNIT_MAP.items() for unit in units
}


# ---------------------------------------------------------------------------
# 0. ルールベース（キーワード照合）分類器 ―― APIを使わずに分野・単元を推定する
# ---------------------------------------------------------------------------
UNIT_KEYWORDS = {
    # ---- 数学I ----
    "数と式": [
        (r"因数分解", 2), (r"有理化", 3), (r"根号", 2), (r"絶対値", 1),
    ],
    "集合と命題": [
        (r"必要条件", 3), (r"十分条件", 3), (r"対偶", 3), (r"背理法", 3),
        (r"全体集合", 3), (r"共通部分", 2), (r"和集合", 2),
    ],
    "2次関数": [
        (r"2\s*次関数", 3), (r"頂点の座標", 2), (r"判別式", 2), (r"平方完成", 3),
        (r"放物線", 1),
    ],
    "図形と計量": [
        (r"正弦定理", 3), (r"余弦定理", 3), (r"三角比", 3), (r"扇形", 2),
    ],
    "データの分析": [
        (r"分散", 2), (r"標準偏差", 3), (r"相関係数", 3), (r"四分位", 3),
        (r"散布図", 3), (r"ヒストグラム", 3), (r"箱ひげ図", 3),
    ],
    # ---- 数学A ----
    "場合の数と確率": [
        (r"場合の数", 3), (r"順列", 2), (r"組合せ", 2), (r"確率", 2),
        (r"期待値", 2), (r"反復試行", 3), (r"条件付き確率", 3), (r"余事象", 2),
    ],
    "整数の性質": [
        (r"最大公約数", 3), (r"最小公倍数", 3), (r"合同式", 3), (r"n\s*進法", 3),
        (r"互いに素", 3), (r"不定方程式", 2), (r"ユークリッドの互除法", 3),
        (r"約数", 2), (r"倍数", 1), (r"自然数.{0,4}の組", 2),
    ],
    "図形の性質": [
        (r"メネラウス", 3), (r"チェバ", 3), (r"内心", 2), (r"外心", 2),
        (r"重心", 2), (r"方べきの定理", 3), (r"内接円", 2), (r"外接円", 2),
    ],
    # ---- 数学II ----
    "式と証明": [
        (r"恒等式", 3), (r"二項定理", 3), (r"相加平均と相乗平均", 3),
        (r"剰余の定理", 3), (r"因数定理", 3),
    ],
    "複素数と方程式": [
        (r"複素数(?!平面)", 2), (r"虚数", 2), (r"解と係数の関係", 3), (r"3\s*次方程式", 2),
    ],
    "図形と方程式": [
        (r"軌跡", 3), (r"領域を図示", 3), (r"円の方程式", 2), (r"点と直線の距離", 3),
        (r"内分点", 2), (r"外分点", 2), (r"円.{0,6}の中心", 2), (r"接線", 1),
        (r"半径", 1),
    ],
    "三角関数": [
        (r"加法定理", 3), (r"弧度法", 3), (r"三角関数の合成", 3), (r"2\s*倍角", 2),
        (r"半角の公式", 3), (r"sin", 1), (r"cos", 1), (r"tan", 1),
    ],
    "指数関数・対数関数": [
        (r"指数関数", 3), (r"対数関数", 3), (r"真数", 3), (r"常用対数", 3), (r"log", 1),
    ],
    "微分・積分の考え": [
        (r"導関数", 1), (r"接線の方程式", 2), (r"極大値", 2), (r"極小値", 2),
        (r"増減表", 2), (r"微分", 1), (r"積分", 1),
    ],
    # ---- 数学B ----
    "数列": [
        (r"漸化式", 3), (r"等差数列", 3), (r"等比数列", 3), (r"階差数列", 3),
        (r"一般項", 2), (r"数学的帰納法", 3), (r"Σ", 1),
    ],
    "統計的な推測": [
        (r"母平均", 3), (r"母集団", 3), (r"標本平均", 3), (r"信頼区間", 3),
        (r"仮説検定", 3), (r"正規分布", 3), (r"二項分布", 3),
    ],
    # ---- 数学C ----
    "ベクトル": [
        (r"ベクトル", 3), (r"内積", 3), (r"空間ベクトル", 3),
    ],
    "平面上の曲線と複素数平面": [
        (r"複素数平面", 3), (r"極方程式", 3), (r"媒介変数", 2), (r"楕円", 2),
        (r"双曲線", 2), (r"偏角", 2),
    ],
    # ---- 数学III ----
    "極限": [
        (r"数列の極限", 3), (r"無限級数", 3), (r"極限値", 2), (r"はさみうち", 3),
        (r"\blim\b", 1),
    ],
    "微分法": [
        (r"微分可能であるか", 3), (r"第\s*2\s*次導関数", 3), (r"陰関数", 3),
        (r"自然対数の底", 2),
    ],
    "積分法": [
        (r"定積分", 2), (r"不定積分", 2), (r"区分求積法", 3), (r"置換積分", 3),
        (r"部分積分", 3), (r"回転体の体積", 3),
    ],
}


def classify_problem_by_rules(text, allowed_subjects=None):
    """
    Gemini APIを使わず、抽出済みテキストのキーワード照合だけで
    「分野」「単元」「キーワード」を判定する（無料・高速）。

    text: その大問から抽出したテキスト全文
    allowed_subjects: この模試のコース(X/Y/Zなど)から出題されうる分野が
                       あらかじめ分かっている場合、候補をここで絞ると精度が上がる。
                       例: 数学Xの問題なら allowed_subjects=["数学I", "数学A"]

    戻り値: {"subject": str, "unit": [str,...], "keywords": [str,...],
             "confidence": float}
            何もヒットしなかった場合は confidence=0.0, subject="未分類"
    """
    unit_scores = {}
    matched_terms = {}

    for unit, patterns in UNIT_KEYWORDS.items():
        owner_subject = UNIT_TO_SUBJECT[unit]
        if allowed_subjects and owner_subject not in allowed_subjects:
            continue

        score = 0
        hits = []
        for pattern, weight in patterns:
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            if matches:
                score += weight * len(matches)
                hits.extend(matches)
        if score > 0:
            unit_scores[unit] = score
            matched_terms[unit] = hits

    if not unit_scores:
        return {"subject": "未分類", "unit": [], "keywords": [], "confidence": 0.0}

    subject_scores = {}
    for unit, score in unit_scores.items():
        subj = UNIT_TO_SUBJECT[unit]
        subject_scores[subj] = subject_scores.get(subj, 0) + score
    best_subject = max(subject_scores, key=subject_scores.get)

    same_subject_scores = {u: s for u, s in unit_scores.items() if UNIT_TO_SUBJECT[u] == best_subject}
    max_score = max(same_subject_scores.values())
    selected_units = [u for u, s in same_subject_scores.items() if s >= max_score * 0.6]
    selected_units.sort(key=lambda u: -same_subject_scores[u])

    keywords = []
    for u in selected_units:
        keywords.extend(matched_terms.get(u, []))
    keywords = list(dict.fromkeys(keywords))[:6]

    total_hits = sum(same_subject_scores.values())
    confidence = min(1.0, total_hits / 3.0)

    return {
        "subject": best_subject,
        "unit": selected_units,
        "keywords": keywords,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# 1. 大問マーカー検出（これまで検証済みのロジックをそのまま使用）
# ---------------------------------------------------------------------------
def _page_is_scanned(plumber_page, min_chars=3):
    text = plumber_page.extract_text() or ""
    return len(text.strip()) < min_chars


def detect_markers(pdf_path, start_page, end_page, prefix_letters,
                    x0_min, x0_max, height_min, height_tolerance=0.6,
                    box_pad=3.0, skip_scanned_pages=True):
    """
    大問見出しを検出する。戻り値は
    [{'page': int, 'top': float, 'label': str, 'page_height': float}, ...]
    （ページ→top順にソート済み）
    """
    markers = []
    skipped_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in range(start_page, end_page + 1):
            page = pdf.pages[p - 1]

            if skip_scanned_pages and _page_is_scanned(page):
                skipped_pages.append(p)
                continue

            words = page.extract_words()
            rects = page.rects
            for i, w in enumerate(words):
                if w['text'] not in prefix_letters:
                    continue
                if not (x0_min <= w['x0'] <= x0_max):
                    continue
                if w['height'] < height_min - height_tolerance:
                    continue
                if i + 1 >= len(words):
                    continue
                nxt = words[i + 1]
                if not re.fullmatch(r'[0-9０-９]{1,3}', nxt['text']):
                    continue
                if abs(nxt['top'] - w['top']) > 3:
                    continue

                box_top = w['top']
                for r in rects:
                    if abs(r['x0'] - w['x0']) > 5:
                        continue
                    rect_h = r['bottom'] - r['top']
                    if not (10 <= rect_h <= 25):
                        continue
                    if r['top'] - 2 <= w['top'] <= r['bottom'] + 2:
                        box_top = r['top']
                        break

                label_num = nxt['text'].translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                markers.append({
                    'page': p,
                    'top': max(box_top - box_pad, 0),
                    'label': w['text'] + label_num,
                    'page_height': page.height,
                })

    if skipped_pages:
        print(f"[detect_markers] スキャンページを除外: {skipped_pages}")

    markers.sort(key=lambda m: (m['page'], m['top']))
    return markers


# ---------------------------------------------------------------------------
# 1.5 大問見出しの自動検出（ページ範囲・見出し文字を先生が入力しなくても済むようにする）
# ---------------------------------------------------------------------------
# 「数学Ｘ　問題　（100分）」のように、科目名＋"問題"＋制限時間(N分)の組み合わせは
# 模試の問題冊子ページに特有の見出しで、解答・解説ページには出現しない。
# これを手がかりに、PDF全体から「問題冊子が始まるページ」だけを高速に絞り込む。
BOOKLET_HEADER_RE = re.compile(r'問\s*題.{0,15}分\s*）')

# 大問見出しの先頭文字（例:「X」）を推定するためのフォールバック用パターン。
# どの模試でも「大問1」は必ず存在するので、ページ冒頭付近で
# 「英字1文字 + (全角/半角の)1」という並びを探せば、その英字が見出し文字だと推定できる。
FIRST_DAIMON_RE = re.compile(r'([A-Zａ-ｚ])\s?[1１]\b')


def _find_booklet_start_pages(pdf_path):
    """
    PDF全体を高速にテキストスキャンし、「問題冊子が始まっていそうなページ」の
    候補を返す。pdfplumberの単語座標解析(_page_is_scannedやfont計測)より
    軽量な処理（テキスト抽出+正規表現のみ）なので、数百ページのPDFでも
    数十秒程度で終わる。

    戻り値: 候補ページ番号のリスト（重複あり得る・未ソートではない昇順）
    """
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    hits = []
    for i in range(len(reader.pages)):
        text = reader.pages[i].extract_text() or ""
        if BOOKLET_HEADER_RE.search(text):
            hits.append(i + 1)
    return hits


def _cluster_pages(pages, max_gap=3):
    """
    近接するページ番号（差がmax_gap以下）を1つのクラスタにまとめ、
    各クラスタの先頭ページのリストを返す。
    同じ問題冊子の見出しが複数ページに渡って(誤)検出された場合の重複を防ぐ。
    """
    if not pages:
        return []
    pages = sorted(set(pages))
    clusters = [[pages[0]]]
    for p in pages[1:]:
        if p - clusters[-1][-1] <= max_gap:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [c[0] for c in clusters]


def _guess_prefix_letter(plumber_page, min_abs_height=13.0, min_body_ratio=1.3):
    """
    そのページの中から大問見出しの先頭文字（例:"X"）を推定する。
    1) まずフォントサイズ・座標をもとに、本文より明確に大きい文字＋直後の数字、
       という組み合わせを探す（きれいなレイアウトのPDFで有効）。
    2) 見つからない場合（フォント計測が乱れているスキャン起因のページ等）は、
       ページ先頭付近のテキストから「英字+1」という並びを正規表現で探す
       フォールバックを使う（大問1は必ず存在するという前提を利用）。
    """
    words = plumber_page.extract_words()
    if words:
        heights = [w['height'] for w in words]
        from collections import Counter
        body_h = Counter([round(h, 1) for h in heights]).most_common(1)[0][0]
        threshold = max(body_h * min_body_ratio, min_abs_height)
        for i, w in enumerate(words):
            if w['height'] < threshold:
                continue
            if i + 1 >= len(words):
                continue
            nxt = words[i + 1]
            if re.fullmatch(r'[0-9０-９]{1,3}', nxt['text']) and abs(nxt['top'] - w['top']) <= 3:
                return w['text']

    # フォールバック: ページ冒頭のテキストから「英字+1」を正規表現で探す
    text = plumber_page.extract_text() or ""
    m = FIRST_DAIMON_RE.search(text[:400])
    if m:
        return m.group(1).upper()
    return None


def auto_detect_subject_configs(pdf_path, scan_start=1, scan_end=None):
    """
    PDF全体（または指定範囲）を自動スキャンし、先生がページ範囲・大問見出しの
    文字を一切指定しなくても subject_configs（ingest_pdf()にそのまま渡せる形）
    を生成する。

    手順:
      1. 「科目名＋問題＋(N分)」という、問題冊子ページに特有の見出しパターンで
         全ページを高速スキャンし、候補ページを絞り込む（解答・解説ページは
         このパターンを含まないため、ここで自然に除外される）。
      2. 近接する候補ページを1つの「問題冊子の開始点」としてクラスタリングする。
      3. 各開始点について、大問見出しの先頭文字（X/Y/Zなど）を推定する。
      4. 開始点を出現順に並べ、次の開始点の直前までをその科目の範囲とする。

    scan_start / scan_end: 全体は遅くて困る場合のみ範囲を絞るための引数
                            （通常は指定不要。省略時はPDF全体を対象にする）。

    戻り値: [
        {"start_page": int, "end_page": int, "letters": {prefix,},
         "label_prefix": f"{prefix}_"},
        ...
    ]  （開始ページ順にソート済み）
    候補が1つも見つからなかった場合は空リストを返す（＝手動設定が必要）。

    注意: 同じ模試が複数回分・複数編集（問題冊子版、解答一体版など）で
    まとまったPDFの場合、同じ大問が複数回検出されることがある。これは
    「取りこぼしよりは重複の方が安全（プレビューで消せる）」という考え方に
    基づく意図的な仕様。
    """
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if scan_end is None:
            scan_end = total_pages
        scan_end = min(scan_end, total_pages)

    raw_hits = [p for p in _find_booklet_start_pages(pdf_path) if scan_start <= p <= scan_end]
    if not raw_hits:
        return []

    start_pages = _cluster_pages(raw_hits, max_gap=3)

    with pdfplumber.open(pdf_path) as pdf:
        entries = []  # (start_page, prefix)
        for sp in start_pages:
            prefix = _guess_prefix_letter(pdf.pages[sp - 1])
            if prefix:
                entries.append((sp, prefix))

    if not entries:
        return []

    entries.sort(key=lambda e: e[0])
    MAX_BOOKLET_SPAN = 30  # 1科目の問題冊子が現実的に取りうる最大ページ数の目安
    subject_configs = []
    for idx, (sp, prefix) in enumerate(entries):
        if idx + 1 < len(entries):
            end_p = min(entries[idx + 1][0] - 1, sp + MAX_BOOKLET_SPAN)
        else:
            end_p = min(sp + 10, scan_end)  # 最後は計算用紙等を見込んで少し余分に含める
        subject_configs.append({
            "start_page": sp,
            "end_page": end_p,
            "letters": {prefix},
            "label_prefix": f"{prefix}_",
        })

    return subject_configs


INSTRUCTION_HEADER_RE = re.compile(r'^【.+?】')


def _is_instruction_block(text):
    first_line = text.strip().split("\n")[0].strip() if text.strip() else ""
    return bool(INSTRUCTION_HEADER_RE.match(first_line))


# ---------------------------------------------------------------------------
# 2. 大問ごとの画像化（fitzで直接クロップ）。抽出済みテキストも同時に返す。
# ---------------------------------------------------------------------------
def render_problem_images(pdf_path, markers, end_page, output_dir,
                           dpi=200, pad_to_full_page=True, file_prefix=""):
    """
    detect_markers() の結果をもとに、大問ごとに1枚のPNG画像を生成する。
    分野・単元判定に使うテキストも同時に抽出して返す。

    fitzの座標系はpdfplumberと同じく「原点は左上、yは下向きが正」なので、
    PDF版で必要だった座標変換(bottom-up⇔top-down)は不要になり、
    get_pixmap(clip=...) で直接その範囲だけラスタライズできる。

    戻り値: [{'label': str, 'image_path': str, 'image_file': str,
               'pages': [int, ...], 'text': str}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)
    import fitz  # PyMuPDF（既存 app.py と同じ依存。ここで遅延import）
    doc = fitz.open(pdf_path)
    plumber_pdf = pdfplumber.open(pdf_path)

    results = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    for idx, m in enumerate(markers):
        start_page, start_top = m['page'], m['top']
        page_height = m['page_height']

        if idx + 1 < len(markers):
            next_page, next_top = markers[idx + 1]['page'], markers[idx + 1]['top']
        else:
            next_page, next_top = end_page, None

        page_width = doc[start_page - 1].rect.width
        slices = []
        text_parts = []

        for pnum in range(start_page, next_page + 1):
            top = start_top if pnum == start_page else 0
            bottom = (next_top if (pnum == next_page and next_top is not None)
                      else page_height)

            plumber_page = plumber_pdf.pages[pnum - 1]
            if _page_is_scanned(plumber_page):
                print(f"[render_problem_images] {pnum}ページはスキャン画像のため除外")
                continue

            region_text = plumber_page.crop(
                (0, max(top, 0), plumber_page.width, min(bottom, page_height))
            ).extract_text() or ""

            if not region_text.strip():
                continue
            if _is_instruction_block(region_text):
                continue

            slices.append((pnum, top, bottom))
            text_parts.append(region_text)

        if not slices:
            continue

        problem_text = "\n".join(text_parts)

        if pad_to_full_page:
            canvas_h_pt = page_height * len(slices)
        else:
            canvas_h_pt = sum(b - t for _, t, b in slices)

        canvas_w_px = int(page_width * zoom)
        canvas_h_px = int(canvas_h_pt * zoom)
        canvas = Image.new("RGB", (canvas_w_px, canvas_h_px), "white")

        y_offset_px = 0
        used_pages = []
        for pnum, top, bottom in slices:
            used_pages.append(pnum)
            page = doc[pnum - 1]
            clip = fitz.Rect(0, top, page_width, bottom)
            pix = page.get_pixmap(matrix=mat, clip=clip)
            if pix.n >= 4:
                # アルファチャンネル付き（RGBA等）の場合、"RGB"としてframbytesするとズレるためRGBに変換する
                pix = fitz.Pixmap(fitz.csRGB, pix)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            canvas.paste(img, (0, y_offset_px))
            y_offset_px += int(page_height * zoom) if pad_to_full_page else img.height

        safe_label = re.sub(r'[^A-Za-z0-9_\-]', '_', m['label'])
        filename = f"{file_prefix}{safe_label}_{uuid.uuid4().hex[:8]}.png"
        out_path = os.path.join(output_dir, filename)
        canvas.save(out_path, "PNG")

        first_page, first_top, first_bottom = slices[0]
        results.append({
            'label': m['label'],
            'image_path': out_path,
            'image_file': filename,
            'pages': used_pages,
            'text': problem_text,
            # 計算用紙・解答用紙が後続ページに混入していた場合に、1ページ目だけを
            # 採用した画像へ差し替えられるよう、1ページ目単体の切り出し範囲も保持しておく
            'first_page': first_page,
            'first_page_top': first_top,
            'first_page_bottom': first_bottom,
        })

    plumber_pdf.close()
    doc.close()
    return results


def crop_single_slice_image(pdf_path, page_num, top, bottom, output_dir,
                             dpi=200, file_prefix="", label=""):
    """
    render_problem_images() が複数ページを1枚に結合した大問画像について、
    計算用紙・解答用紙の混入が疑われる場合に「1ページ目（page_num/top/bottom）」
    だけを切り出し直した新しい画像を生成する。

    戻り値: (image_path, image_file)
    """
    os.makedirs(output_dir, exist_ok=True)
    import fitz  # 遅延import

    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    page = doc[page_num - 1]
    page_width = page.rect.width
    clip = fitz.Rect(0, top, page_width, bottom)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    if pix.n >= 4:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()

    safe_label = re.sub(r'[^A-Za-z0-9_\-]', '_', label) if label else "trimmed"
    filename = f"{file_prefix}{safe_label}_p1only_{uuid.uuid4().hex[:8]}.png"
    out_path = os.path.join(output_dir, filename)
    img.save(out_path, "PNG")
    return out_path, filename


def get_pdf_page_count(pdf_path):
    """PDFの総ページ数を返す（UIでページ範囲の初期値を決める用）。"""
    from pypdf import PdfReader
    return len(PdfReader(pdf_path).pages)


# ---------------------------------------------------------------------------
# 2.5 「1ページ＝1問」形式のPDF（大問見出しが無い過去問集など）の取り込み
# ---------------------------------------------------------------------------
# detect_markers()は「X1」「X2」のような大問見出しの検出に依存しているため、
# そもそも見出しが無い（1ページに1問ずつ独立して収録されている）PDFでは
# 1件も検出できない。この場合は見出し検出を行わず、指定したページ範囲を
# 単純にページ単位で1問ずつ切り出す。
def render_pages_as_problems(pdf_path, start_page, end_page, output_dir,
                              dpi=200, file_prefix=""):
    """
    大問見出しの検出を行わず、start_page〜end_pageの各ページをそのまま
    1問1画像として切り出す。

    戻り値: [{'label': str, 'image_path': str, 'image_file': str,
              'pages': [int], 'text': str}, ...]
    """
    os.makedirs(output_dir, exist_ok=True)
    import fitz  # 遅延import
    doc = fitz.open(pdf_path)
    plumber_pdf = pdfplumber.open(pdf_path)

    results = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    for pnum in range(start_page, end_page + 1):
        plumber_page = plumber_pdf.pages[pnum - 1]
        page_text = plumber_page.extract_text() or ""

        page = doc[pnum - 1]
        pix = page.get_pixmap(matrix=mat)
        if pix.n >= 4:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        filename = f"{file_prefix}p{pnum}_{uuid.uuid4().hex[:8]}.png"
        out_path = os.path.join(output_dir, filename)
        img.save(out_path, "PNG")

        results.append({
            'label': f"p{pnum}",
            'image_path': out_path,
            'image_file': filename,
            'pages': [pnum],
            'text': page_text,
        })

    plumber_pdf.close()
    doc.close()
    return results


def ingest_pdf_one_problem_per_page(pdf_path, university, source_pdf_name, start_page, end_page,
                                     db, img_dir, category="入試", api_key=None,
                                     confidence_threshold=0.5, dry_run=False):
    """
    大問見出しが無い「1ページ＝1問」形式のPDF向けの取り込みオーケストレーター。
    detect_markers()を使わず、ページ単位でそのまま1問として登録する。

    api_key: Gemini APIキー。フォントのエンコードが壊れているなどの理由で
             ページからテキストが正しく抽出できないPDFでは、ルールベース判定
             （キーワード照合）が機能しないため、画像を直接見て判定するAI
             フォールバックの利用を推奨する。

    戻り値: 新規追加されたitem(dict)のリスト
    """
    images = render_pages_as_problems(
        pdf_path=pdf_path, start_page=start_page, end_page=end_page, output_dir=img_dir,
    )

    new_items = []
    for img_info in images:
        tags = classify_problem_hybrid(
            image_path=img_info["image_path"],
            text=img_info["text"],
            api_key=api_key,
            confidence_threshold=confidence_threshold,
        )
        item = {
            "image_file": img_info["image_file"],
            "category": category,
            "university": university,
            "source_pdf": source_pdf_name,
            "page": img_info["pages"][0],
            "daimon_label": img_info["label"],
            "subject": tags["subject"],
            "unit": tags["unit"],
            "keywords": tags["keywords"],
            "classify_method": tags["method"],
            "topic": tags["unit"] if tags["unit"] else ["未分類"],
        }
        new_items.append(item)

    if not dry_run:
        db.extend(new_items)

    return new_items


# ---------------------------------------------------------------------------
# 3. （任意）Gemini APIによる分類 ―― ルールベースで自信が無い場合のみ使う想定
# ---------------------------------------------------------------------------
def classify_problem_ai(image_path, api_key):
    """
    1問の画像を見て、分野(subject)・単元(unit, 複数可)・検索キーワードを
    Gemini に判定させる。api_key が必要（＝コストが発生する）。
    """
    subject_list_str = "\n".join(
        f'- {subj}: {"、".join(units)}' for subj, units in SUBJECT_UNIT_MAP.items()
    )
    prompt = f"""
この数学の入試問題の画像を見て、以下のルールに従ってJSON形式で分類してください。

【分野と単元のリスト】
{subject_list_str}

【判定ルール】
1. まずこの問題がどの「分野」に属するか1つ選んでください。
2. その分野の単元リストから該当する単元をすべて選んでください（複数可）。
3. 検索用の具体的なキーワードを2〜4個あげてください。

【出力形式】（このJSONのみを出力し、他の文章は含めないこと）
{{"subject": "数学II", "unit": ["三角関数"], "keywords": ["加法定理", "最大値・最小値"]}}
"""
    try:
        import gemini_service  # kvillage-app 既存モジュール（遅延import）
        img = Image.open(image_path)
        img.thumbnail((1024, 1024))

        response = gemini_service.generate_with_fallback(
            api_key, [prompt, img], {"response_mime_type": "application/json"}
        )
        result = gemini_service.parse_json_lenient(response.text)

        subject = result.get("subject") if isinstance(result, dict) else None
        if subject not in SUBJECT_UNIT_MAP:
            subject = "未分類"

        units = result.get("unit", []) if isinstance(result, dict) else []
        if not isinstance(units, list):
            units = [units] if units else []
        valid_units = SUBJECT_UNIT_MAP.get(subject, [])
        units = [u for u in units if u in valid_units]

        keywords = result.get("keywords", []) if isinstance(result, dict) else []
        if not isinstance(keywords, list):
            keywords = []

        return {"subject": subject, "unit": units, "keywords": keywords}
    except Exception as e:
        print(f"[classify_problem_ai] AI判定エラー: {e}")
        return {"subject": "未分類", "unit": [], "keywords": []}


def classify_problem_hybrid(image_path, text, api_key=None,
                             allowed_subjects=None, confidence_threshold=0.5):
    """
    まずルールベース（無料）で判定し、自信度が閾値未満の場合のみ
    api_key が渡されていれば Gemini APIにフォールバックする。
    api_key=None なら、自信度が低くてもAPIは一切呼ばず、ルールベースの
    結果をそのまま返す（完全無料モード）。

    戻り値: {"subject","unit","keywords","method"}
    method: "rule"（ルールベースのみ・高自信）/
            "rule_low_confidence"（ルールベースのみ・自信度低いがAPI未使用）/
            "ai"（APIにフォールバックした）
    """
    rule_result = classify_problem_by_rules(text, allowed_subjects=allowed_subjects)

    if rule_result["confidence"] >= confidence_threshold:
        return {
            "subject": rule_result["subject"],
            "unit": rule_result["unit"],
            "keywords": rule_result["keywords"],
            "method": "rule",
        }

    if api_key:
        ai_result = classify_problem_ai(image_path, api_key)
        ai_result["method"] = "ai"
        return ai_result

    return {
        "subject": rule_result["subject"],
        "unit": rule_result["unit"],
        "keywords": rule_result["keywords"],
        "method": "rule_low_confidence",
    }


# ---------------------------------------------------------------------------
# 4. 取り込みオーケストレーション（PDF -> 画像 -> 分野/単元判定 -> db.json追記）
# ---------------------------------------------------------------------------
def ingest_pdf(pdf_path, university, source_pdf_name, subject_configs,
               db, img_dir, category="模試", api_key=None, confidence_threshold=0.5, dry_run=False):
    """
    subject_configs: [
        {
            "start_page": 269, "end_page": 274, "letters": {"X"},
            "label_prefix": "数学X_",
            "allowed_subjects": ["数学I", "数学A"],  # このコースで出うる分野（任意・精度向上用）
        },
        ...
    ]
    db: 既存の db.json をロードしたリスト（呼び出し側で load_json(DB_PATH, []) しておく）
    category: この問題データの出題範囲区分（"教科書"/"問題集"/"模試"/"入試" のいずれか）。
              分野・単元の判定より前に、どの区分の問題として登録するかを表す。
    api_key: Gemini APIキー。None（既定）ならルールベースのみで判定し、APIは一切呼ばない＝無料。
             指定した場合のみ、ルールベースの自信度が低い問題だけAPIにフォールバックする。
    dry_run: True の場合、画像生成・判定のみ行い db には追記しない（プレビュー確認用）

    戻り値: 新規追加された item(dict) のリスト。各itemには、計算用紙・解答用紙の混入を
            検知して1ページ目だけに切り詰め直すための一時情報（"_"で始まるキー）が
            含まれる。db.jsonへの保存直前に strip_preview_fields() で取り除くこと。
    """
    new_items = []

    for cfg in subject_configs:
        markers = detect_markers(
            pdf_path=pdf_path,
            start_page=cfg["start_page"],
            end_page=cfg["end_page"],
            prefix_letters=cfg["letters"],
            x0_min=cfg.get("x0_min", 48.0),
            x0_max=cfg.get("x0_max", 51.0),
            height_min=cfg.get("height_min", 13.5),
        )

        images = render_problem_images(
            pdf_path=pdf_path,
            markers=markers,
            end_page=cfg["end_page"],
            output_dir=img_dir,
            file_prefix=cfg.get("label_prefix", ""),
        )

        allowed_subjects = cfg.get("allowed_subjects")

        for img_info in images:
            tags = classify_problem_hybrid(
                image_path=img_info["image_path"],
                text=img_info["text"],
                api_key=api_key,
                allowed_subjects=allowed_subjects,
                confidence_threshold=confidence_threshold,
            )

            item = {
                "image_file": img_info["image_file"],
                "category": category,
                "university": university,
                "source_pdf": source_pdf_name,
                "page": img_info["pages"][0],
                "daimon_label": img_info["label"],
                "subject": tags["subject"],
                "unit": tags["unit"],
                "keywords": tags["keywords"],
                "classify_method": tags["method"],
                "topic": tags["unit"] if tags["unit"] else ["未分類"],
                # プレビュー画面で「計算用紙・解答用紙の混入」を検知し、1ページ目だけを
                # 採用し直せるようにするための一時情報（db.json保存前に取り除くこと）
                "_pages": img_info["pages"],
                "_first_page": img_info["first_page"],
                "_first_page_top": img_info["first_page_top"],
                "_first_page_bottom": img_info["first_page_bottom"],
                "_label_prefix": cfg.get("label_prefix", ""),
            }
            new_items.append(item)

    if not dry_run:
        db.extend(new_items)

    return new_items


def strip_preview_fields(item):
    """プレビュー専用の一時情報（"_"で始まるキー）を取り除いた、db.json保存用のdictを返す"""
    return {k: v for k, v in item.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# 5. app.py「先生専用管理ダッシュボード」に追加するStreamlit UIの例
# ---------------------------------------------------------------------------
STREAMLIT_UI_SNIPPET = '''
st.markdown("---")
st.subheader("📥 模試PDFの自動取り込み・大問分割・タグ付け")
st.write("模試のPDFをアップロードするだけで、大問ごとに画像を切り出し、分野・単元・キーワードを自動判定してデータベースに登録します（既定ではAPIを使わない無料判定です）。ページ範囲や大問見出しの文字を指定する必要はありません。")

import pdf_ingestion

uploaded_pdf = st.file_uploader("模試PDFをアップロード", type=["pdf"], key="ingest_pdf_uploader")

if uploaded_pdf:
    ingest_category = st.selectbox(
        "出題範囲（どのダンジョン・分類の問題として登録するか）",
        ["模試", "教科書", "問題集", "入試"],
        index=0, key="ingest_category"
    )
    university_name = st.text_input("大学名・模試名（例: 2025ベネッセ模試）", key="ingest_univ")

    tmp_pdf_path = os.path.join(BASE_DIR, f"_tmp_ingest_{uploaded_pdf.name}")
    with open(tmp_pdf_path, "wb") as f:
        f.write(uploaded_pdf.getbuffer())

    use_ai_fallback = st.checkbox(
        "ルールベースで自信が持てない問題だけAIに判定させる（APIコストが発生します）",
        value=False, key="ingest_use_ai"
    )

    if st.button("🔍 大問を自動検出する", key="ingest_autodetect_btn", type="primary"):
        with st.spinner("PDF全体をスキャンして問題冊子を探しています（数百ページある場合は1分ほどかかります）..."):
            detected = pdf_ingestion.auto_detect_subject_configs(tmp_pdf_path)
        st.session_state["ingest_detected_configs"] = detected
        if not detected:
            st.warning(
                "大問の見出しを自動検出できませんでした。"
                "下の「手動で設定する」から開始/終了ページと見出し文字を直接指定してください。"
            )
        else:
            st.success(f"{len(detected)}件の問題冊子を検出しました。内容を確認してください。")

    subject_configs = []

    if st.session_state.get("ingest_detected_configs"):
        st.markdown("#### 検出結果の確認")
        st.caption("同じ問題が複数の版（問題冊子・解答一体版など）で重複して検出されることがあります。不要なものはチェックを外してください。")
        for i, cfg in enumerate(st.session_state["ingest_detected_configs"]):
            prefix = next(iter(cfg["letters"]))
            use_this = st.checkbox(
                f"見出し「{prefix}」: {cfg['start_page']}〜{cfg['end_page']}ページ",
                value=True, key=f"use_detected_{i}"
            )
            if use_this:
                subject_configs.append(cfg)

    with st.expander("自動検出がうまくいかない場合: 手動で設定する"):
        num_subjects = st.number_input("設定する科目数", min_value=0, max_value=5, value=0, key="ingest_num_subj")
        for i in range(int(num_subjects)):
            with st.expander(f"科目 {i+1}", expanded=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    sp = st.number_input("開始ページ", min_value=1, value=1, key=f"ingest_sp_{i}")
                with c2:
                    ep = st.number_input("終了ページ", min_value=1, value=1, key=f"ingest_ep_{i}")
                with c3:
                    letters = st.text_input("大問見出しの文字（例: X）", value="X", key=f"ingest_letters_{i}")
                subject_configs.append({
                    "start_page": int(sp), "end_page": int(ep),
                    "letters": set(letters), "label_prefix": f"{letters}_",
                })

    if subject_configs and st.button("📸 プレビュー生成（まだ保存しない）", key="ingest_preview_btn"):
        gemini_key = st.secrets.get("GEMINI_API_KEY", "") if use_ai_fallback else None
        db = load_json(DB_PATH, [])

        with st.spinner("大問を検出して画像化・分野/単元判定中..."):
            preview_items = pdf_ingestion.ingest_pdf(
                pdf_path=tmp_pdf_path,
                university=university_name,
                source_pdf_name=uploaded_pdf.name,
                subject_configs=subject_configs,
                db=db,
                img_dir=IMG_DIR,
                category=ingest_category,
                api_key=gemini_key,
                dry_run=True,
            )

        st.session_state["ingest_preview_items"] = preview_items
        rule_count = sum(1 for it in preview_items if it["classify_method"] == "rule")
        low_count = sum(1 for it in preview_items if it["classify_method"] == "rule_low_confidence")
        ai_count = sum(1 for it in preview_items if it["classify_method"] == "ai")
        st.success(
            f"{len(preview_items)}問を検出しました"
            f"（高信頼のルール判定: {rule_count}問 / 自信度低いがルールのまま: {low_count}問 / AIに回した: {ai_count}問）。"
            f"内容を確認してください。"
        )

    if st.session_state.get("ingest_preview_items"):
        st.markdown("#### 内容の確認")
        for item in st.session_state["ingest_preview_items"]:
            col1, col2 = st.columns([1, 2])
            with col1:
                st.image(os.path.join(IMG_DIR, item["image_file"]), use_container_width=True)
            with col2:
                st.write(f"**出題範囲**: {item['category']}")
                st.write(f"**大問**: {item['daimon_label']}")
                st.write(f"**分野**: {item['subject']}")
                st.write(f"**単元**: {', '.join(item['unit']) if item['unit'] else '(未判定)'}")
                st.write(f"**キーワード**: {', '.join(item['keywords'])}")
                st.caption(f"判定方法: {item['classify_method']}")
                if item["classify_method"] in ("rule_low_confidence",) or item["subject"] == "未分類":
                    new_subject = st.selectbox(
                        "分野を修正", pdf_ingestion.ALL_SUBJECTS,
                        index=pdf_ingestion.ALL_SUBJECTS.index(item["subject"]) if item["subject"] in pdf_ingestion.ALL_SUBJECTS else 0,
                        key=f"fix_subject_{item['image_file']}"
                    )
                    item["subject"] = new_subject
            st.markdown("---")

        if st.button("💾 この内容でデータベースに保存する", type="primary", key="ingest_commit_btn"):
            db = load_json(DB_PATH, [])
            db.extend(st.session_state["ingest_preview_items"])
            save_json(DB_PATH, db)
            st.session_state["ingest_preview_items"] = None
            st.session_state["ingest_detected_configs"] = None
            st.success("データベースに保存しました！")
            st.rerun()
'''
