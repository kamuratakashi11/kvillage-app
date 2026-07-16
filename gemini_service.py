import json
import os
import re
import streamlit as st
import google.generativeai as genai
from PIL import Image

_VALID_JSON_ESCAPE_CHARS = set('"\\/bfnrtu')


def _escape_stray_backslashes(text):
    """数式（\\le, \\sqrt など）の中の生のバックスラッシュは、JSONの妥当なエスケープ
    （\\", \\\\, \\/, \\b, \\f, \\n, \\r, \\t, \\uXXXX）ではないため、そのままだと
    "Invalid \\escape" でJSON解析が失敗する。妥当なエスケープ以外のバックスラッシュを
    二重にして、文字列中のLaTeX記法をエスケープなしで出力してしまうモデルの応答を救済する。"""
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '\\' and i + 1 < n:
            nxt = text[i + 1]
            if nxt in _VALID_JSON_ESCAPE_CHARS:
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            out.append('\\\\')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _escape_control_chars_in_strings(text):
    """複数行の小論文本文・添削文など、長い自由記述をJSON文字列として生成させると、
    改行やタブが `\\n` `\\t` としてエスケープされず、生の制御文字のまま出力されることがある。
    JSON文字列リテラルの中に生の制御文字が入っていると "Invalid control character" で
    解析が失敗するため、文字列リテラルの内側にいる間だけ制御文字を正しいエスケープに変換する。"""
    out = []
    in_string = False
    escape_next = False
    for ch in text:
        if in_string:
            if escape_next:
                out.append(ch)
                escape_next = False
                continue
            if ch == '\\':
                out.append(ch)
                escape_next = True
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                continue
            if ch == '\n':
                out.append('\\n')
                continue
            if ch == '\r':
                out.append('\\r')
                continue
            if ch == '\t':
                out.append('\\t')
                continue
            if ord(ch) < 0x20:
                out.append(f'\\u{ord(ch):04x}')
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


def parse_json_lenient(text):
    """Geminiの応答をJSONとして解釈する。response_mime_type=application/jsonを指定していても、
    モデルが末尾に余分な閉じかっこを付け足したり、数式中のバックスラッシュ（\\leや\\sqrtなど）を
    エスケープせずに出力したり、複数行の自由記述の中に生の改行を混ぜてしまったりすることが
    稀にあるため、これらを許容してから解釈する。"""
    text = (text or "").strip()
    if not text:
        raise json.JSONDecodeError("空の応答です", text, 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj
    except json.JSONDecodeError:
        pass
    sanitized = _escape_stray_backslashes(text)
    try:
        obj, _ = json.JSONDecoder().raw_decode(sanitized)
        return obj
    except json.JSONDecodeError:
        pass
    sanitized2 = _escape_control_chars_in_strings(sanitized)
    obj, _ = json.JSONDecoder().raw_decode(sanitized2)
    return obj

@st.cache_data(ttl=3600, show_spinner=False)
def get_flash_model_name(api_key, exclude=()):
    """APIキーに紐づく利用可能な中で、最も安価なFlash系モデルの名前を1回だけ取得し、キャッシュする。
    exclude: 廃止（404）が判明したモデル名を除外して再選定する際に使う"""
    try:
        genai.configure(api_key=api_key)
        models = [
            m for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods and m.name not in exclude
        ]

        # gemini-1.5-flash は廃止済みのため、単に「flash」を含む最初のモデルを選ぶと
        # 「思考(thinking)」機能付きの新しい高額なFlashモデル（例: gemini-3.5-flash）を
        # 誤って選んでしまうことがある。最も安価なflash-liteを優先的に探す。
        preferred_substrings = ["flash-lite", "gemini-1.5-flash", "gemini-2.5-flash"]
        for pref in preferred_substrings:
            for m in models:
                if pref in m.name:
                    return m.name

        for m in models:
            if 'flash' in m.name:
                return m.name

        return "gemini-2.5-flash-lite"
    except Exception:
        return "gemini-2.5-flash-lite"

def _is_model_unavailable_error(e):
    msg = str(e).lower()
    return "404" in msg and ("no longer available" in msg or "not found" in msg)

# list_models()の動的な列挙は、APIキーによっては廃止済みモデルしか
# 見つからず、結果的に割高な通常のFlashモデルにフォールバックしてしまう
# ことがある。そのため、まず既知の安価なモデルIDを直接試す。
KNOWN_CHEAP_MODEL_CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite",
]

