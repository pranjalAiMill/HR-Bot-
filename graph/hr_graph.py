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
from agents.approve_agent import approve_agent
from agents.reject_agent import reject_agent
from agents.timesheet_agent import timesheet_agent 
from agents.service_request_agent import service_request_agent
from agents.incident_agent import incident_agent 
from agents.onboard_agent import onboard_agent
from agents.onboard_agent import add_project_agent, add_leave_agent

graph = StateGraph(HRState)

graph.add_node("planner", planner_agent)
graph.add_node("rag", rag_agent)
graph.add_node("sql", text2sql_agent)
graph.add_node("action", action_agent)
graph.add_node("approve", approve_agent) 
graph.add_node("reject", reject_agent)
graph.add_node("timesheet", timesheet_agent) 
graph.add_node("service_request", service_request_agent)
graph.add_node("incident", incident_agent)
graph.add_node("onboard", onboard_agent)
graph.add_node("add_project", add_project_agent) 
graph.add_node("ADD_LEAVE", add_leave_agent)
graph.add_node("summary", summarizer_agent)

graph.set_entry_point("planner")

graph.add_conditional_edges(
    "planner",
    lambda state: state["steps"][0] if state.get("steps") else "summary",
    {
        "RAG": "rag",
        "SQL": "sql",
        "ACTION": "action",
        "APPROVE": "approve",
        "REJECT": "reject", 
        "TIMESHEET": "timesheet",
        "SERVICE_REQUEST": "service_request",
        "INCIDENT": "incident",
        "ONBOARD": "onboard",
        "ADD_PROJECT": "add_project",
        "ADD_LEAVE": "ADD_LEAVE",
        "summary": "summary",  # handles error/empty steps gracefully
    }
)

graph.add_edge("rag", "summary")
graph.add_edge("sql", "summary")
graph.add_edge("action", "summary")
graph.add_edge("approve", "summary") 
graph.add_edge("reject", "summary")
graph.add_edge("timesheet", "summary")
graph.add_edge("service_request", "summary")
graph.add_edge("incident", "summary")
graph.add_edge("onboard", "summary")
graph.add_edge("add_project", "summary")
graph.add_edge("ADD_LEAVE", "summary")
# ✅ Summary is the ONLY terminal node
graph.set_finish_point("summary")

hr_graph = graph.compile()
