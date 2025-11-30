from flask import Flask, request, Response, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv
import uuid
import random
import threading
import queue

# 加载环境变量
load_dotenv()

# 配置静态文件夹路径（前端构建文件在 docs 目录）
app = Flask(__name__, static_folder='docs', static_url_path='')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///bills.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 用于存储用户旅行规划状态（内存存储，实际应用中应使用数据库或Redis）
# 格式: {session_id: {"route_plan": "...", "restaurant_plan": "...", "budget": ..., "awaiting_mediation": False, "awaiting_confirmation": False, "pending_modification_request": "...", "mediation_requesting_user_id": "...", "mediation_modification_type": "route|restaurant"}}
travel_plan_storage = {}

# 投票机制存储
# 格式: {session_id: {"mediation_votes": {user_id: "agree|disagree|pending"}, "confirmation_votes": {user_id: "agree|disagree|pending"}}}
vote_storage = {}

# 多人聊天室系统
# 用户管理：{user_id: {"name": "随机名字", "session_id": "..."}}
user_storage = {}

# 多人聊天室共享session_id（所有用户共享同一个行程计划）
SHARED_CHATROOM_SESSION_ID = "shared_chatroom_session"

# 消息队列：存储所有消息，格式: {"id": "...", "user_id": "...", "username": "...", "type": "user|ai|planner", "content": "...", "timestamp": "..."}
message_queue = []
message_queue_lock = threading.Lock()

# SSE连接管理：{user_id: queue.Queue()}
sse_connections = {}
sse_connections_lock = threading.Lock()

# 随机名字列表
RANDOM_NAMES = [
    "Alex", "Blake", "Casey", "Drew", "Ellis", "Finley", "Gray", "Harper",
    "Jordan", "Kai", "Logan", "Morgan", "Parker", "Quinn", "Riley", "Sage",
    "Taylor", "Avery", "Cameron", "Dakota", "Emery", "Hayden", "Jamie", "Kendall",
    "Phoenix", "River", "Skyler", "Tatum", "Winter", "Zephyr"
]

# 初始化数据库
db = SQLAlchemy(app)

# 账单数据模型
class Bill(db.Model):
    __tablename__ = 'bills'
    
    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(200), nullable=False)
    payer = db.Column(db.String(100), nullable=False)
    participants = db.Column(db.Text, nullable=False)  # JSON字符串存储数组
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='CNY')
    note = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_input = db.Column(db.Text)  # 保存原始用户输入
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'topic': self.topic,
            'payer': self.payer,
            'participants': json.loads(self.participants) if isinstance(self.participants, str) else self.participants,
            'amount': self.amount,
            'currency': self.currency,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'user_input': self.user_input
        }

# 旅行计划数据模型
class TravelPlan(db.Model):
    __tablename__ = 'travel_plans'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), nullable=False, index=True)
    route_plan = db.Column(db.Text, nullable=False)
    restaurant_plan = db.Column(db.Text, default='')
    budget = db.Column(db.Float)
    currency = db.Column(db.String(10), default='USD')
    destination = db.Column(db.String(200))  # 目的地
    days = db.Column(db.Integer)  # 天数
    participants = db.Column(db.Text)  # JSON字符串存储参与者列表
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'session_id': self.session_id,
            'route_plan': self.route_plan,
            'restaurant_plan': self.restaurant_plan,
            'budget': self.budget,
            'currency': self.currency,
            'destination': self.destination,
            'days': self.days,
            'participants': json.loads(self.participants) if isinstance(self.participants, str) else self.participants,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

# 创建数据库表
with app.app_context():
    db.create_all()
    print("数据库初始化完成")

# Main Router AI Prompt
ROUTER_PROMPT = """You are an intelligent routing assistant. Your task is to determine which specialized sub-agent should answer the user's question based on the user's query.

Available sub-agents:
1. "travel" - Travel Assistant: Handles all questions related to travel, tourism, itinerary planning, hotel bookings, attraction recommendations, budget planning, travel expenses, and all non-bill related questions
2. "bill" - Bill Assistant: **Only** handles questions related to AA bills, expense records, and cost sharing (must explicitly mention keywords like "bill", "split", "expense record", etc.)

Important judgment rules:
- **Bill-related keywords (should be judged as "bill"):**
  - Must satisfy all of the following conditions:
    1. Explicitly mention "bill", "expense record", "record bill", "query bill", "view bill", "find bill", "query bill"
    2. Explicitly mention "AA system", "split", "share cost", "cost sharing"
    3. Explicitly mention "record", "save", "bookkeeping" and the context is about expense records that have already occurred
  
- **All other cases (should be judged as "travel"):**
  - Except for the above explicit bill record/query/sharing questions, **all other questions** should be judged as "travel"
  - Including but not limited to: travel, tourism, itinerary, route, planning, schedule, hotel, accommodation, budget, expense, attraction, restaurant, flight ticket, transportation, any city name, country name, region name, any question, any conversation

**Default rule:**
- If the question is not clearly about bill record/query/sharing, **default to "travel"**
- Only return "bill" when the question explicitly involves bill recording, querying bills, or cost sharing

Please return a JSON format response based on the user's question, containing only the agent field:
- If the question is clearly related to bill record/query/sharing, return {{"agent": "bill"}}
- **All other cases**, return {{"agent": "travel"}}

Important requirements:
- Only output JSON, do not add any explanatory text
- JSON format must be strictly correct
- Only return the agent field

User question: {user_input}

Please determine which agent should be used:"""

# Bill Assistant Prompt
BILL_PROMPT = """You are an AA bill assistant. You have two tasks:

Task 1: Record Bill Information
Extract structured information about one or more expenses from the user's natural language description.

[Fields to Extract]
- topic: The theme/purpose of this expense (e.g., dinner, taxi, hotel, coffee, etc.)
- payer: The person who actually paid (string)
- participants: List of all associated person names (string array)
- amount: Total amount of this expense (number)
- currency: Currency (e.g., "CNY", "GBP", "USD")
- note: Other supplementary information (optional)

[Output Requirements]
- Must output strictly formatted, valid JSON
- The top-level structure of JSON must be an array, with each element representing one expense
- Each item in the array must contain topic, payer, participants, and amount fields
- Do not add any explanatory text, do not output content outside JSON

[Parsing Rules]
- If the user's statement contains multiple expenses, split them into multiple JSON records
- If participants are not mentioned, default participants to all person names that appear, including the payer
- If the user does not mention currency, default currency="CNY"
- If there is an ambiguous amount (e.g., "about 100 yuan"), extract the numeric part as amount=100
- If unable to parse, return an empty array []

Task 2: Query Bill Information
If the user asks about recorded bill information (e.g., "query bill ID 1", "which bills did Zhang San pay", "bills Li Si participated in", etc.), identify this as a query request and return query information.

[Query Recognition]
- If the user mentions keywords like "query", "find", "look", "show", etc., and involves bill ID, payer, participant, etc., this is a query request
- For query requests, extract the query conditions (bill ID, payer, participant, etc.) and return in JSON format:
  {{"query": true, "type": "id|payer|participant", "value": "query value"}}

[Output Format Examples]
Record bill:
[
  {{
    "topic": "Dinner",
    "payer": "Zhang San",
    "participants": ["Zhang San", "Li Si", "Wang Wu"],
    "amount": 200,
    "currency": "CNY",
    "note": ""
  }}
]

Query bill:
{{"query": true, "type": "payer", "value": "Zhang San"}}
or
{{"query": true, "type": "id", "value": "1"}}
or
{{"query": true, "type": "participant", "value": "Li Si"}}

Please always follow the above rules.

User input: {user_input}

Please process:"""

# 旅行路线规划师提示词
ROUTE_PLANNER_PROMPT = """You are a professional Travel Route Planner. Your task is to create detailed travel itineraries and route plans based on user requests.

Your responsibilities include:
- Planning travel routes and itineraries
- Recommending attractions and sightseeing spots
- Suggesting transportation methods between locations
- Organizing daily schedules and time allocations
- Providing destination information
- **MANDATORY: Planning hotel accommodations and listing hotel costs**

IMPORTANT - Hotel Planning Requirement:
You MUST include hotel/accommodation planning in your route plan. For each day or location, you must:
1. Recommend specific hotels or accommodation options
2. Clearly list the hotel costs per night
3. Calculate total accommodation costs for the entire trip
4. Include hotel names, locations, and price ranges

CRITICAL - Hotel Price Accuracy:
You MUST NOT invent hotel prices. You MUST NOT artificially adjust prices to satisfy the user's budget.

If real prices are unknown, you MUST:
- State clearly that the price is an assumption or estimate
- Use a price range (e.g., $80–120 per night) instead of a fixed number
- Never adjust prices artificially to satisfy the user's budget
- Never guarantee accuracy of accommodation or transportation costs
- Base your estimates on realistic market rates for the destination

IMPORTANT - Budget Recognition:
Before planning, carefully analyze the user's question to identify any budget constraints mentioned. Budget information may appear in various formats:
- Explicit mentions: "budget of $100", "预算5000元", "with a budget of 5000", "budget is 1000"
- Currency symbols: "$10", "€100", "£50", "5000元"
- Implicit mentions: "I have 1000 dollars", "spending limit is 5000"
- Currency codes: "5000 USD", "3000 CNY", "2000 EUR"

When you identify a budget:
1. Extract the exact amount and currency
2. Note the budget constraint in your planning
3. Ensure your route plan stays within the specified budget
4. If no budget is mentioned, plan normally without budget constraints

CRITICAL - Destination Recognition:
**ALWAYS prioritize the destination mentioned in the user's current request.**
- If the user mentions a NEW destination (e.g., "I'm traveling to Taipei", "I want to go to Tokyo"), you MUST create a plan for that NEW destination, NOT the previous destination.
- If the user mentions a different city/country than the previous plan, you MUST create a completely new plan for the NEW destination.
- Only use the previous route plan as reference if the user is modifying aspects of the SAME destination (e.g., "change hotels in Paris" when the previous plan was for Paris).

CRITICAL - Partial Modification:
**When the user provides feedback or suggestions about specific parts of the route:**
- DO NOT recreate the entire route plan from scratch
- ONLY modify the specific parts that the user mentioned or complained about
- Keep all other parts of the route plan unchanged
- Clearly indicate which parts were modified and why
- Example: If user says "I don't like the hotel on day 2", only change the hotel for day 2, keep everything else the same

{previous_route_plan}

{budget_constraint}

{revision_request}

Please provide a detailed, practical, and well-organized travel route plan. Format your response clearly with day-by-day breakdowns when applicable. **Remember to always include hotel recommendations with explicit cost breakdowns.**

User question: {user_input}

Please provide the travel route plan:"""

# 饭店规划师提示词
RESTAURANT_PLANNER_PROMPT = """You are a professional Restaurant Planner. Your task is to recommend restaurants based on the travel route plan provided.

Your responsibilities include:
- Finding restaurants near the planned attractions and locations
- Recommending restaurants suitable for each meal (breakfast, lunch, dinner)
- Considering cuisine types, price ranges, and local specialties
- Providing restaurant names, locations, and brief descriptions
- **MANDATORY: Listing estimated prices for each restaurant recommendation**

IMPORTANT - Price Requirements:
You MUST include estimated prices for each restaurant recommendation. For each restaurant, you must:
1. Provide estimated cost per person (or per meal)
2. Include price ranges if applicable (e.g., "$15-25 per person" or "$30-50 for dinner")
3. Specify the currency (USD, EUR, GBP, etc.)
4. If prices vary by meal type, specify prices for breakfast, lunch, and dinner separately
5. Calculate total estimated food costs for the entire trip

Price Format Examples:
- "Restaurant Name - $25-35 per person for dinner"
- "Breakfast: $10-15, Lunch: $20-30, Dinner: $40-60 per person"
- "Estimated cost: €30-50 per meal"

CRITICAL - Price Accuracy:
- Do NOT invent unrealistic prices
- Base prices on realistic market rates for the destination
- If exact prices are unknown, use price ranges
- Clearly indicate if prices are estimates

Previous travel route plan:
{route_plan}

User's original question: {user_input}

Please provide restaurant recommendations that align with the travel route, including detailed price information for each recommendation:"""

