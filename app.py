from flask import Flask, request, Response, jsonify
from flask_sqlalchemy import SQLAlchemy
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bills.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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

# 创建数据库表
with app.app_context():
    db.create_all()
    print("数据库初始化完成")

# 总路由AI提示词
ROUTER_PROMPT = """你是一个智能路由助手。你的任务是根据用户的问题，判断应该由哪个专业的子机器人来回答。

可用的子机器人：
1. "travel" - 旅行助手：处理所有与旅行、旅游、行程规划、酒店预订、景点推荐等相关的问题
2. "bill" - 账单助手：处理所有与AA账单、消费记录、费用分摊等相关的问题

请根据用户的问题，返回一个JSON格式的响应，只包含agent字段：
- 如果问题与旅行相关，返回 {{"agent": "travel"}}
- 如果问题与账单相关，返回 {{"agent": "bill"}}
- 如果无法判断或问题不属于以上两类，返回 {{"agent": "unknown"}}

重要要求：
- 只输出JSON，不要添加任何解释性文字
- JSON格式必须严格正确
- 只返回agent字段

用户问题：{user_input}

请判断应该使用哪个agent："""

# 账单助手提示词
BILL_PROMPT = """你是一名 AA 账单助手。你的任务有两个：

任务1：记录账单信息
从用户提供的自然语言描述中，提取出一笔或多笔消费的结构化信息。

【你要抽取的信息字段】
- topic: 本次消费的主题/用途（例如：晚餐、打车、旅馆、咖啡等）
- payer: 实际付款的人（字符串）
- participants: 所有关联的人名列表（字符串数组）
- amount: 此笔消费总金额（数字）
- currency: 货币（如 "CNY", "GBP", "USD"）
- note: 其他补充信息（可选）

【输出要求】
- 必须输出格式严谨、合法的 JSON
- JSON 的顶级结构必须是数组，每个元素代表一笔消费
- 数组中的每一项都必须包含 topic, payer, participants, amount 字段
- 不得添加任何解释性文字，不得输出 JSON 外的内容

【解析规则】
- 若用户提供的语句中包含多笔消费，请分成多条 JSON 记录
- 若未提及 participants，则默认 participants 为包含 payer 在内的所有出现的人名
- 若用户未提及货币，默认 currency="CNY"
- 若出现模糊金额（如"差不多 100 块"），按数字部分提取 amount=100
- 若无法解析，返回一个空数组 []

任务2：查询账单信息
如果用户询问已记录的账单信息（例如："查询账单ID 1"、"张三付了哪些账单"、"李四参与的账单"等），请识别这是查询请求，并返回查询信息。

【查询识别】
- 如果用户提到"查询"、"查找"、"看看"、"显示"等关键词，且涉及账单ID、付款人、参与者等信息，这是查询请求
- 对于查询请求，请提取查询条件（账单ID、付款人、参与者等），并以JSON格式返回：
  {{"query": true, "type": "id|payer|participant", "value": "查询值"}}

【输出格式示例】
记录账单：
[
  {{
    "topic": "晚餐",
    "payer": "张三",
    "participants": ["张三","李四","王五"],
    "amount": 200,
    "currency": "CNY",
    "note": ""
  }}
]

查询账单：
{{"query": true, "type": "payer", "value": "张三"}}
或
{{"query": true, "type": "id", "value": "1"}}
或
{{"query": true, "type": "participant", "value": "李四"}}

请始终遵循上述规则。

用户输入：{user_input}

请处理："""

# 旅行助手提示词
TRAVEL_PROMPT = """你是一名专业的旅行助手。你的任务是帮助用户解决旅行相关的问题，包括但不限于：
- 旅行行程规划
- 景点推荐
- 酒店预订建议
- 交通方式推荐
- 旅行预算规划
- 旅行注意事项
- 目的地信息查询

请以友好、专业的方式回答用户的问题，提供实用的建议和信息。

用户问题：{user_input}

请回答："""

# 初始化 LangChain
api_key = os.getenv('OPENAI_API_KEY', '')
if not api_key:
    print("警告: OPENAI_API_KEY 未设置，请检查 .env 文件")
    llm = None
else:
    try:
        # 使用 LangChain 初始化 ChatOpenAI
        llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0,
            streaming=True,
            api_key=api_key
        )
        print("LangChain 初始化成功")
    except Exception as e:
        print(f"初始化 LangChain 时出错: {e}")
        llm = None

# 创建提示词模板
router_template = ChatPromptTemplate.from_template(ROUTER_PROMPT)
bill_template = ChatPromptTemplate.from_template(BILL_PROMPT)
travel_template = ChatPromptTemplate.from_template(TRAVEL_PROMPT)