def generate_with_fallback(api_key, prompt_parts, generation_config, max_attempts=4):
    """既知の安価なモデルを直接優先的に試し、すべて失敗した場合のみ動的に候補を探して再試行する"""
    genai.configure(api_key=api_key)
    tried = set()
    last_error = None

    for _ in range(max_attempts):
        model_name = next((c for c in KNOWN_CHEAP_MODEL_CANDIDATES if c not in tried), None)
        if model_name is None:
            model_name = get_flash_model_name(api_key, exclude=tuple(tried))
            if model_name in tried:
                break

        tried.add(model_name)
        model = genai.GenerativeModel(model_name=model_name, generation_config=generation_config)
        try:
            return model.generate_content(prompt_parts)
        except Exception as e:
            if _is_model_unavailable_error(e):
                last_error = e
                continue
            raise
    raise last_error

def describe_gemini_error(e):
    """Gemini呼び出し失敗時のエラーメッセージを、生徒に分かりやすい文章に変換する"""
    error_msg = str(e).lower()
    if "429" in error_msg or "resource exhausted" in error_msg or "quota" in error_msg:
        if "generaterequestsperday" in error_msg or "perday" in error_msg or "limit: 200" in error_msg or "limit: 20" in error_msg:
            return f"🙏 **本日のAI利用枠（1日あたりの上限回数）を使い切ってしまいました！**\n\n明日の朝にリセットされるまでお待ちください。\n\n*(デバッグ用内部エラー: {e})*"

        wait_time = "1分ほど"
        match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_msg)
        if match:
            seconds = int(float(match.group(1)))
            wait_time = f"あと **{seconds}秒** ほど"

        return f"🙏 **現在Kvillage先生は他の生徒の質問に答えていて大忙しです！**\n\nごめんね、{wait_time}待ってからもう一度試してみてね！"
    return f"エラーが発生しました: {e}"

# --- コピペ用プロンプト（提出＆添削ページ） ---

FORMAT_RULES = r"""【数式の表示について】
- シグマ記号（∑）、極限（lim）、積分（∫）、分数などは、添え字や分母分子が文字の「上下」に配置されるようにしてください。
- 数式（特に方程式や式の変形）を書くときは、必ず改行して独立した行となる「ブロック数式（$$ で囲む形式）」で書いてください。
- 文中（インライン）に短い変数や数式（例: x や \alpha）を書く場合は、$x$ や $\alpha$ のように $ で囲んでください。バッククォート（`）は使わないでください。
- 複数行の数式を書く場合は、\begin{aligned} と \end{aligned} を使い、その外側を $$ で囲んでください。\begin{align*} は使わないでください。
- \begin{aligned} 環境内で等号（&=）を続ける場合は、1行に複数書かず \\ で改行してください。

【文章のレイアウト】
- 相手は高校生です。文章は1〜2文ごとに空行を入れ、余白をたっぷり取ってください。長い文章を1つの段落に詰め込まないでください。
"""

# --- RPGバトル用データの生成: 既存問題（画像）をAIに解かせて難易度・正解を登録する ---

PROBLEM_ENRICHMENT_PROMPT = """あなたは高校数学の教師です。添付された入試問題の画像を見て、この問題を実際に解いてください。

まず、この問題が「数値や式など、最終的な答えを一つ求める問題（value）」か「軌跡・不等式・恒等式の証明など、論理を積み重ねて示す証明問題（proof）」かを判断してください。

以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{
  "answer_type": "value または proof のいずれか",
  "difficulty": "易しい・普通・難しい のいずれか",
  "correct_answer": "answer_typeがvalueの場合は、この問題の最終的な答え（数値または簡潔な式）。proofの場合は、採点者が生徒の証明の正しさを判定できるように「示すべき結論」と「使うべき主要な論法・着眼点」を2〜3文で簡潔にまとめること。",
  "method_summary": "この問題を解くために主に使った考え方・公式・分野を1文で簡潔に述べてください（例: 微分して増減表を書き、極値を求める／余弦定理を使って辺の長さを求める）"
}
"""

