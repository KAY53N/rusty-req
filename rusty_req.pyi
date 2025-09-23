"""
Type stubs for rusty-req library.
This file provides auto-completion and type hints for IDEs.
"""

from typing import Optional, Dict, Any, List, Union
import asyncio

class ProxyConfig:
    """Proxy configuration for requests."""

    def __init__(
            self,
            http: Optional[str] = None,
            https: Optional[str] = None,
            all: Optional[str] = None,
            no_proxy: Optional[List[str]] = None,
            username: Optional[str] = None,
            password: Optional[str] = None,
            trust_env: Optional[bool] = None
    ) -> None: ...

class HttpVersion:
    """HTTP version enumeration."""

    # 枚举值
    AUTO: str
    HTTP1_1: str
    HTTP2: str

class ConcurrencyMode:
    """Concurrency mode enumeration."""

    # 枚举值
    SELECT_ALL: str
    JOIN_ALL: str

class SslVerify:
    """SSL verification configuration."""

    def __init__(self, verify: bool = True) -> None: ...

class RequestItem:
    """Represents a single HTTP request."""

    def __init__(
            self,
            url: str,
            method: str,
            params: Optional[Dict[str, Any]] = None,
            headers: Optional[Dict[str, str]] = None,
            tag: str = "",
            timeout: float = 30.0,
            ssl_verify: bool = True,
            http_version: Optional[HttpVersion] = None,
            proxy: Optional[ProxyConfig] = None
    ) -> None: ...

async def fetch_single(
        url: str,
        method: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
        tag: Optional[str] = None,
        proxy: Optional[ProxyConfig] = None,
        http_version: Optional[HttpVersion] = None,
        ssl_verify: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Send a single asynchronous HTTP request.

    Args:
        url: The target URL to send the request to
        method: HTTP method (GET, POST, PUT, DELETE). Defaults to GET
        params: Request parameters. For GET/DELETE: URL query parameters.
                For POST/PUT/PATCH: JSON body
        timeout: Request timeout in seconds. Defaults to 30.0
        headers: Custom HTTP headers
        tag: Arbitrary tag to identify the request
        proxy: Proxy configuration for this request
        http_version: HTTP version preference
        ssl_verify: SSL certificate verification. Defaults to True

    Returns:
        Dictionary containing response data with keys:
        - http_status: HTTP status code
        - response: Response content and headers
        - meta: Metadata including processing time and tag
        - exception: Exception information if request failed
    """
    ...

async def fetch_requests(
        requests: List[RequestItem],
        total_timeout: Optional[float] = None,
        mode: Optional[ConcurrencyMode] = None
) -> List[Dict[str, Any]]:
    """
    Send multiple HTTP requests concurrently.

    Args:
        requests: List of RequestItem objects
        total_timeout: Global timeout for the entire batch
        mode: Concurrency strategy (SELECT_ALL or JOIN_ALL)

    Returns:
        List of response dictionaries with the same structure as fetch_single
    """
    ...

def set_debug(enabled: bool, log_file: Optional[str] = None) -> None:
    """
    Enable or disable debug mode.

    Args:
        enabled: Whether to enable debug mode
        log_file: Optional log file path for writing debug logs
    """
    ...

async def set_global_proxy(proxy: ProxyConfig) -> None:
    """
    Set global proxy configuration for all requests.

    Args:
        proxy: Proxy configuration
    """
    ...

# Response type definitions (基于你的实际返回结构)
ResponseHeaders = Dict[str, str]

class ResponseContent:
    """Response content structure."""
    headers: ResponseHeaders
    content: str

class RequestMeta:
    """Request metadata."""
    process_time: str
    request_time: str
    tag: Optional[str]

class RequestException:
    """Exception information."""
    type: str
    message: str

class SingleResponse:
    """Structure of a single response."""
    http_status: int
    response: ResponseContent
    meta: RequestMeta
    exception: Optional[RequestException]

# Module-level attributes
__version__: str