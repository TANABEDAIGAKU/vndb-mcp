"""Main entry point for the VNDB MCP server."""
import asyncio
from vndb_mcp.main import main as main_func

def run():
    """Run the server."""
    asyncio.run(main_func())

if __name__ == "__main__":
    run()

# main関数をエクスポートして、スクリプトからアクセスできるようにする
main = run
