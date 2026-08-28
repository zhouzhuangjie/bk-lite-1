"""opspilot.metis.llm.chain.node 可测行为：消息规范化、RAG 结果整形、MCP 传输解析。

对照 chain 节点契约：System 消息合并到最前；图谱关系去重；QA 文档改写；远程 MCP 仅允许 sse/streamable_http。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from apps.opspilot.metis.llm.chain.node import (
    BasicNode,
    ToolsNodes,
    _safe_log_preview,
    _tool_call_signature,
    normalize_messages_for_llm,
)

pytestmark = pytest.mark.unit


def test_safe_log_preview_truncates_and_handles_empty():
    assert _safe_log_preview("") == ""
    assert _safe_log_preview(None) == ""
    assert _safe_log_preview("abcdefghij", max_len=4) == "abcd"
    assert _safe_log_preview("完整内容") == "完整内容"


def test_tool_call_signature_is_stable_for_dict_and_falls_back():
    assert _tool_call_signature("kubectl", {"ns": "a", "name": "b"}) == _tool_call_signature(
        "kubectl", {"name": "b", "ns": "a"}
    )
    assert _tool_call_signature("echo", None).startswith("echo:")
    assert _tool_call_signature("custom", {"k": object()}).startswith("custom:")


def test_normalize_messages_for_llm_merges_system_messages_to_front():
    assert normalize_messages_for_llm([]) == []
    human = HumanMessage(content="hi")
    ai = AIMessage(content="ok")
    assert normalize_messages_for_llm([human, ai]) == [human, ai]

    merged = normalize_messages_for_llm(
        [
            HumanMessage(content="q"),
            SystemMessage(content="sys-a"),
            AIMessage(content="a"),
            SystemMessage(content="sys-b"),
        ]
    )
    assert isinstance(merged[0], SystemMessage)
    assert merged[0].content == "sys-a\n\nsys-b"
    assert [type(m) for m in merged[1:]] == [HumanMessage, AIMessage]
    assert merged[1].content == "q"
    assert merged[2].content == "a"


def test_basic_node_suggest_question_merges_or_inserts_system_prompt():
    node = BasicNode()
    prompt = "请再问一个问题"

    with patch(
        "apps.opspilot.metis.llm.chain.node.TemplateLoader.render_template",
        return_value=prompt,
    ):
        enabled = SimpleNamespace(enable_suggest=True)
        state = {"messages": [SystemMessage(content="base")]}
        result = node.suggest_question_node(state, {"configurable": {"graph_request": enabled}})
        assert result["messages"][0].content == f"base\n\n{prompt}"

        empty_state = {"messages": [HumanMessage(content="q")]}
        result = node.suggest_question_node(empty_state, {"configurable": {"graph_request": enabled}})
        assert isinstance(result["messages"][0], SystemMessage)
        assert result["messages"][0].content == prompt

        disabled = SimpleNamespace(enable_suggest=False)
        untouched = {"messages": []}
        assert node.suggest_question_node(untouched, {"configurable": {"graph_request": disabled}}) == untouched


def test_basic_node_add_chat_history_supports_text_and_images():
    node = BasicNode()
    history = [
        SimpleNamespace(event="user", message="描述天气", image_data=["http://img/a.png"]),
        SimpleNamespace(event="user", message="", image_data=["http://img/b.png"]),
        SimpleNamespace(event="user", message="纯文本", image_data=None),
        SimpleNamespace(event="assistant", message="晴", image_data=None),
        SimpleNamespace(event="other", message="ignore", image_data=None),
    ]
    request = SimpleNamespace(chat_history=history)
    state = {"messages": []}
    node.add_chat_history_node(state, {"configurable": {"graph_request": request}})

    assert isinstance(state["messages"][0], HumanMessage)
    assert state["messages"][0].content[0] == {"type": "text", "text": "描述天气"}
    assert state["messages"][0].content[1]["image_url"]["url"] == "http://img/a.png"
    assert state["messages"][1].content[0]["text"] == "describe the weather in this image"
    assert state["messages"][2].content == "纯文本"
    assert isinstance(state["messages"][3], AIMessage)
    assert state["messages"][3].content == "晴"
    assert len(state["messages"]) == 4


def test_process_graph_results_deduplicates_relations_and_summaries():
    node = BasicNode()
    graph_item = {
        "fact": "depends_on",
        "source_node": {"name": "svc-a", "summary": "前端服务"},
        "target_node": {"name": "svc-b", "summary": "前端服务"},
    }
    results = node._process_graph_results([graph_item, graph_item], ["kb-1"])
    relation_docs = [item for item in results if item.metadata["knowledge_title"].startswith("图谱关系")]
    summary_docs = [item for item in results if item.metadata["knowledge_title"].startswith("图谱节点详情")]
    assert len(relation_docs) == 1
    assert "svc-a - depends_on - svc-b" in relation_docs[0].page_content
    assert len(summary_docs) == 1
    assert "svc-a" in summary_docs[0].page_content and "svc-b" in summary_docs[0].page_content

    assert node._process_relation_fact({"fact": "", "source_node": {}, "target_node": {}}, set(), "g") is None


def test_process_document_content_rewrites_qa_and_appends_document_answer():
    node = BasicNode()
    qa_doc = SimpleNamespace(page_content="raw", metadata={"is_doc": "0", "qa_question": "Q", "qa_answer": "A"})
    rewritten = node._process_document_content(qa_doc)
    assert rewritten.page_content == "问题: Q\n答案: A"
    assert rewritten.metadata["chunk_type"] == "QA"
    assert rewritten.metadata["knowledge_title"] == "Q"

    doc = SimpleNamespace(page_content="正文", metadata={"is_doc": "1", "qa_answer": "补充"})
    appended = node._process_document_content(doc)
    assert appended.page_content == "正文\n补充"
    assert appended.metadata["chunk_type"] == "Document"

    plain = SimpleNamespace(page_content="x", metadata={})
    assert node._process_document_content(plain).metadata["chunk_type"] == "Document"


def test_extract_image_text_content_and_prepare_template_data():
    node = BasicNode()
    docs = [
        SimpleNamespace(page_content="ocr-1", metadata={}),
        SimpleNamespace(page_content="", metadata={}),
        SimpleNamespace(page_content="ocr-2", metadata={}),
    ]
    extracted = node._extract_image_text_content(docs)
    assert "[图片 1]" in extracted and "ocr-1" in extracted
    assert "ocr-2" in extracted

    rag_doc = SimpleNamespace(
        page_content="chunk-body",
        metadata={
            "knowledge_title": "手册",
            "knowledge_id": 9,
            "chunk_number": 2,
            "chunk_id": "c2",
            "segment_number": 1,
            "segment_id": "s1",
            "chunk_type": "Document",
        },
    )
    template = node._prepare_template_data([rag_doc], {"configurable": {"enable_rag_source": True}})
    assert template["enable_rag_source"] is True
    assert template["rag_results"][0]["title"] == "手册"
    assert template["rag_results"][0]["content"] == "chunk-body"


def test_user_message_node_rewrites_or_falls_back_to_original():
    node = BasicNode()
    request = SimpleNamespace(user_message="原始问题", enable_query_rewrite=True, graph_user_message=None)
    config = {"configurable": {"graph_request": request, "trace_id": "t1"}}

    with patch.object(node, "_rewrite_query", return_value="改写后"):
        state = {"messages": []}
        node.user_message_node(state, config)
        assert state["messages"][0].content == "改写后"
        assert request.graph_user_message == "改写后"

    request.graph_user_message = None
    with patch.object(node, "_rewrite_query", side_effect=RuntimeError("llm down")):
        state = {"messages": []}
        node.user_message_node(state, config)
        assert state["messages"][0].content == "原始问题"


def test_tools_nodes_transport_and_k8s_greeting_filter():
    assert ToolsNodes._resolve_remote_transport("http://x/sse") == "sse"
    assert ToolsNodes._resolve_remote_transport("http://x/mcp") == "streamable_http"
    assert ToolsNodes._resolve_remote_transport("http://x/?transport=streamable_http") == "streamable_http"
    assert ToolsNodes._resolve_remote_transport("http://x/other", transport="SSE") == "sse"
    assert ToolsNodes._resolve_remote_transport("http://x/other") == "sse"

    k8s = SimpleNamespace(url="langchain:kubernetes")
    other = SimpleNamespace(url="langchain:mysql")
    node = ToolsNodes()
    assert node._is_k8s_tool_server(k8s) is True
    assert node._should_apply_first_turn_greeting_filter(SimpleNamespace(tools_servers=[])) is False
    assert node._should_apply_first_turn_greeting_filter(SimpleNamespace(tools_servers=[k8s])) is True
    assert node._should_apply_first_turn_greeting_filter(SimpleNamespace(tools_servers=[k8s, other])) is False


def test_tools_nodes_description_and_k8s_loop_filter():
    node = ToolsNodes()
    assert node.get_tools_description() == ""
    node.tools = [SimpleNamespace(name="t1", description="d1")]
    assert "t1: d1" in node.get_tools_description()

    node._has_skill_package_capability = MagicMock(return_value=False)
    calls = [
        {"name": "list_pods"},
        {"name": "request_user_choice"},
        {"name": "analyze_deployment_configurations"},
    ]
    filtered, stripped = node._filter_basic_k8s_analysis_loop_calls(calls, {"deployments": [{"n": 1}]})
    assert stripped is True
    assert [item["name"] for item in filtered] == ["list_pods"]

    done = ToolsNodes._build_basic_k8s_analysis_done_message(AIMessage(content=""), {"deployments": [1, 2], "cluster_name": "prod"})
    assert "prod" in done.content
    assert "2 个工作负载" in done.content
