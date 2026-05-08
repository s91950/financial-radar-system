"""SSRF 防禦：驗證 URL 是否安全可從伺服器端對外抓取。

封鎖私網段 / loopback / link-local / 多播等內部 IP 範圍，
避免使用者送入的 URL 被用來掃內網或打 GCP metadata service
(169.254.169.254)。

使用方式：
    if not await is_safe_public_url(url):
        # 拒絕
        ...
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}


def _ip_is_private_or_special(ip_str: str) -> bool:
    """判斷 IP 是否屬於不該由伺服器主動連的私有 / 特殊範圍。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 無法解析就視為不安全
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def is_safe_public_url(url: str) -> bool:
    """檢查 URL 是否安全可向外抓取。

    流程：
      1. 必須是 http / https
      2. 必須有 hostname
      3. DNS 解析所有結果（IPv4+IPv6），任一筆指向私網段就拒絕
         （避免 DNS rebinding 與「主機名解析到 127.0.0.1」這類繞過）
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False
    host = parsed.hostname
    if not host:
        return False

    # 若 host 直接就是 IP，直接判斷
    try:
        ipaddress.ip_address(host)
        if _ip_is_private_or_special(host):
            logger.warning("SSRF guard 阻擋私網段 URL: %s", url)
            return False
        return True
    except ValueError:
        pass  # 不是 IP，往下做 DNS 解析

    # DNS 解析（在 executor 跑避免阻塞 event loop）
    try:
        loop = asyncio.get_event_loop()
        infos = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM),
        )
    except Exception as e:
        logger.warning("SSRF guard DNS 解析失敗 %s: %s", url, e)
        return False

    for info in infos:
        ip_str = info[4][0]
        if _ip_is_private_or_special(ip_str):
            logger.warning("SSRF guard 阻擋私網段 URL: %s -> %s", url, ip_str)
            return False
    return True
