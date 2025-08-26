# helper.py
from dataclasses import dataclass
from typing import Optional, Tuple
import socket


@dataclass
class Endpoint:
    ip_address: str
    port: int


def send_message(
    message: str,
    endpoint: Endpoint,
    protocol: str='TCP',
    timeout_seconds: Optional[float]=5.0,
    encoding: str='utf-8') -> None:
    """
    Send a text message to an endpoint using TCP or UDP.

    - TCP: connect, send all, shutdown write side (best-effort), close.
    - UDP: send one datagram.
    """
    if protocol == 'TCP':
        sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        try:
            if timeout_seconds is not None:
                sock.settimeout(timeout_seconds)
            sock.connect((endpoint.ip_address, endpoint.port))
            sock.sendall(message.encode(encoding, errors='strict'))
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        finally:
            sock.close()

    elif protocol == 'UDP':
        sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        try:
            if timeout_seconds is not None:
                sock.settimeout(timeout_seconds)
            sock.sendto(message.encode(encoding, errors='strict'),
                        (endpoint.ip_address, endpoint.port))
        finally:
            sock.close()

    else:
        raise ValueError(f"Unsupported protocol: {protocol!r} (expected 'TCP' or 'UDP')")


def listen_for_message(
    endpoint: Endpoint,
    protocol: str='TCP',
    backlog: int=1,
    bufsize: int=65536,
    timeout_seconds: Optional[float]=None,
    encoding: str='utf-8') -> Optional[str]:
    """
    Receive a single message and return it as text.
    Returns None on timeout.

    - TCP: bind, listen, accept one connection, read until EOF, return text.
    - UDP: bind, receive one datagram, return text.
    """
    if protocol == 'TCP':
        server_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        try:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((endpoint.ip_address, endpoint.port))
            server_socket.listen(backlog)
            if timeout_seconds is not None:
                server_socket.settimeout(timeout_seconds)

            try:
                connection, _address = server_socket.accept()
            except socket.timeout:
                return None

            try:
                if timeout_seconds is not None:
                    connection.settimeout(timeout_seconds)
                chunks: list[bytes] = []
                while True:
                    try:
                        data = connection.recv(bufsize)
                    except socket.timeout:
                        return None
                    if not data:
                        break
                    chunks.append(data)
                return b''.join(chunks).decode(encoding, errors='replace')
            finally:
                connection.close()
        finally:
            server_socket.close()

    elif protocol == 'UDP':
        sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        try:
            sock.bind((endpoint.ip_address, endpoint.port))
            if timeout_seconds is not None:
                sock.settimeout(timeout_seconds)
            try:
                data, _address = sock.recvfrom(bufsize)
            except socket.timeout:
                return None
            return data.decode(encoding, errors='replace')
        finally:
            sock.close()

    else:
        raise ValueError(f"Unsupported protocol: {protocol!r} (expected 'TCP' or 'UDP')")
    
    return


def parse_message(text: str) -> Tuple[str, int, str]:
    """
    Parse a message in the form: "[<ip>:<port>] <payload>"
    Returns (ip_address, port, payload_text).

    Examples:
      "[127.0.0.1:5000] hello" -> ("127.0.0.1", 5000, "hello")
    """
    text = text.strip()
    if not text.startswith('[') or ']' not in text:
        raise ValueError(f'Invalid message format: {text!r}')
    header, payload = text.split(']', maxsplit=1)
    header = header[1:]  # drop leading '['
    if ':' not in header:
        raise ValueError(f'Invalid header (missing colon): {header!r}')
    ip_address, port_str = header.split(':', maxsplit=1)
    ip_address = ip_address.strip()
    port = int(port_str.strip())
    payload = payload.lstrip()
    return ip_address, port, payload
