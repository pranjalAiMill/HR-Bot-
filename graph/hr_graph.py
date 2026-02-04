# from langgraph.graph import StateGraph
# from graph.state import HRState
# from agents.planner_agent import planner_agent
# from agents.rag_agent import rag_agent
# from agents.text2sql_agent import text2sql_agent
# from agents.action_agent import action_agent
# from agents.summarizer_agent import summarizer_agent

# graph = StateGraph(HRState)

# graph.add_node("planner", planner_agent)
# graph.add_node("rag", rag_agent)
# graph.add_node("sql", text2sql_agent)
# graph.add_node("action", action_agent)
# graph.add_node("summary", summarizer_agent)

# graph.set_entry_point("planner")

# def route_from_planner(state):
#     return state["steps"]

# graph.add_conditional_edges(
#     "planner",
#     lambda state: state["steps"],
#     {
#         "RAG": "rag",
#         "SQL": "sql",
#         "ACTION": "action",
#     }
# )

# graph.add_edge("rag", "summary")
# graph.add_edge("sql", "summary")
# graph.add_edge("action", "summary")

# graph.add_edge("planner", "summary")   # for errors / no-op

# hr_graph = graph.compile()

from langgraph.graph import StateGraph
from graph.state import HRState
from agents.planner_agent import planner_agent
from agents.rag_agent import rag_agent
from agents.text2sql_agent import text2sql_agent
from agents.action_agent import action_agent
from agents.summarizer_agent import summarizer_agent

graph = StateGraph(HRState)

graph.add_node("planner", planner_agent)
graph.add_node("rag", rag_agent)
graph.add_node("sql", text2sql_agent)
graph.add_node("action", action_agent)
graph.add_node("summary", summarizer_agent)

graph.set_entry_point("planner")

graph.add_conditional_edges(
    "planner",
    lambda state: state["steps"],
    {
        "RAG": "rag",
        "SQL": "sql",
        "ACTION": "action",
    }
)

graph.add_edge("rag", "summary")
graph.add_edge("sql", "summary")
graph.add_edge("action", "summary")

# ✅ Summary is the ONLY terminal node
graph.set_finish_point("summary")

hr_graph = graph.compile()
