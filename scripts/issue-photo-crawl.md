# [データ] 渋谷スクランブル写真のクロール収集（R2 投入）

> GitHub Issue 用ドラフト（2026-10-14）  
> リポジトリ: https://github.com/bonsai/shibuya-scramble-crossing  
> 貼り付け先: Issues → New issue

---

## 目的

Epic B（街 3DGS）に必要な **視点が散らばった写真 80〜150 枚** を、手動投稿だけでは足りない場合に備えるための **合法的な画像収集経路** を作る。

収集結果は既存の `photos/` 配列で R2 に入れ、`batch_3dgs.py` がそのまま食べられること。

## 背景

- 投稿 UI（`POST /api/upload`）は既にある
- 3DGS には視点多様性が必要（東西南北・高低差・時間帯）
- 手動だけだと初回バッチまで時間がかかる

## 法務・ライセンス（必須）

**無断でやらないこと**

- robots.txt / ToS 違反のスクレイピング
- 著作権が不明または再利用不可の SNS・旅行サイトからの一括保存
- 個人が識別できる写真の無断公開再配布（プライバシー）

**実装時の条件**

1. **再利用可能なライセンスのみ**（CC0 / CC BY / 公的領域・明示的な API 許諾等）
2. 元 URL・ライセンス・取得日時を **メタデータとして残す**（R2 customMetadata または並行 JSON）
3. 収集元は **allowlist**（許可したドメイン / API のみ）
4. レート制限を守り、バルク投稿しない

### 候補ソース（案・決定は実装前）

| ソース | 備考 |
|--------|------|
| Wikimedia Commons | API あり、ライセンス明確。「Shibuya scramble」等 |
| Flickr API（CC フィルタ） | ライセンス指定検索が可能な場合のみ |
| Mapillary / 類似（ToS 確認後） | 街路視点が得やすい可能性。**ToS を先に確認** |
| 手動 allowlist URL 一覧 | 運用者が許可済 URL だけを食わせる |

SNS（X / Instagram 等）の無断クロールは **初期スコープ外**。

## スコープ

### A. 収集スクリプト（推奨: `scripts/` または `colab/`）

- [ ] allowlist ソースから画像 URL 一覧を取得
- [ ] ライセンスフィルタ（CC0/CC-BY 等）
- [ ] ダウンロード（jpeg/png/webp、上限サイズ例: 15MB）
- [ ] 重複除去（コンテンツハッシュ or URL）
- [ ] R2 `photos/YYYY-MM-DD/crawl_<id>.jpg` へアップロード
- [ ] metadata: `source_url`, `license`, `fetched_at`, `query`
- [ ] 環境変数で R2 認証（hardcode 禁止、`.env` を Git に入れない）
- [ ] dry-run モード（取得・保存せず一覧だけ）

### B. 品質フィルタ（最小）

- [ ] 解像度下限（例: 短辺 800px 未満は棄て）
- [ ] 明らかにスクランブル以外（キーワード不一致）は可能な限り除外
- [ ] 人だけ・建物が見えない写真は 3DGS 用には低優先（フラグだけでも可）

### C. 運用

- [ ] 最大収集枚数（例: 1 回 50 枚）
- [ ] 実行ログ（何枚取得 / 何枚スキップ / エラー）
- [ ] README または本 Issue に「許可ソースと制限」を明記

## 非スコープ

- Worker 上での定期クロール（初期はローカル / Colab 一発で十分）
- SNS 全面スクレイピング
- 人物識別・顔ぼかし（別議題）
- 収集写真の自動 3DGS 学習起動（人手または既存バッチを使う）

## 受け入れ条件

- [ ] dry-run で対象 URL 一覧が出る
- [ ] 許可ソース 1 種以上から実ダウンロード→ R2 に 1 枚以上入る（#40 解除後、またはローカルモック）
- [ ] 各オブジェクトに source/license メタが残る
- [ ] 秘密情報がログ・コミットに出ていない
- [ ] 本 Issue に採用したソースと ToS/ライセンス依拠を記載

## 依存

- Epic B #15（学習に枚数が必要）
- Epic A #14 / Blocker #40（本番 R2 への投入確認）
- 既存キー形式: `photos/YYYY-MM-DD/...`

## 実装ノート

- Worker に依存を追加しない（#13 の作法）
- スクリプトは Python（Colab で回しやすい）が有力
- 最初の allowlist は **Wikimedia Commons API の 1 ソース** で十分。増やすのは後

## ラベル案

`enhancement`（必要なら後から `data` 等を追加）

## 関連リンク

- Meta: https://github.com/bonsai/shibuya-scramble-crossing/issues/13
- Epic B: https://github.com/bonsai/shibuya-scramble-crossing/issues/15
- Blocker CF: https://github.com/bonsai/shibuya-scramble-crossing/issues/40