BUDGET_CHECKER_PROMPT = """You are a strict **Travel Financial Auditor**. Your goal is to validate the feasibility of a travel route plan and restaurant plan against a user's budget constraints.

**IMPORTANT: ALL RESPONSES MUST BE IN ENGLISH ONLY. Do not use Chinese or any other language. All text in the "reason" and "suggestion" fields must be in English.**

### INPUT DATA
1. **User's Request:** "{user_input}"
2. **User's Budget Constraint:** "{user_budget}"
3. **Proposed Route Plan:** "{route_plan}"
4. **Proposed Restaurant Plan:** "{restaurant_plan}"

---

### WORKFLOW & RULES

**STEP 1: Global Feasibility Check (Sanity Check)**
Before calculating details, check if the budget is **logically impossible** for the destination and duration.
* *Rule:* If the user's budget is less than 30% of the minimum viable cost for that destination (e.g., $10 for a 3-day Europe trip, or $50 for a flight to another continent), immediately flag as **"IMPOSSIBLE"**.
* *Action:* Skip detailed calculation. Set `is_feasible` to `false` and `error_type` to `"HARD_LIMIT"`.

**STEP 2: Data Normalization**
* **Identify Currency:** Determine the user's budget currency. If the route plan uses a different currency, convert ALL costs to the **User's Currency** using current approximate exchange rates.
* **Missing Budget:** If no budget is specified, assume "Unlimited/Flexible" (set `max_budget` to `null`).

**STEP 3: Detailed Cost Audit (The Calculation)**
If the plan passes the Sanity Check, analyze both the `Route Plan` and `Restaurant Plan` line by line:
1.  **Validate Costs:** Do not blindly trust the prices in the route plan or restaurant plan. If a price seems unrealistically low (e.g., "Hotel: $5"), replace it with a **realistic market average** for that location.
2.  **Estimate Missing Costs:** If "Lunch" or "Taxi" is mentioned without a price, estimate it based on the city's standard of living.
3.  **Calculate Route Costs:** Sum all costs from the route plan (Transport + Accommodation + Activities).
4.  **Calculate Restaurant Costs:** Sum all costs from the restaurant plan (all meals mentioned).
5.  **Add Buffer:** Add a **10% contingency fund** to the total for unexpected expenses.
6.  **Summation:** Calculate `Total_Estimated_Cost` = (Route Costs + Restaurant Costs + Buffer).

**STEP 4: Final Assessment**
* Calculate `Remaining` = `Max_Budget` - `Total_Estimated_Cost`.
* If `Remaining` >= 0, `budget_ok` is `true`.
* If `Remaining` < 0, `budget_ok` is `false`.

---

### OUTPUT FORMAT
Return **ONLY** a valid JSON object. No Markdown blocks. No preamble.

**CRITICAL: All text in "reason" and "suggestion" fields MUST be in English only.**

{{
  "is_feasible": boolean,       // true if the plan is physically possible with reasonable money; false if absurd (e.g. $10 trip)
  "budget_ok": boolean,         // true if Total <= Budget
  "currency": "string",         // e.g., "USD", "CNY", "EUR"
  "max_budget": number,         // User's limit (or null)
  "total_estimated_cost": number,
  "remaining_budget": number,   // max_budget - total (negative means deficit)
  "error_type": "string",       // Options: "NONE", "OVER_BUDGET", "HARD_LIMIT" (for absurd requests)
  "reason": "string",           // Detailed explanation for the user (ENGLISH ONLY)
  "suggestion": "string"        // Actionable advice (ENGLISH ONLY, e.g., "Increase budget by $200" or "Don't go to Europe with $10")
}}

---

### REASONING EXAMPLES

**Scenario A: Absurd Input (Sanity Check Fail)**
*Input:* "Budget $20, Trip to London for 5 days."
*Output:*
{{
  "is_feasible": false,
  "budget_ok": false,
  "currency": "USD",
  "max_budget": 20,
  "total_estimated_cost": 1500,
  "remaining_budget": -1480,
  "error_type": "HARD_LIMIT",
  "reason": "Your $20 budget is completely impossible for a 5-day trip to London. The minimum daily accommodation and food costs in London are typically over $100, not including airfare.",
  "suggestion": "Please significantly increase your budget to at least $1500, or consider local free park walking activities instead."
}}

**Scenario B: Slightly Over Budget**
*Input:* "Budget $1000, Trip to Tokyo." (Calculated cost is $1200)
*Output:*
{{
  "is_feasible": true,
  "budget_ok": false,
  "currency": "USD",
  "max_budget": 1000,
  "total_estimated_cost": 1200,
  "remaining_budget": -200,
  "error_type": "OVER_BUDGET",
  "reason": "The estimated total cost for this trip is $1200, which exceeds your $1000 budget. The main expenses are peak-season airfare and four-star hotels.",
  "suggestion": "Consider downgrading to business hotels or shortening the trip by one day, which could save approximately $250."
}}
"""
# 旅行规划Supervisor提示词
TRAVEL_SUPERVISOR_PROMPT = """You are a Travel Planning Supervisor. Your task is to analyze the user's request and determine what type of modification or planning they need.

Context:
- Previous route plan (if exists): {previous_route_plan}
- Previous restaurant plan (if exists): {previous_restaurant_plan}
- Previous budget (if exists): {previous_budget}
- Awaiting replan confirmation (if exists): {awaiting_replan_confirmation}

User's current request: {user_input}

You need to determine the user's intent and return ONLY a JSON object with the following structure:
{{
  "intent": "string",  // One of: "new_plan", "modify_route", "modify_restaurant", "modify_budget", "replan_after_budget_fail", "confirm_plan"
  "reason": "string"   // Brief explanation of your decision
}}

Intent meanings:
- "new_plan": User is asking for a completely new travel plan (first time or wants to start over). Execute: Route Planner → Restaurant Planner → Budget Checker
- "modify_route": User wants to modify only the route/itinerary (e.g., "change the route", "update itinerary", "modify the schedule"). Execute: Route Planner (replan) → Budget Checker (new route + old restaurant)
- "modify_restaurant": User wants to modify only the restaurant recommendations (e.g., "change restaurants", "update dining options", "modify food plan"). Execute: Restaurant Planner (replan) → Budget Checker (old route + new restaurant)
- "modify_budget": User wants to change the budget only (e.g., "change budget to $2000", "update budget", "new budget is $1500"). Execute: Budget Checker (old route + old restaurant + new budget)
- "replan_after_budget_fail": User is confirming they want to replan after a budget check failure. This happens when:
  * "awaiting_replan_confirmation" is "true" or "yes"
  * AND user responds with "yes", "ok", "sure", "replan", "confirm", "proceed", or similar affirmative responses
  * Execute: Route Planner (replan) → Restaurant Planner (replan) → Budget Checker
- "confirm_plan": User explicitly wants to confirm/finalize the current travel plan. This happens when:
  * There is an existing route plan and/or restaurant plan
  * AND user explicitly mentions "confirm", "finalize", "确定计划", "确认方案", "确定", "finalize plan", "confirm plan", "let's confirm", "确认一下", or similar confirmation requests
  * Execute: Plan Confirmation Agent

Important rules:
1. If "awaiting_replan_confirmation" is "true" or "yes", and user's response is affirmative (yes, ok, sure, replan, etc.), it's "replan_after_budget_fail"
2. If there's no previous route plan or restaurant plan, it's always "new_plan"
3. If user explicitly mentions confirming/finalizing the plan (e.g., "confirm", "finalize", "finalize plan", "confirm plan", "let's confirm"), and there's an existing plan, it's "confirm_plan"
4. If user explicitly mentions changing route/itinerary/schedule, it's "modify_route"
5. If user provides feedback, suggestions, or opinions about the route/itinerary (e.g., "I don't like this part", "change this", "modify that", "this is not good", "I prefer...", "can we change...", "I think we should...", "maybe we could...", "how about..."), it's "modify_route"
   - **In a multi-user chatroom:** If a previous route plan exists and the user is commenting on, suggesting changes to, or providing feedback about the existing plan (even if they didn't create it), it's "modify_route"
6. If user explicitly mentions changing restaurants/dining/food, it's "modify_restaurant"
7. If user explicitly mentions changing budget/price/cost, it's "modify_budget"
8. If intent is unclear, default to "new_plan"

Return ONLY the JSON object, no additional text."""

# 预算提取Agent提示词
BUDGET_EXTRACTOR_PROMPT = """You are a Budget Extractor Agent. Your task is to extract the budget amount from user input.

User input: {user_input}

Your task:
1. Identify if the user mentions a budget amount in their input
2. Extract the numerical budget value
3. Identify the currency (USD, CNY, EUR, GBP, etc.) - default to USD if not specified
4. Convert any currency mentions to the standard currency code

Output format:
Return ONLY a valid JSON object. No Markdown blocks. No preamble.

{{
  "budget": number or null,  // The budget amount as a number (e.g., 1500, 2000.5). null if no budget mentioned
  "currency": "string",       // Currency code (e.g., "USD", "CNY", "EUR"). Default to "USD" if not specified
  "found": boolean            // true if a budget was found, false otherwise
}}

Examples:
Input: "change budget to 1500"
Output: {{"budget": 1500, "currency": "USD", "found": true}}

Input: "update budget to $2000"
Output: {{"budget": 2000, "currency": "USD", "found": true}}

Input: "new budget is 5000 yuan"
Output: {{"budget": 5000, "currency": "CNY", "found": true}}

Input: "I want to travel to Paris"
Output: {{"budget": null, "currency": "USD", "found": false}}

Input: "budget of 3000 dollars"
Output: {{"budget": 3000, "currency": "USD", "found": true}}

Return ONLY the JSON object, no additional text."""

# 调解者Agent提示词
MEDIATOR_PROMPT = """You are a Mediator Agent in a multi-user travel planning chatroom. Your role is to coordinate modifications to travel plans when multiple users are involved.

Context:
- Current route plan: {route_plan}
- Current restaurant plan: {restaurant_plan}
- User requesting modification: {requesting_user}
- Modification request: {modification_request}
- Active users in chatroom: {active_users}

Your task:
1. Present the modification request clearly to all users
2. Ask for agreement from all active users **(excluding the user who initiated the modification)**
3. Wait for everyone to respond with "agree", "yes", "ok", or similar affirmative responses
4. If everyone agrees, proceed with the modification
5. If anyone disagrees or doesn't respond, keep the original plan unchanged

Output format:
- Start with a clear summary of the proposed modification
- List all active users who need to agree
- Ask for explicit confirmation from everyone
- Be friendly and collaborative

Remember: You must wait for ALL active users to agree before proceeding with any modifications."""

# 计划确定师Agent提示词
PLAN_CONFIRMATION_PROMPT = """You are a Plan Confirmation Agent in a multi-user travel planning chatroom. Your role is to finalize travel plans after all planning is complete.

Context:
- Final route plan: {route_plan}
- Final restaurant plan: {restaurant_plan}
- Budget check result: {budget_check_result}
- Active users in chatroom: {active_users}

Your task:
1. **Briefly ask for final confirmation from all active users** - DO NOT repeat the entire plan details
2. List all active users who need to confirm
3. Ask for explicit confirmation from everyone
4. Wait for everyone to respond with "confirm", "agree", "yes", "ok", or similar affirmative responses
5. If everyone confirms, announce that the plan is finalized
6. If anyone objects or wants changes, allow them to request modifications

Output format:
- **Keep it brief and concise** - just ask for confirmation, do NOT repeat all the plan details
- Example: "The travel plan has been completed. Please confirm if you agree with this plan. Waiting for confirmation from: [list of users]"
- List all active users who need to confirm
- Ask for explicit confirmation from everyone
- Be celebratory when everyone agrees

Remember: 
- **DO NOT repeat the entire plan** - users have already seen it
- Just ask for confirmation briefly
- The plan is only finalized when ALL active users confirm. If anyone objects, they can request modifications."""

# Fallback/Generalist AI 提示词
FALLBACK_PROMPT = """You are the Fallback/Generalist AI Agent. Your role is strictly to handle user inputs that were flagged as AMBIGUOUS or out-of-scope by the Main Routing Agent.

Your primary function is to politely acknowledge the user's input and immediately delegate them to the appropriate specialist agent when possible, or state your limitations.

Core Directive:
You MUST NOT answer the user's request.
You MUST NOT attempt to route the request again.
Your output must be a brief, conversational response that serves as a dead-end for the current turn, either redirecting the user or stating the bot's specialty.

Output Rules (Strictly One of Two Types):

If the request clearly involves MONEY/EXPENSES:
Acknowledge the ambiguity and redirect the user to the Budget Tracker.
Example Response: "That sounds like a question for the budget. Could you rephrase your question for the Budget Tracker?"

If the request is GENERAL, VAGUE, or completely OUT-OF-SCOPE (e.g., a greeting, a question about global politics, or a combined topic):
Acknowledge the ambiguity and state the bot's core function (Trip Planning & Budget Tracking) to guide future user inputs.
Example Response: "I apologize, I'm only specialized in trip planning and expense tracking. Could you ask me about your itinerary or budget?"

User input: {user_input}

Please respond:"""

# 初始化 LangChain
api_key = os.getenv('OPENAI_API_KEY', '')
if not api_key:
    print("警告: OPENAI_API_KEY 未设置，请检查 .env 文件")
    llm = None
else:
    try:
        # 使用 LangChain 初始化 ChatOpenAI
        # 使用最新的 GPT-4o 模型
        llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            streaming=True,
            api_key=api_key
        )
        print("LangChain 初始化成功 (使用模型: gpt-4o)")
    except Exception as e:
        print(f"初始化 LangChain 时出错: {e}")
        llm = None

# 创建提示词模板
router_template = ChatPromptTemplate.from_template(ROUTER_PROMPT)
bill_template = ChatPromptTemplate.from_template(BILL_PROMPT)
route_planner_template = ChatPromptTemplate.from_template(ROUTE_PLANNER_PROMPT)
restaurant_planner_template = ChatPromptTemplate.from_template(RESTAURANT_PLANNER_PROMPT)
budget_checker_template = ChatPromptTemplate.from_template(BUDGET_CHECKER_PROMPT)
travel_supervisor_template = ChatPromptTemplate.from_template(TRAVEL_SUPERVISOR_PROMPT)
mediator_template = ChatPromptTemplate.from_template(MEDIATOR_PROMPT)
plan_confirmation_template = ChatPromptTemplate.from_template(PLAN_CONFIRMATION_PROMPT)
fallback_template = ChatPromptTemplate.from_template(FALLBACK_PROMPT)
budget_extractor_template = ChatPromptTemplate.from_template(BUDGET_EXTRACTOR_PROMPT)

