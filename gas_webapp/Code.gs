/**
 * kvillage - AI自動添削 GASバックエンド
 *
 * 【事前準備】このプロジェクトの「プロジェクトの設定」→「スクリプト プロパティ」に
 * 以下を設定してください:
 *   GEMINI_API_KEY : Gemini APIキー
 *   HMAC_SECRET    : Streamlit側のsecrets.tomlに設定する GAS_HMAC_SECRET と同じ値
 *   DOCS_FOLDER_ID : （任意）新規作成する分析ノートを保存するGoogle DriveのフォルダID。
 *                    未設定の場合はマイドライブ直下に作成される。
 *                    フォルダのURL（https://drive.google.com/drive/u/0/folders/XXXXXXXX）の
 *                    末尾のXXXXXXXX部分をコピーして設定する。
 *
 * 【デプロイ設定】「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
 *   実行するユーザー: 自分（Me）
 *   アクセスできるユーザー: 全員（Anyone）
 *   ※「Googleアカウントを持つ全員」にすると、Googleのログイン画面自体が
 *     iframe埋め込みをブロックする仕様のため、Streamlit内に表示できなくなります。
 *   デプロイ後に発行されるURLを、Streamlit側のsecrets.tomlの GAS_WEBAPP_URL に設定してください。
 */

var GEMINI_MODEL = 'gemini-2.5-flash-lite';

var CORRECTION_PROMPT = [
  '# 役割（Role）',
  'あなたは優秀で、生徒に寄り添う親切な高校の数学教師「Kvillage先生」です。',
  '',
  '# 基本タスク（Task）',
  'ユーザー（生徒）から、数学の問題用紙と手書き解答の写真（またはPDF）が送信されます。',
  '以下の手順で画像を読み取り、添削と対話を行ってください。',
  '',
  '1. **画像の読み取り**: 問題文と生徒の手書き解答の両方を正確に読み取ります。',
  '2. **正誤判定と添削**:',
  '   - 解答が合っているか判定し、間違っている場合は「どこで計算ミスをしたか」「どの公式を間違えたか」などを具体的に指摘して添削してください。',
  '   - 解答が白紙の場合は、答えを教えるのではなく「まずはここから考えてみよう」と優しくヒントを出してください。',
  '3. **発想の動機の解説**: ただ公式を当てはめるだけでなく、「なぜここでその公式を使うのか（発想の動機）」を必ず丁寧に語ってください。',
  '4. **対話の継続**: 生徒から追加の質問が来ることを想定し、一方的に終わらせず、自然な励ましの言葉を交えながら対話を続ける姿勢で答えてください。',
  '',
  '# トーン＆スタイル（Tone & Style）',
  '- 口調は「です・ます」調を使用してください。',
  '- 生徒を温かく、優しく励ますトーンを徹底してください。',
  '',
  '# レイアウトのルール（Layout Rules）',
  '- 相手は高校生です。読みやすさを重視し、**必ず1〜2文ごとに空行（改行）を入れ、余白をたっぷり取って**ください。',
  '- 長い文章を1つの段落に詰め込むことは厳禁です。',
  '',
  '# 数式のフォーマットルール（Math Formatting Rules）※厳守',
  '- シグマ記号（∑）、極限（lim）、積分（∫）、分数などは、添え字や分母分子が文字の「上下」に配置されるように出力してください。',
  '- 数式（方程式や式の変形など）を書くときは、必ず改行して独立した行となる「ブロック数式（$$ で囲む形式）」を使用してください。',
  '- 文中（インライン）に短い変数や数式（例: x や \\alpha）を書く場合は、必ず `$x$` や `$\\alpha$` のように `$` で囲んでください。バッククォート（`）は絶対に使用しないでください。',
  '- 複数行の数式を書く場合は、`\\begin{aligned}` と `\\end{aligned}` を使い、その外側を `$$` で囲んでください。`\\begin{align*}` は使用しないでください。',
  '- `\\begin{aligned}` 環境内で等号（`&=`）を続ける場合は、1行に複数書かず `\\\\` で必ず改行してください。',
  '',
  '# 出力フォーマット（Output Format）',
  '対話と添削の文章を出力した後、最後に**必ず**以下のフォーマットで今回の学習記録を出力してください。',
  '',
  '※【重要】生徒がアップロードした画像から元の問題文を読み取り、「【元の問題文】」の項目にテキストとして正確に復元して記載してください（数式も可能な限りテキストやLaTeX記法で再現すること）。',
  '※評価は単なる計算の正誤だけでなく、公式の丸暗記に頼っていないか等、数学的な本質的理解度を含めて評価してください。',
  '',
  '---',
  '【日付】 YYYY-MM-DD（本日の日付）',
  '【単元】',
  '【元の問題文】 （画像から読み取った問題文をテキスト化して記載）',
  '【理解度スコア】 （100点満点）',
  '【解答の状況】',
  '【分析された弱点・思考の癖】',
  '【今後の学習方針】',
  '---'
].join('\n');

