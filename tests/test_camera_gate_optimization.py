"""Request-driven RAM cache, lifecycle, dimensions and safe outage logging."""
import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.intelpark import camera
from custom_components.intelpark.api import IntelparkError

from .test_camera_gate import _gate, _setup


@pytest.fixture
async def image_context(hass):
    entry = await _setup(hass, [_gate()], {"gate_preview_source": "snapshot"})
    coordinator = entry.runtime_data
    entity = camera.IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    entity.hass = hass
    entity.entity_id = "camera.test_gate"
    clock = SimpleNamespace(now=100.0)
    with (
        patch.object(camera, "time", SimpleNamespace(monotonic=lambda: clock.now)),
        patch.object(coordinator.client, "async_fetch_snapshot", new_callable=AsyncMock, return_value=b"snapshot") as fetch,
        patch.object(camera, "async_get_stream_image", new_callable=AsyncMock, return_value=b"frame") as stream,
    ):
        yield SimpleNamespace(entity=entity, coordinator=coordinator, clock=clock, fetch=fetch, stream=stream)
        await entity.async_will_remove_from_hass()


async def _open_circuit(ctx):
    ctx.fetch.return_value = None
    for _ in range(3):
        await ctx.entity.async_camera_image()
    assert ctx.entity._snapshot_failures == 3
    assert ctx.entity._snapshot_open_until == ctx.clock.now + 60


def _block(mock, result=b"snapshot", error=None):
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def work(*args, **kwargs):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        if error is not None:
            raise error
        return result

    mock.side_effect = work
    return started, release, cancelled


async def _start_pair(ctx, target, first=(320, 180), second=(320, 180)):
    started, release, cancelled = _block(target)
    a = asyncio.create_task(ctx.entity.async_camera_image(*first))
    await started.wait()
    b = asyncio.create_task(ctx.entity.async_camera_image(*second))
    await asyncio.sleep(0)
    return a, b, release, cancelled


def _mode(ctx, mode):
    # Recreate as a reload would: selection is fixed for each entity lifetime.
    coordinator = SimpleNamespace(
        config_entry=SimpleNamespace(entry_id=ctx.coordinator.config_entry.entry_id, options={"gate_preview_source": mode}),
        data=ctx.coordinator.data,
        client=ctx.coordinator.client,
    )
    ctx.entity = camera.IntelparkGateCamera(coordinator, coordinator.data.gates[0])
    ctx.entity.hass = ctx.coordinator.hass
    return ctx.fetch if mode == "snapshot" else ctx.stream


async def test_healthy_refresh_retains_only_latest_native_image(image_context, caplog):
    ctx = image_context
    assert await ctx.entity.async_camera_image() == b"snapshot"
    ctx.fetch.return_value = b"new"
    assert await ctx.entity.async_camera_image(320, 180) == b"new"
    assert ctx.fetch.await_count == 2
    assert ctx.entity._last_snapshot == b"new"
    ctx.stream.assert_not_awaited()
    assert not [r for r in caplog.records if r.name == camera.__name__]


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("failure", ["error", "timeout", "empty", "none", "missing"])
async def test_snapshot_failure_returns_last_good_or_none_never_stream(image_context, warm, failure):
    ctx = image_context
    if warm:
        await ctx.entity.async_camera_image()
    if failure == "error":
        ctx.fetch.side_effect = IntelparkError("private")
    elif failure == "timeout":
        ctx.fetch.side_effect = TimeoutError()
    elif failure == "missing":
        ctx.coordinator.data.gates[0].snapshot_image = ""
    else:
        ctx.fetch.return_value = b"" if failure == "empty" else None
    assert await ctx.entity.async_camera_image() == (b"snapshot" if warm else None)
    assert not ctx.entity.use_stream_for_stills
    ctx.stream.assert_not_awaited()


