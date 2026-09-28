"""Discoverable MCP-style contracts for integrations."""
from fastapi import APIRouter

from mcp.registry import list_tools, manifest


router = APIRouter(prefix="/mcp", tags=["MCP"])


@router.get("/manifest")
def get_manifest():
    return manifest()


@router.get("/tools")
def get_tools():
    return list_tools()
