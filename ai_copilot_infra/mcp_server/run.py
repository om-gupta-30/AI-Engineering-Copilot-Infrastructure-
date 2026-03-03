import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "ai_copilot_infra.mcp_server.app:app",
        host="0.0.0.0",
        port=8100,
        reload=True,
    )