def enrich_problem_for_battle(image_path, api_key):
    """既存の問題画像をAIに解かせ、RPGバトルで使う難易度・正解（または証明問題の採点基準）を生成する。画像から何も判定できない場合はNoneを返す。"""
    if not os.path.exists(image_path):
        return None

    img = Image.open(image_path)
    img.thumbnail((1024, 1024))

    response = generate_with_fallback(
        api_key, [PROBLEM_ENRICHMENT_PROMPT, img], {"response_mime_type": "application/json"}
    )
    try:
        data = parse_json_lenient(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = (response.text or "")[:200]
        raise RuntimeError(f"Geminiの応答がJSONとして解釈できませんでした: {e} / 応答内容: {snippet!r}") from e

    correct_answer = str(data.get("correct_answer", "")).strip()
    if not correct_answer:
        return None

    answer_type = data.get("answer_type") if data.get("answer_type") in ("value", "proof") else "value"

    return {
        "difficulty": data.get("difficulty", "普通"),
        "correct_answer": correct_answer,
        "answer_type": answer_type,
        "method_summary": str(data.get("method_summary", "")).strip(),
    }

# --- 先生用: 単元演習作成のための検索キーワード抽出（解かせずに画像だけで判定するため安価） ---

SEARCH_KEYWORD_PROMPT = """あなたは高校数学の教師です。添付された入試問題の画像を見て、この問題の内容を表す具体的なキーワードを3〜5個、日本語で挙げてください。

【キーワードの例】
最大値・最小値、軌跡、反復試行の確率、漸化式、内積、面積、通過領域、接線、極限の計算、恒等式の証明 など

「数と式」「二次関数」のような大きな分野名ではなく、授業で単元演習を作る先生が検索しやすい、もっと具体的な出題テーマ・設定を表す言葉にしてください。

以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{
  "keywords": ["キーワード1", "キーワード2", ...]
}
"""

def generate_search_keywords(image_path, api_key):
    """問題画像から、先生が単元演習を検索しやすい具体的なキーワードを抽出する（解かせないため安価）"""
    if not os.path.exists(image_path):
        return []

    img = Image.open(image_path)
    img.thumbnail((1024, 1024))

    response = generate_with_fallback(
        api_key, [SEARCH_KEYWORD_PROMPT, img], {"response_mime_type": "application/json"}
    )
    try:
        data = parse_json_lenient(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = (response.text or "")[:200]
        raise RuntimeError(f"Geminiの応答がJSONとして解釈できませんでした: {e} / 応答内容: {snippet!r}") from e

    keywords = data.get("keywords", [])
    if not isinstance(keywords, list):
        return []
    return [str(k).strip() for k in keywords if str(k).strip()]

# --- RPGバトル: 手書き解答の採点（正誤判定のみ） ---

JUDGE_PROMPT_TEMPLATE_VALUE = """あなたは高校数学の採点者です。添付された画像は、生徒が手書きで解いた数学の解答です。

【この問題の正解】
{correct_answer}

画像を読み取り、次の2点を両方満たす場合のみ正解にしてください。
1. 生徒の最終的な解答が上記の正解と一致している（同値な式・数値を含む）
2. そこに至るまでの途中式・論理展開に明らかな誤り（計算ミス、公式の誤用、符号ミスなど）がない
誤った計算や誤った考え方をしているのに、たまたま最終的な数値・式だけが正解と一致している場合は不正解にしてください。途中式が省略されている場合は、書かれている範囲で明らかな矛盾がなければ正解として構いません。
以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{{
  "is_correct": 正解ならtrue、不正解や白紙ならfalseの真偽値,
  "extracted_answer": "画像から読み取れた生徒の最終解答（読み取れない場合は空文字）"
}}
"""

JUDGE_PROMPT_TEMPLATE_PROOF = """あなたは高校数学の採点者です。添付された画像は、生徒が手書きで書いた証明・論証の解答です。

【この証明で示すべきこと・採点基準】
{correct_answer}

画像を読み取り、生徒の証明が論理の飛躍や誤りなく上記の結論を正しく導けているかを判定してください。模範解答と異なる方針でも、論理が正しく完結していれば正解としてください。
以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{{
  "is_correct": 論理的に正しく証明が完結していればtrue、論理の誤りや未完成、白紙ならfalseの真偽値,
  "extracted_answer": "生徒が書いた証明の要旨を1文で簡潔にまとめたもの（読み取れない場合は空文字）"
}}
"""

def judge_battle_answer(image, correct_answer, api_key, answer_type="value"):
    template = JUDGE_PROMPT_TEMPLATE_PROOF if answer_type == "proof" else JUDGE_PROMPT_TEMPLATE_VALUE
    prompt = template.format(correct_answer=correct_answer)
    response = generate_with_fallback(
        api_key, [prompt, image], {"response_mime_type": "application/json"}
    )
    data = parse_json_lenient(response.text)
    return {
        "is_correct": bool(data.get("is_correct", False)),
        "extracted_answer": data.get("extracted_answer", ""),
    }

# --- RPGバトル: くわしい添削（Gemini APIを直接呼び出し、分析ノートDocsへの追記用の学習記録も生成する） ---

MISMATCH_MARKER = "[NO_MATCH]"

def generate_battle_review_and_record(unit_name, correct_answer, problem_image, answer_image, api_key, answer_type="value"):
    """RPGバトルで間違えた問題について、①問題画像 と ②生徒の解答画像 の2枚をGeminiに渡し、
    くわしい添削の対話文と、分析ノートDocs追記用の構造化された学習記録（【単元】〜【今後の学習方針】）を
    まとめて生成する。戻り値: Geminiの応答テキスト全文（対話文＋末尾の学習記録）。
    解答画像が問題に対応していないとGeminiが判断した場合は、応答の先頭にMISMATCH_MARKERが付く
    （呼び出し側はこれを見て、分析ノートへの保存をスキップすること）。"""
    answer_label = "採点基準（証明で示すべきこと）" if answer_type == "proof" else "模範解答（最終的な答え）"
    prompt = f"""# 役割（Role）
あなたは優秀で、受験本番を見据えて生徒を鍛える、指導に妥協しない高校数学教師「Kvillage先生」です。

# 基本タスク（Task）
生徒はRPG風の数学学習アプリで、「{unit_name}」分野のバトル問題に挑戦しました。
このメッセージには、①解いた問題の画像 と ②生徒が手書きで解いた解答の画像、の2枚が添付されています。
まずその両方の画像を読み取ってください。

【{answer_label}】
{correct_answer}

0. **対応関係の確認（最優先・必須）**: まず、②の解答画像が、①の問題に対する解答として書かれたものかどうかを確認してください。
   - 明らかに別の問題の解答である、白紙である、数学と無関係な画像である等、①の問題に対応していないと判断した場合は、絶対に「正解」とは言わず、辻褄合わせの添削もしないでください。応答の一番最初の行に必ず半角文字列 `{MISMATCH_MARKER}` だけを出力し、改行してから「アップロードされた解答が、この問題の解答になっていないようです。もう一度、この問題を解いた写真をアップロードしてください」という趣旨を伝えてください。この場合、添削・学習記録は一切生成しないでください。
   - 対応関係が確認できた場合のみ、`{MISMATCH_MARKER}`は出力せず、以下の1〜3に進んでください。
1. **正誤判定と添削**: 生徒の解答のどこが合っていて、どこが間違っているかを具体的に指摘してください。間違っている場合は、どの考え方・公式を修正すればよいか丁寧に教えてください。
2. **発想の動機の解説**: ただ公式を当てはめるだけでなく、「なぜここでその公式を使うのか（発想の動機）」を必ず丁寧に語ってください。
3. **対話の継続**: 生徒から追加の質問が来ることを想定し、一方的に終わらせず、対話を続ける姿勢で答えてください。
4. **簡潔さ**: 同じ指摘・結論を言い回しを変えて何度も繰り返さないでください。一つの論点は一度だけ、簡潔に述べてください。

# トーン＆スタイル（Tone & Style）
- 口調は「です・ます」調を使用してください。
- 受験生に対する指導であることを意識し、間違いや理解不足は曖昧にせず、はっきりと具体的に指摘してください。「惜しい」で済ませず、なぜ間違えたのか、次に同じ間違いをしないためにどう考えればよいかを厳密に詰めてください。あいまいな理解のまま「なんとなくできた」で終わらせないでください。
- 安易に「よくできました」を連発せず、本当にできている部分だけを具体的に評価してください。
- ただし人格を否定するような厳しさではなく、期待水準の高い指導者として、粘り強く生徒を鍛える姿勢を大切にしてください。

{FORMAT_RULES}

# 出力フォーマット（Output Format）
対話と添削の文章を出力した後、最後に**必ず**以下のフォーマットで今回の学習記録を出力してください。

※評価は単なる計算の正誤だけでなく、公式の丸暗記に頼っていないか等、数学的な本質的理解度を含めて評価してください。

---
【単元】 {unit_name}
【元の問題文】 （画像から読み取った問題文をテキスト化して記載）
【理解度スコア】 （100点満点）
【解答の状況】
【分析された弱点・思考の癖】
【今後の学習方針】
---
"""
    # max_output_tokensを指定しないと、モデルが同じ指摘を言い回しを変えて延々と
    # 繰り返す「反復退化」を起こし、分析ノートDocsが際限なく膨張することがあるため、
    # 自由記述の添削文にも上限を設けておく
    response = generate_with_fallback(
        api_key, [prompt, problem_image, answer_image], {"max_output_tokens": 4096}
    )
    return response.text

# --- 小論文添削: テーマの自動生成 ---

ESSAY_THEME_PROMPT_TEMPLATE = """あなたは大学入試小論文の指導教師です。生徒のために、小論文の練習テーマを1つ作成してください。

【最重要の制約】
実在する大学入試・模試の小論文問題を参照したり、その文言を流用したりしては絶対にいけません。あなたが今この場で考えた、完全にオリジナルの一からの創作テーマにしてください。

【生徒の志望分野】
大分類: {target_faculty}
詳細: {target_faculty_detail}

【直前の提出で指摘された弱点（克服を意識したテーマにすること）】
{weakness_tags}

【過去に生徒が持ち込んだ問題から分かっているジャンル・論点の傾向（あくまで参考。文面や具体的な設問設定を真似しないこと）】
{genre_hints}

以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{{
  "theme_text": "生徒に提示する小論文のテーマ文（1〜3文程度、明確な問いの形にすること）",
  "design_note": "このテーマでどの弱点の克服を狙ったかの意図（生徒には見せない内部メモ、1文で簡潔に）"
}}
"""

def generate_essay_theme(target_faculty, target_faculty_detail, recent_weakness_tags, genre_hints, api_key):
    """志望分野・直前の弱点を踏まえて、AIが完全オリジナルの小論文テーマを1つ生成する。"""
    prompt = ESSAY_THEME_PROMPT_TEMPLATE.format(
        target_faculty=target_faculty or "指定なし",
        target_faculty_detail=target_faculty_detail or "指定なし",
        weakness_tags="、".join(recent_weakness_tags) if recent_weakness_tags else "まだ提出履歴がありません",
        genre_hints="、".join(genre_hints) if genre_hints else "なし",
    )
    response = generate_with_fallback(
        api_key, [prompt], {"response_mime_type": "application/json"}
    )
    try:
        data = parse_json_lenient(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = (response.text or "")[:200]
        raise RuntimeError(f"Geminiの応答がJSONとして解釈できませんでした: {e} / 応答内容: {snippet!r}") from e

    theme_text = str(data.get("theme_text", "")).strip()
    if not theme_text:
        raise RuntimeError("Geminiがテーマ文を生成できませんでした。")
    return theme_text

# --- 小論文添削: 生徒が持ち込んだ実在の問題文の読み取り（OCR） ---

PROBLEM_STATEMENT_OCR_PROMPT = """添付された画像には、生徒が持ち込んだ小論文の設問・課題文が写っています（手書きの解答ではなく、印刷または手書きされた「問題文・テーマ」そのものです）。
画像に写っている設問・課題文を、そのまま正確に書き起こしてください。

以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{
  "problem_text": "書き起こした設問・課題文全体"
}
"""

def read_problem_statement_image(image, api_key):
    """生徒が持ち込んだ実在の入試問題（設問文・テーマ）の画像を読み取り、テキスト化する。
    この関数の戻り値はその場の添削にのみ使用し、共有のテーマプールには保存しないこと。"""
    response = generate_with_fallback(
        api_key, [PROBLEM_STATEMENT_OCR_PROMPT, image], {"response_mime_type": "application/json"}
    )
    try:
        data = parse_json_lenient(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = (response.text or "")[:200]
        raise RuntimeError(f"Geminiの応答がJSONとして解釈できませんでした: {e} / 応答内容: {snippet!r}") from e

    return str(data.get("problem_text", "")).strip()

# --- 小論文添削: 800字詰め原稿用紙の書き起こし（OCR） ---

MANUSCRIPT_TRANSCRIBE_PROMPT = """あなたはOCRの専門家です。添付された画像は、生徒が800字詰め原稿用紙（20×40マス、1マスに1文字）に手書きした小論文です。
複数枚の画像が添付されている場合は、原稿の続きとして順番通りに1つの文章として結合してください。

マス目の罫線を基準に1マス1文字として本文を正確に書き起こしてください。句読点・かぎかっこも1マスとして数えてください。マスの罫線が無い自由な用紙の場合でも、読み取れる範囲で構いません。
判読できない文字があれば、その部分に `[判読不能]` と記載してください。

以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{
  "transcribed_text": "書き起こした本文全体",
  "char_count": マス目の数（推定）を基準にした整数の文字数,
  "low_confidence_notes": "判読に自信が持てなかった箇所の説明（無ければ空文字）"
}
"""

def transcribe_manuscript_paper(images, api_key):
    """800字詰め原稿用紙の画像（複数ページ可）から本文を書き起こす。
    戻り値はOCR結果であり、生徒が確認・修正してから採点に使うことを前提とする
    （マス目のOCR誤読による不当な採点を避けるため、この関数の出力を直接採点には使わない）。"""
    response = generate_with_fallback(
        api_key, [MANUSCRIPT_TRANSCRIBE_PROMPT, *images], {"response_mime_type": "application/json"}
    )
    try:
        data = parse_json_lenient(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = (response.text or "")[:200]
        raise RuntimeError(f"Geminiの応答がJSONとして解釈できませんでした: {e} / 応答内容: {snippet!r}") from e

    return {
        "transcribed_text": str(data.get("transcribed_text", "")).strip(),
        "char_count": int(data.get("char_count") or 0),
        "low_confidence_notes": str(data.get("low_confidence_notes", "")).strip(),
    }

# --- 小論文添削: 固定ルーブリックによる採点 ---

ESSAY_RUBRIC_PROMPT_TEMPLATE = """あなたは大学入試小論文の指導教師です。以下のテーマに対する生徒の小論文を、固定のルーブリックで採点してください。

【テーマ】
{theme_text}

【生徒の志望分野】
{target_faculty} / {target_faculty_detail}

【生徒の提出本文】
{essay_text}

まず、この本文が上記テーマに対する小論文として成立しているか（白紙・テーマと無関係な内容・課題文の丸写しのみ、ではないか）を確認してください。成立していない場合は、"off_topic": true とし、他のスコアは0にしてください。

成立している場合は、以下5つの観点で採点してください（配点は必ず以下の通りにすること）:
- structure（構成・展開）: 25点満点
- logic（論理性・説得力）: 30点満点
- originality（独自性）: 20点満点
- expression（表現力・文章力）: 15点満点
- relevance（課題理解・テーマ適合性）: 10点満点
{brought_in_note}
以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{{
  "off_topic": 成立していなければtrue、成立していればfalseの真偽値,
  "off_topic_reason": "off_topicがtrueの場合の理由（falseの場合は空文字）",
  "scores": {{
    "structure": {{"points": 0から25の整数, "comment": "この観点の講評"}},
    "logic": {{"points": 0から30の整数, "comment": "この観点の講評"}},
    "originality": {{"points": 0から20の整数, "comment": "この観点の講評"}},
    "expression": {{"points": 0から15の整数, "comment": "この観点の講評"}},
    "relevance": {{"points": 0から10の整数, "comment": "この観点の講評"}}
  }},
  "strengths": ["良かった点を簡潔に1〜3個"],
  "weakness_tags": ["改善が必要な点を簡潔な短いタグで1〜3個（例: 具体例が抽象的、反論への言及不足）"],
  "feedback_summary": "総合講評（3〜5文程度）"{genre_hint_field}
}}
"""

BROUGHT_IN_RUBRIC_NOTE = """
【重要】この小論文は生徒が実在の入試問題を持ち込んで提出したものです。この文章の原文自体（テーマ文・本文の引用）を分析結果やJSON出力に含めてはいけません。genre_hintフィールドには、原文を一切引用せずに「ジャンル・論点の傾向」だけを1〜2文で要約してください（例: 医療倫理に関する時事的な出題、都市部と地方の格差をテーマにした出題、など）。
"""

ESSAY_RUBRIC_MAX_POINTS = {
    "structure": 25,
    "logic": 30,
    "originality": 20,
    "expression": 15,
    "relevance": 10,
}

def grade_essay(theme_text, essay_text, target_faculty, target_faculty_detail, api_key, is_brought_in=False):
    """固定ルーブリック5軸で小論文を採点する。テーマと無関係・白紙の場合はoff_topic=Trueで
    スコアを確定せず差し戻す。is_brought_in=Trueの場合、原文はレスポンスに含めず
    ジャンル・論点の傾向（genre_hint）だけを生成させる。"""
    prompt = ESSAY_RUBRIC_PROMPT_TEMPLATE.format(
        theme_text=theme_text,
        target_faculty=target_faculty or "指定なし",
        target_faculty_detail=target_faculty_detail or "指定なし",
        essay_text=essay_text,
        brought_in_note=BROUGHT_IN_RUBRIC_NOTE if is_brought_in else "",
        genre_hint_field=',\n  "genre_hint": "原文を引用しない、ジャンル・論点の傾向の要約"' if is_brought_in else "",
    )
    response = generate_with_fallback(
        api_key, [prompt], {"response_mime_type": "application/json", "max_output_tokens": 4096}
    )
    try:
        data = parse_json_lenient(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = (response.text or "")[:200]
        raise RuntimeError(f"Geminiの応答がJSONとして解釈できませんでした: {e} / 応答内容: {snippet!r}") from e

    if data.get("off_topic"):
        return {
            "off_topic": True,
            "off_topic_reason": str(data.get("off_topic_reason", "")).strip(),
        }

    raw_scores = data.get("scores", {})
    scores = {}
    total_score = 0
    for criterion in ESSAY_RUBRIC_MAX_POINTS:
        entry = raw_scores.get(criterion, {})
        points = max(0, min(ESSAY_RUBRIC_MAX_POINTS[criterion], int(entry.get("points") or 0)))
        scores[criterion] = {"points": points, "comment": str(entry.get("comment", "")).strip()}
        total_score += points

    return {
        "off_topic": False,
        "scores": scores,
        "total_score": total_score,
        "strengths": [str(s).strip() for s in data.get("strengths", []) if str(s).strip()],
        "weakness_tags": [str(w).strip() for w in data.get("weakness_tags", []) if str(w).strip()],
        "feedback_summary": str(data.get("feedback_summary", "")).strip(),
        "genre_hint": str(data.get("genre_hint", "")).strip() if is_brought_in else None,
    }

# --- 小論文添削: 対策レポートの生成 ---

PROGRESS_REPORT_PROMPT_TEMPLATE = """あなたは大学入試小論文の指導教師です。以下は、生徒「{student_name}」（志望分野: {target_faculty}）の小論文の提出履歴の要約です（本文全体ではなく、日時・テーマ概要・総合点・弱点タグのみ）。

【提出履歴】
{submission_summaries}

この履歴を分析し、生徒本人が読む「対策レポート」をMarkdown形式で作成してください。以下の観点を含めてください:
- スコアの推移（伸びている点・停滞している点）
- 克服できてきた弱点
- まだ残っている課題
- 志望分野に即した、今後取り組むべき具体的な対策

生徒本人が読むものなので、「です・ます」調で、励ましつつも具体的に書いてください。
"""

def generate_progress_report(student_name, target_faculty, submission_summaries, api_key):
    """提出履歴の軽量な要約（本文全文は含めない）から、生徒向けの対策レポートをMarkdownで生成する。"""
    prompt = PROGRESS_REPORT_PROMPT_TEMPLATE.format(
        student_name=student_name,
        target_faculty=target_faculty or "指定なし",
        submission_summaries=submission_summaries,
    )
    response = generate_with_fallback(api_key, [prompt], {"max_output_tokens": 2048})
    return response.text
