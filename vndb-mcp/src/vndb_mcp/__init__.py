"""VNDB MCP（Model-Controller-Presenter）パッケージ。

このパッケージは、Visual Novel Database（VNDB）と構造化されたAPI
インターフェースを通じて対話するためのサーバー実装を提供します。
"""

from . import server
import asyncio
import logging
import sys

# パッケージのバージョン情報
__version__ = '0.2.0'

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """VNDB MCPサーバーを実行します。
    
    これはパッケージのメインエントリーポイントであり、適切なエラー処理を
    備えたサーバープロセスを設定して起動します。
    
    戻り値:
        int: 終了コード（0は成功、0以外は失敗）
    """
    try:
        logger.info(f"VNDB MCPサーバー v{__version__}を起動中")
        asyncio.run(server.main())
        return 0
    except KeyboardInterrupt:
        logger.info("ユーザーによる中断を検出しました")
        return 0
    except Exception as e:
        logger.error(f"サーバー実行中にエラーが発生しました: {e}", exc_info=True)
        return 1

# パッケージレベルでエクスポートする項目
__all__ = ['main', 'server', '__version__']