# 创建输出解析器
output_parser = StrOutputParser()

# 创建链
if llm:
    router_chain = router_template | llm | output_parser
    bill_chain = bill_template | llm | output_parser
    route_planner_chain = route_planner_template | llm | output_parser
    restaurant_planner_chain = restaurant_planner_template | llm | output_parser
    budget_checker_chain = budget_checker_template | llm | output_parser
    travel_supervisor_chain = travel_supervisor_template | llm | output_parser
    mediator_chain = mediator_template | llm | output_parser
    plan_confirmation_chain = plan_confirmation_template | llm | output_parser
    fallback_chain = fallback_template | llm | output_parser
    budget_extractor_chain = budget_extractor_template | llm | output_parser
else:
    router_chain = None
    bill_chain = None
    route_planner_chain = None
    restaurant_planner_chain = None
    budget_checker_chain = None
    travel_supervisor_chain = None
    mediator_chain = None
    plan_confirmation_chain = None
    fallback_chain = None
    budget_extractor_chain = None


def extract_json_from_text(text):
    """从文本中提取 JSON 内容"""
    # 尝试找到 JSON 对象
    json_match = re.search(r'\{.*?\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except:
            pass
    
    # 如果没找到对象，尝试找数组
    json_match = re.search(r'\[.*?\]', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except:
            pass
    
    # 如果都没找到，尝试解析整个文本
    try:
        return json.loads(text)
    except:
        return None


def parse_router_response(text):
    """解析路由响应，提取agent类型"""
    try:
        result = extract_json_from_text(text)
        if result and isinstance(result, dict):
            agent = result.get('agent', 'unknown')
            if agent in ['travel', 'bill', 'unknown']:
                return agent
        return 'unknown'
    except:
        return 'unknown'


def save_bills_to_db(bills_data, user_input):
    """保存账单数据到数据库，返回保存的ID列表"""
    with app.app_context():
        try:
            saved_ids = []
            for bill_data in bills_data:
                # 验证必需字段
                if not all(key in bill_data for key in ['topic', 'payer', 'participants', 'amount']):
                    continue
                
                # 创建账单记录
                bill = Bill(
                    topic=bill_data.get('topic', ''),
                    payer=bill_data.get('payer', ''),
                    participants=json.dumps(bill_data.get('participants', []), ensure_ascii=False),
                    amount=float(bill_data.get('amount', 0)),
                    currency=bill_data.get('currency', 'CNY'),
                    note=bill_data.get('note', ''),
                    user_input=user_input
                )
                db.session.add(bill)
                db.session.flush()  # 获取ID
                saved_ids.append(bill.id)
            
            db.session.commit()
            return saved_ids
        except Exception as e:
            db.session.rollback()
            print(f'保存账单错误: {str(e)}')
            return []


def query_bills_from_db(query_type, query_value):
    """根据查询类型和值查询账单"""
    with app.app_context():
        try:
            if query_type == 'id':
                # 按ID查询
                bill = Bill.query.get(int(query_value))
                return [bill] if bill else []
            elif query_type == 'payer':
                # 按付款人查询
                bills = Bill.query.filter(Bill.payer.like(f'%{query_value}%')).order_by(Bill.created_at.desc()).all()
                return bills
            elif query_type == 'participant':
                # 按参与者查询
                bills = Bill.query.filter(Bill.participants.like(f'%{query_value}%')).order_by(Bill.created_at.desc()).all()
                return bills
            else:
                return []
        except Exception as e:
            print(f'查询账单错误: {str(e)}')
            return []


def format_bills_for_display(bills):
    """格式化账单数据用于显示"""
    if not bills:
        return "No matching bill records found."
    
    result = []
    for bill in bills:
        participants = json.loads(bill.participants) if isinstance(bill.participants, str) else bill.participants
        participants_str = ', '.join(participants) if isinstance(participants, list) else str(participants)
        
        bill_info = f"Bill ID: {bill.id}\n"
        bill_info += f"Topic: {bill.topic}\n"
        bill_info += f"Payer: {bill.payer}\n"
        bill_info += f"Participants: {participants_str}\n"
        bill_info += f"Amount: {bill.amount} {bill.currency}\n"
        if bill.note:
            bill_info += f"Note: {bill.note}\n"
        bill_info += f"Created at: {bill.created_at.strftime('%Y-%m-%d %H:%M:%S') if bill.created_at else 'Unknown'}\n"
        result.append(bill_info)
    
    return "\n\n".join(result)


def extract_budget_with_agent(user_input):
    """使用 AI agent 从用户输入中提取预算"""
    if not llm or not budget_extractor_chain:
        return None
    
    try:
        # 调用预算提取 agent
        response = ""
        for chunk in budget_extractor_chain.stream({"user_input": user_input}):
            if chunk:
                response += chunk
        
        # 解析 JSON 响应
        budget_result = extract_json_from_text(response)
        if budget_result and isinstance(budget_result, dict):
            if budget_result.get("found", False):
                budget_value = budget_result.get("budget")
                if budget_value is not None:
                    return float(budget_value)
        return None
    except Exception as e:
        print(f"Error extracting budget with agent: {e}")
        import traceback
        traceback.print_exc()
        return None


def extract_travel_info(user_input):
    """从用户输入中提取旅行信息：目的地（大洲）、预算、天数"""
    user_input_lower = user_input.lower()
    
    # 提取天数（保留正则表达式，因为天数提取相对简单）
    days = None
    day_patterns = [
        r'(\d+)\s*days?',
        r'(\d+)\s*day',
        r'(\d+)\s*-day',
        r'for\s*(\d+)\s*days?',
        r'(\d+)\s*night',
        r'(\d+)\s*nights?'
    ]
    for pattern in day_patterns:
        match = re.search(pattern, user_input_lower)
        if match:
            days = int(match.group(1))
            break
    
    # 使用 AI agent 提取预算
    budget = extract_budget_with_agent(user_input)
    
    # 识别目的地（大洲）
    continent = None
    continent_keywords = {
        "Asia": ["asia", "asian", "china", "japan", "korea", "india", "thailand", "vietnam", "singapore", "malaysia", "indonesia", "philippines", "taiwan", "hong kong", "bangkok", "tokyo", "beijing", "shanghai", "seoul", "mumbai", "delhi"],
        "Europe": ["europe", "european", "france", "germany", "italy", "spain", "uk", "united kingdom", "london", "paris", "rome", "berlin", "madrid", "amsterdam", "vienna", "prague", "athens"],
        "North America": ["north america", "usa", "united states", "america", "canada", "mexico", "new york", "los angeles", "chicago", "san francisco", "toronto", "vancouver", "miami"],
        "South America": ["south america", "brazil", "argentina", "chile", "peru", "colombia", "rio", "buenos aires", "lima", "santiago"],
        "Africa": ["africa", "african", "south africa", "egypt", "morocco", "kenya", "cape town", "cairo", "marrakech"],
        "Oceania": ["oceania", "australia", "new zealand", "sydney", "melbourne", "auckland", "queensland"]
    }
    
    for cont, keywords in continent_keywords.items():
        if any(keyword in user_input_lower for keyword in keywords):
            continent = cont
            break
    
    return {
        "continent": continent,
        "budget": budget,
        "days": days
    }


def parse_budget_check_result(budget_check_response):
    """解析预算检查结果"""
    # 从JSON响应中提取预算检查结果
    
    # 尝试解析JSON
    budget_check_result = extract_json_from_text(budget_check_response)
    result = {
        "success": True,
        "budget_ok": None,
        "is_feasible": True,
        "reason": "",
        "suggestion": ""
    }
    
    if budget_check_result and isinstance(budget_check_result, dict):
        # 成功解析JSON（使用新的格式）
        result["budget_ok"] = budget_check_result.get('budget_ok', None)
        result["is_feasible"] = budget_check_result.get('is_feasible', True)
        total_estimated_cost = budget_check_result.get('total_estimated_cost', 0)
        max_budget = budget_check_result.get('max_budget', None)
        remaining_budget = budget_check_result.get('remaining_budget', 0)
        error_type = budget_check_result.get('error_type', 'NONE')
        result["reason"] = budget_check_result.get('reason', '')
        result["suggestion"] = budget_check_result.get('suggestion', '')
    else:
        # 如果无法解析JSON，尝试从文本中提取
        # 默认假设在预算内（如果没有明确的预算约束）
        result["budget_ok"] = True
        result["reason"] = "Unable to parse budget check result. Assuming within budget."
    
    return result


def get_or_create_user(user_id, session_id=None):
    """获取或创建用户，分配随机名字"""
    if user_id not in user_storage:
        # 生成随机名字
        available_names = [name for name in RANDOM_NAMES if name not in [u.get("name") for u in user_storage.values()]]
        if not available_names:
            # 如果所有名字都用完了，添加数字后缀
            name = random.choice(RANDOM_NAMES) + str(random.randint(1, 999))
        else:
            name = random.choice(available_names)
        
        user_storage[user_id] = {
            "name": name,
            "session_id": session_id
        }
    
    return user_storage[user_id]


def get_active_users_count():
    """获取当前活跃用户数量（通过SSE连接判断）"""
    with sse_connections_lock:
        return len(sse_connections)


def get_active_users_list():
    """获取当前活跃用户列表"""
    active_users = []
    with sse_connections_lock:
        for user_id in sse_connections.keys():
            if user_id in user_storage:
                active_users.append({
                    "user_id": user_id,
                    "username": user_storage[user_id]["name"]
                })
    return active_users


def check_all_users_agreed(session_id, vote_type="mediation", exclude_user_id=None):
    """检查所有活跃用户是否都同意了（排除指定用户）"""
    if session_id not in vote_storage:
        return False
    
    votes = vote_storage[session_id].get(vote_type + "_votes", {})
    active_users = get_active_users_list()
    
    if len(active_users) == 0:
        return False
    
    # 过滤掉发起者（如果指定）
    users_to_check = active_users
    if exclude_user_id:
        users_to_check = [u for u in active_users if u["user_id"] != exclude_user_id]
    
    if len(users_to_check) == 0:
        return True  # 如果没有需要检查的用户，返回True
    
    # 检查所有需要检查的用户是否都同意了
    for user in users_to_check:
        user_id = user["user_id"]
        vote = votes.get(user_id, "pending")
        if vote != "agree":
            return False
    
    # 确保所有需要检查的用户都已经投票
    agreed_count = sum(1 for user in users_to_check if votes.get(user["user_id"]) == "agree")
    result = agreed_count == len(users_to_check) and agreed_count > 0
    
    # 调试信息
    print(f"[DEBUG] check_all_users_agreed: session_id={session_id}, vote_type={vote_type}, exclude_user_id={exclude_user_id}")
    print(f"[DEBUG] active_users={[u['user_id'] for u in active_users]}, users_to_check={[u['user_id'] for u in users_to_check]}")
    print(f"[DEBUG] votes={votes}, agreed_count={agreed_count}, len(users_to_check)={len(users_to_check)}, result={result}")
    
    return result


def reset_votes(session_id, vote_type="mediation", exclude_user_id=None):
    """重置投票状态（排除指定用户）"""
    if session_id not in vote_storage:
        vote_storage[session_id] = {}
    
    active_users = get_active_users_list()
    votes = {}
    for user in active_users:
        # 如果是调解者投票且指定了排除用户，则跳过发起者
        if exclude_user_id and user["user_id"] == exclude_user_id:
            continue
        votes[user["user_id"]] = "pending"
    
    vote_storage[session_id][vote_type + "_votes"] = votes


def execute_route_modification(session_id, modification_request, route_plan, restaurant_plan, previous_budget, travel_info, user_id, username):
    """执行路线修改"""
    # 提取预算约束（优先从存储中获取最新预算，因为用户可能已经修改过预算）
    current_budget = None
    if session_id in travel_plan_storage:
        current_budget = travel_plan_storage[session_id].get("budget")
    # 如果存储中没有，尝试从 travel_info 中获取
    if not current_budget and travel_info:
        current_budget = travel_info.get("budget")
    # 如果还是没有，使用传入的 previous_budget
    if not current_budget:
        current_budget = previous_budget
    budget_constraint_text = ""
    if current_budget:
        budget_constraint_text = f"\nBudget constraint: ${current_budget:.2f}\n"
    
    # 准备之前的路线计划作为上下文
    previous_route_plan_context = ""
    if route_plan and len(route_plan.strip()) > 10:
        previous_route_plan_context = f"\n=== PREVIOUS ROUTE PLAN (MODIFY ONLY THE PARTS USER MENTIONED, KEEP EVERYTHING ELSE UNCHANGED) ===\n{route_plan[:3000]}\n=== END OF PREVIOUS ROUTE PLAN ===\n"
    else:
        previous_route_plan_context = "\nNo previous route plan exists.\n"
    
    planner_name = "🗺️ Travel Route Planner"
    yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
    
    route_plan = ""
    route_plan_input = {
        "user_input": modification_request,
        "previous_route_plan": previous_route_plan_context,
        "budget_constraint": budget_constraint_text,
        "revision_request": f"IMPORTANT: The user is providing feedback or requesting modifications to the existing route plan. Your task is to MODIFY ONLY the specific parts they mentioned:\n- If they mention a NEW destination (different city/country), create a completely NEW plan for that destination.\n- If they are providing feedback, suggestions, or complaints about specific parts (e.g., 'I don't like this hotel', 'change this attraction', 'modify day 2', 'this is not good'), ONLY modify those specific parts. Keep ALL other parts of the route plan EXACTLY as they were.\n- DO NOT recreate the entire route plan unless the user explicitly asks for a complete replan.\n- When you modify a part, clearly indicate which parts were changed and why.\n- Preserve the structure, format, and all unchanged content from the previous plan.\n\nUser's feedback/request: {modification_request}"
    }
    
    for chunk in route_planner_chain.stream(route_plan_input):
        if chunk:
            route_plan += chunk
            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
    
    # 预算检查
    budget_checker_name = "💰 Budget Checker"
    yield f"data: {json.dumps({'type': 'planner_start', 'planner': budget_checker_name})}\n\n"
    
    budget_str = str(current_budget) if current_budget else ""
    budget_check_response = ""
    for chunk in budget_checker_chain.stream({
        "user_budget": budget_str,
        "user_input": modification_request,
        "route_plan": route_plan,
        "restaurant_plan": restaurant_plan
    }):
        if chunk:
            budget_check_response += chunk
    
    budget_check_result = parse_budget_check_result(budget_check_response)
    budget_ok = budget_check_result["budget_ok"]
    is_feasible = budget_check_result.get("is_feasible", True)
    budget_reason = budget_check_result["reason"]
    budget_suggestion = budget_check_result.get("suggestion", "")
    
    # 流式发送reason字段
    if budget_reason:
        chunk_size = 50
        for i in range(0, len(budget_reason), chunk_size):
            chunk = budget_reason[i:i + chunk_size]
            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': chunk})}\n\n"
    else:
        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': 'Budget check completed.'})}\n\n"
    
    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': budget_checker_name})}\n\n"
    
    # 检查预算是否失败
    if budget_ok is False or is_feasible is False:
        yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Budget Alert'})}\n\n"
        
        budget_alert = f"\n⚠️ **Budget Check Failed**\n\n"
        if budget_reason:
            budget_alert += f"{budget_reason}\n\n"
        if budget_suggestion:
            budget_alert += f"**Suggestion:**\n{budget_suggestion}\n\n"
        
        # 询问用户是否要重新规划
        budget_alert += f"\n**Would you like me to replan the route and restaurants to fit your budget?**\n"
        budget_alert += f"Please reply with 'yes', 'ok', 'replan', or 'replan' if you want me to create a new plan within your budget.\n"
        
        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Budget Alert', 'content': budget_alert})}\n\n"
        yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Budget Alert'})}\n\n"
        
        # 保存状态，标记正在等待用户确认重新规划
        travel_plan_storage[session_id]["awaiting_replan_confirmation"] = True
        travel_plan_storage[session_id]["route_plan"] = route_plan
        travel_plan_storage[session_id]["restaurant_plan"] = restaurant_plan
        return
    
    # 更新状态（预算检查通过）
    travel_plan_storage[session_id]["route_plan"] = route_plan
    travel_plan_storage[session_id]["awaiting_mediation"] = False
    travel_plan_storage[session_id]["awaiting_replan_confirmation"] = False
    travel_plan_storage[session_id]["pending_modification_request"] = ""
    travel_plan_storage[session_id]["mediation_requesting_user_id"] = ""
    travel_plan_storage[session_id]["mediation_modification_type"] = ""


def execute_restaurant_modification(session_id, modification_request, route_plan, restaurant_plan, previous_budget, travel_info, user_id, username):
    """执行餐厅修改"""
    planner_name = "🍽️ Restaurant Planner"
    yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
    
    restaurant_plan = ""
    for chunk in restaurant_planner_chain.stream({
        "user_input": modification_request,
        "route_plan": route_plan
    }):
        if chunk:
            restaurant_plan += chunk
            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
    
    # 预算检查
    budget_checker_name = "💰 Budget Checker"
    yield f"data: {json.dumps({'type': 'planner_start', 'planner': budget_checker_name})}\n\n"
    
    # 优先从存储中获取最新预算（因为用户可能已经修改过预算）
    current_budget = None
    if session_id in travel_plan_storage:
        current_budget = travel_plan_storage[session_id].get("budget")
    # 如果存储中没有，尝试从 travel_info 中获取
    if not current_budget and travel_info:
        current_budget = travel_info.get("budget")
    # 如果还是没有，使用传入的 previous_budget
    if not current_budget:
        current_budget = previous_budget
    budget_str = str(current_budget) if current_budget else ""
    budget_check_response = ""
    for chunk in budget_checker_chain.stream({
        "user_budget": budget_str,
        "user_input": modification_request,
        "route_plan": route_plan,
        "restaurant_plan": restaurant_plan
    }):
        if chunk:
            budget_check_response += chunk
    
    budget_check_result = parse_budget_check_result(budget_check_response)
    budget_ok = budget_check_result["budget_ok"]
    is_feasible = budget_check_result.get("is_feasible", True)
    budget_reason = budget_check_result["reason"]
    budget_suggestion = budget_check_result.get("suggestion", "")
    
    # 流式发送reason字段
    if budget_reason:
        chunk_size = 50
        for i in range(0, len(budget_reason), chunk_size):
            chunk = budget_reason[i:i + chunk_size]
            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': chunk})}\n\n"
    else:
        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': 'Budget check completed.'})}\n\n"
    
    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': budget_checker_name})}\n\n"
    
    # 检查预算是否失败
    if budget_ok is False or is_feasible is False:
        yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Budget Alert'})}\n\n"
        
        budget_alert = f"\n⚠️ **Budget Check Failed**\n\n"
        if budget_reason:
            budget_alert += f"{budget_reason}\n\n"
        if budget_suggestion:
            budget_alert += f"**Suggestion:**\n{budget_suggestion}\n\n"
        
        # 询问用户是否要重新规划
        budget_alert += f"\n**Would you like me to replan the route and restaurants to fit your budget?**\n"
        budget_alert += f"Please reply with 'yes', 'ok', 'replan', or 'replan' if you want me to create a new plan within your budget.\n"
        
        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Budget Alert', 'content': budget_alert})}\n\n"
        yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Budget Alert'})}\n\n"
        
        # 保存状态，标记正在等待用户确认重新规划
        travel_plan_storage[session_id]["awaiting_replan_confirmation"] = True
        travel_plan_storage[session_id]["route_plan"] = route_plan
        travel_plan_storage[session_id]["restaurant_plan"] = restaurant_plan
        return
    
    # 更新状态（预算检查通过）
    travel_plan_storage[session_id]["restaurant_plan"] = restaurant_plan
    travel_plan_storage[session_id]["awaiting_mediation"] = False
    travel_plan_storage[session_id]["awaiting_replan_confirmation"] = False
    travel_plan_storage[session_id]["pending_modification_request"] = ""
    travel_plan_storage[session_id]["mediation_requesting_user_id"] = ""
    travel_plan_storage[session_id]["mediation_modification_type"] = ""


def execute_budget_modification(session_id, modification_request, route_plan, restaurant_plan, previous_budget, travel_info, user_id, username):
    """执行预算修改"""
    # 提取新预算（优先使用 travel_info，如果没有则直接从 modification_request 中提取）
    new_budget = None
    if travel_info and travel_info.get("budget"):
        new_budget = travel_info.get("budget")
    else:
        # 如果 travel_info 中没有预算，直接从 modification_request 中使用 AI agent 提取
        new_budget = extract_budget_with_agent(modification_request)
    
    # 如果仍然没有提取到，使用 previous_budget（但这种情况不应该发生）
    if new_budget is None:
        new_budget = previous_budget
        print(f"[WARNING] Could not extract new budget from request: {modification_request}, using previous budget: {previous_budget}")
    else:
        print(f"[DEBUG] Extracted new budget: {new_budget} from request: {modification_request}")
    
    # 预算检查（老路线 + 老饭店 + 新预算）
    budget_checker_name = "💰 Budget Checker"
    yield f"data: {json.dumps({'type': 'planner_start', 'planner': budget_checker_name})}\n\n"
    
    budget_str = str(new_budget) if new_budget else ""
    print(f"[DEBUG] Using budget_str for budget checker: {budget_str}")
    budget_check_response = ""
    for chunk in budget_checker_chain.stream({
        "user_budget": budget_str,
        "user_input": modification_request,
        "route_plan": route_plan,
        "restaurant_plan": restaurant_plan
    }):
        if chunk:
            budget_check_response += chunk
    
    budget_check_result = parse_budget_check_result(budget_check_response)
    budget_ok = budget_check_result["budget_ok"]
    is_feasible = budget_check_result["is_feasible"]
    budget_reason = budget_check_result["reason"]
    budget_suggestion = budget_check_result["suggestion"]
    
    # 流式发送reason字段
    if budget_reason:
        chunk_size = 50
        for i in range(0, len(budget_reason), chunk_size):
            chunk = budget_reason[i:i + chunk_size]
            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': chunk})}\n\n"
    else:
        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': 'Budget check completed.'})}\n\n"
    
    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': budget_checker_name})}\n\n"
    
    # 检查预算是否失败
    if budget_ok is False or is_feasible is False:
        yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Budget Alert'})}\n\n"
        
        budget_alert = f"\n⚠️ **Budget Check Failed**\n\n"
        if budget_reason:
            budget_alert += f"{budget_reason}\n\n"
        if budget_suggestion:
            budget_alert += f"**Suggestion:**\n{budget_suggestion}\n\n"
        
        # 询问用户是否要重新规划
        budget_alert += f"\n**Would you like me to replan the route and restaurants to fit your budget?**\n"
        budget_alert += f"Please reply with 'yes', 'ok', 'replan', or 'replan' if you want me to create a new plan within your budget.\n"
        
        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Budget Alert', 'content': budget_alert})}\n\n"
        yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Budget Alert'})}\n\n"
        
        # 保存状态，标记正在等待用户确认重新规划
        travel_plan_storage[session_id]["awaiting_replan_confirmation"] = True
        travel_plan_storage[session_id]["route_plan"] = route_plan
        travel_plan_storage[session_id]["restaurant_plan"] = restaurant_plan
        
        # 更新预算（即使检查失败也更新，因为用户明确要求修改预算）
        if new_budget:
            travel_plan_storage[session_id]["budget"] = new_budget
        
        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
        return
    
    # 更新预算（预算检查通过）
    if new_budget:
        travel_plan_storage[session_id]["budget"] = new_budget
    
    # 更新状态
    travel_plan_storage[session_id]["awaiting_mediation"] = False
    travel_plan_storage[session_id]["awaiting_replan_confirmation"] = False
    travel_plan_storage[session_id]["pending_modification_request"] = ""
    travel_plan_storage[session_id]["mediation_requesting_user_id"] = ""
    travel_plan_storage[session_id]["mediation_modification_type"] = ""


def broadcast_message(message_data):
    """广播消息给所有连接的客户端"""
    # 确保消息有id
    if 'id' not in message_data:
        message_data['id'] = str(uuid.uuid4())
    
    with message_queue_lock:
        # 如果是更新现有消息（相同id），更新队列中的消息而不是追加
        message_id = message_data.get('id')
        updated = False
        for i, msg in enumerate(message_queue):
            if msg.get('id') == message_id:
                message_queue[i] = message_data
                updated = True
                break
        
        if not updated:
            message_queue.append(message_data)
            # 保持消息队列大小（最多保留最近1000条消息）
            if len(message_queue) > 1000:
                message_queue.pop(0)
    
    # 发送给所有SSE连接
    with sse_connections_lock:
        disconnected_users = []
        for user_id, msg_queue in sse_connections.items():
            try:
                msg_queue.put_nowait(message_data)
            except queue.Full:
                # 队列满了，可能客户端断开连接
                disconnected_users.append(user_id)
            except Exception as e:
                disconnected_users.append(user_id)
        
        # 清理断开的连接
        for user_id in disconnected_users:
            sse_connections.pop(user_id, None)


def add_cors_headers(response):
    """为响应添加 CORS 头"""
    # 确保响应对象存在
    if response is None:
        response = jsonify({})
    # 强制设置 CORS 头
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, HEAD'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, X-Session-ID, X-User-ID'
    response.headers['Access-Control-Allow-Credentials'] = 'false'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response


@app.before_request
def handle_preflight():
    """处理 OPTIONS 预检请求"""
    if request.method == "OPTIONS":
        response = jsonify({})
        return add_cors_headers(response)


@app.after_request
def after_request(response):
    """为所有响应添加 CORS 头"""
    # 确保响应对象存在
    if response is None:
        response = jsonify({})
    # 强制添加 CORS 头
    response = add_cors_headers(response)
    # 双重确保 CORS 头存在
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, HEAD'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, X-Session-ID, X-User-ID'
    response.headers['Access-Control-Allow-Credentials'] = 'false'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response


def generate_stream(user_message, session_id=None, user_id=None, username=None):
    """生成流式响应"""
    if not llm:
        error_msg = {'type': 'error', 'content': 'OpenAI API Key not configured. Please check .env file'}
        yield f"data: {json.dumps(error_msg)}\n\n"
        if user_id and username:
            broadcast_message({
                'type': 'error',
                'user_id': user_id,
                'username': username,
                'content': error_msg['content'],
                'timestamp': datetime.utcnow().isoformat()
            })
        return
    
    # 如果没有提供session_id，生成一个新的
    if session_id is None:
        session_id = str(uuid.uuid4())
    
    try:
        # 发送开始信号
        start_msg = {'type': 'start'}
        yield f"data: {json.dumps(start_msg)}\n\n"
        
        # 第一步：调用总路由判断agent类型
        router_response = ""
        for chunk in router_chain.stream({"user_input": user_message}):
            if chunk:
                router_response += chunk
        
        # 解析路由响应
        agent = parse_router_response(router_response)
        
        # 发送agent类型
        yield f"data: {json.dumps({'type': 'agent', 'agent': agent})}\n\n"
        
        # 第二步：根据agent类型调用对应的子机器人
        if agent == 'bill':
            # 调用账单助手
            full_response = ""
            # 先完整获取响应，不流式输出
            for chunk in bill_chain.stream({"user_input": user_message}):
                if chunk:
                    full_response += chunk
            
            # 尝试解析响应
            try:
                result = extract_json_from_text(full_response)
                
                # 判断是查询请求还是记录请求
                if result and isinstance(result, dict) and result.get('query'):
                    # 这是查询请求
                    query_type = result.get('type', '')
                    query_value = result.get('value', '')
                    
                    # 执行查询
                    bills = query_bills_from_db(query_type, query_value)
                    
                    if bills:
                        # 格式化查询结果
                        result_text = format_bills_for_display(bills)
                        yield f"data: {json.dumps({'type': 'chunk', 'content': result_text})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': 'No matching bill records found.'})}\n\n"
                        
                elif result and isinstance(result, list) and len(result) > 0:
                    # 这是记录请求（数组格式），保存到数据库并返回ID
                    saved_ids = save_bills_to_db(result, user_message)
                    
                    if saved_ids:
                        # 返回账单ID信息
                        if len(saved_ids) == 1:
                            id_message = f"Bill successfully recorded! Bill ID: {saved_ids[0]}"
                        else:
                            id_message = f"Successfully recorded {len(saved_ids)} bills! Bill IDs: {', '.join(map(str, saved_ids))}"
                        yield f"data: {json.dumps({'type': 'chunk', 'content': id_message})}\n\n"
                        yield f"data: {json.dumps({'type': 'bill_ids', 'ids': saved_ids})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': 'Failed to record bill. Please check the data format.'})}\n\n"
                elif result and isinstance(result, dict) and all(key in result for key in ['topic', 'payer', 'participants', 'amount']):
                    # 这是记录请求（单个对象格式），转换为数组格式
                    bills_array = [result]
                    saved_ids = save_bills_to_db(bills_array, user_message)
                    
                    if saved_ids:
                        # 返回账单ID信息
                        id_message = f"Bill successfully recorded! Bill ID: {saved_ids[0]}"
                        yield f"data: {json.dumps({'type': 'chunk', 'content': id_message})}\n\n"
                        yield f"data: {json.dumps({'type': 'bill_ids', 'ids': saved_ids})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': 'Failed to record bill. Please check the data format.'})}\n\n"
                else:
                    # 无法解析，返回原始响应
                    yield f"data: {json.dumps({'type': 'chunk', 'content': full_response})}\n\n"
                    
            except Exception as parse_error:
                print(f'解析错误: {parse_error}')
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'chunk', 'content': f'Error processing bill information: {str(parse_error)}'})}\n\n"
                
        elif agent == 'travel':
            # 使用传入的session_id（用于状态管理）
            if session_id not in travel_plan_storage:
                travel_plan_storage[session_id] = {
                    "route_plan": "",
                    "restaurant_plan": "",
                    "budget": None,
                    "awaiting_replan_confirmation": False,
                    "awaiting_mediation": False,
                    "awaiting_confirmation": False,
                    "pending_modification_request": "",
                    "mediation_requesting_user_id": "",
                    "mediation_modification_type": ""
                }
            
            previous_state = travel_plan_storage[session_id]
            
            # 调试信息：打印当前状态
            route_plan_length = len(previous_state.get("route_plan", ""))
            restaurant_plan_length = len(previous_state.get("restaurant_plan", ""))
            
            # 优先检查是否在等待调解确认（调解者在计划确认之前，优先级更高）
            awaiting_mediation = previous_state.get("awaiting_mediation", False)
            if awaiting_mediation:
                # 处理调解者投票
                user_message_lower = user_message.lower()
                is_agree = any(word in user_message_lower for word in ["agree", "yes", "ok", "同意", "好的", "确定", "confirm", "proceed"])
                is_disagree = any(word in user_message_lower for word in ["disagree", "no", "不同意", "反对", "cancel"])
                
                if is_disagree:
                    # 用户反对，保持原计划
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '🤝 Mediator Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '🤝 Mediator Agent', 'content': f'**{username}** has disagreed with the modification. The original plan will be kept unchanged.\n\n'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '🤝 Mediator Agent'})}\n\n"
                    travel_plan_storage[session_id]["awaiting_mediation"] = False
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                if is_agree:
                    # 记录用户同意调解
                    if session_id not in vote_storage:
                        vote_storage[session_id] = {}
                    if "mediation_votes" not in vote_storage[session_id]:
                        vote_storage[session_id]["mediation_votes"] = {}
                    vote_storage[session_id]["mediation_votes"][user_id] = "agree"
                    
                    # 获取发起者ID（排除发起者）
                    requesting_user_id = travel_plan_storage[session_id].get("mediation_requesting_user_id", "")
                    
                    # 检查是否除了发起者外的所有人都同意了
                    if check_all_users_agreed(session_id, "mediation", exclude_user_id=requesting_user_id):
                        # 所有人都同意，执行修改
                        yield f"data: {json.dumps({'type': 'planner_start', 'planner': '🤝 Mediator Agent'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '🤝 Mediator Agent', 'content': f'All users have agreed to the modification. Proceeding with the changes...\n\n'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '🤝 Mediator Agent'})}\n\n"
                        
                        travel_plan_storage[session_id]["awaiting_mediation"] = False
                        modification_type = travel_plan_storage[session_id].get("mediation_modification_type", "route")
                        original_request = travel_plan_storage[session_id].get("pending_modification_request", user_message)
                        
                        # 从原始修改请求中提取旅行信息
                        travel_info = extract_travel_info(original_request)
                        
                        # 从状态中获取当前的route_plan和restaurant_plan
                        current_route_plan = previous_state.get("route_plan", "")
                        current_restaurant_plan = previous_state.get("restaurant_plan", "")
                        current_budget = previous_state.get("budget")
                        
                        # 根据修改类型调用对应的agent
                        if modification_type == "route":
                            # 调用路线规划师
                            yield from execute_route_modification(session_id, original_request, current_route_plan, current_restaurant_plan, current_budget, travel_info, user_id, username)
                        elif modification_type == "restaurant":
                            # 调用餐厅规划师
                            yield from execute_restaurant_modification(session_id, original_request, current_route_plan, current_restaurant_plan, current_budget, travel_info, user_id, username)
                        elif modification_type == "budget":
                            # 调用预算修改
                            yield from execute_budget_modification(session_id, original_request, current_route_plan, current_restaurant_plan, current_budget, travel_info, user_id, username)
                        
                        # 重置投票状态
                        if session_id in vote_storage and "mediation_votes" in vote_storage[session_id]:
                            vote_storage[session_id]["mediation_votes"] = {}
                        
                        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                        return
                    else:
                        # 还有人没同意，等待
                        active_users_list = get_active_users_list()
                        requesting_user_id = travel_plan_storage[session_id].get("mediation_requesting_user_id", "")
                        waiting_users = [u["username"] for u in active_users_list if u["user_id"] != requesting_user_id and vote_storage.get(session_id, {}).get("mediation_votes", {}).get(u["user_id"]) != "agree"]
                        waiting_users_str = ", ".join(waiting_users) if waiting_users else "others"
                        
                        yield f"data: {json.dumps({'type': 'planner_start', 'planner': '🤝 Mediator Agent'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '🤝 Mediator Agent', 'content': f'**{username}** has agreed to the modification. Waiting for {waiting_users_str} to confirm...\n\n'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '🤝 Mediator Agent'})}\n\n"
                        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                        return
                else:
                    # 不是明确的同意/反对，继续等待
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '🤝 Mediator Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '🤝 Mediator Agent', 'content': 'Please respond with "agree"/"yes"/"ok" or "disagree"/"no" to confirm your decision about the modification.\n\n'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '🤝 Mediator Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
            
            # 检查是否在等待计划确认
            awaiting_confirmation = previous_state.get("awaiting_confirmation", False)
            if awaiting_confirmation:
                # 处理计划确认投票（注意：这里不会与调解者冲突，因为调解者已经在前面处理了）
                user_message_lower = user_message.lower()
                # 计划确认使用更明确的关键词，避免与调解者混淆
                is_agree = any(word in user_message_lower for word in ["agree", "yes", "ok", "同意", "好的", "确定", "confirm", "proceed", "finalize", "确认计划", "确定方案"])
                is_disagree = any(word in user_message_lower for word in ["disagree", "no", "cancel", "replan", "modify"])
                
                if is_disagree:
                    # 用户反对，需要重新规划
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '✅ Plan Confirmation Agent', 'content': f'**{username}** has objected to the plan. The plan will be revised. Please provide your feedback or request modifications.\n\n'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                    travel_plan_storage[session_id]["awaiting_confirmation"] = False
                    # 继续执行，让Supervisor判断为modify_route
                elif is_agree:
                    # 记录用户同意
                    if session_id not in vote_storage:
                        vote_storage[session_id] = {}
                    if "confirmation_votes" not in vote_storage[session_id]:
                        vote_storage[session_id]["confirmation_votes"] = {}
                    vote_storage[session_id]["confirmation_votes"][user_id] = "agree"
                    
                    # 检查是否所有人都同意了
                    if check_all_users_agreed(session_id, "confirmation"):
                        # 所有人都同意，计划确定
                        yield f"data: {json.dumps({'type': 'planner_start', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '✅ Plan Confirmation Agent', 'content': f'🎉 **All users have confirmed!** The travel plan is now finalized.\n\n'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                        travel_plan_storage[session_id]["awaiting_confirmation"] = False
                        
                        # 保存旅行计划到数据库
                        try:
                            route_plan = previous_state.get("route_plan", "")
                            restaurant_plan = previous_state.get("restaurant_plan", "")
                            budget = previous_state.get("budget")
                            
                            # 尝试从route_plan中提取目的地（简单提取，查找常见城市名）
                            destination = None
                            days = None
                            
                            # 从route_plan中提取目的地（查找常见城市名）
                            route_plan_lower = route_plan.lower()
                            city_keywords = {
                                "Tokyo": ["tokyo"],
                                "Paris": ["paris"],
                                "London": ["london"],
                                "New York": ["new york", "nyc"],
                                "Beijing": ["beijing", "beijing"],
                                "Shanghai": ["shanghai"],
                                "Taipei": ["taipei", "taiwan"],
                                "Bangkok": ["bangkok"],
                                "Singapore": ["singapore"],
                                "Sydney": ["sydney"],
                                "Dubai": ["dubai"],
                                "Rome": ["rome"],
                                "Barcelona": ["barcelona"],
                                "Amsterdam": ["amsterdam"],
                                "Berlin": ["berlin"],
                                "Vienna": ["vienna"],
                                "Prague": ["prague"],
                                "Athens": ["athens"],
                                "Istanbul": ["istanbul"],
                                "Bali": ["bali"],
                                "Phuket": ["phuket"],
                                "Seoul": ["seoul"],
                                "Hong Kong": ["hong kong"],
                                "Macau": ["macau"],
                                "Osaka": ["osaka"],
                                "Kyoto": ["kyoto"]
                            }
                            
                            for city, keywords in city_keywords.items():
                                if any(keyword in route_plan_lower for keyword in keywords):
                                    destination = city
                                    break
                            
                            # 如果没找到，尝试从route_plan中提取天数
                            import re
                            day_match = re.search(r'(\d+)\s*(?:day|days|night|nights)', route_plan_lower)
                            if day_match:
                                days = int(day_match.group(1))
                            
                            # 获取参与者列表
                            active_users_list = get_active_users_list()
                            participants = [u["username"] for u in active_users_list]
                            
                            # 保存到数据库（确保在应用上下文中）
                            with app.app_context():
                                travel_plan = TravelPlan(
                                    session_id=session_id,
                                    route_plan=route_plan,
                                    restaurant_plan=restaurant_plan,
                                    budget=budget,
                                    currency="USD",  # 默认货币
                                    destination=destination,
                                    days=days,
                                    participants=json.dumps(participants)
                                )
                                db.session.add(travel_plan)
                                db.session.commit()
                                plan_id = travel_plan.id
                            
                            yield f"data: {json.dumps({'type': 'planner_start', 'planner': '💾 TripWise Pro'})}\n\n"
                            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '💾 TripWise Pro', 'content': f'✅ Travel plan has been saved to TripWise Pro! Plan ID: {plan_id}\n\n'})}\n\n"
                            yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '💾 TripWise Pro'})}\n\n"
                        except Exception as e:
                            print(f"Error saving travel plan to database: {e}")
                            import traceback
                            traceback.print_exc()
                            yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Error'})}\n\n"
                            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Error', 'content': f'Failed to save travel plan to database: {str(e)}\n\n'})}\n\n"
                            yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Error'})}\n\n"
                        
                        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                        return
                    else:
                        # 还有人没同意，等待
                        yield f"data: {json.dumps({'type': 'planner_start', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '✅ Plan Confirmation Agent', 'content': f'**{username}** has confirmed. Waiting for other users to confirm...\n\n'})}\n\n"
                        yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                        return
                else:
                    # 不是明确的同意/反对，继续等待
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '✅ Plan Confirmation Agent', 'content': 'Please respond with "confirm"/"agree"/"yes" or "disagree"/"no" to confirm your decision.\n\n'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
            
            # 第一步：调用Travel Supervisor判断用户意图
            supervisor_response = ""
            
            # 准备传递给supervisor的previous_route_plan
            previous_route_plan = previous_state.get("route_plan", "")
            previous_restaurant_plan = previous_state.get("restaurant_plan", "")
            previous_budget = previous_state.get("budget")
            awaiting_replan_confirmation = previous_state.get("awaiting_replan_confirmation", False)
            
            # 如果route_plan为空或很短，传递给supervisor时使用"None"
            if not previous_route_plan or len(previous_route_plan.strip()) < 10:
                previous_route_plan_for_supervisor = "None"
            else:
                previous_route_plan_for_supervisor = previous_route_plan[:500]  # 限制长度避免token过多
            
            if not previous_restaurant_plan or len(previous_restaurant_plan.strip()) < 10:
                previous_restaurant_plan_for_supervisor = "None"
            else:
                previous_restaurant_plan_for_supervisor = previous_restaurant_plan[:500]
            
            
            for chunk in travel_supervisor_chain.stream({
                "user_input": user_message,
                "previous_route_plan": previous_route_plan_for_supervisor,
                "previous_restaurant_plan": previous_restaurant_plan_for_supervisor,
                "previous_budget": str(previous_budget) if previous_budget else "None",
                "awaiting_replan_confirmation": "true" if awaiting_replan_confirmation else "false"
            }):
                if chunk:
                    supervisor_response += chunk
            
            # 解析supervisor响应
            supervisor_result = extract_json_from_text(supervisor_response)
            intent = "new_plan"  # 默认值
            if supervisor_result and isinstance(supervisor_result, dict):
                intent = supervisor_result.get('intent', 'new_plan')
                pass
            else:
                pass
            
            # 提取旅行信息（目的地、预算、天数）
            travel_info = extract_travel_info(user_message)
            
            # 根据intent执行不同的流程
            route_plan = previous_state.get("route_plan", "")
            restaurant_plan = previous_state.get("restaurant_plan", "")
            
            # 处理重新规划确认
            if intent == "replan_after_budget_fail":
                # 清除等待确认标记
                travel_plan_storage[session_id]["awaiting_replan_confirmation"] = False
                
                # 1. 路线规划师（重新规划）
                planner_name = "🗺️ Travel Route Planner"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
                
                # 获取之前的路线计划（用于上下文）
                old_route_plan = previous_state.get("route_plan", "")
                
                # 准备之前的路线计划作为上下文（如果有）
                previous_route_plan_context = ""
                if old_route_plan and len(old_route_plan.strip()) > 10:
                    previous_route_plan_context = f"\nPrevious route plan (for reference - create a more budget-friendly version):\n{old_route_plan[:1000]}\n"
                else:
                    previous_route_plan_context = "\nNo previous route plan exists.\n"
                
                # 提取预算约束
                budget_constraint_text = ""
                if previous_budget:
                    budget_constraint_text = f"\nBudget constraint: ${previous_budget:.2f}\n"
                
                route_plan = ""
                route_plan_input = {
                    "user_input": f"{user_message} Please create a budget-friendly plan that fits within the budget constraints.",
                    "previous_route_plan": previous_route_plan_context,
                    "budget_constraint": budget_constraint_text,
                    "revision_request": "Please replan the route to be more budget-friendly and fit within the specified budget."
                }
                
                for chunk in route_planner_chain.stream(route_plan_input):
                    if chunk:
                        route_plan += chunk
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
                
                # 2. 饭店规划师（重新规划）
                restaurant_plan = ""
                planner_name = "🍽️ Restaurant Planner"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
                for chunk in restaurant_planner_chain.stream({
                    "user_input": f"{user_message} Please recommend budget-friendly restaurants that fit within the budget.",
                    "route_plan": route_plan
                }):
                    if chunk:
                        restaurant_plan += chunk
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
                
                # 3. 预算检查
                budget_checker_name = "💰 Budget Checker"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': budget_checker_name})}\n\n"
                
                # 提取预算（优先从存储中获取最新预算）
                current_budget = None
                if session_id in travel_plan_storage:
                    current_budget = travel_plan_storage[session_id].get("budget")
                # 如果存储中没有，尝试从 travel_info 中获取
                if not current_budget and travel_info:
                    current_budget = travel_info.get("budget")
                # 如果还是没有，使用传入的 previous_budget
                if not current_budget:
                    current_budget = previous_budget
                budget_str = str(current_budget) if current_budget else ""
                
                budget_check_response = ""
                for chunk in budget_checker_chain.stream({
                    "user_budget": budget_str,
                    "user_input": user_message,
                    "route_plan": route_plan,
                    "restaurant_plan": restaurant_plan
                }):
                    if chunk:
                        budget_check_response += chunk
                
                budget_check_result = parse_budget_check_result(budget_check_response)
                
                budget_ok = budget_check_result["budget_ok"]
                is_feasible = budget_check_result["is_feasible"]
                budget_reason = budget_check_result["reason"]
                budget_suggestion = budget_check_result["suggestion"]
                
                # 流式发送reason字段
                if budget_reason:
                    chunk_size = 50
                    for i in range(0, len(budget_reason), chunk_size):
                        chunk = budget_reason[i:i + chunk_size]
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': chunk})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': 'Budget check completed.'})}\n\n"
                
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': budget_checker_name})}\n\n"
                
                # 检查预算是否失败
                if budget_ok is False or is_feasible is False:
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    budget_alert = f"\n⚠️ **Budget Check Still Failed After Replanning**\n\n"
                    if budget_reason:
                        budget_alert += f"{budget_reason}\n\n"
                    if budget_suggestion:
                        budget_alert += f"**Suggestion:**\n{budget_suggestion}\n\n"
                    budget_alert += f"**Please consider increasing your budget or reducing the trip duration.**\n"
                    
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Budget Alert', 'content': budget_alert})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    # 保存状态
                    travel_plan_storage[session_id] = {
                        "route_plan": route_plan,
                        "restaurant_plan": restaurant_plan,
                        "budget": previous_budget,
                        "awaiting_replan_confirmation": False
                    }
                    
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 保存状态（预算检查通过，但不自动调用计划确定师）
                travel_plan_storage[session_id] = {
                    "route_plan": route_plan,
                    "restaurant_plan": restaurant_plan,
                    "budget": previous_budget,
                    "awaiting_replan_confirmation": False,
                    "awaiting_confirmation": False
                }
            
            elif intent == "new_plan":
                # 新规划：路线规划 → 饭店规划 → 预算检查 → 预算规划
                
                # 1. 路线规划师
                planner_name = "🗺️ Travel Route Planner"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
                
                # 提取预算约束
                current_budget = travel_info.get("budget")
                budget_constraint_text = ""
                if current_budget:
                    budget_constraint_text = f"\nBudget constraint: ${current_budget:.2f}\n"
                
                route_plan = ""
                route_plan_input = {
                    "user_input": user_message,
                    "previous_route_plan": "\nNo previous route plan exists.\n",
                    "budget_constraint": budget_constraint_text,
                    "revision_request": ""
                }
                
                for chunk in route_planner_chain.stream(route_plan_input):
                    if chunk:
                        route_plan += chunk
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
                
                # 2. 饭店规划师
                restaurant_plan = ""
                planner_name = "🍽️ Restaurant Planner"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
                for chunk in restaurant_planner_chain.stream({
                    "user_input": user_message,
                    "route_plan": route_plan
                }):
                    if chunk:
                        restaurant_plan += chunk
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
                
                # 3. 预算检查
                budget_checker_name = "💰 Budget Checker"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': budget_checker_name})}\n\n"
                
                budget_check_response = ""
                for chunk in budget_checker_chain.stream({
                    "user_budget": "",
                    "user_input": user_message,
                    "route_plan": route_plan,
                    "restaurant_plan": restaurant_plan
                }):
                    if chunk:
                        budget_check_response += chunk
                
                budget_check_result = parse_budget_check_result(budget_check_response)
                
                budget_ok = budget_check_result["budget_ok"]
                is_feasible = budget_check_result["is_feasible"]
                budget_reason = budget_check_result["reason"]
                budget_suggestion = budget_check_result["suggestion"]
                
                # 流式发送reason字段
                if budget_reason:
                    chunk_size = 50
                    for i in range(0, len(budget_reason), chunk_size):
                        chunk = budget_reason[i:i + chunk_size]
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': chunk})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': 'Budget check completed.'})}\n\n"
                
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': budget_checker_name})}\n\n"
                
                # 检查预算是否失败
                if budget_ok is False or is_feasible is False:
                    print("预算检查失败，询问用户是否要重新规划...")
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    budget_alert = f"\n⚠️ **Budget Check Failed**\n\n"
                    if budget_reason:
                        budget_alert += f"{budget_reason}\n\n"
                    if budget_suggestion:
                        budget_alert += f"**Suggestion:**\n{budget_suggestion}\n\n"
                    
                    # 询问用户是否要重新规划
                    budget_alert += f"\n**Would you like me to replan the route and restaurants to fit your budget?**\n"
                    budget_alert += f"Please reply with 'yes', 'ok', 'replan', or 'replan' if you want me to create a new plan within your budget.\n"
                    
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Budget Alert', 'content': budget_alert})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    # 保存状态，标记正在等待用户确认重新规划
                    travel_plan_storage[session_id]["awaiting_replan_confirmation"] = True
                    travel_plan_storage[session_id]["route_plan"] = route_plan
                    travel_plan_storage[session_id]["restaurant_plan"] = restaurant_plan
                    
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 保存状态（预算检查通过，但不自动调用计划确定师）
                travel_plan_storage[session_id] = {
                    "route_plan": route_plan,
                    "restaurant_plan": restaurant_plan,
                    "budget": travel_info.get("budget"),
                    "awaiting_replan_confirmation": False,
                    "awaiting_confirmation": False
                }
                
            elif intent == "modify_route":
                # 修改路线：检查用户数量 → 如果>=2则调用调解者 → 路线规划（部分修改）→ 预算检查（新路线 + 老饭店）→ 计划确定师
                
                # 检查活跃用户数量
                active_users_count = get_active_users_count()
                active_users_list = get_active_users_list()
                
                # 如果有2个或更多用户，需要调解者协调
                if active_users_count >= 2:
                    # 调用调解者Agent
                    mediator_name = "🤝 Mediator Agent"
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': mediator_name})}\n\n"
                    
                    # 保存原始修改请求、发起者ID和修改类型
                    travel_plan_storage[session_id]["pending_modification_request"] = user_message
                    travel_plan_storage[session_id]["mediation_requesting_user_id"] = user_id
                    travel_plan_storage[session_id]["mediation_modification_type"] = "route"
                    
                    # 重置投票（排除发起者）
                    reset_votes(session_id, "mediation", exclude_user_id=user_id)
                    travel_plan_storage[session_id]["awaiting_mediation"] = True
                    
                    # 准备活跃用户列表字符串
                    active_users_str = ", ".join([u["username"] for u in active_users_list])
                    
                    mediator_response = ""
                    for chunk in mediator_chain.stream({
                        "route_plan": route_plan[:1000] if route_plan else "No route plan yet",
                        "restaurant_plan": restaurant_plan[:1000] if restaurant_plan else "No restaurant plan yet",
                        "requesting_user": username,
                        "modification_request": user_message,
                        "active_users": active_users_str
                    }):
                        if chunk:
                            mediator_response += chunk
                            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': mediator_name, 'content': chunk})}\n\n"
                    
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': mediator_name})}\n\n"
                    
                    # 等待所有用户同意（这里先标记状态，实际投票通过用户消息处理）
                    # 如果用户回复"agree", "yes", "ok"等，会在下次请求时检查
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 执行路线修改
                # 如果是在等待调解确认后所有人都同意了，使用保存的原始请求
                if travel_plan_storage[session_id].get("pending_modification_request"):
                    original_request = travel_plan_storage[session_id]["pending_modification_request"]
                    # 清除保存的请求
                    travel_plan_storage[session_id]["pending_modification_request"] = ""
                    # 使用原始请求
                    modification_request = original_request
                else:
                    modification_request = user_message
                
                planner_name = "🗺️ Travel Route Planner"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
                
                # 准备之前的路线计划作为上下文（完整传递，用于部分修改）
                previous_route_plan_context = ""
                if route_plan and len(route_plan.strip()) > 10:
                    # 传递完整的路线计划，让AI能够进行部分修改（增加到3000字符以包含更多上下文）
                    previous_route_plan_context = f"\n=== PREVIOUS ROUTE PLAN (MODIFY ONLY THE PARTS USER MENTIONED, KEEP EVERYTHING ELSE UNCHANGED) ===\n{route_plan[:3000]}\n=== END OF PREVIOUS ROUTE PLAN ===\n"
                else:
                    previous_route_plan_context = "\nNo previous route plan exists.\n"
                
                # 提取预算约束（优先从存储中获取最新预算）
                current_budget = None
                if session_id in travel_plan_storage:
                    current_budget = travel_plan_storage[session_id].get("budget")
                # 如果存储中没有，尝试从 travel_info 中获取
                if not current_budget and travel_info:
                    current_budget = travel_info.get("budget")
                # 如果还是没有，使用传入的 previous_budget
                if not current_budget:
                    current_budget = previous_budget
                budget_constraint_text = ""
                if current_budget:
                    budget_constraint_text = f"\nBudget constraint: ${current_budget:.2f}\n"
                
                route_plan = ""
                route_plan_input = {
                    "user_input": modification_request,
                    "previous_route_plan": previous_route_plan_context,
                    "budget_constraint": budget_constraint_text,
                    "revision_request": f"IMPORTANT: The user is providing feedback or requesting modifications to the existing route plan. Your task is to MODIFY ONLY the specific parts they mentioned:\n- If they mention a NEW destination (different city/country), create a completely NEW plan for that destination.\n- If they are providing feedback, suggestions, or complaints about specific parts (e.g., 'I don't like this hotel', 'change this attraction', 'modify day 2', 'this is not good'), ONLY modify those specific parts. Keep ALL other parts of the route plan EXACTLY as they were.\n- DO NOT recreate the entire route plan unless the user explicitly asks for a complete replan.\n- When you modify a part, clearly indicate which parts were changed and why.\n- Preserve the structure, format, and all unchanged content from the previous plan.\n\nUser's feedback/request: {modification_request}"
                }
                
                for chunk in route_planner_chain.stream(route_plan_input):
                    if chunk:
                        route_plan += chunk
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
                
                # 2. 预算检查（新路线 + 老饭店）
                budget_checker_name = "💰 Budget Checker"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': budget_checker_name})}\n\n"
                
                # 使用上面已经获取的 current_budget（优先从存储中获取最新预算）
                budget_str = str(current_budget) if current_budget else ""
                
                budget_check_response = ""
                for chunk in budget_checker_chain.stream({
                    "user_budget": budget_str,
                    "user_input": user_message,
                    "route_plan": route_plan,
                    "restaurant_plan": restaurant_plan
                }):
                    if chunk:
                        budget_check_response += chunk
                
                budget_check_result = parse_budget_check_result(budget_check_response)
                
                budget_ok = budget_check_result["budget_ok"]
                is_feasible = budget_check_result["is_feasible"]
                budget_reason = budget_check_result["reason"]
                budget_suggestion = budget_check_result["suggestion"]
                
                # 流式发送reason字段
                if budget_reason:
                    chunk_size = 50
                    for i in range(0, len(budget_reason), chunk_size):
                        chunk = budget_reason[i:i + chunk_size]
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': chunk})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': 'Budget check completed.'})}\n\n"
                
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': budget_checker_name})}\n\n"
                
                # 检查预算是否失败
                if budget_ok is False or is_feasible is False:
                    print("预算检查失败，询问用户是否要重新规划...")
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    budget_alert = f"\n⚠️ **Budget Check Failed**\n\n"
                    if budget_reason:
                        budget_alert += f"{budget_reason}\n\n"
                    if budget_suggestion:
                        budget_alert += f"**Suggestion:**\n{budget_suggestion}\n\n"
                    
                    # 询问用户是否要重新规划
                    budget_alert += f"\n**Would you like me to replan the route and restaurants to fit your budget?**\n"
                    budget_alert += f"Please reply with 'yes', 'ok', 'replan', or 'replan' if you want me to create a new plan within your budget.\n"
                    
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Budget Alert', 'content': budget_alert})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    # 保存状态，标记正在等待用户确认重新规划
                    travel_plan_storage[session_id]["awaiting_replan_confirmation"] = True
                    travel_plan_storage[session_id]["route_plan"] = route_plan
                    
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 更新状态（预算检查通过，但不自动调用计划确定师）
                travel_plan_storage[session_id]["route_plan"] = route_plan
                travel_plan_storage[session_id]["awaiting_replan_confirmation"] = False
                travel_plan_storage[session_id]["awaiting_mediation"] = False
                
            elif intent == "modify_restaurant":
                # 修改饭店：检查用户数量 → 如果>=2则调用调解者 → 饭店规划（重新）→ 预算检查（老路线 + 新饭店）
                
                # 检查活跃用户数量
                active_users_count = get_active_users_count()
                active_users_list = get_active_users_list()
                
                # 如果有2个或更多用户，需要调解者协调
                if active_users_count >= 2:
                    # 调用调解者Agent
                    mediator_name = "🤝 Mediator Agent"
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': mediator_name})}\n\n"
                    
                    # 保存原始修改请求、发起者ID和修改类型
                    travel_plan_storage[session_id]["pending_modification_request"] = user_message
                    travel_plan_storage[session_id]["mediation_requesting_user_id"] = user_id
                    travel_plan_storage[session_id]["mediation_modification_type"] = "restaurant"
                    
                    # 重置投票（排除发起者）
                    reset_votes(session_id, "mediation", exclude_user_id=user_id)
                    travel_plan_storage[session_id]["awaiting_mediation"] = True
                    
                    # 准备活跃用户列表字符串
                    active_users_str = ", ".join([u["username"] for u in active_users_list])
                    
                    mediator_response = ""
                    for chunk in mediator_chain.stream({
                        "route_plan": route_plan[:1000] if route_plan else "No route plan yet",
                        "restaurant_plan": restaurant_plan[:1000] if restaurant_plan else "No restaurant plan yet",
                        "requesting_user": username,
                        "modification_request": user_message,
                        "active_users": active_users_str
                    }):
                        if chunk:
                            mediator_response += chunk
                            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': mediator_name, 'content': chunk})}\n\n"
                    
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': mediator_name})}\n\n"
                    
                    # 等待所有用户同意（这里先标记状态，实际投票通过用户消息处理）
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 1. 饭店规划师（重新规划）
                planner_name = "🍽️ Restaurant Planner"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
                
                restaurant_plan = ""
                for chunk in restaurant_planner_chain.stream({
                    "user_input": user_message,
                    "route_plan": route_plan
                }):
                    if chunk:
                        restaurant_plan += chunk
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
                
                # 2. 预算检查（老路线 + 新饭店）
                budget_checker_name = "💰 Budget Checker"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': budget_checker_name})}\n\n"
                
                # 提取预算（优先从存储中获取最新预算）
                current_budget = None
                if session_id in travel_plan_storage:
                    current_budget = travel_plan_storage[session_id].get("budget")
                # 如果存储中没有，尝试从 travel_info 中获取
                if not current_budget and travel_info:
                    current_budget = travel_info.get("budget")
                # 如果还是没有，使用传入的 previous_budget
                if not current_budget:
                    current_budget = previous_budget
                budget_str = str(current_budget) if current_budget else ""
                
                budget_check_response = ""
                for chunk in budget_checker_chain.stream({
                    "user_budget": budget_str,
                    "user_input": user_message,
                    "route_plan": route_plan,
                    "restaurant_plan": restaurant_plan
                }):
                    if chunk:
                        budget_check_response += chunk
                
                budget_check_result = parse_budget_check_result(budget_check_response)
                
                budget_ok = budget_check_result["budget_ok"]
                is_feasible = budget_check_result["is_feasible"]
                budget_reason = budget_check_result["reason"]
                budget_suggestion = budget_check_result["suggestion"]
                
                # 流式发送reason字段
                if budget_reason:
                    chunk_size = 50
                    for i in range(0, len(budget_reason), chunk_size):
                        chunk = budget_reason[i:i + chunk_size]
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': chunk})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': budget_checker_name, 'content': 'Budget check completed.'})}\n\n"
                
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': budget_checker_name})}\n\n"
                
                # 检查预算是否失败
                if budget_ok is False or is_feasible is False:
                    print("预算检查失败，询问用户是否要重新规划...")
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    budget_alert = f"\n⚠️ **Budget Check Failed**\n\n"
                    if budget_reason:
                        budget_alert += f"{budget_reason}\n\n"
                    if budget_suggestion:
                        budget_alert += f"**Suggestion:**\n{budget_suggestion}\n\n"
                    
                    # 询问用户是否要重新规划
                    budget_alert += f"\n**Would you like me to replan the route and restaurants to fit your budget?**\n"
                    budget_alert += f"Please reply with 'yes', 'ok', 'replan', or 'replan' if you want me to create a new plan within your budget.\n"
                    
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '⚠️ Budget Alert', 'content': budget_alert})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '⚠️ Budget Alert'})}\n\n"
                    
                    # 保存状态，标记正在等待用户确认重新规划
                    travel_plan_storage[session_id]["awaiting_replan_confirmation"] = True
                    travel_plan_storage[session_id]["restaurant_plan"] = restaurant_plan
                    
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 更新状态（预算检查通过，但不自动调用计划确定师）
                travel_plan_storage[session_id]["restaurant_plan"] = restaurant_plan
                travel_plan_storage[session_id]["awaiting_replan_confirmation"] = False
                travel_plan_storage[session_id]["awaiting_confirmation"] = False
                
            elif intent == "modify_budget":
                # 修改预算：预算检查（老路线 + 老饭店 + 新预算）
                # 检查活跃用户数量
                active_users_count = get_active_users_count()
                active_users_list = get_active_users_list()
                
                # 如果有2个或更多用户，需要调解者协调
                if active_users_count >= 2:
                    # 调用调解者Agent
                    mediator_name = "🤝 Mediator Agent"
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': mediator_name})}\n\n"
                    
                    # 保存原始修改请求、发起者ID和修改类型
                    travel_plan_storage[session_id]["pending_modification_request"] = user_message
                    travel_plan_storage[session_id]["mediation_requesting_user_id"] = user_id
                    travel_plan_storage[session_id]["mediation_modification_type"] = "budget"
                    
                    # 重置投票（排除发起者）
                    reset_votes(session_id, "mediation", exclude_user_id=user_id)
                    travel_plan_storage[session_id]["awaiting_mediation"] = True
                    
                    # 准备活跃用户列表字符串
                    active_users_str = ", ".join([u["username"] for u in active_users_list])
                    
                    # 提取新预算用于显示
                    new_budget = travel_info.get("budget") or previous_budget
                    budget_display = f"${new_budget:.2f}" if new_budget else "not specified"
                    
                    mediator_response = ""
                    for chunk in mediator_chain.stream({
                        "route_plan": route_plan[:1000] if route_plan else "No route plan yet",
                        "restaurant_plan": restaurant_plan[:1000] if restaurant_plan else "No restaurant plan yet",
                        "requesting_user": username,
                        "modification_request": f"{username} wants to change the budget to {budget_display}",
                        "active_users": active_users_str
                    }):
                        if chunk:
                            mediator_response += chunk
                            yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': mediator_name, 'content': chunk})}\n\n"
                    
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': mediator_name})}\n\n"
                    
                    # 等待所有用户同意（这里先标记状态，实际投票通过用户消息处理）
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 执行预算修改（只有一个人时直接执行）
                yield from execute_budget_modification(session_id, user_message, route_plan, restaurant_plan, previous_budget, travel_info, user_id, username)
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return
                    
            elif intent == "confirm_plan":
                # 确认计划：调用计划确定师
                # 检查是否有现有的计划
                if not route_plan and not restaurant_plan:
                    yield f"data: {json.dumps({'type': 'planner_start', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': '✅ Plan Confirmation Agent', 'content': 'There is no travel plan to confirm yet. Please create a plan first.\n\n'})}\n\n"
                    yield f"data: {json.dumps({'type': 'planner_complete', 'planner': '✅ Plan Confirmation Agent'})}\n\n"
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return
                
                # 检查活跃用户数量
                active_users_count = get_active_users_count()
                active_users_list = get_active_users_list()
                active_users_str = ", ".join([u["username"] for u in active_users_list])
                
                # 调用计划确定师
                planner_name = "✅ Plan Confirmation Agent"
                yield f"data: {json.dumps({'type': 'planner_start', 'planner': planner_name})}\n\n"
                
                # 重置确认投票
                reset_votes(session_id, "confirmation")
                travel_plan_storage[session_id]["awaiting_confirmation"] = True
                
                # 获取预算检查结果（如果有）
                budget_check_result = "Budget check not performed yet"
                if previous_budget:
                    budget_check_result = f"Budget: ${previous_budget:.2f}"
                
                confirmation_response = ""
                for chunk in plan_confirmation_chain.stream({
                    "route_plan": route_plan[:2000] if route_plan else "No route plan",
                    "restaurant_plan": restaurant_plan[:2000] if restaurant_plan else "No restaurant plan",
                    "budget_check_result": budget_check_result,
                    "active_users": active_users_str
                }):
                    if chunk:
                        confirmation_response += chunk
                        yield f"data: {json.dumps({'type': 'planner_chunk', 'planner': planner_name, 'content': chunk})}\n\n"
                
                yield f"data: {json.dumps({'type': 'planner_complete', 'planner': planner_name})}\n\n"
                
                # 等待所有用户确认
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                return
                    
        else:
            # unknown 情况，调用 Fallback Agent
            for chunk in fallback_chain.stream({"user_input": user_message}):
                if chunk:
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        
        # 发送完成信号
        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
        
    except Exception as e:
        print(f'错误: {str(e)}')
        yield f"data: {json.dumps({'type': 'error', 'content': f'Error processing message: {str(e)}'})}\n\n"


