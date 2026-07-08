# YeahKau Home Buying Flow AI

- YeahKau 家購入補佐AI — 知らないまま、家を買わせない。

住宅購入の進捗状況や不安点を入力すると、AIが「今やること」「確認すべきこと」「専門家に聞くべきこと」を整理するMVPです。
住宅購入の進捗状況（契約・審査・金消・保険・住民票・決済日）と質問を入力すると、AIが会話形式で整理して返すStreamlitアプリです。

- 次にやること（優先度順）
- リスク（重要なものから）
- 補足説明（簡潔に）

最小構成で「まず動くこと」を優先したMVPです。

## セットアップ方法

1. Python 3.10+ を用意
2. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

## 設定方法

`settings.yaml` に Gemini API キーを設定してください。

`settings_template.yaml` をコピーして `settings.yaml` を用意しても構いません。

### `settings.yaml` の例

```yaml
api_ai: gemini
api_key: あなたのVertex AI APIキー
api_key_name: Gemini API Key
project_id: your-gcp-project-id
location: global
model: google/gemini-2.5-flash
model_options: google/gemini-2.5-flash,anthropic/claude-opus-4-7,x-ai/grok-4.20
anthropic_location: us-east5
x_ai_location: us-east5
```

## Vertex で Claude/Grok を使う場合の Google 側設定

1. 対象プロジェクトで Vertex AI API を有効化する
2. Vertex AI Model Garden で Anthropic と xAI のモデル利用を有効化する
3. 利用モデルに対応したリージョンを settings.yaml の location に設定する
4. APIキー制限を設定している場合は、Vertex AI API への利用を許可する

補足: settings.yaml の location が global の場合、アプリは Claude/Grok 選択時に
anthropic_location / x_ai_location へ自動切り替えます。

補足: Claude/Grok はリージョンや利用許可が不足していると 403/404 になりやすいです。その場合は model と location の組み合わせを見直してください。

## 実行方法

以下コマンドで起動します。

```bash
streamlit run app.py
```

起動後、ブラウザで表示されたURL（通常 `http://localhost:8501`）を開いて利用します。
