from flask import Flask, request, jsonify

from graph.hr_graph import hr_graph
from utils.logger import get_logger
from utils.vector_store import get_retriever
from utils.db_loader import build_db
from utils.user_context import get_user_context

# import os
# print("RUNNING FILE:", os.path.abspath(__file__))


logger = get_logger("api")

app = Flask(__name__)

# 🔹 1️⃣ Build / initialize DB at startup
try:
    logger.info("Initializing database")
    build_db()
except Exception:
    logger.exception("Database initialization failed")
    raise

# 🔹 2️⃣ Ensure vector DB is loadable
try:
    logger.info("Loading vector store")
    get_retriever()
except Exception:
    logger.exception("Vector store not ready")
    raise


@app.route("/chat", methods=["POST"])
def chat():
    query = request.json.get("query")
    logger.info(f"Incoming query: {query}")

    result = hr_graph.invoke({"query": query})
    return jsonify({"response": result["final_answer"]})

# @app.route("/slack/command", methods=["POST"])
# def slack_command():
#     from flask import request
#     import threading
#     import requests

#     user_query = request.form.get("text")
#     response_url = request.form.get("response_url")

#     logger.info(f"Slack query received: {user_query}")

#     # 🔹 Run HR bot asynchronously
#     def process_query():
#         try:
#             result = hr_graph.invoke({"query": user_query})
#             requests.post(
#                 response_url,
#                 json={
#                     "response_type": "ephemeral",
#                     "text": result["final_answer"]
#                 },
#                 timeout=5
#             )
#         except Exception as e:
#             logger.exception("Slack async processing failed")
#             requests.post(
#                 response_url,
#                 json={
#                     "response_type": "ephemeral",
#                     "text": "⚠️ Something went wrong while processing your request."
#                 }
#             )

#     threading.Thread(target=process_query).start()

#     # 🔹 Immediate ACK to Slack (within 3s)
#     return {
#         "response_type": "ephemeral",
#         "text": "⏳ Processing your request..."
#     }

@app.route("/slack/command", methods=["POST"])
def slack_command():
    import threading, requests

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

    logger.info(
    f"User={user_ctx}"
    )

    def process():
        try:
            result = hr_graph.invoke(state)
            requests.post(
                response_url,
                json={
                    "response_type": "ephemeral",
                    "text": result["final_answer"]
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



if __name__ == "__main__":
    logger.info("Starting HR Bot")
    app.run(port=8080)