function getSecret_(key) {
  return PropertiesService.getScriptProperties().getProperty(key);
}

function b64UrlDecodeToString_(b64url) {
  var padded = b64url.replace(/-/g, '+').replace(/_/g, '/');
  while (padded.length % 4) padded += '=';
  return Utilities.newBlob(Utilities.base64Decode(padded)).getDataAsString();
}

function b64UrlEncodeBytes_(bytes) {
  return Utilities.base64Encode(bytes).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * Streamlit（gas_auth.generate_gas_token）が発行した署名付きトークンを検証する。
 * 有効ならstudent_id（sid）を、無効・改ざん・期限切れなら null を返す。
 * トークン形式: base64url(payload_json) + "." + base64url(hmac_sha256_signature)
 */
function verifyToken(token, secret) {
  return verifyTokenDetailed_(token, secret).sid;
}

/**
 * verifyTokenの内部実装。失敗理由（reason）付きで返す。
 * gradeAnswer側でエラーメッセージを具体的にするために使う。
 */
function verifyTokenDetailed_(token, secret) {
  if (!token) return { sid: null, reason: 'トークンがありません' };
  if (!secret) return { sid: null, reason: 'サーバー側にHMAC_SECRETスクリプトプロパティが設定されていません' };
  if (token.indexOf('.') === -1) return { sid: null, reason: 'トークンの形式が不正です（.が含まれていません）' };
  var parts = token.split('.');
  if (parts.length !== 2) return { sid: null, reason: 'トークンの形式が不正です（区切りの数が不正）' };
  var payloadB64 = parts[0];
  var sigB64 = parts[1];

  var expectedSigBytes = Utilities.computeHmacSha256Signature(payloadB64, secret);
  var expectedSigB64 = b64UrlEncodeBytes_(expectedSigBytes);
  if (expectedSigB64 !== sigB64) {
    console.log('verifyToken debug: payloadB64=' + payloadB64);
    console.log('verifyToken debug: sigB64 (received)=' + sigB64 + ' (len=' + sigB64.length + ')');
    console.log('verifyToken debug: expectedSigB64 (computed)=' + expectedSigB64 + ' (len=' + expectedSigB64.length + ')');
    console.log('verifyToken debug: secret length=' + secret.length);
    return { sid: null, reason: '署名が一致しません（StreamlitのGAS_HMAC_SECRETと、このスクリプトのHMAC_SECRETが一致していない可能性があります）' };
  }

  var payload;
  try {
    payload = JSON.parse(b64UrlDecodeToString_(payloadB64));
  } catch (e) {
    return { sid: null, reason: 'ペイロードの解析に失敗しました: ' + e.message };
  }
  if (!payload || !payload.sid || !payload.exp) {
    return { sid: null, reason: 'ペイロードにsidまたはexpが含まれていません' };
  }
  var now = Math.floor(Date.now() / 1000);
  if (payload.exp < now) {
    return { sid: null, reason: 'トークンが期限切れです（exp=' + payload.exp + ', now=' + now + ', 差=' + (now - payload.exp) + '秒）' };
  }
  return { sid: payload.sid, reason: null };
}

function doGet(e) {
  var token = (e && e.parameter && e.parameter.token) || '';
  var secret = getSecret_('HMAC_SECRET');
  var studentId = verifyToken(token, secret);

  console.log('doGet debug: token=' + token);
  console.log('doGet debug: secret length=' + (secret ? secret.length : 0));
  console.log('doGet debug: valid=' + !!studentId);

  var template = HtmlService.createTemplateFromFile('index');
  template.valid = !!studentId;
  template.token = token;
  return template.evaluate()
      .setTitle('AI自動添削')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * クライアント（index.html）から google.script.run 経由で呼ばれる添削処理本体。
 * token はここで再検証する（クライアントの自己申告のstudent_idは信用しない）。
 *
 * 戻り値: { resultText: string, docUrl: string }
 */
function gradeAnswer(token, base64Image, mimeType) {
  var secret = getSecret_('HMAC_SECRET');
  var verified = verifyTokenDetailed_(token, secret);
  if (!verified.sid) {
    throw new Error('セッションの検証に失敗しました（' + verified.reason + '）。Streamlitの画面を再読み込みしてください。');
  }
  var studentId = verified.sid;

  var resultText = callGemini_(base64Image, mimeType);
  var docUrl = appendToStudentDoc_(studentId, extractStudyRecord_(resultText));

  return { resultText: resultText, docUrl: docUrl };
}

/**
 * Geminiの応答（対話・添削の説明文＋末尾の学習記録）から、
 * 【日付】〜【今後の学習方針】の学習記録部分だけを取り出す。
 * Docsにはこの部分だけを書き込み、説明文でページが埋まらないようにする。
 * 【日付】が見つからない場合は、想定外の出力形式とみなし全文をそのまま返す（記録の取りこぼしを防ぐため）。
 */
function extractStudyRecord_(resultText) {
  var startIdx = resultText.indexOf('【日付】');
  if (startIdx === -1) {
    return resultText;
  }
  var record = resultText.substring(startIdx);
  // 末尾の区切り線（---）が含まれていれば取り除く
  record = record.replace(/-{3,}\s*$/, '');
  return record.trim();
}

function callGemini_(base64Image, mimeType) {
  var apiKey = getSecret_('GEMINI_API_KEY');
  if (!apiKey) {
    throw new Error('GEMINI_API_KEYが設定されていません。スクリプトのプロパティを確認してください。');
  }

  var url = 'https://generativelanguage.googleapis.com/v1beta/models/' + GEMINI_MODEL +
      ':generateContent?key=' + apiKey;

  var payload = {
    contents: [{
      parts: [
        { text: CORRECTION_PROMPT },
        { inline_data: { mime_type: mimeType || 'image/jpeg', data: base64Image } }
      ]
    }]
  };

  var response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });

  var status = response.getResponseCode();
  var body = JSON.parse(response.getContentText());
  if (status !== 200) {
    var message = (body.error && body.error.message) || response.getContentText();
    throw new Error('Geminiの呼び出しに失敗しました: ' + message);
  }

  var candidate = body.candidates && body.candidates[0];
  var parts = candidate && candidate.content && candidate.content.parts;
  var text = parts && parts.map(function (p) { return p.text || ''; }).join('');
  if (!text) {
    throw new Error('Geminiから有効な応答が得られませんでした。');
  }
  return text;
}

