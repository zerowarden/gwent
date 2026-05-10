from __future__ import annotations

from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Literal, final

type HandledException = type[BaseException] | tuple[type[BaseException], ...]


def handle_exception[ResultT](
    operation: Callable[[], ResultT],
    handled_exception: HandledException,
    error_handler: Callable[[BaseException], ResultT],
) -> ResultT:
    context = RecoverExceptionContext(handled_exception, error_handler)
    with context:
        return operation()
    return context.result


def translate_exception[ResultT](
    operation: Callable[[], ResultT],
    handled_exception: HandledException,
    error_factory: Callable[[BaseException], Exception],
) -> ResultT:
    with translate_exception_context(handled_exception, error_factory):
        return operation()


def recover_exception[ResultT](
    operation: Callable[[], ResultT],
    handled_exception: HandledException,
    fallback: Callable[[BaseException], ResultT],
) -> ResultT:
    return handle_exception(operation, handled_exception, fallback)


class _ExceptionContextBase:
    def __enter__(self) -> None:
        return None


@final
class TranslatedExceptionContext(_ExceptionContextBase):
    def __init__(
        self,
        handled_exception: HandledException,
        error_factory: Callable[[BaseException], Exception],
    ) -> None:
        self._handled_exception: HandledException = handled_exception
        self._error_factory: Callable[[BaseException], Exception] = error_factory

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, traceback
        if exc is None or not isinstance(exc, self._handled_exception):
            return False
        raise self._error_factory(exc) from exc


@final
class RecoverExceptionContext[ResultT](_ExceptionContextBase):
    def __init__(
        self,
        handled_exception: HandledException,
        fallback: Callable[[BaseException], ResultT],
    ) -> None:
        self._handled_exception: HandledException = handled_exception
        self._fallback: Callable[[BaseException], ResultT] = fallback
        self._result: ResultT | None = None

    @property
    def result(self) -> ResultT:
        assert self._result is not None
        return self._result

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, traceback
        if exc is None or not isinstance(exc, self._handled_exception):
            return False
        self._result = self._fallback(exc)
        return True


def translate_exception_context(
    handled_exception: HandledException,
    error_factory: Callable[[BaseException], Exception],
) -> TranslatedExceptionContext:
    return TranslatedExceptionContext(handled_exception, error_factory)


def translate_mapping_key[KeyT, ValueT](
    mapping: Mapping[KeyT, ValueT],
    key: KeyT,
    error_factory: Callable[[KeyT], Exception],
) -> ValueT:
    return translate_exception(
        lambda: mapping[key],
        KeyError,
        lambda _exc: error_factory(key),
    )
