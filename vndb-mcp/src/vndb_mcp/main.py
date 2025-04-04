"""Main entry point for the VNDB MCP server."""
import asyncio
from vndb_mcp.server import main

if __name__ == "__main__":
    asyncio.run(main())