"""日志 SSE tail：数据帧、心跳、最大连接时长切断。"""
import pytest

from itertools import chain, repeat

from apps.log.services.search import SearchService

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_tail_sse_emits_data_heartbeat_and_stops_at_max_time(mocker):
    mocker.patch(
        "apps.log.services.search.LogGroupQueryBuilder.build_query_with_groups",
        return_value=("error", []),
    )
    mocker.patch.object(SearchService, "_log_query_context")

    times = chain([100.0, 100.1, 104.0, 104.1, 200.0], repeat(200.0))
    mocker.patch("apps.log.services.search.time.time", side_effect=lambda: next(times))
    mocker.patch("apps.log.services.search.VictoriaLogsConstants.MAX_CONNECTION_TIME", 50)
    mocker.patch("apps.log.services.search.VictoriaLogsConstants.KEEPALIVE_INTERVAL", 45)

    async def fake_tail(query):
        assert query == "error"
        yield "line-1"
        yield "line-2"
        yield "line-3"

    api = mocker.MagicMock()
    api.tail_async = fake_tail
    mocker.patch("apps.log.services.search.VictoriaMetricsAPI", return_value=api)

    response = SearchService.tail("error")
    chunks = []
    async for chunk in response.streaming_content:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    assert chunks[0] == ": heartbeat\n\n"
    assert "data: line-1\n\n" in chunks
    assert "data: line-3\n\n" not in chunks


@pytest.mark.asyncio
async def test_tail_sse_records_outer_exception_and_ends(mocker):
    mocker.patch(
        "apps.log.services.search.LogGroupQueryBuilder.build_query_with_groups",
        return_value=("error", []),
    )
    mocker.patch.object(SearchService, "_log_query_context")

    async def boom(query):
        raise RuntimeError("vm down")
        yield "unused"

    api = mocker.MagicMock()
    api.tail_async = boom
    logger = mocker.patch("apps.log.services.search.logger")
    mocker.patch("apps.log.services.search.VictoriaMetricsAPI", return_value=api)
    response = SearchService.tail("error")
    chunks = []
    async for chunk in response.streaming_content:
        chunks.append(chunk)
    assert chunks == []
    logger.error.assert_called()
    assert logger.error.call_args.args[0] == "异步SSE tail连接异常"
