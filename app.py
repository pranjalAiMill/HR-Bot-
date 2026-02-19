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

from sqlalchemy import true
import re
from graph.hr_graph import hr_graph
from utils.logger import get_logger
from utils.vector_store import get_retriever
from utils.db_loader import build_db
from utils.user_context import get_user_context
from datetime import datetime

logger = get_logger("api")

app = Flask(__name__)
CORS(app)  # 🔹 REQUIRED for OpenWebUI

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

@app.route("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}


# ----------------------------------------------------
# 🔹 OpenAI-Compatible: List Models (REQUIRED)
# ----------------------------------------------------
@app.route("/v1/models", methods=["GET"])
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
# 🔹 OpenWebUI compatibility alias
# ----------------------------------------------------
@app.route("/models", methods=["GET"])
def list_models_root():
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
# 🔹 OpenAI-Compatible: Chat Completions
# ----------------------------------------------------
@app.route("/v1/chat/completions", methods=["POST"])
def openwebui_chat():
    data = request.json or {}
    messages = data.get("messages", [])
    model = data.get("model", "hr-bot")

    # 🔹 Extract last user message
    user_message = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content")
            break

    if not user_message:
        return jsonify({"error": "No user message found"}), 400

# Ignore OpenWebUI auto "follow-up suggestions" prompts
    if user_message and user_message.lstrip().startswith("### Task:"):
        return jsonify({
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "[]"
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        })

# 🔹 Optional OpenWebUI user context
    openwebui_user = data.get("user", {})
    logger.info(f"OpenWebUI incoming user field: {data.get('user')}")
    user_ctx = get_user_context(openwebui_user.get("id"))
    if not user_ctx:
        m = re.search(r"\b[A-Z]{1,3}\d{3}\b", (user_message or "").upper())
        if m:
            user_ctx = {"emp_id": m.group(0), "role": "employee"}
    
    state = {
        "query": user_message,
        "user": user_ctx
    }

    logger.info(
        f"OpenWebUI | model={model} | user={user_ctx} | query={user_message}"
    )
    
    try:
        result = hr_graph.invoke(state)
        answer = result.get("final_answer", "")
    except Exception:
        logger.exception("OpenWebUI processing failed")
        answer = "⚠️ Something went wrong while processing your request."

    return jsonify({
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": answer
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": len(user_message),
            "completion_tokens": len(answer),
            "total_tokens": len(user_message) + len(answer)
        }
    })


# ----------------------------------------------------
# 🔹 OpenWebUI compatibility alias (chat)
# ----------------------------------------------------
@app.route("/chat/completions", methods=["POST"])
def openwebui_chat_alias():
    return openwebui_chat()


# ----------------------------------------------------
# 🔹 BASIC API (Postman / curl)
# ----------------------------------------------------
# @app.route("/chat", methods=["POST"])
# def chat():
#     data = request.json or {}
#     query = data.get("query")

#     if not query:
#         return jsonify({"error": "query is required"}), 400

#     result = hr_graph.invoke({"query": query})
#     return jsonify({"response": result.get("final_answer", "")})
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    query = data.get("query")
    user = data.get("user", {})

    if not query:
        return jsonify({"error": "query is required"}), 400

    result = hr_graph.invoke({
        "query": query,
        "user": user
    })
    return jsonify({"response": result.get("final_answer", "")})

# ----------------------------------------------------
# 🔹 Slack Command Endpoint
# ----------------------------------------------------
@app.route("/slack/command", methods=["POST"])
def slack_command():
    user_query = request.form.get("text")
    slack_user_id = request.form.get("user_id")
    response_url = request.form.get("response_url")

    logger.info(
        f"Slack query received | user_id={slack_user_id} | query={user_query}"
    )

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
                json={
                    "response_type": "ephemeral",
                    "text": result.get("final_answer", "")
                },
                timeout=5
            )
        except Exception:
            logger.exception("Slack processing failed")
            requests.post(
                response_url,
                json={
                    "response_type": "ephemeral",
                    "text": "⚠️ Something went wrong. Please try again later."
                }
            )

    threading.Thread(target=process).start()

    return {
        "response_type": "ephemeral",
        "text": "⏳ Processing your request..."
    }

# ----------------------------------------------------
# 🔹 Main
# ----------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting HR Bot API")
    app.run(port=8080)
