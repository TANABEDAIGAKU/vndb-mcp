import json
import asyncio
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from pydantic import AnyUrl
import mcp.server.stdio
# VNDB APIクライアント用のインポートを追加
from azaka import Client, Node, select

# Store notes as a simple key-value dict to demonstrate state management
notes: dict[str, str] = {}

# VNDBキャッシュ用の辞書を追加
vndb_cache: dict[str, dict] = {}

server = Server("vndb-mcp")

@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """ List available note resources. Each note is exposed as a resource with a custom note:// URI scheme. """
    return [
        types.Resource(
            uri=AnyUrl(f"note://internal/{name}"),
            name=f"Note: {name}",
            description=f"A simple note named {name}",
            mimeType="text/plain",
        )
        for name in notes
    ]

@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """ Read a specific note's content by its URI. The note name is extracted from the URI host component. """
    if uri.scheme != "note":
        raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

    name = uri.path
    if name is not None:
        name = name.lstrip("/")
        return notes[name]
    raise ValueError(f"Note not found: {name}")

@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """ List available prompts. Each prompt can have optional arguments to customize its behavior. """
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

@server.get_prompt()
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    """ Generate a prompt by combining arguments with server state. The prompt includes all current notes and can be customized via arguments. """
    if name != "summarize-notes":
        raise ValueError(f"Unknown prompt: {name}")

    style = (arguments or {}).get("style", "brief")
    detail_prompt = " Give extensive details." if style == "detailed" else ""

    return types.GetPromptResult(
        description="Summarize the current notes",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=f"Here are the current notes to summarize:{detail_prompt}\n\n"
                    + "\n".join(
                        f"- {name}: {content}" for name, content in notes.items()
                    ),
                ),
            )
        ],
    )

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """ List available tools. Each tool specifies its arguments using JSON Schema validation. """
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
        # VNDBの検索ツールを追加
        types.Tool(
            name="search-vn",
            description="検索クエリに基づいてビジュアルノベルを検索します",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索するタイトルやキーワード"},
                    "limit": {"type": "integer", "description": "返す結果の最大数（デフォルト: 10）"}
                },
                "required": ["query"]
            }
        ),
        # VNDBの詳細情報取得ツールを追加
        types.Tool(
            name="get-vn-details",
            description="指定されたIDのビジュアルノベルの詳細情報を取得します",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "ビジュアルノベルのID（例: v17）"}
                },
                "required": ["id"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """ Handle tool execution requests. Tools can modify server state and notify clients of changes. """
    
    if name == "add-note":
        if not arguments:
            raise ValueError("Missing arguments")
            
        note_name = arguments.get("name")
        content = arguments.get("content")
        
        if not note_name or not content:
            raise ValueError("Missing name or content")
            
        # Update server state
        notes[note_name] = content
        
        # Notify clients that resources have changed
        await server.request_context.session.send_resource_list_changed()
        
        return [
            types.TextContent(
                type="text",
                text=f"Added note '{note_name}' with content: {content}",
            )
        ]
    
    # VNDB検索機能を追加
    elif name == "search-vn":
        if not arguments:
            raise ValueError("Missing arguments")
            
        query = arguments.get("query")
        limit = arguments.get("limit", 10)
        
        if not query:
            raise ValueError("Missing query parameter")
            
        results = await search_vn(query, limit)
        
        return [
            types.TextContent(
                type="text",
                text=json.dumps(results, ensure_ascii=False, indent=2),
            )
        ]
    
    # VNDB詳細情報取得機能を追加
    elif name == "get-vn-details":
        if not arguments:
            raise ValueError("Missing arguments")
            
        vn_id = arguments.get("id")
        
        if not vn_id:
            raise ValueError("Missing id parameter")
            
        details = await get_vn_details(vn_id)
        
        return [
            types.TextContent(
                type="text",
                text=json.dumps(details, ensure_ascii=False, indent=2),
            )
        ]
    
    else:
        raise ValueError(f"Unknown tool: {name}")

async def search_vn(query: str, limit: int = 10) -> dict:
    """検索クエリに基づいてビジュアルノベルを検索します"""
    
    # キャッシュをチェック
    cache_key = f"search:{query}:{limit}"
    if cache_key in vndb_cache:
        return vndb_cache[cache_key]
    
    try:
        async with Client() as client:
            search_query = (
                select("id", "title", "released", "image.url")
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
                    "image_url": vn.image["url"] if hasattr(vn, "image") and vn.image else None
                }
                results.append(vn_data)
            
            result_data = {
                "results": results,
                "count": len(results)
            }
            
            # キャッシュに保存
            vndb_cache[cache_key] = result_data
            return result_data
    except Exception as e:
        return {"error": str(e)}

async def get_vn_details(vn_id: str) -> dict:
    """指定されたIDのビジュアルノベルの詳細情報を取得します"""
    
    # キャッシュをチェック
    if f"vn:{vn_id}" in vndb_cache:
        return vndb_cache[f"vn:{vn_id}"]
    
    try:
        async with Client() as client:
            detail_query = (
                select("title", "aliases", "image.url", "length", "description", 
                      "rating", "languages", "platforms", "tags.name")
                .frm("vn")
                .where(Node("id") == vn_id)
            )
            
            response = await client.execute(query=detail_query)
            
            if not response.results:
                return {"error": f"Visual novel with ID {vn_id} not found"}
            
            vn = response.results[0]
            
            # レスポンスを整形
            vn_data = {
                "id": vn.id,
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
            vndb_cache[f"vn:{vn_id}"] = vn_data
            return vn_data
    except Exception as e:
        return {"error": str(e)}

async def main():
    # Run the server using stdin/stdout streams
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="vndb-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
