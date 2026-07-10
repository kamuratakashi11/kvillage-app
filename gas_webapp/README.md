# AI自動添削 - Google Apps Script セットアップ手順

このフォルダの `Code.gs` と `index.html` は、kvillageアプリの「🤖 AI自動添削」ページに
iframeで埋め込む、Google Apps Script（GAS）製のウェブアプリです。

**重要**: このコードはPythonアプリ（Streamlit）とは別に、Googleアカウント上で
手動でデプロイする必要があります。Claude（このセッション）はGoogleアカウントの
認証・承認操作を代行できないため、以下の手順はご自身で行ってください。

## 1. Apps Scriptプロジェクトを作成する

1. [script.google.com](https://script.google.com/) を開き、「新しいプロジェクト」を作成
2. デフォルトの `Code.gs` の中身を、このフォルダの `Code.gs` の内容で丸ごと置き換える
3. 左側の「＋」→「HTML」で `index` という名前のファイルを追加し、このフォルダの
   `index.html` の内容で丸ごと置き換える（ファイル名は必ず `index`。拡張子`.html`は
   自動で付くので不要）

## 2. スクリプトのプロパティを設定する

「プロジェクトの設定」（左側の歯車アイコン）→「スクリプト プロパティ」→
「スクリプト プロパティを追加」で、以下を設定する:

| プロパティ名 | 値 |
|---|---|
| `GEMINI_API_KEY` | Gemini APIキー（[Google AI Studio](https://aistudio.google.com/) で取得） |
| `HMAC_SECRET` | 自分で決めた、十分に長いランダムな文字列（例: 32文字以上の英数字） |
| `DOCS_FOLDER_ID` | （任意）新規作成する分析ノートをまとめて保存したいGoogle DriveのフォルダID |

`HMAC_SECRET` は、この後Streamlit側の `secrets.toml` にも**全く同じ値**を設定します。

`DOCS_FOLDER_ID` は、対象のフォルダをGoogle Driveで開いたときのURL
（`https://drive.google.com/drive/u/0/folders/XXXXXXXX`）の末尾`XXXXXXXX`部分です。
設定しない場合は、今まで通りマイドライブ直下に作成されます。**既に作成済みの
分析ノートには影響しません**（次に新しい生徒の分析ノートが作られるときから
このフォルダに保存されます）。

## 3. ウェブアプリとしてデプロイする

1. 右上の「デプロイ」→「新しいデプロイ」
2. 種類の選択で歯車アイコン→「ウェブアプリ」を選択
3. 設定:
   - **実行するユーザー**: 自分（Me）
   - **アクセスできるユーザー**: **全員（Anyone）**
   
   ⚠️ 「Googleアカウントを持つ全員」を選ぶと、アクセス時にGoogleのログイン・認証画面が
   表示されますが、この画面自体がセキュリティ上iframe埋め込みをブロックする仕様のため、
   Streamlit内での表示が壊れます。**必ず「全員」を選んでください**（トークンによる
   本人確認は別途HMAC署名で行っているため、これで問題ありません）。
4. 「デプロイ」をクリックし、初回は権限の承認（このプロジェクトにGoogle Docs/Driveへの
   アクセスを許可する）を求められるので許可する
5. 発行された「ウェブアプリのURL」（`https://script.google.com/macros/s/.../exec` の形式）
   をコピーする

## 4. Streamlit側に設定を反映する

kvillageアプリの `.streamlit/secrets.toml`（Streamlit Cloudの場合はダッシュボードの
Secrets設定）に、以下を追加する:

```toml
GAS_WEBAPP_URL = "https://script.google.com/macros/s/xxxxxxxxxxxx/exec"
GAS_HMAC_SECRET = "手順2で設定したHMAC_SECRETと全く同じ値"
```

保存して再起動すると、「🤖 AI自動添削」ページにGASのウェブアプリが表示されます。

## 5. 動作確認

1. kvillageアプリにログインし、「🤖 AI自動添削」ページを開く
2. 解答の写真をアップロードして「✏️ 添削してもらう」を押す
3. 添削結果と、自動作成された分析ノート（Google Docs）へのリンクが表示されることを確認
4. 「💬 追加で質問する」ボタンを押すと、クリップボードにコピーされ、Geminiが別タブで
   開くことを確認

## コードを更新した場合

`Code.gs` / `index.html` の内容を変更したら、Apps Scriptエディタ側の該当ファイルも
同じ内容に更新し、「デプロイ」→「デプロイを管理」→ 既存のデプロイの鉛筆アイコン→
バージョン「新バージョン」を選んで再デプロイしてください（URLは変わりません）。

## 生徒データの扱いについて

- 分析ノート（Google Docs）は先生（このスクリプトの実行者）のGoogleアカウント所有になり、
  「リンクを知っている全員が閲覧可」で共有されます。学習記録には生徒の弱点・理解度など
  やや個人情報に近い内容が含まれるため、Doc URLの管理・共有範囲には注意してください。
- 生徒ID→DocIDの対応は、Apps Scriptの「スクリプト プロパティ」に保存されます
  （`doc_<student_id>` というキー）。生徒が増えるとプロパティの数も増えますが、
  Apps Scriptの上限（プロジェクトあたり500件、1件あたり9KB）に達する心配は
  通常の生徒数では発生しません。
