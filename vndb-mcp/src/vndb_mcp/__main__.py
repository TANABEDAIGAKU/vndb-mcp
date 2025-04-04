"""Main entry point for the VNDB MCP server."""
import asyncio
import signal
import sys
import logging
from vndb_mcp.main import main as main_func

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def shutdown(signal, loop):
    """シャットダウンシーケンスを処理する関数"""
    logger.info(f"Received exit signal {signal.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    logger.info(f"Cancelling {len(tasks)} outstanding tasks")
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

def run():
    """Run the server with proper signal handling and error management."""
    loop = asyncio.get_event_loop()
    
    # シグナルハンドラーの設定
    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            s, lambda s=s: asyncio.create_task(shutdown(s, loop))
        )
    
    try:
        logger.info("Starting VNDB MCP server")
        loop.run_until_complete(main_func())
    except Exception as e:
        logger.error(f"Error in main function: {e}", exc_info=True)
        return 1
    finally:
        logger.info("Shutting down")
        loop.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(run())

# エクスポートして、スクリプトからアクセスできるようにする
main = run
