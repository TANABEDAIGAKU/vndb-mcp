import json
import asyncio
import time
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from pydantic import AnyUrl, validator
import mcp.server.stdio
from azaka import Client, Node, select
from typing import Dict, List, Optional, Any, Union, Tuple
import hashlib
import logging
from datetime import datetime, timedelta
import re

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("vndb-mcp")

class CacheManager:
    """キャッシュの管理とライフサイクル処理を行うクラス"""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        
    def get(self, key: str) -> Optional[Any]:
        """キーに対応する値を取得し、存在しない場合はNoneを返す"""
        if key not in self.cache:
            return None
            
        value, timestamp = self.cache[key]
        current_time = time.time()
        
        # TTLをチェック
        if current_time - timestamp > self.ttl_seconds:
            del self.cache[key]
            return None
            
        return value
        
    def set(self, key: str, value: Any) -> None:
        """キャッシュに値を設定する。サイズ制限を超えた場合は古いエントリを削除"""
        # キャッシュサイズを確認
        if len(self.cache) >= self.max_size and key not in self.cache:
            # 最も古いエントリを削除
            oldest_key = min(self.cache.items(), key=lambda x: x[1][1])[0]
            del self.cache[oldest_key]
            
        self.cache[key] = (value, time.time())
        
    def generate_key(self, prefix: str, *args) -> str:
        """引数からキャッシュキーを安全に生成する"""
        # 文字列の連結とハッシュ化
        key_parts = [prefix] + [str(arg) for arg in args]
        combined = ":".join(key_parts)
        
        # 長いキーの場合はハッシュを使用
        if len(combined) > 100:
            hashed = hashlib.md5(combined.encode()).hexdigest()
            return f"{prefix}:hash:{hashed}"
        return combined
        
    def clear_expired(self) -> int:
        """期限切れのキャッシュエントリをクリアし、削除された数を返す"""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if current_time - timestamp > self.ttl_seconds
        ]
        
        for key in expired_keys:
            del self.cache[key]
            
        return len(expired_keys)

class RateLimiter:
    """APIリクエストのレート制限を管理するクラス"""
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.request_timestamps: List[float] = []
        
    async def wait_if_needed(self) -> None:
        """必要な場合、リクエスト制限に達しないよう待機する"""
        current_time = time.time()
        
        # 最近60秒間のリクエストのみを保持
        self.request_timestamps = [
            ts for ts in self.request_timestamps 
            if current_time - ts < 60
        ]
        
        # リクエスト数が上限に達している場合は待機
        if len(self.request_timestamps) >= self.requests_per_minute:
            oldest_request = min(self.request_timestamps)
            wait_time = 60 - (current_time - oldest_request)
            
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting for {wait_time:.2f} seconds")
                await asyncio.sleep(wait_time)
                
        # 現在のリクエストを記録
        self.request_timestamps.append(time.time())

class NoteManager:
    """ノートの保存と管理を行うクラス"""
    
    def __init__(self):
        self.notes: Dict[str, str] = {}
        
    def add_note(self, name: str, content: str) -> None:
        """ノートを追加する"""
        self.notes[name] = content
        
    def get_note(self, name: str) -> Optional[str]:
        """ノートを取得する"""
        return self.notes.get(name)
        
    def list_notes(self) -> Dict[str, str]:
        """全てのノートを取得する"""
        return self.notes.copy()

