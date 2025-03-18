from flask import Flask, jsonify, request # 导入Flask库
from flask_cors import CORS # 导入CORS库
from functools import wraps # 导入wraps函数
import jwt # 导入jwt库
import json     # 导入json库
import os # 导入os库
from datetime import datetime, timedelta # 导入datetime库
import time # 导入time库
import threading

file_lock = threading.Lock()  # 线程锁

last_request_time = {}

def rate_limit(limit_seconds): # 限制访问频率
    def decorator(f): 
        @wraps(f) 
        def wrapped(*args, **kwargs): 
            ip = request.remote_addr # 获取请求IP
            now = time.time() # 获取当前时间
            if ip in last_request_time and now - last_request_time[ip] < limit_seconds: # 如果请求时间间隔小于限制时间
                return jsonify({"error": "Too many requests"}), 429 # 返回错误信息
            last_request_time[ip] = now # 更新上次请求时间
            return f(*args, **kwargs) 
        return wrapped
    return decorator

app = Flask(__name__) # 初始化Flask应用
CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": "*"}}) # 允许跨域请求

# 配置项
JWT_SECRET = 'your_super_secret_key_123!' # JWT密钥
DATA_FILE = 'sisiexpense/data.json' # 数据文件
ALLOWED_USERS = {'bowei', 'winston', 'alan', 'zach'} # 允许的用户

def init_data():
    # 初始化数据文件
    if not os.path.exists(DATA_FILE) or os.path.getsize(DATA_FILE) == 0:  # 检查文件是否为空
        with open(DATA_FILE, 'w') as f:
            json.dump({
                "expenses": [],
                "users": {
                    user: {"password": f"hashed_{user}",
                        "balance": 0.0} 
                    for user in ALLOWED_USERS
                },
                "system": {
                    "last_id": 0
                }
            }, f, indent=2)

# 认证装饰器
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        
        if not token:
            return jsonify({'error': '缺少认证token'}), 100
            
        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            current_user = data['user']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token已过期'}), 101
        except jwt.InvalidTokenError:
            return jsonify({'error': '无效Token'}), 102
            
        return f(current_user, *args, **kwargs)
    return decorated

def with_data(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        with file_lock:  # 线程锁，确保不会有多个线程同时读写
            if not os.path.exists(DATA_FILE):
                init_data()
            try:
                with open(DATA_FILE, 'r') as file:
                    data = json.load(file)
            except (json.JSONDecodeError, FileNotFoundError):
                return jsonify({"error": "数据文件读取错误"}), 501

            result = f(data, *args, **kwargs)

            try:
                with open(DATA_FILE, 'w') as file:
                    json.dump(data, file, indent=2)
            except:
                return jsonify({"error": "数据文件写入错误"}), 500

            return result
    return wrapper

@app.route('/api/login', methods=['POST']) # 登录
@with_data
def login(data):
    if not request.is_json:
        return jsonify({"error": "需要JSON格式数据"}), 400
    
    username = request.json.get('username')
    if not username or username not in ALLOWED_USERS: # 检查用户名是否合法
        return jsonify({"error": "非法用户"}), 403
        
    token = jwt.encode({ # 生成Token
        'user': username, # 设置用户名
        'exp': datetime.utcnow() + timedelta(hours=1) # 设置过期时间
    }, JWT_SECRET, algorithm='HS256') # 加密Token
        
    return jsonify({ # 返回Token
        "user": username,   # 返回用户名
        "token": token # 返回Token
    })

@app.route('/api/expenses/<expense_id>', methods=['GET']) # 获取消费记录
@with_data
@token_required
def get_expenses(current_user, data, expense_id): # 获取消费记录

    if expense_id != '-1': # 如果请求特定ID的记录
        expense_id = int(expense_id)
        for expense in data['expenses']:
            if expense['id'] == expense_id:
                return jsonify(expense)
        return jsonify({"error": "未找到对应记录"}), 404
    else: # 如果请求所有记录
        return jsonify(list(reversed(data['expenses'][-10:])))

@app.route('/api/expenses', methods=['POST']) # 添加消费记录
@with_data # 读取数据文件
@token_required # 需要认证
def add_expense(current_user, data):
    required_fields = ['payer', 'item', 'price'] # 必填字段
    if missing := [f for f in required_fields if f not in request.json]: # 检查是否有缺少字段
        return jsonify({"error": f"缺少字段: {', '.join(missing)}"}), 400 # 返回错误信息
    
    try: # 尝试解析价格
        new_expense = {
            "id": data['system']['last_id'] + 1,
            "time": datetime.utcnow().isoformat(),
            "payer": request.json['payer'],
            "item": request.json['item'],
            "price": float(request.json['price']),
            "uploader": current_user,
            "is_calculate": True,
            "is_system": True if request.json['payer'] == 'System' else False
        } # 构造新记录

        #print("新记录:", new_expense)  # 调试信息

        data['system']['last_id'] += 1 # 更新ID计数器
    except ValueError:
        return jsonify({"error": "无效数据类型"}), 400 # 返回错误信息
    
    if 'expenses' not in data: # 如果没有消费记录
        data['expenses'] = [] # 初始化消费记录
    
    data['expenses'].append(new_expense) # 添加新记录
    if new_expense['payer'] != 'System': # 如果不是系统记录
        data['users'][new_expense['payer']]['balance'] += new_expense['price'] # 更新支付人余额
    return jsonify(new_expense), 201 # 返回新记录

@app.route('/api/balances', methods=['GET']) # 获取用户余额
@with_data # 读取数据文件
@token_required # 需要认证
def get_balances(current_user, data):
    balances = {} # 初始化余额字典
    for payer in data['users']: # 遍历所有用户
        price = data['users'][payer].get('balance', 0.0) # 获取余额
        if price != 0: # 如果余额不为0
            balances[payer.capitalize()] = data['users'][payer].get('balance', 0.0) # 添加到余额字典
    return jsonify(balances) # 返回余额字典

@app.route('/api/balances/clear', methods=['POST']) #  清零用户余额
@with_data
@token_required
def clear_balances(current_user, data): 
    for payer in data['users']: # 遍历所有用户
        data['users'][payer]['balance'] = 0.0 # 清零余额
    for expense in data['expenses']: # 遍历所有消费记录
        expense['is_calculate'] = False # 标记为不计算
    return jsonify({"message": "所有用户余额已清零"}) # 返回成功信息

@app.route('/api/expenses/<int:expense_id>', methods=['DELETE']) # 删除消费记录
@with_data
@token_required
def delete_expense(current_user, data, expense_id):
    print("收到请求删除 ID:", expense_id)  # 调试信息

    for i, expense in enumerate(data['expenses']):
        if expense['id'] == expense_id:
            # 更新支付人余额
            if expense['is_calculate']:
                payer = expense['payer']
                if payer in data['users'] and 'balance' in data['users'][payer]:
                    data['users'][payer]['balance'] -= expense['price']
            
            # 删除记录
            print("删除记录:", data['expenses'][i])
            del data['expenses'][i]
            return jsonify({"message": "删除成功"}), 200

    return jsonify({"error": "未找到对应记录"}), 404

if __name__ == '__main__':
    init_data()
    app.run(host='0.0.0.0', port=5000, debug=True)  # 启动Flask应用