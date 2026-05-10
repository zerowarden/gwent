from dataclasses import dataclass, field

from gwent_engine.core.events import GameEvent


@dataclass(slots=True)
class EventBuilder:
    base_event_counter: int
    _events: list[GameEvent] = field(default_factory=list)

    def next_event_id(self) -> int:
        return self.base_event_counter + len(self._events) + 1

    def append(self, event: GameEvent) -> None:
        self._events.append(event)

    def extend(self, events: tuple[GameEvent, ...]) -> None:
        self._events.extend(events)

    def build(self) -> tuple[GameEvent, ...]:
        return tuple(self._events)
