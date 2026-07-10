"""
GAS Webアプリ（gas_webapp/Code.gs）のdoPostエンドポイントを、
StreamlitからHTTP経由で呼び出すためのクライアント。

RPGバトルの「くわしく添削してほしい」機能のように、Streamlit側で既に
Gemini APIキーを使って添削結果を生成できる場面では、GAS側で改めて
Geminiを呼び出す必要はない。GASには、生成済みの結果テキストをDocsに
追記する処理だけを任せる。
"""

import requests

import gas_auth


def append_review_to_docs(gas_webapp_url, gas_hmac_secret, student_id, result_text, timeout=30):
    """添削結果テキストを、GAS側のdoPostエンドポイント経由で生徒の分析ノートDocsに追記する。
    戻り値: (成功したか, docUrlまたはエラーメッセージ)"""
    token = gas_auth.generate_gas_token(student_id, gas_hmac_secret)
    try:
        response = requests.post(
            gas_webapp_url,
            json={"token": token, "resultText": result_text},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return False, f"通信エラー: {e}"

    if data.get("error"):
        return False, data["error"]
    return True, data.get("docUrl", "")
