# 渋谷スクランブル 3D 街ビューア (SKELETON)

渋谷スクランブル交差点の 3D 街（GLB / 3DGS）を表示するための WebGL ビューアのスケルトン実装です。
ローカルまたは Cloudflare Worker 上で静的アセットとして配信され、ブラウザ単体で動作します。

- 実行方法: 静的 Web サーバー（例: `npx serve public`）でホストし `/viewer/` にアクセスします。
- 未実装事項: PC 向け 3D Gaussian Splatting (3DGS) レンダラーおよび写真パネル（Placements）レイヤーの重畳表示。
