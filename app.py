# from flask import Flask, request, jsonify

# from graph.hr_graph import hr_graph
# from utils.logger import get_logger
# from utils.vector_store import get_retriever
# from utils.db_loader import build_db
# from utils.user_context import get_user_context

# # import os
# # print("RUNNING FILE:", os.path.abspath(__file__))


# logger = get_logger("api")

# app = Flask(__name__)

# # 🔹 1️⃣ Build / initialize DB at startup
# try:
#     logger.info("Initializing database")
#     build_db()
# except Exception:
#     logger.exception("Database initialization failed")
#     raise

# # 🔹 2️⃣ Ensure vector DB is loadable
# try:
#     logger.info("Loading vector store")
#     get_retriever()
# except Exception:
#     logger.exception("Vector store not ready")
#     raise


# @app.route("/chat", methods=["POST"])
# def chat():
#     query = request.json.get("query")
#     logger.info(f"Incoming query: {query}")

#     result = hr_graph.invoke({"query": query})
#     return jsonify({"response": result["final_answer"]})

# # @app.route("/slack/command", methods=["POST"])
# # def slack_command():
# #     from flask import request
# #     import threading
# #     import requests

# #     user_query = request.form.get("text")
# #     response_url = request.form.get("response_url")

# #     logger.info(f"Slack query received: {user_query}")

# #     # 🔹 Run HR bot asynchronously
# #     def process_query():
# #         try:
# #             result = hr_graph.invoke({"query": user_query})
# #             requests.post(
# #                 response_url,
# #                 json={
# #                     "response_type": "ephemeral",
# #                     "text": result["final_answer"]
# #                 },
# #                 timeout=5
# #             )
# #         except Exception as e:
# #             logger.exception("Slack async processing failed")
# #             requests.post(
# #                 response_url,
# #                 json={
# #                     "response_type": "ephemeral",
# #                     "text": "⚠️ Something went wrong while processing your request."
# #                 }
# #             )

# #     threading.Thread(target=process_query).start()

# #     # 🔹 Immediate ACK to Slack (within 3s)
# #     return {
# #         "response_type": "ephemeral",
# #         "text": "⏳ Processing your request..."
# #     }

# @app.route("/slack/command", methods=["POST"])
# def slack_command():
#     import threading, requests

#     user_query = request.form.get("text")
#     slack_user_id = request.form.get("user_id")
#     response_url = request.form.get("response_url")

#     logger.info(
#         f"Slack query received | user_id={slack_user_id} | query={user_query}"
#     )

#     user_ctx = get_user_context(slack_user_id)

#     state = {
#         "query": user_query,
#         "user": user_ctx,
#         "slack_user_id": slack_user_id
#     }

#     logger.info(
#     f"User={user_ctx}"
#     )

#     def process():
#         try:
#             result = hr_graph.invoke(state)
#             requests.post(
#                 response_url,
#                 json={
#                     "response_type": "ephemeral",
#                     "text": result["final_answer"]
#                 },
#                 timeout=5
#             )
#         except Exception:
#             logger.exception("Slack processing failed")
#             requests.post(
#                 response_url,
#                 json={
#                     "response_type": "ephemeral",
#                     "text": "⚠️ Something went wrong. Please try again later."
#                 }
#             )

#     threading.Thread(target=process).start()

#     return {
#         "response_type": "ephemeral",
#         "text": "⏳ Processing your request..."
#     }



# if __name__ == "__main__":
#     logger.info("Starting HR Bot")
#     app.run(port=8080)




from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import requests
import time
import uuid
import re
import jwt

from graph.hr_graph import hr_graph
from utils.logger import get_logger
from utils.vector_store import get_retriever
from utils.db_loader import build_db
from utils.user_context import get_user_context, get_user_context_by_any
from datetime import datetime
from utils.session_store import get_history, save_history

logger = get_logger("api")

app = Flask(__name__)
CORS(app)

# ----------------------------------------------------
# 🔹 Startup Initialization
# ----------------------------------------------------
try:
    logger.info("Initializing database")
    build_db()
except Exception:
    logger.exception("Database initialization failed")
    raise

try:
    logger.info("Loading vector store")
    get_retriever()
except Exception:
    logger.exception("Vector store not ready")
    raise


