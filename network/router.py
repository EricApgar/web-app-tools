import os
import sys

from dataclasses import dataclass
from typing import Callable, List, Optional
import socket
import threading

repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(repo_dir)

from network.helper.helper import Endpoint, send_message


class Router:
    """
    A simple router that listens on one endpoint and forwards received messages
    to zero or more connections. Starts in a background thread and stops
    immediately by closing sockets (no polling / micro-timeouts).
    """

    def __init__(
        self,
        endpoint: Endpoint,
        connections: Optional[List[Endpoint]] = None,
        on_log: Optional[Callable[[str], None]] = None
    ) -> None:

        self.endpoint: Endpoint = endpoint
        self.connections: List[Endpoint] = list(connections) if connections is not None else []
        # Default to printing logs if no handler is provided
        self.on_log: Callable[[str], None] = on_log or print

        self._thread: Optional[threading.Thread] = None
        self._is_running: bool = False
        self._protocol: Optional[str] = None

        # Sockets maintained so stop() can close to unblock worker immediately
        self.server_socket: Optional[socket.socket] = None
        self._active_connection: Optional[socket.socket] = None
        self._lock: threading.Lock = threading.Lock()

        return

    @property
    def running(self) -> bool:
        """Public, read-only running state."""
        return self._is_running

    # Optional mutators if you want to manage connections at runtime
    def add_connections(self, endpoints: List[Endpoint]) -> None:

        # Don't add connections that already exist, and don't add yourself.
        new_endpoints = [endpoint for endpoint in endpoints if (endpoint not in self.connections) and (endpoint != self.endpoint)]
        if len(new_endpoints) != len(endpoints):
            self._log(f'Ignoring attempt to connect self or duplicate endpoint.')
        
        self.connections.extend(new_endpoints)

        return

    def remove_connections(self, endpoints: List[Endpoint]) -> None:

        self.connections = [e for e in self.connections if e not in endpoints]

        return

    def start(self, protocol: str = 'TCP') -> None:
        """
        Start the router with the given protocol ('TCP' or 'UDP').
        """

        if self._is_running:
            return

        if protocol not in ('TCP', 'UDP'):
            raise ValueError(f"Unsupported protocol: {protocol!r} (expected 'TCP' or 'UDP')")

        self._protocol = protocol

        self._thread = threading.Thread(target=self._worker, name='Router', daemon=True)
        self._is_running = True
        self._thread.start()

        self._log(f"Router started: {self.endpoint.ip_address}:{self.endpoint.port}, ({protocol})")

        return

    def stop(self) -> None:
        """
        Stop immediately by closing sockets to unblock accept()/recv()/recvfrom().
        """

        if not self._is_running:
            return

        with self._lock:
            if self.server_socket is not None:
                try:
                    self.server_socket.close()
                except Exception:
                    pass

                self.server_socket = None

            if self._active_connection is not None:
                try:
                    try:
                        self._active_connection.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    self._active_connection.close()
                except Exception:
                    pass

                self._active_connection = None

        if self._thread is not None:
            self._thread.join(timeout=2.0)

        self._is_running = False
        self._log("Router stopped.")

        return

    def _worker(self) -> None:

        try:
            if self._protocol == 'TCP':
                self._serve_tcp()
            else:
                self._serve_udp()

        finally:
            # Best-effort cleanup
            with self._lock:
                if self.server_socket is not None:
                    try:
                        self.server_socket.close()
                    except Exception:
                        pass

                    self.server_socket = None

                if self._active_connection is not None:
                    try:
                        self._active_connection.close()
                    except Exception:
                        pass

                    self._active_connection = None

        return

    def _serve_tcp(self) -> None:

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.endpoint.ip_address, self.endpoint.port))
        server.listen(8)

        with self._lock:
            self.server_socket = server

        while True:
            try:
                connection, _address = server.accept()  # blocks; unblocked when server closed
            except OSError:
                break  # stop() closed the server socket

            with self._lock:
                self._active_connection = connection

            try:
                chunks: list[bytes] = []
                while True:
                    try:
                        data = connection.recv(65536)  # blocks; unblocked if connection closed
                    except OSError:
                        data = b''

                    if not data:
                        break

                    chunks.append(data)

                if not chunks:
                    continue

                message = b''.join(chunks).decode('utf-8', errors='replace')
                self._log(f"Received: {message}")

                for endpoint in self.connections:
                    try:
                        send_message(
                            message=message,
                            endpoint=endpoint,
                            protocol=self._protocol or 'TCP',
                            timeout_seconds=2.0,
                            encoding='utf-8'
                        )
                        self._log(f"Forwarded to {endpoint.ip_address}:{endpoint.port}")

                    except Exception as exc:
                        self._log(
                            f"Forward failed to {endpoint.ip_address}:{endpoint.port} -> {exc!r}"
                        )

            finally:
                with self._lock:
                    try:
                        connection.close()
                    except Exception:
                        pass

                    self._active_connection = None

        return

    def _serve_udp(self) -> None:

        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind((self.endpoint.ip_address, self.endpoint.port))

        with self._lock:
            self.server_socket = server

        while True:
            try:
                data, _address = server.recvfrom(65536)  # blocks; unblocked when server closed
            except OSError:
                break

            message = data.decode('utf-8', errors='replace')
            self._log(f"Received: {message}")

            for endpoint in self.connections:
                try:
                    send_message(
                        message=message,
                        endpoint=endpoint,
                        protocol=self._protocol or 'TCP',
                        timeout_seconds=2.0,
                        encoding='utf-8'
                    )

                    self._log(f"Forwarded to {endpoint.ip_address}:{endpoint.port}")

                except Exception as exc:
                    self._log(
                        f"Forward failed to {endpoint.ip_address}:{endpoint.port} -> {exc!r}"
                    )

        return

    def _log(self, text: str) -> None:

        # Always route through the configured logger (defaults to print)
        self.on_log(text)

        return


if __name__ == '__main__':
    EP_HOST = Endpoint(ip_address='127.0.0.1', port=8000)
    router = Router(endpoint=EP_HOST)  # default on_log prints to stdout
    router.start(protocol='TCP')

    import time

    # Give the router a moment to spin up
    time.sleep(0.5)

    # Send a test message to itself (no connections, so it should only log receive)
    send_message(
        message='[127.0.0.1:9999] Hello Router!',
        endpoint=EP_HOST,
        protocol='TCP',
        timeout_seconds=2.0
    )

    time.sleep(1.0)
    router.stop()
