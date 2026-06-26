"""
Tool Hardening
==============

Time-boxing and prechecks for provider tools.

A rundown fans `use_context` out to several provider sub-agents back to back, and
agno puts no timeout around each one. We time-box every read here so a slow source
degrades to a one-line "skipped" and the rest of the brief still lands.

Google reads get an extra guard: on a dead OAuth token we skip before spinning the
sub-agent, which also avoids agno's interactive browser-auth fallback (wrong on a
headless server).
"""

import asyncio
import contextlib
import inspect
import json

from agno.run import RunContext
from agno.tools import tool


def timeout_error(label: str, timeout: float) -> str:
    """JSON error chunk for a timed-out tool."""
    return json.dumps({"error": f"{label} timed out after {int(timeout)}s — skipped"})


async def _drain_into(queue: asyncio.Queue, sentinel: object, make_call) -> None:
    """Producer task: run a provider tool and push each chunk onto ``queue``.

    A provider ``query_*`` entrypoint returns a coroutine; awaiting it yields either an
    async generator of streamed events or a finished value. Running this in its own
    task means a timeout cancels only the task — never the consumer or the calling
    agent's tool flow — so a slow source can't corrupt the outer stream.
    """
    try:
        res = make_call()
        if inspect.iscoroutine(res):
            res = await res
        if inspect.isasyncgen(res):
            async for chunk in res:
                await queue.put(chunk)
        else:
            await queue.put(res)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await queue.put(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
    finally:
        await queue.put(sentinel)


async def bounded_tool_call(make_call, timeout: float, label: str):
    """Yield a provider tool's chunks under a total wall-clock ``timeout``.

    The tool runs as an isolated producer task feeding a queue. On timeout we emit one
    error chunk (the providers' own ``{"error": ...}`` shape) and cancel the producer.
    The remaining budget also caps inter-chunk stalls, not just the total.
    """
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()
    task = asyncio.create_task(_drain_into(queue, sentinel, make_call))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                yield timeout_error(label, timeout)
                return
            try:
                item = await asyncio.wait_for(queue.get(), timeout=remaining)
            except (asyncio.TimeoutError, TimeoutError):
                yield timeout_error(label, timeout)
                return
            if item is sentinel:
                return
            yield item
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(BaseException):
            await task


def time_boxed_query_tool(original, timeout: float, precheck=None):
    """Wrap a provider ``query_*`` tool so its sub-agent run is time-boxed.

    Same name + description; the explicit ``question`` / ``run_context`` signature keeps
    agno's schema inference and run_context injection unchanged. The optional ``precheck``
    (an async callable) runs first: if it returns a chunk, we yield that and skip the
    sub-agent — the Google guard uses it to short-circuit on a dead token.
    """
    raw = original.entrypoint
    label = original.name

    @tool(name=original.name, description=original.description)
    async def _query(question: str, run_context: RunContext | None = None):
        if precheck is not None:
            skip = await precheck()
            if skip is not None:
                yield skip
                return
        async for chunk in bounded_tool_call(lambda: raw(question=question, run_context=run_context), timeout, label):
            yield chunk

    return _query
