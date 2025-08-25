from dataclasses import dataclass, field
from typing import Callable, Dict, List
from nicegui import ui


@dataclass
class Counter:
    running: bool = False
    value: int = 0


@dataclass
class AppState:
    counters: Dict[str, Counter] = field(default_factory=dict)


class Store:

    def __init__(self, state: AppState) -> None:

        self.state: AppState = state
        self._subscribers: List[Callable[[AppState], None]] = []


    # --- subscription (optional for cross-component reactions) ---
    def subscribe(self, fn: Callable[[AppState], None]) -> Callable[[], None]:

        self._subscribers.append(fn)
        def unsubscribe() -> None:
            self._subscribers.remove(fn)

        return unsubscribe


    def _notify(self) -> None:
        # Call subscribers (if any). Useful when a change should refresh other widgets.
        for fn in list(self._subscribers):
            fn(self.state)


    # --- actions (the only place that mutates state) ---
    def ensure_counter(self, name: str) -> Counter:
        if name not in self.state.counters:
            self.state.counters[name] = Counter()
        return self.state.counters[name]


    def start_counter(self, name: str) -> None:
        c = self.ensure_counter(name=name)
        # c.value = 0
        c.running = True
        # self._notify()  # optional; uncomment if others need to react
        return


    def stop_counter(self, name: str) -> None:
        c = self.ensure_counter(name=name)
        c.running = False
        # self._notify()
        return


    def tick_counter(self, name: str) -> None:
        c = self.ensure_counter(name=name)
        if c.running:
            c.value = (c.value + 1) % 101
        # No notify needed if the owner widget updates its own label each tick.
        return


class CounterWidget:

    def __init__(
        self,
        store: Store,
        name: str,
        title: str,
        period_sec: float=0.1) -> None:

        self.store: Store = store
        self.name: str = name
        self.title: str = title

        # Ensure state exists
        self.store.ensure_counter(name=self.name)

        # --- UI layout ---
        with ui.card().classes('w-80'):
            ui.label(text=self.title).classes('text-lg font-medium')
            self.counter_label = ui.label(text='Counter: 0')
            self.button = ui.button(text='OFF', on_click=self.on_toggle_click).props('push color=grey outline')

        # Each widget owns a timer that calls the store's tick for *its* counter
        self.timer = ui.timer(
            interval=period_sec,
            callback=self.on_tick,
            active=False)

        # Optional: subscribe for external changes (not strictly needed here,
        # but shows how you'd react if something else toggled this counter)
        self._unsubscribe = self.store.subscribe(self.on_state_change)

        return


    # --- lifecycle / events ---
    def on_toggle_click(self) -> None:

        c = self.store.state.counters[self.name]
        if c.running:
            self.store.stop_counter(name=self.name)
            self.button.text = 'OFF'
            self.button.props('color=red')
            self.timer.active = False
        else:
            self.store.start_counter(name=self.name)
            self.button.text = 'ON'
            self.button.props('color=green')
            self.counter_label.text = f'Counter: {c.value}'
            self.timer.active = True

        return


    def on_tick(self) -> None:

        self.store.tick_counter(name=self.name)
        c = self.store.state.counters[self.name]
        self.counter_label.text = f'Counter: {c.value}'
        # When c.value hits 100 it wraps (handled in store)

        return


    def on_state_change(self, state: AppState) -> None:

        # If some *other* component/action changed our state, reflect it in the UI.
        c = state.counters[self.name]
        # Sync visuals (idempotent updates are fine)
        self.counter_label.text = f'Counter: {c.value}'
        if c.running and not self.timer.active:
            self.timer.active = True
            self.button.text = 'ON'
            self.button.props('push color=green')
        if not c.running and self.timer.active:
            self.timer.active = False
            self.button.text = 'OFF'
            self.button.props('push color=grey outline')

        return


store = Store(state=AppState())
with ui.row().classes('gap-6'):
    CounterWidget(store=store, name='counter_a', title='Counter A', period_sec=0.1)
    CounterWidget(store=store, name='counter_b', title='Counter B', period_sec=0.1)

ui.run()
