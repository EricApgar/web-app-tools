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
        self.protocol: str = protocol
        self._selected_connections: set[str] = set()

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        # Router logs go to the queue; UI timer flushes them into textarea
        self.router = Router(
            endpoint=endpoint,
            connections=list(connections) if connections else [],
            on_log=self.log_queue.put
        )

        with ui.card().classes('w-[40rem]'):
            ui.label(text='Router Service').classes('text-lg font-medium')
            with ui.row().classes('items-center gap-4'):
                ui.label(text=f'Host IP: {self.router.endpoint.ip_address}')
                self.port_input = ui.input(
                    label='Port',
                    value=str(self.router.endpoint.port),
                    on_change=self.on_port_change
                ).props('outlined dense').classes('w-[8rem]')
                self.protocol_select = ui.select(
                    options=['TCP', 'UDP'],
                    value=self.protocol,
                    label='Protocol',
                    on_change=self.on_protocol_change
                ).props('outlined dense')

            self.toggle_btn = ui.button(
                text='OFF',
                on_click=self.on_toggle
            ).props('push color=grey outline')

            ui.separator()

            # --- Send message section ---
            self.message_input = ui.input(
                label='Message to send',
                value='[127.0.0.1:9999] Hello Router!'
            ).props('outlined dense').classes('w-[36rem]')

            self.send_btn = ui.button(
                text='Send',
                on_click=self.on_send_click
            ).props('push color=primary')

            ui.separator()

            # --- Connections section ---
            ui.label(text='Connections').classes('text-md font-medium')
            self.conn_table = ui.table(
                columns=[
                    {"name": "ip", "label": "IP Address", "field": "ip", "align": "left"},
                    {"name": "port", "label": "Port", "field": "port", "align": "left"},
                ],
                rows=self._rows_from_connections(),
                row_key='key',
            ).props('selection="multiple"').classes('w-full').style('max-height: 220px; overflow:auto;')
            self.conn_table.on('selection', self.on_table_selection)

            with ui.row().classes('items-center gap-3 mt-2'):
                self.new_ip_input = ui.input(label='IP', value='').props('outlined dense').classes('w-[14rem]')
                self.new_port_input = ui.input(label='Port', value='').props('outlined dense').classes('w-[8rem]')
                ui.button(text='+ Add', on_click=self.on_add_connection).props('push color=secondary')
                ui.button(text='Remove Selected', on_click=self.on_remove_selected).props('push color=negative outline')

            ui.separator()

            self.log_area = ui.textarea(
                label='Router Logs',
                value='',
                placeholder='Router logs will appear here…'
            ).props('readonly').classes('w-full').style('height: 220px; overflow:auto;')

        self.log_timer = ui.timer(
            interval=0.2,
            callback=self.flush_logs,
            active=True
        )

    def on_toggle(self) -> None:
        if self.router.running:
            self.router.stop()
            self.toggle_btn.text = 'OFF'
            self.toggle_btn.props('push color=grey outline')
        else:
            self.router.start(protocol=self.protocol)
            self.toggle_btn.text = 'ON'
            self.toggle_btn.props('push color=green')

    def on_protocol_change(self, e) -> None:
        selected: str = str(self.protocol_select.value)
        if selected not in ('TCP', 'UDP'):
            self.protocol_select.value = self.protocol
            return
        if selected == self.protocol:
            return
        self.protocol = selected
        if self.router.running:
            self.router.stop()
            self.router.start(protocol=self.protocol)
            self.toggle_btn.text = 'ON'
            self.toggle_btn.props('push color=green')

    def on_port_change(self, e) -> None:
        raw = str(self.port_input.value).strip()
        try:
            new_port = int(raw)
            if not (1 <= new_port <= 65535):
                raise ValueError('port out of range')
        except Exception:
            self.port_input.value = str(self.router.endpoint.port)
            self.log_queue.put('Invalid port. Enter an integer 1–65535.')
            return
        if new_port == self.router.endpoint.port:
            return
        self.router.endpoint = Endpoint(ip_address=self.router.endpoint.ip_address, port=new_port)
        self.log_queue.put(f'Port set to {new_port}.')
        if self.router.running:
            self.router.stop()
            self.router.start(protocol=self.protocol)
            self.toggle_btn.text = 'ON'
            self.toggle_btn.props('push color=green')

    def on_add_connection(self) -> None:
        ip = str(self.new_ip_input.value).strip()
        port_raw = str(self.new_port_input.value).strip()
        if not ip or not port_raw:
            self.log_queue.put('Both IP and Port are required to add a connection.')
            return

        try:
            port = int(port_raw)
            if not (1 <= port <= 65535):
                raise ValueError('port out of range')
        except Exception:
            self.log_queue.put('Port must be an integer 1–65535.')
            return
        
        new_connection = Endpoint(ip_address=ip, port=port)

        if new_connection in self.router.connections:
            self.log_queue.put(f'Connection {ip}:{port} already exists.')
            return
        elif new_connection == self.router.endpoint:
            self.log_queue.put(f'Connection {ip}:{port} is self. Ignoring.')
            return

        self.router.add_connections(endpoints=[new_connection])
        self._refresh_table()
        self.log_queue.put(f'Added connection {ip}:{port}.')
        self.new_ip_input.value = ''
        self.new_port_input.value = ''

        return

    def on_send_click(self) -> None:
        if not self.router.running:
            self.log_queue.put('Router must be started to send message.')
            return
        try:
            send_message(
                message=str(self.message_input.value),
                endpoint=self.router.endpoint,
                protocol=self.protocol,
                timeout_seconds=2.0,
                encoding='utf-8'
            )
            self.log_queue.put(f"UI: Sent -> {self.message_input.value}")
        except Exception as exc:
            self.log_queue.put(f"UI: Send failed -> {exc!r}")

        return

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
        # No auto-scroll; fixed-size container is scrollable

        return

    def _rows_from_connections(self) -> list[dict]:
        return [
            {"key": f"{c.ip_address}:{c.port}", "ip": c.ip_address, "port": c.port}
            for c in self.router.connections
        ]
    
        return


    def _refresh_table(self) -> None:

        self.conn_table.rows = self._rows_from_connections()
        self.conn_table.update()

        return


    def on_table_selection(self, e) -> None:

        selected = getattr(e, 'args', [])
        self._selected_connections = [Endpoint(ip_address=i['ip'], port=i['port']) for i in selected['rows']]

        return


    def on_remove_selected(self) -> None:
        '''
        Remove selected endpoints from Router.
        '''

        if not self._selected_connections:
            self.log_queue.put('No connections selected to remove.')
            return

        self.router.remove_connections(self._selected_connections)

        self._refresh_table()
        removed_str = ', '.join(f"{e.ip_address}:{e.port}" for e in self._selected_connections)
        self._selected_connections.clear()
        self.log_queue.put(f'Removed: {removed_str}')

        return


# =========================
# Page assembly
# =========================

with ui.row().classes('gap-6'):
    CounterWidget(title='Counter A')
    CounterWidget(title='Counter B')

with ui.row().classes('gap-6'):
    RouterWidget(
        endpoint=Endpoint(ip_address='127.0.0.1', port=8000),
        connections=[],
        protocol='TCP'
    )

ui.run(title='Network Control')  # reload=False
