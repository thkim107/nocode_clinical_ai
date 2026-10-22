"""
Main entry point for the Word Document MCP Server.
Acts as the central controller for the MCP server that handles Word document operations.
"""

import os
import sys
from mcp.server.fastmcp import FastMCP
from word_document_server.tools import (
    document_tools,
    content_tools,
    format_tools,
    protection_tools,
    footnote_tools,
    extended_document_tools,
    prompt_tools
)



# Initialize FastMCP server
mcp = FastMCP(
    "word-document-tools",  # Name of the MCP server
    host="0.0.0.0",  # Host address (0.0.0.0 allows connections from any IP)
    # port=29501,  # Port number for the server
    stateless_http=True
)

def register_tools():
    """Register all tools with the MCP server."""
    # Document tools (create, copy, info, etc.)
    mcp.tool()(document_tools.create_document)
    mcp.tool()(document_tools.copy_document)
    mcp.tool()(document_tools.get_document_info)
    mcp.tool()(document_tools.get_document_text)
    mcp.tool()(document_tools.get_document_outline)
    mcp.tool()(document_tools.list_available_documents)
    
    # Content tools (paragraphs, headings, tables, etc.)
    mcp.tool()(content_tools.add_paragraph)
    mcp.tool()(content_tools.add_heading)
    mcp.tool()(content_tools.add_picture)
    mcp.tool()(content_tools.add_table)
    mcp.tool()(content_tools.add_page_break)
    mcp.tool()(content_tools.delete_paragraph)
    mcp.tool()(content_tools.search_and_replace)
    
    # Format tools (styling, text formatting, etc.)
    mcp.tool()(format_tools.create_custom_style)
    mcp.tool()(format_tools.format_text)
    mcp.tool()(format_tools.format_table)
    
    # Protection tools
    mcp.tool()(protection_tools.protect_document)
    mcp.tool()(protection_tools.unprotect_document)
    
    # Footnote tools
    mcp.tool()(footnote_tools.add_footnote_to_document)
    mcp.tool()(footnote_tools.add_endnote_to_document)
    # mcp.tool()(footnote_tools.convert_footnotes_to_endnotes_in_document)
    mcp.tool()(footnote_tools.customize_footnote_style)
    
    # Extended document tools
    mcp.tool()(extended_document_tools.get_paragraph_text_from_document)
    mcp.tool()(extended_document_tools.find_text_in_document)
    mcp.tool()(extended_document_tools.convert_to_pdf)

    # Prompt/Guideline tools
    mcp.tool()(prompt_tools.get_tripod_ai_guideline)


def run_server():
    """Run the Word Document MCP Server."""
    # Register all tools
    register_tools()
    
    # Run the server
    mcp.run(transport="streamable-http")
    return mcp

if __name__ == "__main__":
    run_server()
