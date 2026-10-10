# MCP（任意）

ローカルから学習バッチの指定や R2 の確認をするための **Model Context Protocol** 用フォルダ。

現状は **必須ではない**。主経路は「Colab が R2 を直接読む」。

## 想定ツール（実装時）

| ツール | 内容 |
|--------|------|
| `list_r2_photos` | `photos/` 一覧 |
| `suggest_batch` | prefix / 枚数の提案（画像は中継しない） |
| `note_model` | 学習済み `.ply` のキーメモ |

## 置き場所

```
mcp/
  README.md      # このファイル
  server.py      # 未着手
  requirements.txt
  .env.example   # R2 キーは Git に入れない
```

実装するときは Epic / Issue を切ってから。