async def test_real_timeout_cancels_fetch_within_budget(image_context):
    ctx = image_context
    await ctx.entity.async_camera_image()
    _, _, cancelled = _block(ctx.fetch)
    assert camera.GATE_SNAPSHOT_TIMEOUT == 3
    with patch.object(camera, "GATE_SNAPSHOT_TIMEOUT", 0):
        async with asyncio.timeout(1):
            assert await ctx.entity.async_camera_image() == b"snapshot"
    assert cancelled.is_set()
    assert ctx.entity._snapshot_failures == 1
    ctx.stream.assert_not_awaited()


async def test_threshold_cooldown_failed_probe_and_recovery(image_context):
    ctx = image_context
    assert camera.GATE_SNAPSHOT_COOLDOWN == 60
    await _open_circuit(ctx)
    ctx.clock.now = 159.999
    assert await ctx.entity.async_camera_image() is None
    assert ctx.fetch.await_count == 6
    assert ctx.entity._snapshot_failures == 3
    ctx.clock.now = 160
    await ctx.entity.async_camera_image()
    assert ctx.entity._snapshot_open_until == 220
    ctx.clock.now = 219
    await ctx.entity.async_camera_image()
    assert ctx.fetch.await_count == 8
    assert ctx.entity._snapshot_failures == 3
    ctx.clock.now = 220
    ctx.fetch.return_value = b"recovered"
    assert await ctx.entity.async_camera_image() == b"recovered"
    assert ctx.entity._snapshot_failures == 0
    assert ctx.entity._snapshot_open_until == 0


async def test_success_resets_consecutive_failures(image_context):
    ctx = image_context
    ctx.fetch.side_effect = [None, None, None, b"healthy", None, None]
    assert await ctx.entity.async_camera_image() is None
    assert ctx.entity._snapshot_failures == 1
    assert await ctx.entity.async_camera_image() == b"healthy"
    assert ctx.entity._snapshot_failures == 0
    assert await ctx.entity.async_camera_image() == b"healthy"
    assert ctx.fetch.await_count == 6
    assert ctx.entity._snapshot_failures == 1


async def test_cache_and_circuits_are_per_entity_and_lost_on_recreation(image_context):
    ctx = image_context
    await ctx.entity.async_camera_image()
    await _open_circuit(ctx)
    other_gate = _gate(gid="other")
    ctx.coordinator.data.gates.append(other_gate)
    other = camera.IntelparkGateCamera(ctx.coordinator, other_gate)
    replacement = camera.IntelparkGateCamera(ctx.coordinator, ctx.coordinator.data.gates[0])
    assert await other.async_camera_image() is None
    assert await replacement.async_camera_image() is None
    assert await ctx.entity.async_camera_image() == b"snapshot"
    assert other._snapshot_failures == replacement._snapshot_failures == 1
    await other.async_will_remove_from_hass()
    await replacement.async_will_remove_from_hass()


@pytest.mark.parametrize("mode", ["snapshot", "stream"])
async def test_identical_requests_share_inflight_but_next_request_refreshes(image_context, mode):
    ctx = image_context
    target = _mode(ctx, mode)
    a, b, release, _ = await _start_pair(ctx, target)
    release.set()
    assert await asyncio.gather(a, b) == [b"snapshot", b"snapshot"]
    assert target.await_count == 1
    assert not ctx.entity._image_inflight
    assert not ctx.entity._image_tasks
    target.side_effect = None
    target.return_value = b"next"
    assert await ctx.entity.async_camera_image() == b"next"
    assert target.await_count == 2


@pytest.mark.parametrize("mode", ["snapshot", "stream"])
@pytest.mark.parametrize("second", [(320, 180), (640, None), (None, 360)])
async def test_cancelling_one_waiter_preserves_other(image_context, mode, second):
    ctx = image_context
    target = _mode(ctx, mode)
    # Stream dimensions deliberately differ only in separate dimension test.
    first = second if mode == "stream" else (320, 180)
    a, b, release, cancelled = await _start_pair(ctx, target, first, second)
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    assert not cancelled.is_set()
    release.set()
    assert await b == b"snapshot"
    assert target.await_count == 1


