from utils.logger import get_logger
from config.llm_factory import get_llm
import json
import re

logger = get_logger("planner")
llm = get_llm()

ALLOWED_STEPS = {"RAG", "SQL", "ACTION", "TIMESHEET", "APPROVE", "REJECT", "SERVICE_REQUEST", "INCIDENT", "ONBOARD", "ADD_PROJECT", "ADD_LEAVE"}


def planner_agent(state):
    logger.info("Planner agent started")

    query = state["query"]
    q     = query.lower()

    user   = state.get("user", {})
    role   = user.get("role", "employee")
    emp_id = user.get("emp_id")

    chat_history = state.get("chat_history", [])
    history_text = ""
    if chat_history:
        recent = chat_history[-6:]
        history_text = "\n".join(f"{r.upper()}: {c}" for r, c in recent)

    logger.info(f"Incoming query: {query} | role={role} | emp_id={emp_id}")

    # ----------------------------
    # 🔒 RBAC RULES
    # ----------------------------

    # Salary RBAC — only block viewing OTHERS' salary, not asking about salary policy/advance
    if "salary" in q and not any(w in q for w in ["advance", "policy", "how", "when", "what", "process", "request"]):
        if role != "hr":
            if not any(k in q for k in ["my", "mine"]) and emp_id not in q:
                return {"steps": [], "error": {
                    "code": "UNAUTHORIZED",
                    "message": "You can only view your own salary."
                }}

    if "apply" in q and "for e" in q and role != "hr":
        if emp_id not in q:
            return {"steps": [], "error": {
                "code": "UNAUTHORIZED",
                "message": "You can only apply leave for yourself."
            }}

    if "approve" in q and role != "hr":
        return {"steps": [], "error": {
            "code": "UNAUTHORIZED",
            "message": "Only HR can approve requests."
        }}

    if "reject" in q and role != "hr":
        return {"steps": [], "error": {
            "code": "UNAUTHORIZED",
            "message": "Only HR can reject requests."
        }}

    if "timesheet" in q and any(w in q for w in ["all", "list", "show", "view", "everyone", "employees"]):
        if role != "hr":
            return {"steps": [], "error": {
                "code": "UNAUTHORIZED",
                "message": "You can only view your own timesheets."
            }}

    if "incident" in q and any(w in q for w in ["all", "everyone", "employees", "reported by"]):
        if role != "hr":
            return {"steps": [], "error": {
                "code": "UNAUTHORIZED",
                "message": "You can only view your own reported incidents."
            }}
    # Onboarding employee
    if role != "hr" and any(t in q for t in ["onboard", "add employee", "new hire", "new employee", "register employee", "create employee"]):
        return {"steps": [], "error": {
            "code": "UNAUTHORIZED",
            "message": "Only HR can onboard new employees."
        }}

    # add project
    if role != "hr" and any(t in q for t in ["add project", "new project", "create project", "register project"]):
        return {"steps": [], "error": {
            "code": "UNAUTHORIZED",
            "message": "Only HR can add new projects."
        }}

    # ----------------------------
    # ✅ DETERMINISTIC ROUTING
    # ----------------------------

    # Policy questions → always RAG regardless of topic keywords
    if "policy" in q or "leave policy" in q:
        return {"steps": ["RAG"]}

    # Salary/payroll POLICY questions → RAG (not SQL)
    # e.g. "how do I request a salary advance", "when do I get paid", "what is overtime pay"
    salary_policy_triggers = [
        "salary advance", "advance", "paycheck", "when will i get paid",
        "when do i get paid", "first salary", "first paycheck", "payroll cut",
        "payslip", "how does pay", "how is salary", "overtime pay",
        "pay cycle", "pay date", "deductions", "allowances"
    ]
    if any(t in q for t in salary_policy_triggers):
        return {"steps": ["RAG"]}

    if "apply leave" in q:
        return {"steps": ["ACTION"]}

    # SQL only for personal data lookups — not policy/how-to questions
    if "my balance" in q or "my salary" in q or "my leave" in q or "my payslip" in q:
        return {"steps": ["SQL"]}

    if "balance" in q and any(w in q for w in ["how many", "remaining", "left", "check"]):
        return {"steps": ["SQL"]}

    if "pending" in q and any(w in q for w in ["leave", "timesheet", "request"]):
        return {"steps": ["SQL"]}

    if any(w in q for w in ["submit timesheet", "log timesheet", "timesheet for today", "timesheet for yesterday"]):
        return {"steps": ["TIMESHEET"]}

    if any(w in q for w in ["show", "list", "view"]) and "timesheet" in q:
        return {"steps": ["SQL"]}

    if any(w in q for w in ["show", "list", "view", "status"]) and "service" in q and "request" in q:
        return {"steps": ["SQL"]}

    # ── HR: Approve — approve_agent handles leave / timesheet / service request internally
    if "approve" in q and role == "hr":
        return {"steps": ["APPROVE"]}

    # ── HR: Reject — reject_agent handles leave / service request internally
    if "reject" in q and role == "hr":
        return {"steps": ["REJECT"]}

    # Incident reporting
    incident_report_keywords = [
        "report incident", "report an incident", "log incident",
        "incident occurred", "want to report", "raise incident",
        "there was an incident", "filing an incident"
    ]
    if any(kw in q for kw in incident_report_keywords):
        return {"steps": ["INCIDENT"]}

    # Incident viewing
    if "incident" in q and any(w in q for w in ["my", "show", "list", "view", "status", "check", "all"]):
        return {"steps": ["SQL"]}

    # Policy/how-to questions about equipment, IT setup, onboarding → RAG
    # Catches: "when should my laptop be ready", "what equipment do I get", etc.
    rag_topic_triggers = [
        "how do i", "how can i", "how does", "how long", "how many",
        "when should", "when will", "when do",
        "what happens", "what will happen", "what is", "what are",
        "can i", "am i allowed", "am i eligible",
        "laptop ready", "equipment", "ready by", "it setup",
        "onboarding", "buddy", "first day", "probation",
        "performance review", "pip", "performance improvement",
        "bradford", "gift", "hospitality", "bribery",
        "freelance", "competitor", "conflict of interest",
        "work from home", "remote work", "hybrid",
        "public wi-fi", "coffee shop", "wifi",
        "password", "mfa", "vpn", "data breach",
        "confidential", "google drive", "personal device",
    ]
    if any(t in q for t in rag_topic_triggers):
        return {"steps": ["RAG"]}
     # Add project routing — HR only
    if role == "hr" and "project" in q and any(t in q for t in ["add", "new", "create", "register"]):
        return {"steps": ["ADD_PROJECT"]}

    # Catches: "add leave for E101", "set leave balance", "assign 14 days leave" etc.
    if role == "hr" and any(t in q for t in ["add leave", "set leave", "assign leave", "update leave", "leave balance"]) and "balance" not in q.replace("leave balance", ""):
        return {"steps": ["ADD_LEAVE"]}
    if role == "hr" and re.search(r"leave.*for.*e\w+", q):
        return {"steps": ["ADD_LEAVE"]}
    
    # ----------------------------
    # 🔁 LLM FALLBACK
    # ----------------------------

    logger.warning("No hard rule matched — falling back to LLM planner")

    prompt = f"""
You are an expert HR assistant with over 20 years of experience.
Decide the execution steps for this HR query.

Recent conversation (for context):
{history_text if history_text else "None"}

Query: "{query}"

Return STRICT JSON array using only these steps:
- RAG: Answer comes from a policy document, handbook, or company rules.
       Use for ANY question about how things work, rules, entitlements, processes,
       consequences, eligibility, deadlines, or policy.
- SQL: Use when the answer requires looking up a specific employee's 
       personal data from a database — their own records, numbers, 
       or history that is unique to them.
- ACTION: Use ONLY when the user is explicitly requesting to perform 
          an operation — submitting, applying, cancelling, or booking 
          something right now.
- APPROVE: HR is explicitly approving any request (leave, timesheet, or service request).
- REJECT: HR is explicitly rejecting any request.
- TIMESHEET: Employee is logging/submitting timesheet hours.
- SERVICE_REQUEST: Employee needs a company resource — software, hardware, equipment,
  access, or any physical/digital asset. Use ONLY when the employee is REQUESTING
  something, not asking a question about it.
- INCIDENT: User is reporting a workplace/IT/safety incident.
- ONBOARD: HR is registering a brand new employee into the system.
Use when HR mentions adding, onboarding, registering, or creating a new employee entry.
- ADD_PROJECT: HR is adding a new project to the system. 
Use when HR mentions adding, creating, or registering a new project.

Critical distinctions:
- "when should my laptop be ready" → RAG (IT policy question)
- "I need a laptop" → SERVICE_REQUEST (employee requesting something)
- "how do I request a salary advance" → RAG (payroll policy question)
- "what is my salary" → SQL (personal data lookup)
- "approve [anything] for E007" → APPROVE
- "reject [anything] for E007" → REJECT
- "onboard new employee E108, John, Engineering" → ONBOARD
- "add a new employee" → ONBOARD
- "add new project P005, Data Analytics" → ADD_PROJECT  
- "create a new project" → ADD_PROJECT 

Decision rule:
- HOW / WHEN / WHAT / CAN I / POLICY / RULE → RAG
- MY specific records / numbers / history → SQL
- I NEED / REQUEST / APPLY right now → ACTION or SERVICE_REQUEST
- When in doubt → RAG

Rules:
- No markdown, no explanation
- Return ONLY JSON
Example: ["RAG"]
"""

    resp    = llm.invoke(prompt)
    content = resp.content

    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and "text" in p:
                parts.append(p["text"])
            else:
                parts.append(str(p))
        planner_json = "\n".join(parts).strip()
    else:
        planner_json = str(content).strip()

    steps = json.loads(planner_json)

    for s in steps:
        if s not in ALLOWED_STEPS:
            raise RuntimeError(f"Invalid planner step: {s}")

    logger.info(f"Planner steps: {steps}")
    return {"steps": steps}