class VNDBClient:
    """VNDBのAPIリクエストを処理するクラス"""
    
    def __init__(self, cache_manager: CacheManager, rate_limiter: RateLimiter):
        self.cache_manager = cache_manager
        self.rate_limiter = rate_limiter
        
    async def search_vn(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """検索クエリに基づいてビジュアルノベルを検索する"""
        # 入力バリデーション
        query = self._sanitize_input(query)
        limit = min(max(1, limit), 50)  # 1〜50の範囲に制限
        
        # キャッシュをチェック
        cache_key = self.cache_manager.generate_key("search", query, limit)
        cached_result = self.cache_manager.get(cache_key)
        
        if cached_result:
            return cached_result
        
        try:
            # レート制限の確認
            await self.rate_limiter.wait_if_needed()
            
            async with Client() as client:
                search_query = (
                    select("id", "title", "released", "image.url", "description", "rating")
                    .frm("vn")
                    .where(Node("search") == query)
                    .results(limit)
                )
                
                response = await client.execute(query=search_query)
                
                results = []
                for vn in response.results:
                    vn_data = {
                        "id": vn.id,
                        "title": vn.title,
                        "released": vn.released,
                        "description": getattr(vn, "description", None),
                        "rating": getattr(vn, "rating", None),
                        "image_url": vn.image["url"] if hasattr(vn, "image") and vn.image else None
                    }
                    results.append(vn_data)
                
                result_data = {
                    "results": results,
                    "count": len(results)
                }
                
                # キャッシュに保存
                self.cache_manager.set(cache_key, result_data)
                return result_data
                
        except ConnectionError as e:
            logger.error(f"Connection error when searching VNs: {str(e)}")
            return {"error": "Connection error", "details": str(e)}
        except TimeoutError as e:
            logger.error(f"Timeout when searching VNs: {str(e)}")
            return {"error": "Request timed out", "details": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error when searching VNs: {str(e)}")
            return {"error": "Unexpected error", "details": str(e)}
    
    async def get_vn_details(self, vn_id: str) -> Dict[str, Any]:
        """指定されたIDのビジュアルノベルの詳細情報を取得する"""
        # 入力バリデーション
        vn_id = self._sanitize_input(vn_id)
        if not re.match(r'^v\d+$', vn_id):
            return {"error": "Invalid VN ID format. Expected format: 'v' followed by numbers (e.g. v17)"}
        
        # キャッシュをチェック
        cache_key = self.cache_manager.generate_key("vn", vn_id)
        cached_result = self.cache_manager.get(cache_key)
        
        if cached_result:
            return cached_result
        
        try:
            # レート制限の確認
            await self.rate_limiter.wait_if_needed()
            
            async with Client() as client:
                detail_query = (
                    select("title", "aliases", "image.url", "length", "description", 
                          "rating", "languages", "platforms", "tags.name")
                    .frm("vn")
                    .where(Node("id") == vn_id)
                )
                
                response = await client.execute(query=detail_query)
                
                if not response.results:
                    logger.warning(f"Visual novel with ID {vn_id} not found")
                    return {"error": f"Visual novel with ID {vn_id} not found"}
                
                vn = response.results[0]
                
                # レスポンスを整形
                vn_data = {
                    "id": vn_id,
                    "title": vn.title,
                    "aliases": vn.aliases if hasattr(vn, "aliases") else [],
                    "image_url": vn.image["url"] if hasattr(vn, "image") and vn.image else None,
                    "length": vn.length if hasattr(vn, "length") else None,
                    "description": vn.description if hasattr(vn, "description") else None,
                    "rating": vn.rating if hasattr(vn, "rating") else None,
                    "languages": vn.languages if hasattr(vn, "languages") else [],
                    "platforms": vn.platforms if hasattr(vn, "platforms") else [],
                    "tags": [tag["name"] for tag in vn.tags] if hasattr(vn, "tags") else []
                }
                
                # キャッシュに保存
                self.cache_manager.set(cache_key, vn_data)
                return vn_data
                
        except ConnectionError as e:
            logger.error(f"Connection error when getting VN details: {str(e)}")
            return {"error": "Connection error", "details": str(e)}
        except TimeoutError as e:
            logger.error(f"Timeout when getting VN details: {str(e)}")
            return {"error": "Request timed out", "details": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error when getting VN details: {str(e)}")
            return {"error": "Unexpected error", "details": str(e)}
    
    def _sanitize_input(self, input_str: str) -> str:
        """入力を安全に処理するためのサニタイズ関数"""
        # 基本的なサニタイズ処理
        return input_str.strip()

class VNDBServer:
    """MCPサーバーの主要な機能を提供するクラス"""
    
    def __init__(self):
        self.server = Server("vndb-mcp")
        self.cache_manager = CacheManager()
        self.rate_limiter = RateLimiter()
        self.note_manager = NoteManager()
        self.vndb_client = VNDBClient(self.cache_manager, self.rate_limiter)
        
        # 定期的なキャッシュクリーンアップのタスク
        self.cleanup_task = None
        
        # サーバー関数を設定
        self._setup_server_handlers()
        
    def _setup_server_handlers(self):
        """サーバーのハンドラ関数を設定する"""
        self.server.list_resources(self._handle_list_resources)
        self.server.read_resource(self._handle_read_resource)
        self.server.list_prompts(self._handle_list_prompts)
        self.server.get_prompt(self._handle_get_prompt)
        self.server.list_tools(self._handle_list_tools)
        self.server.call_tool(self._handle_call_tool)
        
    async def run(self):
        """サーバーを実行する"""
        # キャッシュクリーンアップタスクを開始
        self.cleanup_task = asyncio.create_task(self._periodic_cache_cleanup())
        
        try:
            # サーバーを実行
            async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="vndb-mcp",
                        server_version="0.2.0",
                        capabilities=self.server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )
        finally:
            # クリーンアップタスクをキャンセル
            if self.cleanup_task:
                self.cleanup_task.cancel()
                try:
                    await self.cleanup_task
                except asyncio.CancelledError:
                    pass
    
    async def _periodic_cache_cleanup(self):
        """定期的にキャッシュをクリーンアップするタスク"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分ごとに実行
                cleared_count = self.cache_manager.clear_expired()
                if cleared_count > 0:
                    logger.info(f"Cleared {cleared_count} expired cache entries")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error during cache cleanup: {str(e)}")
    
    async def _handle_list_resources(self) -> List[types.Resource]:
        """利用可能なノートリソースをリストする"""
        return [
            types.Resource(
                uri=AnyUrl(f"note://internal/{name}"),
                name=f"Note: {name}",
                description=f"A simple note named {name}",
                mimeType="text/plain",
            )
            for name in self.note_manager.list_notes()
        ]
    
    async def _handle_read_resource(self, uri: AnyUrl) -> str:
        """特定のノートの内容をURIから読み取る"""
        if uri.scheme != "note":
            raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

        name = uri.path
        if name is not None:
            name = name.lstrip("/")
            note_content = self.note_manager.get_note(name)
            if note_content:
                return note_content
        raise ValueError(f"Note not found: {name}")
    
    async def _handle_list_prompts(self) -> List[types.Prompt]:
        """利用可能なプロンプトをリストする"""
        return [
            types.Prompt(
                name="summarize-notes",
                description="Creates a summary of all notes",
                arguments=[
                    types.PromptArgument(
                        name="style",
                        description="Style of the summary (brief/detailed)",
                        required=False,
                    )
                ],
            )
        ]
    
    async def _handle_get_prompt(
        self, name: str, arguments: Dict[str, str] | None
    ) -> types.GetPromptResult:
        """引数をサーバー状態と組み合わせてプロンプトを生成する"""
        if name != "summarize-notes":
            raise ValueError(f"Unknown prompt: {name}")

        style = (arguments or {}).get("style", "brief")
        detail_prompt = " Give extensive details." if style == "detailed" else ""

        notes_list = self.note_manager.list_notes()
        
        return types.GetPromptResult(
            description="Summarize the current notes",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=f"Here are the current notes to summarize:{detail_prompt}\n\n"
                        + "\n".join(
                            f"- {name}: {content}" for name, content in notes_list.items()
                        ),
                    ),
                )
            ],
        )
    
    async def _handle_list_tools(self) -> List[types.Tool]:
        """利用可能なツールをリストする"""
        return [
            types.Tool(
                name="add-note",
                description="Add a new note",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["name", "content"],
                },
            ),
            types.Tool(
                name="search-vn",
                description="Search for visual novels based on a query term",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Title or keywords to search for"},
                        "limit": {"type": "integer", "description": "Maximum number of results to return (default: 10, max: 50)"}
                    },
                    "required": ["query"]
                }
            ),
            types.Tool(
                name="get-vn-details",
                description="Get detailed information about a visual novel by its ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "The ID of the visual novel (e.g. v17)"}
                    },
                    "required": ["id"]
                }
            )
        ]
    
    async def _handle_call_tool(
        self, name: str, arguments: Dict | None
    ) -> List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]:
        """ツール実行リクエストを処理する"""
        if name == "add-note":
            return await self._handle_add_note(arguments)
        elif name == "search-vn":
            return await self._handle_search_vn(arguments)
        elif name == "get-vn-details":
            return await self._handle_get_vn_details(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    async def _handle_add_note(self, arguments: Dict | None) -> List[types.TextContent]:
        """add-noteツールの処理ロジック"""
        if not arguments:
            raise ValueError("Missing arguments")
            
        note_name = arguments.get("name")
        content = arguments.get("content")
        
        if not note_name or not content:
            raise ValueError("Missing name or content")
            
        # サーバー状態を更新
        self.note_manager.add_note(note_name, content)
        
        # クライアントにリソースが変更されたことを通知
        await self.server.request_context.session.send_resource_list_changed()
        
        return [
            types.TextContent(
                type="text",
                text=f"Added note '{note_name}' with content: {content}",
            )
        ]
    
    async def _handle_search_vn(self, arguments: Dict | None) -> List[types.TextContent]:
        """search-vnツールの処理ロジック"""
        if not arguments:
            raise ValueError("Missing arguments")
            
        query = arguments.get("query")
        limit = int(arguments.get("limit", 10))
        
        if not query:
            raise ValueError("Missing query parameter")
            
        results = await self.vndb_client.search_vn(query, limit)
        
        return [
            types.TextContent(
                type="text",
                text=json.dumps(results, ensure_ascii=False, indent=2),
            )
        ]
    
    async def _handle_get_vn_details(self, arguments: Dict | None) -> List[types.TextContent]:
        """get-vn-detailsツールの処理ロジック"""
        if not arguments:
            raise ValueError("Missing arguments")
            
        vn_id = arguments.get("id")
        
        if not vn_id:
            raise ValueError("Missing id parameter")
            
        details = await self.vndb_client.get_vn_details(vn_id)
        
        return [
            types.TextContent(
                type="text",
                text=json.dumps(details, ensure_ascii=False, indent=2),
            )
        ]

async def main():
    # サーバーインスタンスを作成して実行
    server = VNDBServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())