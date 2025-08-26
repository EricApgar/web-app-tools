import os
import sys

from dataclasses import dataclass
from typing import Optional, Callable, List
import queue

from nicegui import ui

repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(repo_dir)

from network.helper.helper import Endpoint, send_message
from network.router import Router


# =========================
# Small counter widget
# =========================

@dataclass
class CounterState:
    value: int = 0
    running: bool = False


class CounterWidget:
    def __init__(self, title: str) -> None:
        self.state: CounterState = CounterState()
        with ui.card().classes('w-[24rem]'):
            ui.label(text=title).classes('text-lg font-medium')
            with ui.row().classes('items-center gap-4'):
                self.status = ui.label(text='Status: OFF')
                self.display = ui.label(text='0').classes('text-3xl')

            self.toggle_btn = ui.button(
                text='OFF',
                on_click=self.toggle
            ).props('push color=grey outline')

        self.timer = ui.timer(
            interval=0.1,          # 10 Hz
            callback=self.tick,
            active=False
        )

    def toggle(self) -> None:
        self.state.running = not self.state.running
        if self.state.running:
            self.status.text = 'Status: ON'
            self.toggle_btn.text = 'ON'
            self.toggle_btn.props('push color=green')
            self.timer.active = True
        else:
            self.status.text = 'Status: OFF'
            self.toggle_btn.text = 'OFF'
            self.toggle_btn.props('push color=grey outline')
            self.timer.active = False

    def tick(self) -> None:
        if not self.state.running:
            return
        self.state.value = (self.state.value + 1) % 101
        self.display.text = str(self.state.value)


# =========================
# Router widget
# =========================

class RouterWidget:
    def __init__(
        self,
        endpoint: Endpoint,
        connections: Optional[List[Endpoint]] = None,
        protocol: str = 'TCP'
    ) -> None:
        self.endpoint: Endpoint = endpoint
        self.connections: List[Endpoint] = list(connections) if connections else []
        self.protocol: str = protocol

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        # Router logs go to the queue; UI timer flushes them into textarea
        self.router = Router(
            endpoint=self.endpoint,
            connections=self.connections,
            on_log=self.log_queue.put
        )

        with ui.card().classes('w-[40rem]'):
            ui.label(text='Router Service').classes('text-lg font-medium')
            with ui.row().classes('items-center gap-4'):
                self.status = ui.label(text='Status: OFF')
                self.protocol_select = ui.select(
                    options=['TCP', 'UDP'],
                    value=self.protocol,
                    label='Protocol',
                    on_change=self.on_protocol_change
                ).props('outlined dense')
                self.endpoint_label = ui.label(
                    text=f'Listening on: {self.endpoint.ip_address}:{self.endpoint.port}'
                )

            self.toggle_btn = ui.button(
                text='OFF',
                on_click=self.on_toggle
            ).props('push color=grey outline')

            ui.separator()

            self.message_input = ui.input(
                label='Message to send',
                value='[127.0.0.1:9999] Hello Router!'
            ).props('outlined dense')

            self.send_btn = ui.button(
                text='Send',
                on_click=self.on_send_click
            ).props('push color=primary')

            # Fixed-height, scrollable log output
            self.log_area = ui.textarea(
                label='Router Logs',
                value='',
                placeholder='Router logs will appear here…'
            ).props('readonly').classes('w-full').style('height: 220px; overflow:auto;')

        # Periodically flush logs from the queue to the textarea (UI thread)
        self.log_timer = ui.timer(
            interval=0.2,
            callback=self.flush_logs,
            active=True
        )

    def on_toggle(self) -> None:
        if self.router.running:
            self.router.stop()
            self.status.text = 'Status: OFF'
            self.toggle_btn.text = 'OFF'
            self.toggle_btn.props('push color=grey outline')
        else:
            self.router.start(protocol=self.protocol)
            self.status.text = 'Status: ON'
            self.toggle_btn.text = 'ON'
            self.toggle_btn.props('push color=green')

    def on_protocol_change(self, e) -> None:
        selected: str = str(self.protocol_select.value)
        if selected not in ('TCP', 'UDP'):
            # Defensive: ignore invalid selections
            self.protocol_select.value = self.protocol
            return
        if selected == self.protocol:
            return
        # Update current protocol; if running, restart to apply
        self.protocol = selected
        if self.router.running:
            self.router.stop()
            self.router.start(protocol=self.protocol)
            self.status.text = 'Status: ON'
            self.toggle_btn.text = 'ON'
            self.toggle_btn.props('push color=green')
        # No log line here; router will log its own start/stop

    def on_send_click(self) -> None:
        if not self.router.running:
            self.log_queue.put('Router must be started to send message.')
            return
        try:
            send_message(
                message=str(self.message_input.value),
                endpoint=self.endpoint,
                protocol=self.protocol,
                timeout_seconds=2.0,
                encoding='utf-8'
            )
            # Optional UI feedback
            self.log_queue.put(f"UI: Sent -> {self.message_input.value}")
        except Exception as exc:
            self.log_queue.put(f"UI: Send failed -> {exc!r}")

    def flush_logs(self) -> None:
        updated: bool = False
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            else:
                self.log_area.value = (self.log_area.value + line + '\n').lstrip()
                updated = True
        # For fixed-height textarea with scrollbars, we won't auto-scroll for now


# =========================
# Page assembly
# =========================

with ui.row().classes('gap-6'):
    CounterWidget(title='Counter A')
    CounterWidget(title='Counter B')

with ui.row().classes('gap-6'):
    RouterWidget(
        endpoint=Endpoint(ip_address='127.0.0.1', port=8000),
        connections=[],     # you can add Endpoint(...)s here later
        protocol='TCP'
    )

ui.run(
    title='Network Control',
    reload=False
)
