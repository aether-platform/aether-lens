# Aether Lens (Aether Vision) - Tilt 連携ガイド

Aether Platform は `kustomize` および `kubectl` をベースとしたデプロイフローを採用しています。`aether-lens` をローカル開発環境（Tilt 等を利用した環境）に統合するための手順と設定です。

## 1. Tiltfile への組み込みイメージ

もし `Tiltfile` を利用して開発している場合、以下のコードを追加することで `aether-vision` サイドカーを Pod に追加できます。

```python
# Aether Lens (Aether Vision) のデプロイ
k8s_yaml('aether-lens/deployment.yaml')

# ローカルエージェントの同期（オプション）
local_resource(
    'aether-lens-agent',
    cmd='pip install -e aether-lens && aether-lens',
    deps=['app/public/docs/starlight/src', 'aether-lens/src']
)
```

## 2. 実装の Tilt 互換性

現在の PoC は以下の形で Tilt 環境（またはそれに類する K8s ローカル開発環境）に適合しています。

- **Live Update 代替**: パッケージを編集モード (`-e`) でインストールすることで、`src` 配下の変更が即座に反映されます。
- **Port Forwarding**: Tilt の `k8s_resource` を使用して `test-runner` (Browserless) の 3000 ポートをフォワードすることで、ローカルからライブビューを確認できます。

## 3. 起動手順

Aether Platform 全体を起動した状態で、以下のコマンドを実行します。

```bash
# パッケージのインストール
pip install -e aether-lens

# プラットフォーム層のデプロイ (Browserless 等のサイドカーの準備)
kubectl apply -f aether-lens/deployment.yaml

# ローカル解析パイプラインの開始
aether-lens
```
