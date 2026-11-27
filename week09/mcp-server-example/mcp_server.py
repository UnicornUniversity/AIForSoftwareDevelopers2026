#!/usr/bin/env python3
"""
Minimal MCP Server in Python

Exposes 1 tool via Model Context Protocol:
- get_weather(city) - Returns fake weather data

Usage:
    python mcp_server.py

Then send JSON-RPC requests via stdin.
"""

import json
import sys
import logging

logging.basicConfig(level=logging.DEBUG, filename='mcp_server.log')

# Tool definitions (JSON Schema format)
TOOLS = [
    {
        "name": "get_weather",
        "description": "Get current weather for a city",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name"
                }
            },
            "required": ["city"]
        }
    }
]


def get_weather(city: str) -> dict:
    """
    Fake weather API.

    In production, call a real API (OpenWeatherMap, etc.)
    """
    return {
        "city": city,
        "temperature": 22,
        "condition": "sunny",
        "humidity": 60,
        "wind_speed": 10
    }


def handle_request(request: dict) -> dict:
    """
    Handle MCP JSON-RPC request.

    Supported methods:
    - initialize: Handshake
    - tools/list: List available tools
    - tools/call: Execute a tool
    """
    method = request.get("method")
    params = request.get("params", {})
    request_id = request.get("id")

    logging.debug(f"Received request: {method}")

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "weather-server",
                    "version": "1.0.0"
                }
            }

        elif method == "tools/list":
            result = {"tools": TOOLS}

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            logging.debug(f"Calling tool: {tool_name} with args: {args}")

            if tool_name == "get_weather":
                content = get_weather(args["city"])
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unknown tool: {tool_name}"
                    }
                }

            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(content)
                    }
                ]
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown method: {method}"
                }
            }

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        }

    except Exception as e:
        logging.error(f"Error handling request: {e}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": str(e)
            }
        }


def main():
    """
    Main loop: read JSON-RPC from stdin, write responses to stdout.
    """
    logging.info("MCP Server started")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            response = handle_request(request)
            print(json.dumps(response))
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                }
            }
            print(json.dumps(error_response))
            sys.stdout.flush()


if __name__ == "__main__":
    main()
