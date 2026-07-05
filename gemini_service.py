import json
import os
import re
import streamlit as st
import google.generativeai as genai
from PIL import Image


@st.cache_data(ttl=3600, show_spinner=False)
def get_flash_model_name(api_key):
    """APIキーに紐づく利用可能なFlashモデルの名前を1回だけ取得し、キャッシュする"""
    try:
        genai.configure(api_key=api_key)
        models = [m for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

        for m in models:
            if 'gemini-1.5-flash' in m.name:
                return m.name

        for m in models:
            if 'flash' in m.name:
                return m.name

        return "gemini-1.5-flash-latest"
    except Exception:
        return "gemini-1.5-flash"


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

MODE_INSTRUCTIONS = {
    "hint": "問題文と生徒の書き込みを読み取り、解き方の「最初のヒント」や「アプローチ方法」だけを教えてください。絶対に最終的な答えや完全な数式は教えないでください。",
    "answer": "問題文を読み取り、この問題に対する「完全な模範解答と丁寧な解説」を作成してください。教育的配慮（ヒントで止めるなど）は不要です。最後の結論（答えの数値や証明の完了）まで全ての数式と論理展開を省略せず書き切ってください。",
    "correction": "問題文と生徒の手書き解答の両方を読み取ってください。生徒の解答が合っているか判定し、間違っている場合は「どこで計算ミスをしたか」「どの公式を間違えたか」などを具体的に指摘して添削してください。白紙の場合は「まずはここから考えてみよう」と優しくヒントを出してください。",
}


def generate_copy_prompt(mode, student_name, level, streak):
    """生徒がGeminiに直接貼り付けて使う、ヒント/添削/解答用のプロンプト文字列を組み立てる"""
    instruction = MODE_INSTRUCTIONS[mode]
    header = f"""あなたは優秀で、生徒に寄り添う親切な高校の数学教師「Kvillage先生」です。
このメッセージと一緒に、生徒が解いた問題用紙の写真（またはPDF）が添付されています。まずその画像を読み取ってください。

生徒の名前は「{student_name}さん」、現在のレベルは{level}、連続学習日数は{streak}日です。機械的に言うのではなく、自然な励ましの中に含めてください。

【生徒からの要望】
{instruction}

口調は「です・ます」調で、生徒を温かく励ますトーンにしてください。ただ公式を当てはめるだけでなく、「なぜここでその公式を使うのか（発想の動機）」を必ず語ってください。この後、生徒から追加の質問が来るかもしれないので、対話を続けるつもりで答えてください。
"""
    return header + "\n" + FORMAT_RULES


# --- RPGバトル用データの生成: 既存問題（画像）をAIに解かせて難易度・正解を登録する ---

PROBLEM_ENRICHMENT_PROMPT = """あなたは高校数学の教師です。添付された入試問題の画像を見て、この問題を実際に解いてください。

以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{{
  "difficulty": "易しい・普通・難しい のいずれか",
  "correct_answer": "この問題の最終的な答え（数値または簡潔な式）。証明問題など、簡潔な答えの形にできない場合は空文字にすること。",
  "solvable": この問題を解いて明確な最終解答を出せた場合はtrue、証明問題や解答が定まらない場合はfalseの真偽値
}}
"""


def enrich_problem_for_battle(image_path, api_key):
    """既存の問題画像をAIに解かせ、RPGバトルで使う難易度・正解を生成する。証明問題等で解答が定まらない場合はNoneを返す。"""
    if not os.path.exists(image_path):
        return None

    genai.configure(api_key=api_key)
    model_name = get_flash_model_name(api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config={"response_mime_type": "application/json"}
    )

    img = Image.open(image_path)
    img.thumbnail((1024, 1024))

    response = model.generate_content([PROBLEM_ENRICHMENT_PROMPT, img])
    try:
        data = json.loads(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = (response.text or "")[:200]
        raise RuntimeError(f"Geminiの応答がJSONとして解釈できませんでした: {e} / 応答内容: {snippet!r}") from e

    if not data.get("solvable", False) or not str(data.get("correct_answer", "")).strip():
        return None

    return {
        "difficulty": data.get("difficulty", "普通"),
        "correct_answer": str(data.get("correct_answer")).strip(),
    }


# --- RPGバトル: 手書き解答の採点（正誤判定のみ） ---

JUDGE_PROMPT_TEMPLATE = """あなたは高校数学の採点者です。添付された画像は、生徒が手書きで解いた数学の解答です。

【この問題の正解】
{correct_answer}

画像を読み取り、生徒の最終的な解答が上記の正解と一致しているか（同値な式・数値を含む）を判定してください。
以下のJSON形式で必ず出力してください（他の文章は一切含めないこと）:
{{
  "is_correct": 正解ならtrue、不正解や白紙ならfalseの真偽値,
  "extracted_answer": "画像から読み取れた生徒の最終解答（読み取れない場合は空文字）"
}}
"""


def judge_battle_answer(image, correct_answer, api_key):
    genai.configure(api_key=api_key)
    model_name = get_flash_model_name(api_key)
    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config={"response_mime_type": "application/json"}
    )
    prompt = JUDGE_PROMPT_TEMPLATE.format(correct_answer=correct_answer)
    response = model.generate_content([prompt, image])
    data = json.loads(response.text)
    return {
        "is_correct": bool(data.get("is_correct", False)),
        "extracted_answer": data.get("extracted_answer", ""),
    }


# --- RPGバトル: くわしい添削が欲しい生徒向けのコピペ用プロンプト ---

def generate_battle_review_prompt(unit_name, correct_answer):
    header = f"""あなたは高校の数学教師「Kvillage先生」です。RPG風の数学学習アプリで、生徒が「{unit_name}」分野のバトル問題に挑戦しました。

このメッセージと一緒に、①解いた問題の画像 と ②生徒が手書きで解いた解答の画像、の2枚が添付されています。まずその両方の画像を読み取ってください。

【模範解答（最終的な答え）】
{correct_answer}

生徒の解答のどこが合っていて、どこが間違っているかを具体的に指摘し、間違えた場合はどの考え方を修正すればよいか丁寧に教えてください。この後、生徒から追加の質問が来るかもしれないので、対話を続けるつもりで答えてください。
"""
    return header + "\n" + FORMAT_RULES


# --- 学習カルテ: NotebookLM/Gemini向けの弱点分析プロンプト（API呼び出しなし、テキスト生成のみ） ---

def generate_notebooklm_analysis_prompt(unit_name, correct_count, total_count):
    return f"""このPDFには、「{unit_name}」分野の問題と、それぞれに対する私（生徒）の正誤結果（{correct_count}/{total_count}問正解）がまとめられています。

いきなり答えや解説を教えるのではなく、私が自分で気づけるように、次の順番で手伝ってください。

1. 間違えた問題について、それぞれどんな「考え方」や「公式」でつまずいていそうか、傾向を指摘してください。
2. その傾向から、私が特に弱いと思われる「知識」や「解法パターン」を2〜3個挙げてください。
3. それらを克服するために、次に何を勉強するとよいか、優先順位をつけて提案してください。
4. 最後に、「なぜそこが弱点だと思うか、自分の言葉で説明してみて」と私に問いかけてください。
"""