# ----------------------------------------------------
# 🔹 Helper: Extract user email from JWT token
# ----------------------------------------------------
def resolve_user_from_request(data: dict) -> dict:

    # ── Strategy 1: UUID from JWT ──────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            decoded = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])
            user_id = decoded.get("id") or decoded.get("sub") or ""
            logger.info(f"JWT decoded → id={user_id}")
            if user_id:
                ctx = get_user_context(user_id)
                if ctx:
                    logger.info(f"User: {ctx}")
                    return ctx
        except Exception as e:
            logger.warning(f"JWT decode failed: {e}")

    # # ── Strategy 2: user object in body (Pipeline/Slack) ──────────
    # openwebui_user = data.get("user") or {}
    # if openwebui_user:
    #     ctx = get_user_context_by_any(openwebui_user)
    #     if ctx:
    #         logger.info(f"User resolved via body: {ctx}")
    #         return ctx

    # logger.warning("Could not resolve user identity")
    # return {}


# ----------------------------------------------------
# 🔹 Health Check
# ----------------------------------------------------
@app.route("/health")
def health_check():
    return {"status": "healthy", "timestamp": str(datetime.utcnow())}


# ----------------------------------------------------
# 🔹 OpenAI-Compatible: List Models
# ----------------------------------------------------
@app.route("/v1/models", methods=["GET"])
@app.route("/models", methods=["GET"])
def list_models():
    return jsonify({
        "data": [
            {
                "id": "hr-bot",
                "object": "model",
                "owned_by": "internal"
            }
        ]
    })


# ----------------------------------------------------
# 🔹 OpenAI-Compatible: Chat Completions (core logic)
# ----------------------------------------------------
def handle_chat_completions():
    data = request.json or {}
    messages = data.get("messages", [])
    model = data.get("model", "hr-bot")

    # Extract last user message
    user_message = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content")
            break

    if not user_message:
        return jsonify({"error": "No user message found"}), 400

    # Ignore OpenWebUI auto follow-up suggestion prompts
    if user_message.lstrip().startswith("### Task:"):
        return jsonify({
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "[]"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        })

    # ✅ Resolve user identity
    user_ctx = resolve_user_from_request(data)

    # Build chat history from messages (exclude current message)
    chat_history = [
        (msg["role"], msg["content"])
        for msg in messages[:-1]
        if msg.get("role") in ("user", "assistant")
    ][-10:]

    logger.info(f"Chat history: {len(chat_history)} messages")
    logger.info(f"Final user context: {user_ctx}")
    logger.info(f"Query: {user_message}")

    state = {
        "query": user_message,
        "user": user_ctx,
        "chat_history": chat_history
    }

    try:
        result = hr_graph.invoke(state)
        answer = result.get("final_answer", "")
    except Exception:
        logger.exception("Graph processing failed")
        answer = "⚠️ Something went wrong while processing your request."

    return jsonify({
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": len(user_message),
            "completion_tokens": len(answer),
            "total_tokens": len(user_message) + len(answer)
        }
    })


@app.route("/v1/chat/completions", methods=["POST"])
def openwebui_chat():
    return handle_chat_completions()


@app.route("/chat/completions", methods=["POST"])
def openwebui_chat_alias():
    return handle_chat_completions()


# ----------------------------------------------------
# 🔹 Basic API (Postman / curl)
# ----------------------------------------------------
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    query = data.get("query")
    user = data.get("user", {})

    logger.info(f"[chat] Requested for user: {user}")

    if not query:
        return jsonify({"error": "query is required"}), 400

    session_id = data.get("session_id") or str(uuid.uuid4())
    chat_history = get_history(session_id)

    result = hr_graph.invoke({
        "query": query,
        "user": user,
        "chat_history": chat_history,
    })

    answer = result.get("final_answer", "")

    save_history(session_id, "user", query)
    save_history(session_id, "assistant", answer)

    return jsonify({"response": answer, "session_id": session_id})


# ----------------------------------------------------
# 🔹 Slack Command Endpoint
# ----------------------------------------------------
@app.route("/slack/command", methods=["POST"])
def slack_command():
    user_query = request.form.get("text")
    slack_user_id = request.form.get("user_id")
    response_url = request.form.get("response_url")

    logger.info(f"Slack | user_id={slack_user_id} | query={user_query}")

    user_ctx = get_user_context(slack_user_id)

    state = {
        "query": user_query,
        "user": user_ctx,
        "slack_user_id": slack_user_id
    }

    def process():
        try:
            result = hr_graph.invoke(state)
            requests.post(
                response_url,
                json={"response_type": "ephemeral", "text": result.get("final_answer", "")},
                timeout=5
            )
        except Exception:
            logger.exception("Slack processing failed")
            requests.post(
                response_url,
                json={"response_type": "ephemeral", "text": "⚠️ Something went wrong. Please try again later."}
            )

    threading.Thread(target=process).start()
    return {"response_type": "ephemeral", "text": "⏳ Processing your request..."}


# ----------------------------------------------------
# 🔹 Main
# ----------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting HR Bot API")
    app.run(port=8080)