@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    """处理聊天请求，返回流式响应"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        return add_cors_headers(response)
    
    data = request.get_json()
    if not data:
        response = jsonify({'error': '请求体不能为空'})
        return add_cors_headers(response), 400
    
    user_message = data.get('message', '')
    
    if not user_message:
        response = jsonify({'error': '消息不能为空'})
        return add_cors_headers(response), 400
    
    # 获取user_id和session_id
    user_id = request.headers.get('X-User-ID', None) or data.get('user_id', None)
    if not user_id:
        user_id = str(uuid.uuid4())
    
    # 在多人聊天室中，所有用户共享同一个session_id，以便共享行程计划
    session_id = SHARED_CHATROOM_SESSION_ID
    
    # 获取或创建用户
    user_info = get_or_create_user(user_id, session_id)
    username = user_info['name']
    
    # 更新用户的session_id
    user_info['session_id'] = session_id
    
    # 广播用户消息
    broadcast_message({
        'id': str(uuid.uuid4()),
        'type': 'user',
        'user_id': user_id,
        'username': username,
        'content': user_message,
        'timestamp': datetime.utcnow().isoformat()
    })
    
    
    # 返回流式响应（包装generate_stream以支持消息广播）
    def generate_with_broadcast():
        ai_message_id = str(uuid.uuid4())
        ai_content = ""
        current_agent = None
        current_planner = None
        planner_messages = {}  # {planner_name: {"id": "...", "content": ""}}
        ai_message_created = False
        
        try:
            for chunk in generate_stream(user_message, session_id=session_id, user_id=user_id, username=username):
                yield chunk
                
                # 解析chunk以收集消息内容用于广播
                if chunk.startswith('data: '):
                    try:
                        data = json.loads(chunk[6:].strip())
                        
                        if data.get('type') == 'agent':
                            current_agent = data.get('agent')
                        elif data.get('type') == 'planner_start':
                            planner_name = data.get('planner')
                            planner_id = str(uuid.uuid4())
                            planner_messages[planner_name] = {
                                'id': planner_id,
                                'content': ''
                            }
                            current_planner = planner_name
                            # 立即广播planner开始消息（用于实时显示）
                            broadcast_message({
                                'id': planner_id,
                                'type': 'planner',
                                'user_id': user_id,
                                'username': username,
                                'planner': planner_name,
                                'content': '',
                                'timestamp': datetime.utcnow().isoformat(),
                                'isStreaming': True
                            })
                        elif data.get('type') == 'planner_chunk':
                            planner_name = data.get('planner')
                            content = data.get('content', '')
                            if planner_name in planner_messages:
                                planner_messages[planner_name]['content'] += content
                                # 实时广播planner内容更新
                                broadcast_message({
                                    'id': planner_messages[planner_name]['id'],
                                    'type': 'planner',
                                    'user_id': user_id,
                                    'username': username,
                                    'planner': planner_name,
                                    'content': planner_messages[planner_name]['content'],
                                    'timestamp': datetime.utcnow().isoformat(),
                                    'isStreaming': True
                                })
                        elif data.get('type') == 'planner_complete':
                            planner_name = data.get('planner')
                            if planner_name in planner_messages:
                                # 广播planner完成消息
                                broadcast_message({
                                    'id': planner_messages[planner_name]['id'],
                                    'type': 'planner',
                                    'user_id': user_id,
                                    'username': username,
                                    'planner': planner_name,
                                    'content': planner_messages[planner_name]['content'],
                                    'timestamp': datetime.utcnow().isoformat(),
                                    'isStreaming': False
                                })
                                del planner_messages[planner_name]
                        elif data.get('type') == 'chunk':
                            ai_content += data.get('content', '')
                            # 如果AI消息还没创建，先创建并广播
                            if not ai_message_created and current_agent:
                                ai_message_created = True
                                broadcast_message({
                                    'id': ai_message_id,
                                    'type': 'ai',
                                    'user_id': user_id,
                                    'username': username,
                                    'agent': current_agent,
                                    'content': '',
                                    'timestamp': datetime.utcnow().isoformat(),
                                    'isStreaming': True
                                })
                            # 实时广播AI内容更新
                            if ai_message_created:
                                broadcast_message({
                                    'id': ai_message_id,
                                    'type': 'ai',
                                    'user_id': user_id,
                                    'username': username,
                                    'agent': current_agent,
                                    'content': ai_content,
                                    'timestamp': datetime.utcnow().isoformat(),
                                    'isStreaming': True
                                })
                    except Exception as parse_error:
                        print(f'解析chunk时出错: {parse_error}')
                        pass
            
            # 广播AI消息完成（如果有内容）
            if ai_content:
                broadcast_message({
                    'id': ai_message_id,
                    'type': 'ai',
                    'user_id': user_id,
                    'username': username,
                    'agent': current_agent,
                    'content': ai_content,
                    'timestamp': datetime.utcnow().isoformat(),
                    'isStreaming': False
                })
        except Exception as e:
            print(f'生成流时出错: {e}')
            import traceback
            traceback.print_exc()
            broadcast_message({
                'id': str(uuid.uuid4()),
                'type': 'error',
                'user_id': user_id,
                'username': username,
                'content': f'Error: {str(e)}',
                'timestamp': datetime.utcnow().isoformat()
            })
    
    # 返回流式响应
    response = Response(
        generate_with_broadcast(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-Session-ID, X-User-ID',
            'Access-Control-Allow-Methods': 'POST, OPTIONS'
        }
    )
    return add_cors_headers(response)


@app.route('/api/events', methods=['GET', 'OPTIONS'])
def events():
    """SSE事件流，用于接收广播消息"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        return add_cors_headers(response)
    
    # 获取user_id
    user_id = request.headers.get('X-User-ID', None) or request.args.get('user_id', None)
    if not user_id:
        response = jsonify({'error': 'user_id is required'})
        return add_cors_headers(response), 400
    
    # 创建消息队列
    msg_queue = queue.Queue(maxsize=100)
    
    # 注册连接
    with sse_connections_lock:
        sse_connections[user_id] = msg_queue
    
    # 发送历史消息（最近50条）
    with message_queue_lock:
        history_messages = message_queue[-50:] if len(message_queue) > 50 else message_queue
    
    def generate():
        # 发送历史消息
        for msg in history_messages:
            yield f"data: {json.dumps(msg)}\n\n"
        
        # 持续监听新消息
        while True:
            try:
                # 等待新消息（超时1秒，用于心跳检测）
                try:
                    msg = msg_queue.get(timeout=1)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    # 发送心跳
                    yield f": heartbeat\n\n"
            except GeneratorExit:
                break
            except Exception as e:
                print(f"SSE事件流错误: {e}")
                break
    
    # 清理连接
    def cleanup():
        with sse_connections_lock:
            sse_connections.pop(user_id, None)
    
    response = Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, X-User-ID',
            'Access-Control-Allow-Methods': 'GET, OPTIONS'
        }
    )
    
    # 注册清理函数
    import atexit
    atexit.register(cleanup)
    
    return add_cors_headers(response)


