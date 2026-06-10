(function () {
    'use strict';

    // ==================== DOM 引用 ====================
    const $ = (sel) => document.querySelector(sel);
    const sessionList = $('#session-list');
    const messagesContainer = $('#messages-container');
    const msgInput = $('#msg-input');
    const btnSend = $('#btn-send');
    const btnNewSession = $('#btn-new-session');
    const btnDeleteSession = $('#btn-delete-session');
    const toggleStream = $('#toggle-stream');
    const currentSessionTitle = $('#current-session-title');

    // ==================== 状态 ====================
    const STORAGE_KEY = 'rocomate_sessions';
    let sessions = [];           // { id, title, messages: [{role, content}] }
    let currentSessionId = null;
    let isStreaming = false;

    // ==================== 持久化 ====================
    function loadSessions() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            sessions = raw ? JSON.parse(raw) : [];
        } catch {
            sessions = [];
        }
    }

    function saveSessions() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
    }

    function findSession(id) {
        return sessions.find(s => s.id === id);
    }

    // ==================== 会话管理 ====================
    function createSession() {
        const id = 'sess_' + Date.now();
        const session = {
            id: id,
            title: '新对话',
            messages: []
        };
        sessions.unshift(session);
        saveSessions();
        return session;
    }

    function switchSession(id) {
        currentSessionId = id;
        renderSessionList();
        renderMessages();
        const s = findSession(id);
        if (s) {
            currentSessionTitle.textContent = s.title.length > 30 ? s.title.slice(0, 30) + '...' : s.title;
        }
    }

    function deleteCurrentSession() {
        if (!currentSessionId) return;
        sessions = sessions.filter(s => s.id !== currentSessionId);
        saveSessions();
        if (sessions.length === 0) {
            const s = createSession();
            currentSessionId = s.id;
        } else {
            currentSessionId = sessions[0].id;
        }
        switchSession(currentSessionId);
    }

    // ==================== UI 渲染 ====================
    function renderSessionList() {
        sessionList.innerHTML = '';
        sessions.forEach(s => {
            const li = document.createElement('li');
            li.textContent = s.title;
            li.title = s.title;
            li.classList.toggle('active', s.id === currentSessionId);
            li.addEventListener('click', () => switchSession(s.id));
            sessionList.appendChild(li);
        });
    }

    function renderMessages() {
        messagesContainer.innerHTML = '';
        const s = findSession(currentSessionId);
        if (!s || s.messages.length === 0) {
            messagesContainer.innerHTML = '<div style="text-align:center;color:var(--text-secondary);margin-top:40px;">开始一段新对话吧</div>';
            return;
        }
        s.messages.forEach((msg, idx) => {
            appendMessageEl(msg.role, msg.content, idx === s.messages.length - 1 && msg.role === 'assistant' && isStreaming);
        });
        scrollToBottom();
    }

    function appendMessageEl(role, content, isStreamingMsg) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        if (isStreamingMsg) div.classList.add('streaming');

        const label = document.createElement('div');
        label.className = 'role-label';
        label.textContent = role === 'user' ? 'You' : 'RocoMate';

        const body = document.createElement('div');
        body.className = 'message-body';
        body.textContent = content;

        div.appendChild(label);
        div.appendChild(body);
        messagesContainer.appendChild(div);
        scrollToBottom();
        return { div, body };
    }

    function appendTypingIndicator() {
        const div = document.createElement('div');
        div.className = 'message assistant streaming';
        div.id = 'typing-indicator';
        div.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
        messagesContainer.appendChild(div);
        scrollToBottom();
    }

    function removeTypingIndicator() {
        const el = document.getElementById('typing-indicator');
        if (el) el.remove();
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function setSending(isSending) {
        btnSend.disabled = isSending;
        msgInput.disabled = isSending;
        if (isSending) {
            btnSend.textContent = '...';
        } else {
            btnSend.textContent = '发送';
            msgInput.focus();
        }
    }

    // ==================== API 调用 ====================
    async function sendNonStream(message) {
        const resp = await fetch('/chat/invoke', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ Id: currentSessionId, Message: message })
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const result = await resp.json();
        if (result.code === 200 && result.data) {
            return result.data.content || '';
        }
        throw new Error(result.message || '请求失败');
    }

    async function sendStream(message) {
        const resp = await fetch('/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ Id: currentSessionId, Message: message })
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullContent = '';

        // 创建流式消息元素
        const msgEl = document.createElement('div');
        msgEl.className = 'message assistant streaming';
        const label = document.createElement('div');
        label.className = 'role-label';
        label.textContent = 'RocoMate';
        const body = document.createElement('div');
        body.className = 'message-body';
        body.textContent = '';
        msgEl.appendChild(label);
        msgEl.appendChild(body);
        messagesContainer.appendChild(msgEl);

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6).trim();
                    if (data === '[DONE]') break;
                    fullContent += data;
                    body.textContent = fullContent;
                    scrollToBottom();
                }
            }
        }

        msgEl.classList.remove('streaming');
        return fullContent;
    }

    // ==================== 发送消息主流程 ====================
    async function handleSend() {
        const message = msgInput.value.trim();
        if (!message || isStreaming) return;

        isStreaming = true;
        setSending(true);
        msgInput.value = '';

        // 确保当前会话存在
        let session = findSession(currentSessionId);
        if (!session) {
            session = createSession();
            currentSessionId = session.id;
            renderSessionList();
        }

        // 添加用户消息
        session.messages.push({ role: 'user', content: message });
        appendMessageEl('user', message, false);

        // 更新标题（取第一条用户消息）
        if (session.title === '新对话' || session.title === '新对话') {
            session.title = message.length > 20 ? message.slice(0, 20) + '...' : message;
            currentSessionTitle.textContent = session.title;
            renderSessionList();
        }

        // 显示输入指示器
        appendTypingIndicator();

        try {
            let reply;
            if (toggleStream.checked) {
                removeTypingIndicator();
                reply = await sendStream(message);
            } else {
                reply = await sendNonStream(message);
                removeTypingIndicator();
                appendMessageEl('assistant', reply, false);
            }

            // 保存助手回复
            const finalReply = reply || '';
            if (finalReply) {
                session.messages.push({ role: 'assistant', content: finalReply });
            }
            saveSessions();
        } catch (err) {
            removeTypingIndicator();
            appendMessageEl('assistant', '错误: ' + err.message, false);
        } finally {
            isStreaming = false;
            setSending(false);
        }
    }

    // ==================== 事件绑定 ====================
    btnSend.addEventListener('click', handleSend);

    msgInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    });

    btnNewSession.addEventListener('click', () => {
        const s = createSession();
        currentSessionId = s.id;
        switchSession(currentSessionId);
        msgInput.focus();
    });

    btnDeleteSession.addEventListener('click', () => {
        if (!confirm('确定要删除当前对话吗？')) return;
        // 调用后端接口 (fire-and-forget)
        fetch(`/chat/delete_session?id=${encodeURIComponent(currentSessionId)}`);
        deleteCurrentSession();
        msgInput.focus();
    });

    // ==================== 初始化 ====================
    function init() {
        loadSessions();
        if (sessions.length === 0) {
            const s = createSession();
            sessions.push(s);
            saveSessions();
        }
        currentSessionId = sessions[0].id;
        switchSession(currentSessionId);
        msgInput.focus();
    }

    init();
})();
