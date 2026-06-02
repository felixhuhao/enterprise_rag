"""SSE client for querying the RAG API during golden-set evaluation."""

import json

import requests


def query_rag(
    api_base: str,
    question: str,
    token: str,
    session_id: str = "",
    config: dict | None = None,
) -> dict:
    """POST /query/chat/stream，消费 SSE，返回聚合结果。"""
    url = f"{api_base}/query/chat/stream"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    body = {"query": question, "session_id": session_id, "is_eval": True}
    if config:
        body["config"] = config

    result = {
        "answer": "",
        "citations": [],
        "trace": {},
        "retrieval_step": {},
        "rerank_results": [],
        "search_mode": "",
        "retrieval_flavor": "",
        "strict_evidence": False,
        "groundedness": {},
        "error": None,
    }

    with requests.post(url, headers=headers, json=body, stream=True, timeout=120) as resp:
        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}: {resp.text[:500]}"
            return result

        buffer = ""
        for chunk in resp.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk:
                continue
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                evt_type = event.get("type", "")

                if evt_type == "delta":
                    result["answer"] += event.get("content", "")
                elif evt_type == "citations":
                    result["citations"] = event.get("citations", [])
                elif evt_type == "trace":
                    result["trace"].update(event.get("trace", {}))
                elif evt_type == "groundedness":
                    result["groundedness"] = {
                        key: value
                        for key, value in event.items()
                        if key != "type"
                    }
                elif evt_type == "retrieval_step":
                    result["retrieval_step"] = {
                        "results_count": event.get("results_count"),
                        "entity": event.get("entity"),
                        "rewritten_query": event.get("rewritten_query"),
                        "search_mode": event.get("search_mode"),
                        "search_mode_hyde": event.get("search_mode_hyde"),
                        "retrieval_flavor": event.get("retrieval_flavor"),
                        "strict_evidence": event.get("strict_evidence"),
                    }
                    result["search_mode"] = event.get("search_mode", "")
                    result["retrieval_flavor"] = event.get("retrieval_flavor", "")
                    result["strict_evidence"] = bool(event.get("strict_evidence", False))
                elif evt_type == "rerank":
                    result["rerank_results"] = event.get("results", [])
                elif evt_type == "error":
                    result["error"] = {
                        "code": event.get("code"),
                        "message": event.get("message"),
                    }
                elif evt_type == "message_end":
                    return result

    return result