@pytest.mark.parametrize("mode", ["snapshot", "stream"])
async def test_all_consumers_cancel_drains_and_retry_is_fresh(image_context, mode):
    ctx = image_context
    target = _mode(ctx, mode)
    a, b, _, cancelled = await _start_pair(ctx, target)
    a.cancel()
    b.cancel()
    results = await asyncio.gather(a, b, return_exceptions=True)
    assert all(isinstance(r, asyncio.CancelledError) for r in results)
    assert cancelled.is_set()
    assert not ctx.entity._image_inflight
    assert not ctx.entity._image_tasks
    assert ctx.entity._snapshot_failures == 0
    target.side_effect = None
    assert await ctx.entity.async_camera_image() == target.return_value


@pytest.mark.parametrize("mode", ["snapshot", "stream"])
async def test_unload_cancels_and_drains_all_work(image_context, mode):
    ctx = image_context
    target = _mode(ctx, mode)
    a, b, _, cancelled = await _start_pair(ctx, target, (1, 2), (2, 1))
    with patch.object(camera.HACamera, "async_will_remove_from_hass", new_callable=AsyncMock) as base:
        await ctx.entity.async_will_remove_from_hass()
        base.assert_awaited_once()
    results = await asyncio.gather(a, b, return_exceptions=True)
    assert all(isinstance(r, asyncio.CancelledError) for r in results)
    assert cancelled.is_set()
    assert not ctx.entity._image_inflight
    assert not ctx.entity._image_tasks
    assert await ctx.entity.async_camera_image() is None


@pytest.mark.parametrize("mode", ["snapshot", "stream"])
@pytest.mark.parametrize("dimensions", [((320, 180), (180, 320)), ((None, 180), (320, 180)), ((320, None), (320, 180))])
async def test_dimensions_coalesce_only_for_native_snapshot(image_context, mode, dimensions):
    ctx = image_context
    target = _mode(ctx, mode)
    started, release, _ = _block(target)
    tasks = [asyncio.create_task(ctx.entity.async_camera_image(*size)) for size in dimensions]
    await started.wait()
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(*tasks) == [b"snapshot", b"snapshot"]
    assert target.await_count == (1 if mode == "snapshot" else 2)
    if mode == "stream":
        assert {(c.kwargs["width"], c.kwargs["height"]) for c in target.await_args_list} == set(dimensions)
        assert all(c.kwargs["wait_for_next_keyframe"] is False for c in target.await_args_list)


async def test_unknown_shared_exception_propagates_without_circuit_change(image_context):
    ctx = image_context
    error = ValueError("synthetic")
    started, release, _ = _block(ctx.fetch, error=error)
    a = asyncio.create_task(ctx.entity.async_camera_image())
    await started.wait()
    b = asyncio.create_task(ctx.entity.async_camera_image())
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(a, b, return_exceptions=True) == [error, error]
    assert ctx.entity._snapshot_failures == 0
    ctx.fetch.side_effect = None
    assert await ctx.entity.async_camera_image() == b"snapshot"


async def test_half_open_probe_shared_across_dimensions(image_context):
    ctx = image_context
    await _open_circuit(ctx)
    ctx.clock.now = 160
    a, b, release, _ = await _start_pair(ctx, ctx.fetch, (1, 2), (2, 1))
    release.set()
    assert await asyncio.gather(a, b) == [b"snapshot", b"snapshot"]
    assert ctx.fetch.await_count == 7


async def test_failed_probe_not_duplicated(image_context):
    ctx = image_context
    await _open_circuit(ctx)
    ctx.clock.now = 160
    await asyncio.gather(ctx.entity.async_camera_image(1, 2), ctx.entity.async_camera_image(2, 1))
    assert ctx.fetch.await_count == 8
    assert ctx.entity._snapshot_open_until == 220


