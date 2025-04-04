"""Main entry point for the VNDB MCP server.
This revised version includes cross-platform signal handling and modern asyncio patterns.
"""
import asyncio
import signal
import sys
import logging
import platform
from vndb_mcp.main import main as main_func

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def shutdown(signal_obj, loop):
    """シャットダウンシーケンスを処理する関数
    
    すべての実行中タスクをキャンセルし、イベントループを安全に停止します。
    """
    logger.info(f"Received exit signal {signal_obj.name if hasattr(signal_obj, 'name') else signal_obj}...")
    
    # 現在のタスク以外のすべてのタスクを取得
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    if tasks:
        logger.info(f"Cancelling {len(tasks)} outstanding tasks")
        # すべてのタスクをキャンセル
        for task in tasks:
            task.cancel()
        
        # キャンセルされたタスクの完了を待機
        await asyncio.gather(*tasks, return_exceptions=True)
    
    # イベントループが実行中であれば停止
    if loop.is_running():
        loop.stop()

async def main():
    """メインの非同期関数。
    
    例外処理を含むメイン処理を実装します。
    """
    try:
        logger.info("Starting VNDB MCP server")
        await main_func()
        return 0
    except Exception as e:
        logger.error(f"Error in main function: {e}", exc_info=True)
        return 1

def run():
    """サーバーを実行します。
    
    プラットフォームに応じたシグナルハンドリングとエラー管理を行います。
    """
    # 新しいイベントループを作成（非推奨のget_event_loopを避ける）
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # プラットフォームに応じたシグナルハンドリング
    if platform.system() != 'Windows':
        # UNIXシステム向けのシグナルハンドラー
        logger.info("Setting up UNIX signal handlers")
        for s in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown(s, loop))
            )
    else:
        # Windowsではadd_signal_handlerがサポートされていないため、
        # try-exceptブロックでKeyboardInterruptを捕捉
        logger.info("Running on Windows, using alternative signal handling")
    
    exit_code = 1
    try:
        # asyncio.runではなくrun_until_completeを使用
        # これにより、シグナルハンドリングとの互換性を確保
        exit_code = loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        # Windowsでのクリーンアップ処理
        loop.run_until_complete(shutdown("SIGINT (Ctrl+C)", loop))
        exit_code = 0
    finally:
        # イベントループに残っているタスクの確認
        pending = asyncio.all_tasks(loop)
        if pending:
            logger.info(f"Cleaning up {len(pending)} pending tasks...")
            # 残りのタスクのキャンセルと完了待機
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        
        logger.info("Shutting down event loop")
        loop.close()
    
    return exit_code

# 代替実装（最新のasyncioパターン）
def run_modern():
    """最新のasyncioパターンでサーバーを実行する代替関数。
    
    このバージョンは`asyncio.run()`を使用し、より簡潔ですが
    詳細なシグナル処理やShutdownの制御は行いません。
    """
    try:
        return asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        return 0

if __name__ == "__main__":
    # デフォルトの実行方法
    sys.exit(run())
    
    # 最新のasyncioパターンを使用する場合は上の行をコメントアウトして
    # 以下の行のコメントを解除してください
    # sys.exit(run_modern())

# エクスポートして、スクリプトからアクセスできるようにする
main_entry = run  # 旧来のmain = runを変更し、名前の衝突を避ける