@app.route('/api/user', methods=['GET', 'POST', 'OPTIONS'])
def user():
    """获取或创建用户信息"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        return add_cors_headers(response)
    
    if request.method == 'POST':
        # 创建新用户
        user_id = str(uuid.uuid4())
        user_info = get_or_create_user(user_id)
        return add_cors_headers(jsonify({
            'user_id': user_id,
            'username': user_info['name']
        }))
    else:
        # 获取用户信息
        user_id = request.headers.get('X-User-ID', None) or request.args.get('user_id', None)
        if not user_id:
            response = jsonify({'error': 'user_id is required'})
            return add_cors_headers(response), 400
        
        if user_id in user_storage:
            user_info = user_storage[user_id]
            return add_cors_headers(jsonify({
                'user_id': user_id,
                'username': user_info['name']
            }))
        else:
            response = jsonify({'error': 'User not found'})
            return add_cors_headers(response), 404


@app.route('/api/health', methods=['GET', 'OPTIONS'])
def health():
    """健康检查接口"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        return add_cors_headers(response)
    
    response = jsonify({
        'status': 'ok',
        'client_configured': llm is not None
    })
    return add_cors_headers(response)


@app.route('/api/bills', methods=['POST', 'OPTIONS'])
def save_bills():
    """保存账单数据到数据库"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        return add_cors_headers(response)
    
    try:
        data = request.get_json()
        if not data:
            response = jsonify({'error': '请求体不能为空'})
            return add_cors_headers(response), 400
        
        bills = data.get('bills', [])
        user_input = data.get('user_input', '')
        
        if not isinstance(bills, list) or len(bills) == 0:
            response = jsonify({'error': '账单数据不能为空'})
            return add_cors_headers(response), 400
        
        saved_ids = []
        for bill_data in bills:
            # 验证必需字段
            if not all(key in bill_data for key in ['topic', 'payer', 'participants', 'amount']):
                continue
            
            # 创建账单记录
            bill = Bill(
                topic=bill_data.get('topic', ''),
                payer=bill_data.get('payer', ''),
                participants=json.dumps(bill_data.get('participants', []), ensure_ascii=False),
                amount=float(bill_data.get('amount', 0)),
                currency=bill_data.get('currency', 'CNY'),
                note=bill_data.get('note', ''),
                user_input=user_input
            )
            db.session.add(bill)
            saved_ids.append(bill.id)
        
        db.session.commit()
        
        response = jsonify({
            'success': True,
            'message': f'成功保存 {len(saved_ids)} 条账单记录',
            'saved_count': len(saved_ids),
            'ids': saved_ids
        })
        return add_cors_headers(response)
        
    except Exception as e:
        db.session.rollback()
        print(f'保存账单错误: {str(e)}')
        response = jsonify({'error': f'保存失败: {str(e)}'})
        return add_cors_headers(response), 500


@app.route('/api/bills', methods=['GET', 'OPTIONS'])
def get_bills():
    """查询所有账单数据"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        return add_cors_headers(response)
    
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        payer = request.args.get('payer', None)
        
        # 构建查询
        query = Bill.query
        
        # 按付款人筛选
        if payer:
            query = query.filter(Bill.payer.like(f'%{payer}%'))
        
        # 按创建时间倒序排列
        query = query.order_by(Bill.created_at.desc())
        
        # 分页
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        bills = [bill.to_dict() for bill in pagination.items]
        
        response = jsonify({
            'success': True,
            'data': bills,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        })
        return add_cors_headers(response)
        
    except Exception as e:
        print(f'查询账单错误: {str(e)}')
        response = jsonify({'error': f'查询失败: {str(e)}'})
        return add_cors_headers(response), 500


