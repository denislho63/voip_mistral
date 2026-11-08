"""Generic remote service framework.

This module provides a base class for creating remote services that can be
called by the phone-stream server. It handles:
- HTTP server setup with FastAPI
- Authentication via token or IP whitelist
- JSON request/response handling
- Error handling and logging

To create a new service:
1. Subclass RemoteService
2. Implement the process() method
3. Optionally override __init__ to set custom configuration
4. Run with: python my_service.py

Example:
    class MyService(RemoteService):
        ALLOWED_IPS = ["127.0.0.1", "192.168.1.100"]
        TOKEN = "my-secret-token"

        def process(self, data: dict) -> dict:
            text = data.get("realtime_text", "")
            return {"response": f"You said: {text}"}

    if __name__ == "__main__":
        MyService.run()
"""

from __future__ import annotations

import json
import logging
from typing import ClassVar

# Try to import FastAPI and uvicorn
try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    FastAPI = None
    HTTPException = None
    Request = None
    status = None
    JSONResponse = None

log = logging.getLogger("phone-stream.remote")


class RemoteService:
    """Base class for remote services.

    Provides authentication (token or IP-based) and JSON request/response handling.
    Subclasses should implement the process() method to handle domain-specific logic.

    Configuration:
    - Set ALLOWED_IPS class variable to a list of allowed IP addresses
    - Set TOKEN class variable to the expected authorization token
    - If both are set, token takes precedence over IP
    - If neither is set, all requests are accepted (not recommended for production)

    Request format (JSON):
    {
        "realtime_text": "...",
        "batch_text": "...",
        "client_id": "...",
        "domain": "...",
        "history": [...]
    }

    Response format (JSON):
    {
        "response": "...",
        "text": "...",  // alternative field names also supported
        ...
    }

    Dependencies:
    - Requires FastAPI and uvicorn for HTTP server functionality
    - Install with: pip install fastapi uvicorn[standard]
    """

    # Authentication configuration - override in subclasses
    ALLOWED_IPS: ClassVar[list[str]] = []
    TOKEN: str = ""

    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    def __init__(self):
        """Initialize the service."""
        if not FASTAPI_AVAILABLE:
            raise ImportError(
                "FastAPI and uvicorn are required for remote services. "
                "Install them with: pip install fastapi uvicorn[standard]"
            )

        self.app = FastAPI(title=self.__class__.__name__)

        # Add CORS middleware for development
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        )

        # Register routes
        self._setup_routes()

    def _setup_routes(self):
        """Setup FastAPI routes."""

        @self.app.post("/")
        @self.app.post("/process")
        async def handle_request(request: Request):
            """Handle incoming POST requests."""
            return await self._handle_request(request)

        # Health check endpoint
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return JSONResponse(
                content={"status": "ok", "service": self.__class__.__name__},
                status_code=status.HTTP_200_OK,
            )

    async def _handle_request(self, request: Request) -> JSONResponse:
        """Handle an incoming request with authentication."""
        # Check client IP
        client_ip = self._get_client_ip(request)

        # Verify authentication
        if not self._verify_auth(request, client_ip):
            log.warning("Unauthorized request from IP: %s", client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
            )

        # Parse JSON payload
        try:
            data = await request.json()
            log.debug(
                "Received data from %s: %s",
                client_ip,
                json.dumps(data, ensure_ascii=False)[:200],
            )
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON from %s: %s", client_ip, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON",
            ) from exc

        # Process the request
        try:
            result = self.process(data)
            log.debug("Processed successfully for %s", client_ip)
            return JSONResponse(content=result, status_code=status.HTTP_200_OK)
        except Exception as exc:
            log.error("Processing error for %s: %s", client_ip, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request."""
        # Try various headers that might contain the real client IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # X-Forwarded-For can contain multiple IPs, take the first
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to client host
        client = request.client
        if client:
            return client.host

        return "unknown"

    def _verify_auth(self, request: Request, client_ip: str) -> bool:
        """Verify authentication via token or IP whitelist."""
        # Check token first (Bearer authentication)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer ") :].strip()
            if self.TOKEN and token == self.TOKEN:
                return True

        # Check IP whitelist
        if client_ip in self.ALLOWED_IPS:
            return True

        # If no token configured and no IPs whitelisted, accept all (dev mode)
        if not self.TOKEN and not self.ALLOWED_IPS:
            log.warning(
                "No authentication configured - accepting all requests (dev mode)"
            )
            return True

        return False

    def process(self, data: dict) -> dict:
        """Process the incoming data and return a response.

        Subclasses MUST override this method to implement service-specific logic.

        Args:
            data: Dictionary containing request parameters:
                - realtime_text: str
                - batch_text: str
                - client_id: str
                - domain: str
                - history: list[dict]

        Returns:
            Dictionary with response. Common field names:
                - response: str (primary)
                - text: str
                - answer: str
                - result: str
                - output: str
        """
        raise NotImplementedError("Subclasses must implement process() method")

    @classmethod
    def run(cls, host: str | None = None, port: int | None = None):
        """Run the service as a standalone HTTP server.

        Args:
            host: Server host (default: HOST class variable)
            port: Server port (default: PORT class variable)
        """
        service = cls()
        run_host = host or cls.HOST
        run_port = port or cls.PORT

        log.info("Starting %s on %s:%d", cls.__name__, run_host, run_port)
        uvicorn.run(
            service.app,
            host=run_host,
            port=run_port,
            log_level="info",
        )