/**
 * 生徒ごとの分析ノート（Google Docs）に添削結果を追記する。
 * 初めての生徒の場合は新規作成し、スクリプトプロパティに studentId→docId を保存する。
 * Docsの所有権はシステム（このスクリプトの実行者=先生）側。
 */
function appendToStudentDoc_(studentId, resultText) {
  var props = PropertiesService.getScriptProperties();
  var propKey = 'doc_' + studentId;
  var docId = props.getProperty(propKey);
  var doc;

  if (docId) {
    try {
      doc = DocumentApp.openById(docId);
    } catch (e) {
      docId = null; // ドキュメントが削除されている等の場合は作り直す
    }
  }

  if (!docId) {
    doc = DocumentApp.create('数学 学習記録ノート（' + studentId + '）');
    docId = doc.getId();
    props.setProperty(propKey, docId);
    var file = DriveApp.getFileById(docId);
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);

    var folderId = getSecret_('DOCS_FOLDER_ID');
    if (folderId) {
      var folder = DriveApp.getFolderById(folderId);
      folder.addFile(file);
      DriveApp.getRootFolder().removeFile(file);
    }
  }

  var body = doc.getBody();
  body.appendParagraph('');
  body.appendParagraph('====== ' + new Date().toLocaleString('ja-JP') + ' ======');
  body.appendParagraph(resultText);
  doc.saveAndClose();

  return 'https://docs.google.com/document/d/' + docId + '/edit';
}

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}