@app.route('/api/travel-plans', methods=['GET', 'OPTIONS'])
def get_travel_plans():
    """获取所有旅行计划"""
    if request.method == 'OPTIONS':
        return add_cors_headers(jsonify({})), 200
    
    try:
        # 获取查询参数
        session_id = request.args.get('session_id', SHARED_CHATROOM_SESSION_ID)
        
        # 查询数据库
        if session_id:
            plans = TravelPlan.query.filter_by(session_id=session_id).order_by(TravelPlan.created_at.desc()).all()
        else:
            plans = TravelPlan.query.order_by(TravelPlan.created_at.desc()).all()
        
        return add_cors_headers(jsonify({
            'success': True,
            'plans': [plan.to_dict() for plan in plans]
        })), 200
    except Exception as e:
        print(f"Error fetching travel plans: {e}")
        import traceback
        traceback.print_exc()
        return add_cors_headers(jsonify({
            'success': False,
            'error': str(e)
        })), 500


@app.route('/api/travel-plans/<int:plan_id>', methods=['GET', 'OPTIONS'])
def get_travel_plan(plan_id):
    """获取单个旅行计划"""
    if request.method == 'OPTIONS':
        return add_cors_headers(jsonify({})), 200
    
    try:
        plan = TravelPlan.query.get_or_404(plan_id)
        return add_cors_headers(jsonify({
            'success': True,
            'plan': plan.to_dict()
        })), 200
    except Exception as e:
        print(f"Error fetching travel plan: {e}")
        import traceback
        traceback.print_exc()
        return add_cors_headers(jsonify({
            'success': False,
            'error': str(e)
        })), 500


@app.route('/api/bills/<int:bill_id>', methods=['GET', 'OPTIONS'])
def get_bill(bill_id):
    """根据ID查询单条账单"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        return add_cors_headers(response)
    
    try:
        bill = Bill.query.get_or_404(bill_id)
        response = jsonify({
            'success': True,
            'data': bill.to_dict()
        })
        return add_cors_headers(response)
        
    except Exception as e:
        print(f'查询账单错误: {str(e)}')
        response = jsonify({'error': f'查询失败: {str(e)}'})
        return add_cors_headers(response), 500


@app.route('/')
def index():
    """返回主页"""
    return app.send_static_file('index.html')


if __name__ == '__main__':
    # 从环境变量获取端口，如果没有则使用默认值 5000
    port = int(os.getenv('PORT', 5000))
    # 在生产环境中，debug 应该为 False
    debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug, threaded=True)
