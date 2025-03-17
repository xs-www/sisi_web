const API_BASE = 'http://localhost:5000/api';
        let updateController = null;  // 请求中止控制器
        let lastUpdateTime = 0;       // 最后更新时间戳
        let is_data_updated = false;  // 数据更新状态

        // 初始化检查登录状态
        function checkLogin() {
            const token = localStorage.getItem('token');
            if (token) {
                document.getElementById('loginSection').style.display = 'none';
                document.getElementById('mainContent').style.display = 'block';
                document.getElementById('currentUser').textContent = 
                    localStorage.getItem('currentUser');
                if (is_data_updated) {  
                    showMainInterface(user);
                }
            }
        }

        async function login() {
            try {
                const response = await fetch(`${API_BASE}/login`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username: document.getElementById('username').value.trim() })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP错误: ${response.status}`);
                }

                const { user, token } = await response.json();
                localStorage.setItem('token', token);
                showMainInterface(user);
            } catch (error) {
                alert(`登录失败: ${error.message}`);
                console.error('登录错误详情:', error);
            }
        }

        // 显示主界面
        function showMainInterface(user) {
            document.getElementById('loginSection').style.display = 'none';
            document.getElementById('mainContent').style.display = 'block';
            document.getElementById('currentUser').textContent = user;
            localStorage.setItem('currentUser', user);
            updateData();
            is_data_updated = false;
        }

        // 添加记录
        async function addExpense() {
            const record = {
                item: document.getElementById('item').value,
                price: parseFloat(document.getElementById('price').value),
                payer: document.getElementById('payer').value
            };
            
            try {
                const response = await fetch(`${API_BASE}/expenses`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${localStorage.getItem('token')}`
                    },
                    body: JSON.stringify(record)
                });
                
                if (response.ok) {
                    is_data_updated = true;
                    document.getElementById('item').value = '';
                    document.getElementById('price').value = '';
                } else {
                    alert('保存失败');
                }
            } catch (error) {
                alert('网络错误', error);
            }
        }

        // 强化版数据更新函数
        let isUpdating = false; // 新增更新状态锁
        async function updateData() {
            const now = Date.now();
            
            // 多重防护机制
            if (now - lastUpdateTime < 1000 || 
                isUpdating || 
                updateController?.signal.aborted) {
                console.log('更新请求被阻止');
                return;
            }
            
            isUpdating = true;
            if (updateController) {
                updateController.abort();
            }
            
            updateController = new AbortController();
            lastUpdateTime = now;

            try {
                // 获取并更新余额数据
                const [balances, expenses] = await Promise.all([
                    fetch(`${API_BASE}/balances`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    }).then(r => r.json()),
                    
                    fetch(`${API_BASE}/expenses/${-1}`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    }).then(r => r.json())
                ]);

                console.log('更新成功:', balances, expenses);

                // 批量更新DOM
                document.getElementById('balanceBody').innerHTML = 
                    Object.entries(balances).map(([name, amount]) => `
                        <tr><td>${name}</td><td>¥${amount.toFixed(2)}</td></tr>
                    `).join('');

                document.getElementById('logBody').innerHTML = expenses.map(e => `
                    <tr class="${e.payer === 'System' ? 'system-record' : ''}">
                        <td>${new Date(e.time).toLocaleString()}</td>
                        <td>${e.payer}</td>
                        <td>${e.item}</td>
                        <td>¥${e.price.toFixed(2)}</td>
                        <td>${e.payer !== 'System' ? 
                            `<button onclick="deleteExpense('${e.id}')">删除</button>` : 
                            '系统记录'}
                        </td>
                    </tr>
                `).join('');

            } catch (error) {
                console.error('更新失败:', error);
                lastUpdateTime = 0;  // 允许失败后立即重试
            } finally {
                updateController = null;
                isUpdating = false; // 确保状态锁释放
            }
        }

        // 修改scheduleUpdate避免递归调用
        let scheduled = false;
        function scheduleUpdate() {
            if (scheduled) return;
            
            const now = Date.now();
            const delay = Math.max(1000 - (now - lastUpdateTime), 0);
            
            scheduled = true;
            setTimeout(() => {
                updateData();
                scheduled = false;
            }, delay);
        }

        // 新增清账功能
        async function clearBalances() {
            if (!confirm('清账将重置所有金额并添加系统记录，确认继续吗？')) return;
            
            try {
                // 1. 执行清账操作
                const clearResponse = await fetch(`${API_BASE}/balances/clear`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${localStorage.getItem('token')}`
                    }
                });

                if (!clearResponse.ok) {
                    alert('清账失败');
                    return;
                }

                // 2. 添加系统记录
                const logResponse = await fetch(`${API_BASE}/expenses`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${localStorage.getItem('token')}`
                    },
                    body: JSON.stringify({
                        payer: "System",
                        item: "清账",
                        price: 0.0
                    })
                });

                console.log('清账记录:', logResponse);

                if (logResponse.ok) {
                    is_data_updated = true;
                    alert('清账成功，已添加系统记录');
                } else {
                    alert('清账成功但添加记录失败');
                }
            } catch (error) {
                alert('操作失败: ' + error.message);
            }
        }

        // 新增删除功能
        async function deleteExpense(expenseId) {

            // 获取要删除的记录详情
            const expense = await fetch(`${API_BASE}/expenses/${expenseId}`, {
                headers: {'Authorization': `Bearer ${localStorage.getItem('token')}`},
            }).then(r => r.json());

            // 阻止删除系统记录
            if (expense.payer === "System") {
                alert('系统记录不可删除');
                return;
            }
            
            if (!confirm('确定要删除这条记录吗？')) return;
            
            try {
                const response = await fetch(`${API_BASE}/expenses/${expenseId}`, {
                    method: 'DELETE',
                    headers: {
                        'Authorization': `Bearer ${localStorage.getItem('token')}`
                    }
                });

                const result = await response.json();
                if (response.ok) {
                    alert('删除成功');
                    is_data_updated = true;
                } else {
                    alert(`删除失败: ${result.error}`);
                }
            } catch (error) {
                console.error("删除请求出错:", error);
                alert('网络错误');
            }
        }
        // 注销
        function logout() {
            localStorage.clear();
            location.reload();
        }

        // 初始化时取消可能的遗留定时器
        checkLogin();