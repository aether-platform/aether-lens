FROM python:3.11-slim

# インストールに必要な最小限のツール（git等）を導入
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# パッケージのコピーとインストール
COPY . .
RUN pip install .

# 環境変数の設定 (ログをリアルタイムで出力するため)
ENV PYTHONUNBUFFERED=1

# 出力先などを外部から指定できるようにエントリポイントを設定
ENTRYPOINT ["aether-lens"]