async def test_cancelled_probe_does_not_extend_circuit(image_context):
    ctx = image_context
    await _open_circuit(ctx)
    ctx.clock.now = 160
    started, _, cancelled = _block(ctx.fetch)
    task = asyncio.create_task(ctx.entity.async_camera_image())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert ctx.entity._snapshot_failures == 3
    assert ctx.entity._snapshot_open_until == 160


async def test_cancel_while_waiting_for_snapshot_lock(image_context):
    ctx = image_context
    await ctx.entity._snapshot_lock.acquire()
    task = asyncio.create_task(ctx.entity.async_camera_image())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    ctx.entity._snapshot_lock.release()
    ctx.fetch.assert_not_awaited()
    assert not ctx.entity._image_tasks


async def test_old_done_callback_does_not_remove_new_request(image_context):
    entity = image_context.entity
    old = asyncio.create_task(asyncio.sleep(0))
    await old
    replacement = [old, 1]
    entity._image_inflight[(None, None)] = replacement
    entity._image_done((None, None), [old, 0], old)
    assert entity._image_inflight[(None, None)] is replacement
    entity._image_inflight.clear()


@pytest.mark.parametrize("disappear_during_fetch", [False, True])
async def test_removed_gate_never_returns_or_caches_image(image_context, disappear_during_fetch):
    ctx = image_context
    async def fetch(url):
        ctx.coordinator.data.gates.clear()
        return b"invalidated"
    if disappear_during_fetch:
        ctx.fetch.side_effect = fetch
    else:
        await _open_circuit(ctx)
        ctx.coordinator.data.gates.clear()
    assert await ctx.entity.async_camera_image() is None
    assert ctx.entity._last_snapshot is None
    ctx.stream.assert_not_awaited()


async def test_next_request_uses_updated_snapshot_url(image_context):
    ctx = image_context
    await ctx.entity.async_camera_image()
    ctx.coordinator.data.gates[0].snapshot_image = "https://example.invalid/new"
    await ctx.entity.async_camera_image()
    ctx.fetch.assert_awaited_with("https://example.invalid/new")


@pytest.mark.parametrize("warm", [False, True])
async def test_warning_after_continuous_300s_once_then_info_recovery(image_context, caplog, warm):
    ctx = image_context
    caplog.set_level(logging.DEBUG, logger=camera.__name__)
    if warm:
        await ctx.entity.async_camera_image()
    ctx.fetch.side_effect = IntelparkError("PRIVATE_TOKEN_URL")
    for now in [100, 160, 220, 280, 340, 399]:
        ctx.clock.now = now
        await ctx.entity.async_camera_image()
    assert not [r for r in caplog.records if r.name == camera.__name__ and r.levelno >= logging.WARNING]
    for now in [400, 460, 520]:
        ctx.clock.now = now
        await ctx.entity.async_camera_image()
    ctx.fetch.side_effect = None
    ctx.clock.now = 580
    await ctx.entity.async_camera_image()
    records = [r for r in caplog.records if r.name == camera.__name__]
    assert sum(r.levelno == logging.WARNING for r in records) == 1
    assert sum(r.levelno == logging.INFO for r in records) == 1
    assert sum(r.levelno == logging.DEBUG for r in records) == 1
    assert "PRIVATE_TOKEN_URL" not in caplog.text
    assert "https://s/" not in caplog.text
    assert all(r.exc_info is None for r in records)
    ctx.stream.assert_not_awaited()


async def test_idle_gap_restarts_observation_not_warned_flag(image_context, caplog):
    ctx = image_context
    ctx.fetch.return_value = None
    for now in [100, 160, 220, 280]:
        ctx.clock.now = now
        await ctx.entity.async_camera_image()
    ctx.clock.now = 1000
    await ctx.entity.async_camera_image()
    assert not ctx.entity._snapshot_warned
    for now in [1060, 1120, 1180, 1240, 1300]:
        ctx.clock.now = now
        await ctx.entity.async_camera_image()
    assert ctx.entity._snapshot_warned
    ctx.clock.now = 2000
    await ctx.entity.async_camera_image()
    for now in [2060, 2120, 2180, 2240, 2300]:
        ctx.clock.now = now
        await ctx.entity.async_camera_image()
    assert sum(r.levelno == logging.WARNING and r.name == camera.__name__ for r in caplog.records) == 1


