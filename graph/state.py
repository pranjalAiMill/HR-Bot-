from typing import TypedDict, Optional, List, Any, Dict,Tuple


class HRState(TypedDict, total=False):
    # 🔹 Input
    query: str
    user: Dict[str, Any]          # {"emp_id": "...", "role": "..."}
    slack_user_id: str

    # 🆕 Chat history
    chat_history: List[Tuple[str, str]] 

    # 🔹 Planner
    steps: List[str]
    error: Dict[str, str]         # {"code": "...", "message": "..."}
    

    # 🔹 RAG
    rag_context: str
    policy_citations: List[str]
    rag_chunks: List[str]
    
    # 🔹 SQL
    sql_result: Any

    # 🔹 Action
    action_status: str

    # 🔹 Output
    final_answer: str
