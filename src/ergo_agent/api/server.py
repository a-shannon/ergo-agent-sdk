import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ergo_agent.api.routes import router
from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.defi.privacy_client import PrivacyPoolClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load configuration
    node_url = os.getenv("NODE_URL", "http://127.0.0.1:9052")
    explorer_url = os.getenv("EXPLORER_URL", "https://api-testnet.ergoplatform.com")
    api_key = os.getenv("API_KEY", "hello")
    wallet_address = os.getenv("WALLET_ADDRESS")

    if not wallet_address:
        print("WARNING: WALLET_ADDRESS not set in environment. API might fail on signing.")

    # Initialize Ergo dependencies
    node = ErgoNode(node_url, explorer_url, api_key)

    # We load the wallet if provided, otherwise the client might just use the node
    Wallet.from_node_wallet(wallet_address) if wallet_address else None

    privacy_client = PrivacyPoolClient(node=node)

    # Attach to app state
    app.state.privacy_client = privacy_client

    yield
    # Cleanup (if any)
    pass


app = FastAPI(
    title="Ergo Agent SDK - Privacy Pool API",
    description="REST API wrapping the privacy pool Privacy Pool SDK",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow CORS for easy frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(router)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