async def test_idle_after_success_and_transient_recovery_no_warning(image_context, caplog):
    ctx = image_context
    caplog.set_level(logging.INFO, logger=camera.__name__)
    await ctx.entity.async_camera_image()
    ctx.clock.now += 10000
    ctx.fetch.return_value = None
    await ctx.entity.async_camera_image()
    ctx.fetch.return_value = b"fresh"
    await ctx.entity.async_camera_image()
    assert not [r for r in caplog.records if r.name == camera.__name__]


async def test_no_background_polling(image_context):
    ctx = image_context
    await ctx.entity.async_camera_image()
    ctx.clock.now += 10000
    await asyncio.sleep(0)
    assert ctx.fetch.await_count == 1
    assert not ctx.entity._image_tasks


@pytest.mark.parametrize("first", [None, b"", IntelparkError("private"), TimeoutError()])
async def test_second_attempt_success_resets_failed_cycle_without_sleep(image_context, first):
    ctx = image_context
    ctx.entity._snapshot_failures = 2
    ctx.fetch.side_effect = [first, b"second-success"]
    with patch.object(camera.asyncio, "sleep", side_effect=AssertionError("retry must not sleep")):
        assert await ctx.entity.async_camera_image() == b"second-success"
    assert ctx.fetch.await_count == 2
    assert ctx.entity._snapshot_failures == 0
    assert ctx.entity._snapshot_open_until == 0
    ctx.stream.assert_not_awaited()


async def test_first_attempt_success_does_not_retry(image_context):
    ctx = image_context
    ctx.fetch.side_effect = [b"first-success", AssertionError("unnecessary retry")]
    assert await ctx.entity.async_camera_image() == b"first-success"
    ctx.fetch.assert_awaited_once()


async def test_both_attempts_timeout_separately(image_context):
    ctx = image_context
    started = []
    cancelled = []
    async def fetch(url):
        started.append(url)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(url)
    ctx.fetch.side_effect = fetch
    with patch.object(camera, "GATE_SNAPSHOT_TIMEOUT", 0):
        async with asyncio.timeout(1):
            assert await ctx.entity.async_camera_image() is None
    assert len(started) == len(cancelled) == 2
    assert ctx.entity._snapshot_failures == 1


@pytest.mark.parametrize("attempt", [1, 2])
async def test_cancel_during_each_attempt_does_not_count_failed_cycle(image_context, attempt):
    ctx = image_context
    started, _, cancelled = _block(ctx.fetch)
    blocked = ctx.fetch.side_effect
    calls = 0
    async def fetch(url):
        nonlocal calls
        calls += 1
        if calls < attempt:
            return None
        return await blocked(url)
    ctx.fetch.side_effect = fetch
    waiter = asyncio.create_task(ctx.entity.async_camera_image())
    async with asyncio.timeout(1):
        await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert cancelled.is_set()
    assert ctx.fetch.await_count == attempt
    assert ctx.entity._snapshot_failures == 0
    assert not ctx.entity._image_tasks
    ctx.stream.assert_not_awaited()


async def test_failed_cycle_is_shared_across_mixed_dimensions(image_context):
    ctx = image_context
    started, release, _ = _block(ctx.fetch, result=None)
    first = asyncio.create_task(ctx.entity.async_camera_image(320, 180))
    await started.wait()
    second = asyncio.create_task(ctx.entity.async_camera_image(640, 360))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [None, None]
    assert ctx.fetch.await_count == 2
    assert ctx.entity._snapshot_failures == 1