# 创建输出解析器
output_parser = StrOutputParser()

# 创建链
if llm:
    router_chain = router_template | llm | output_parser
    bill_chain = bill_template | llm | output_parser
    travel_chain = travel_template | llm | output_parser


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


def add_cors_headers(response):
    """为响应添加 CORS 头"""
    # 确保响应对象存在
    if response is None:
        response = jsonify({})
    # 强制设置 CORS 头
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, HEAD'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
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
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    return response


def generate_stream(user_message):
    """生成流式响应"""
    if not llm:
        yield f"data: {json.dumps({'type': 'error', 'content': 'OpenAI API Key not configured. Please check .env file'})}\n\n"
        return
    
    try:
        # 发送开始信号
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        
        # 第一步：调用总路由判断agent类型
        print("正在判断agent类型...")
        router_response = ""
        for chunk in router_chain.stream({"user_input": user_message}):
            if chunk:
                router_response += chunk
        
        # 解析路由响应
        agent = parse_router_response(router_response)
        print(f"路由判断结果: {agent}")
        
        # 发送agent类型
        yield f"data: {json.dumps({'type': 'agent', 'agent': agent})}\n\n"
        
        # 第二步：根据agent类型调用对应的子机器人
        if agent == 'bill':
            # 调用账单助手
            print("调用账单助手...")
            full_response = ""
            # 先完整获取响应，不流式输出
            for chunk in bill_chain.stream({"user_input": user_message}):
                if chunk:
                    full_response += chunk
            
            # 尝试解析响应
            try:
                result = extract_json_from_text(full_response)
                print(f"解析结果: {result}")
                
                # 判断是查询请求还是记录请求
                if result and isinstance(result, dict) and result.get('query'):
                    # 这是查询请求
                    query_type = result.get('type', '')
                    query_value = result.get('value', '')
                    print(f"查询请求: type={query_type}, value={query_value}")
                    
                    # 执行查询
                    bills = query_bills_from_db(query_type, query_value)
                    print(f"查询结果数量: {len(bills) if bills else 0}")
                    
                    if bills:
                        # 格式化查询结果
                        result_text = format_bills_for_display(bills)
                        yield f"data: {json.dumps({'type': 'chunk', 'content': result_text})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': 'No matching bill records found.'})}\n\n"
                        
                elif result and isinstance(result, list) and len(result) > 0:
                    # 这是记录请求（数组格式），保存到数据库并返回ID
                    print(f"记录请求，账单数量: {len(result)}")
                    saved_ids = save_bills_to_db(result, user_message)
                    print(f"保存的ID: {saved_ids}")
                    
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
                    print(f"记录请求（单个对象），转换为数组格式")
                    bills_array = [result]
                    saved_ids = save_bills_to_db(bills_array, user_message)
                    print(f"保存的ID: {saved_ids}")
                    
                    if saved_ids:
                        # 返回账单ID信息
                        id_message = f"Bill successfully recorded! Bill ID: {saved_ids[0]}"
                        yield f"data: {json.dumps({'type': 'chunk', 'content': id_message})}\n\n"
                        yield f"data: {json.dumps({'type': 'bill_ids', 'ids': saved_ids})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': 'Failed to record bill. Please check the data format.'})}\n\n"
                else:
                    # 无法解析，返回原始响应
                    print(f"无法解析为查询或记录，返回原始响应")
                    yield f"data: {json.dumps({'type': 'chunk', 'content': full_response})}\n\n"
                    
            except Exception as parse_error:
                print(f'解析错误: {parse_error}')
                import traceback
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'chunk', 'content': f'Error processing bill information: {str(parse_error)}'})}\n\n"
                
        elif agent == 'travel':
            # 调用旅行助手
            print("调用旅行助手...")
            for chunk in travel_chain.stream({"user_input": user_message}):
                if chunk:
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                    
        else:
            # unknown 情况，返回提示信息
            yield f"data: {json.dumps({'type': 'chunk', 'content': 'Sorry, I cannot understand your question. Please try asking about travel or bill-related questions.'})}\n\n"
        
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
    
    print(f'收到消息: {user_message}')
    
    # 返回流式响应
    response = Response(
        generate_stream(user_message),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
            'Access-Control-Allow-Methods': 'POST, OPTIONS'
        }
    )
    return add_cors_headers(response)


@app.route('/api/health', methods=['GET', 'OPTIONS'])
def health():
    """健康检查接口"""
    if request.method == 'OPTIONS':
        response = jsonify({})
        response = add_cors_headers(response)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
        return response
    
    response = jsonify({
        'status': 'ok',
        'client_configured': llm is not None
    })
    response = add_cors_headers(response)
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


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
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
