# VNDB MCP Server

Visual Novel Database (VNDB) APIにアクセスするためのModel Context Protocol (MCP) サーバー。このサーバーを使用することで、Claude AIがVNDBのデータにアクセスできるようになります。

## 機能

- ビジュアルノベルの検索
- ビジュアルノベルの詳細情報の取得
- キャッシング機能によるAPIリクエスト最適化

## インストール方法

```bash
# GitHubからクローン
git clone https://github.com/あなたのユーザー名/vndb-mcp.git
cd vndb-mcp

# 依存関係のインストール
pip install -e .
