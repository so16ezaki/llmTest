"""
Dify → OpenAI互換APIプロキシ
pip install flask requests でOK
"""

import json
import time
import uuid
from flask import Flask, request, Response, jsonify

app = Flask(__name__)

# ===== 設定 =====
DIFY_API_URL = "https://your-company-dify.com/v1"  # 会社のDify URL
DIFY_API_KEY = "app-xxxxxxxxxxxxx"                  # DifyアプリのAPIキー
# ================


@app.route("/v1/models", methods=["GET"])
def models():
    """Clineがモデル一覧を取得するエンドポイント"""
    return jsonify({
        "data": [{"id": "dify", "object": "model", "owned_by": "dify"}]
    })


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    data = request.json
    messages = data.get("messages", [])
    stream = data.get("stream", False)

    # OpenAI形式 → Dify形式に変換
    # 最後のuserメッセージをqueryに、それ以前を会話履歴にマッピング
    query = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            query = msg["content"]
            break

    # APIキーはリクエストヘッダーから取るか、デフォルトを使う
    auth = request.headers.get("Authorization", "")
    api_key = auth.replace("Bearer ", "") if auth else DIFY_API_KEY
    # Difyキーでない場合（Clineが独自キーを送る場合）デフォルトにフォールバック
    if not api_key.startswith("app-"):
        api_key = DIFY_API_KEY

    dify_payload = {
        "inputs": {},
        "query": query,
        "user": "cline-agent",
        "response_mode": "streaming" if stream else "blocking",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    import requests as req

    if stream:
        return _handle_stream(dify_payload, headers)
    else:
        return _handle_blocking(dify_payload, headers)


def _handle_blocking(payload, headers):
    import requests as req
    resp = req.post(f"{DIFY_API_URL}/chat-messages", json=payload, headers=headers)
    result = resp.json()
    answer = result.get("answer", "")

    return jsonify({
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "dify",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    })


def _handle_stream(payload, headers):
    import requests as req

    def generate():
        resp = req.post(
            f"{DIFY_API_URL}/chat-messages",
            json=payload, headers=headers, stream=True
        )
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw.strip() == "[DONE]":
                yield "data: [DONE]\n\n"
                break
            try:
                dify_data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event = dify_data.get("event", "")
            if event == "message":
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "dify",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": dify_data.get("answer", "")},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            elif event == "message_end":
                chunk = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "dify",
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    print("Dify→OpenAI proxy running on http://localhost:3000/v1")
    app.run(host="0.0.0.0", port=3000)