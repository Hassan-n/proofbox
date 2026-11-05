import asyncio
import ipaddress
import json
import os
import socket
from urllib.parse import urlsplit

LOG_FILE = "/logs/proxy_events.jsonl"
LOG_LOCK = asyncio.Lock()
MAX_HEADER_BYTES = 65536


def is_blocked_ip(ip_text: str) -> bool:
    try:
        return not ipaddress.ip_address(ip_text).is_global
    except ValueError:
        return True


async def log_event(event: str, host: str, ip: str, detail: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = json.dumps(
        {"event": event, "host": host, "ip": ip, "detail": detail}
    ) + "\n"
    async with LOG_LOCK:
        with open(LOG_FILE, "a", encoding="utf-8") as log_file:
            log_file.write(entry)


async def resolve_and_check(host: str, port: int) -> str | None:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal:
        if not literal.is_global:
            await log_event(
                "network_blocked", host, host, f"Blocked non-public destination {host}:{port}"
            )
            return None
        return host

    if port not in (80, 443):
        await log_event(
            "network_blocked", host, "", f"Blocked disallowed destination port {port}"
        )
        return None
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as error:
        await log_event("network_blocked", host, "", f"DNS resolution failed: {error}")
        return None
    if not addresses:
        await log_event("network_blocked", host, "", "DNS returned no addresses")
        return None

    resolved = list(dict.fromkeys(info[4][0] for info in addresses))
    for address in resolved:
        if is_blocked_ip(address):
            await log_event(
                "network_blocked",
                host,
                address,
                f"Blocked {host}: DNS resolved to non-public address {address}",
            )
            return None
    await log_event("network_allowed", host, resolved[0], f"Allowed outbound {host}:{port}")
    return resolved[0]


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(16384):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        if not writer.is_closing():
            writer.close()


async def read_headers(reader: asyncio.StreamReader) -> list[bytes]:
    headers = []
    total = 0
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        total += len(line)
        if total > MAX_HEADER_BYTES:
            raise ValueError("Request headers exceed limit")
        if line in (b"\r\n", b"\n"):
            return headers
        if not line:
            raise ValueError("Unexpected end of request headers")
        headers.append(line)


async def reject(writer: asyncio.StreamWriter, status: str, detail: str) -> None:
    body = (detail + "\n").encode("utf-8")
    writer.write(
        f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    await writer.drain()
    writer.close()


async def handle_client(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
) -> None:
    remote_writer = None
    try:
        request_line = await asyncio.wait_for(client_reader.readline(), timeout=10)
        parts = request_line.decode("latin-1").strip().split(" ", 2)
        if len(parts) != 3:
            await reject(client_writer, "400 Bad Request", "Malformed request line")
            return
        method, target, version = parts
        headers = await read_headers(client_reader)

        if method.upper() == "CONNECT":
            parsed = urlsplit("//" + target)
            host = parsed.hostname or ""
            port = parsed.port or 443
            if not host or port != 443:
                await reject(client_writer, "403 Forbidden", "Only HTTPS tunnels on port 443 are allowed")
                return
            destination = await resolve_and_check(host, port)
            if not destination:
                await reject(client_writer, "403 Forbidden", "Blocked by Proofbox egress policy")
                return
            _, remote_writer = await asyncio.open_connection(destination, port)
            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()
        else:
            parsed = urlsplit(target)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if (
                parsed.scheme not in ("http", "https")
                or not host
                or parsed.username is not None
                or parsed.password is not None
            ):
                await reject(client_writer, "400 Bad Request", "Expected an absolute HTTP URL")
                return
            if parsed.scheme == "https" or method.upper() not in {"GET", "HEAD"}:
                await log_event(
                    "network_blocked", host, "", f"Blocked unsupported proxy request method {method}"
                )
                await reject(client_writer, "403 Forbidden", "Blocked by Proofbox egress policy")
                return
            destination = await resolve_and_check(host, port)
            if not destination:
                await reject(client_writer, "403 Forbidden", "Blocked by Proofbox egress policy")
                return
            remote_reader, remote_writer = await asyncio.open_connection(destination, port)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            remote_writer.write(f"{method} {path} {version}\r\n".encode("latin-1"))
            for header in headers:
                if not header.lower().startswith(b"proxy-connection:"):
                    remote_writer.write(header)
            remote_writer.write(b"Connection: close\r\n\r\n")
            await remote_writer.drain()
            await asyncio.gather(pipe(remote_reader, client_writer), pipe(client_reader, remote_writer))
            return

        remote_reader = await asyncio.open_connection(destination, port)
        remote_reader, remote_writer = remote_reader
        await asyncio.gather(pipe(client_reader, remote_writer), pipe(remote_reader, client_writer))
    except (asyncio.TimeoutError, ValueError, UnicodeError, OSError) as error:
        if not client_writer.is_closing():
            await reject(client_writer, "400 Bad Request", str(error))
    finally:
        if remote_writer and not remote_writer.is_closing():
            remote_writer.close()
        if not client_writer.is_closing():
            client_writer.close()


async def main() -> None:
    server = await asyncio.start_server(handle_client, "0.0.0.0", 3128)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())