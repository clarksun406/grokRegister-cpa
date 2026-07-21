# -*- coding: utf-8 -*-
"""本地代理转发器：解决 Chrome 不支持带认证代理的问题。

在本地开一个无认证端口，转发请求到上游带 user:pass 的代理。
支持 HTTP CONNECT 隧道（HTTPS）和普通 HTTP 转发。

Usage:
    from local_proxy import start_local_proxy, stop_local_proxy
    port = start_local_proxy("http://user:pass@1.2.3.4:3129")
    # Chrome 连 http://127.0.0.1:{port}
    stop_local_proxy()
"""
import socket, threading, select, base64
from urllib.parse import urlparse

_server_socket = None
_server_thread = None
_running = False


def _parse_upstream(proxy_url: str):
    parsed = urlparse(proxy_url)
    host = parsed.hostname
    port = parsed.port or 3129
    auth = ""
    if parsed.username:
        cred = f"{parsed.username}:{parsed.password or ''}"
        auth = base64.b64encode(cred.encode()).decode()
    return host, port, auth


def _tunnel(client_sock, upstream_host, upstream_port, auth):
    try:
        up_sock = socket.create_connection((upstream_host, upstream_port), timeout=15)
    except Exception:
        client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        client_sock.close()
        return

    if auth:
        up_sock.sendall(
            f"CONNECT {upstream_host}:{upstream_port} HTTP/1.1\r\n"
            f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode()
        )
    else:
        up_sock.sendall(
            f"CONNECT {upstream_host}:{upstream_port} HTTP/1.1\r\n\r\n".encode()
        )

    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = up_sock.recv(4096)
        if not chunk:
            break
        resp += chunk

    if b"200" not in resp.split(b"\r\n")[0]:
        client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        client_sock.close()
        up_sock.close()
        return

    client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

    _relay(client_sock, up_sock)


def _relay(sock_a, sock_b):
    sockets = [sock_a, sock_b]
    try:
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional:
                break
            if not readable:
                break
            for s in readable:
                data = s.recv(65536)
                if not data:
                    return
                target = sock_b if s is sock_a else sock_a
                target.sendall(data)
    except Exception:
        pass
    finally:
        try:
            sock_a.close()
        except Exception:
            pass
        try:
            sock_b.close()
        except Exception:
            pass


def _handle_http(client_sock, first_data, upstream_host, upstream_port, auth):
    try:
        up_sock = socket.create_connection((upstream_host, upstream_port), timeout=15)
        if auth:
            header_end = first_data.find(b"\r\n")
            if header_end > 0:
                inject = f"Proxy-Authorization: Basic {auth}\r\n".encode()
                first_data = first_data[:header_end + 2] + inject + first_data[header_end + 2:]
        up_sock.sendall(first_data)
        _relay(client_sock, up_sock)
    except Exception:
        try:
            client_sock.close()
        except Exception:
            pass


def _handle_client(client_sock, upstream_host, upstream_port, auth):
    try:
        first_data = client_sock.recv(65536)
        if not first_data:
            client_sock.close()
            return
        first_line = first_data.split(b"\r\n")[0].decode("utf-8", "replace")
        if first_line.upper().startswith("CONNECT"):
            parts = first_line.split()
            if len(parts) >= 2:
                target = parts[1]
                if ":" in target:
                    t_host, t_port = target.rsplit(":", 1)
                    _tunnel(client_sock, t_host, int(t_port), auth)
                else:
                    _tunnel(client_sock, target, 443, auth)
            else:
                client_sock.close()
        else:
            _handle_http(client_sock, first_data, upstream_host, upstream_port, auth)
    except Exception:
        try:
            client_sock.close()
        except Exception:
            pass


def start_local_proxy(proxy_url: str, listen_port: int = 0) -> int:
    global _server_socket, _server_thread, _running
    stop_local_proxy()

    upstream_host, upstream_port, auth = _parse_upstream(proxy_url)

    _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _server_socket.bind(("127.0.0.1", listen_port))
    _server_socket.listen(32)
    actual_port = _server_socket.getsockname()[1]
    _running = True

    def _serve():
        while _running:
            try:
                _server_socket.settimeout(1.0)
                try:
                    client, _ = _server_socket.accept()
                except socket.timeout:
                    continue
                t = threading.Thread(
                    target=_handle_client,
                    args=(client, upstream_host, upstream_port, auth),
                    daemon=True,
                )
                t.start()
            except OSError:
                break

    _server_thread = threading.Thread(target=_serve, daemon=True)
    _server_thread.start()
    return actual_port


def stop_local_proxy():
    global _server_socket, _server_thread, _running
    _running = False
    if _server_socket:
        try:
            _server_socket.close()
        except Exception:
            pass
        _server_socket = None
    _server_thread = None
