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

    // ==================== Markdown 渲染 ====================
    // 依赖: marked, DOMPurify, hljs (在 index.html 中通过 CDN 引入)
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true
        });
    }

    function renderMarkdown(text) {
        if (!text) return '';
        if (typeof marked === 'undefined') return escapeHtml(text);
        const html = marked.parse(text);
        const clean = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : html;
        return clean;
    }

    function highlightCodeBlocks(rootEl) {
        if (typeof hljs === 'undefined') return;
        rootEl.querySelectorAll('pre code:not([data-highlighted])').forEach((block) => {
            try { hljs.highlightElement(block); block.setAttribute('data-highlighted', 'true'); } catch (e) {}
        });
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // ==================== 状态 ====================
    const STORAGE_KEY = 'papermate_sessions';
    const DEFAULT_USER_ID = 'default_user';
    let sessions = [];           // { id, title, rawTitle?, messages, isBackend? }
    let currentSessionId = null;
    let isStreaming = false;

    // ==================== 后端历史消息适配 ====================
    // 后端返回清洗后的结构: [{role, content, timestamp, tool_name}]
    // role: human | ai | tool
    function mapBackendRoleToLocal(role) {
        switch (role) {
            case 'human': return 'user';
            case 'ai': return 'assistant';
            case 'tool': return 'tool';
            default: return 'assistant';
        }
    }

    function extractContent(content) {
        if (typeof content === 'string') return content;
        if (Array.isArray(content)) {
            return content.map(c => typeof c === 'string' ? c : (c && c.text) || JSON.stringify(c)).join('');
        }
        if (content && typeof content === 'object') return content.text || JSON.stringify(content);
        return String(content == null ? '' : content);
    }

    function backendMessagesToLocal(messages) {
        return (messages || []).map(m => {
            const role = mapBackendRoleToLocal(m.role);
            let content;
            let timestamp = '';
            if (role === 'tool') {
                content = m.tool_name ? `调用工具：${m.tool_name}` : '调用工具：未知';
            } else {
                content = extractContent(m.content);
                timestamp = m.timestamp || '';
            }
            return { role, content, timestamp };
        });
    }

    function formatTimestamp(ts) {
        if (ts === '' || ts === null || ts === undefined) return '';
        const n = Number(ts);
        if (!n || isNaN(n)) return '';
        const d = new Date(n * 1000);
        if (isNaN(d.getTime())) return '';

        const now = new Date();
        const pad = (x) => String(x).padStart(2, '0');
        const sameYear = d.getFullYear() === now.getFullYear();
        const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const diffMs = now.getTime() - d.getTime();
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const isToday = d.getTime() >= startOfToday.getTime();

        if (diffSec < 0) {
            // 未来时间回退为标准格式
        } else if (diffSec < 60) {
            return `${diffSec}秒前`;
        } else if (diffMin < 60) {
            return `${diffMin}分钟前`;
        } else if (diffHour < 24 && isToday) {
            return `${diffHour}小时前`;
        }

        const timeStr = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
        if (isToday) return `今天 ${timeStr}`;
        if (sameYear) {
            return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${timeStr}`;
        }
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${timeStr}`;
    }

    function roleLabel(role) {
        switch (role) {
            case 'user': return 'You';
            case 'assistant': return 'PaperMate';
            case 'tool': return 'Tool';
            case 'system': return 'System';
            default: return role;
        }
    }

    async function getHistory(threadId) {
        const resp = await fetch(`/chat/get_history?thread_id=${encodeURIComponent(threadId)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    }

    async function getThreadIds(userId) {
        const resp = await fetch(`/chat/get_thread_ids?user_id=${encodeURIComponent(userId)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    }

    // 解析后端 update_time 字符串 (SQLite CURRENT_TIMESTAMP 返回 "YYYY-MM-DD HH:MM:SS" 且为 UTC)，
    // 返回 Date 或 null
    function parseBackendTime(s) {
        if (!s) return null;
        const t = String(s).replace(' ', 'T') + 'Z';
        const d = new Date(t);
        return isNaN(d.getTime()) ? null : d;
    }

    // ==================== 持久化 ====================
    function loadSessions() {
        // 会话列表由后端动态返回，本地不再持久化会话
        sessions = [];
    }

    function saveSessions() {
        // 不再使用 localStorage 持久化会话
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
            messages: [],
            isBackend: false
        };
        sessions.unshift(session);
        return session;
    }

    async function refreshSessionList() {
        try {
            const list = await getThreadIds(DEFAULT_USER_ID);
            // 后端返回: [{thread_id, latest_message, update_time}], 已按 update_time DESC 排序
            const backendSessions = (list || []).map(item => ({
                id: item.thread_id,
                title: item.latest_message ? (item.latest_message.length > 30 ? item.latest_message.slice(0, 30) + '...' : item.latest_message) : '新对话',
                rawTitle: item.latest_message || '',
                messages: [],
                isBackend: true,
                updateTime: item.update_time || ''
            }));
            // 保留本地新建未发送的会话，但需避免与后端列表重复（id 已被持久化则丢弃本地项）
            const localNew = sessions.find(s => !s.isBackend && !backendSessions.some(b => b.id === s.id));
            sessions = backendSessions;
            if (localNew) sessions.unshift(localNew);
            renderSessionList();
        } catch (err) {
            console.error('加载会话列表失败:', err);
        }
    }

    async function switchSession(id) {
        currentSessionId = id;
        renderSessionList();
        const s = findSession(id);
        if (s) {
            const displayTitle = s.rawTitle || s.title || '新对话';
            currentSessionTitle.textContent = displayTitle.length > 30 ? displayTitle.slice(0, 30) + '...' : displayTitle;
        }
        // 后端会话：每次点击都从后端拉取历史
        if (s && s.isBackend) {
            messagesContainer.innerHTML = '<div style="text-align:center;color:var(--text-secondary);margin-top:40px;">加载历史中...</div>';
            try {
                const history = await getHistory(s.id);
                if (currentSessionId !== id) return; // 已切换到其他会话，丢弃过期结果
                s.messages = backendMessagesToLocal(history);
                renderMessages();
            } catch (err) {
                if (currentSessionId !== id) return;
                messagesContainer.innerHTML = `<div style="text-align:center;color:var(--danger);margin-top:40px;">加载历史失败: ${err.message}</div>`;
            }
        } else {
            renderMessages();
        }
    }

    function deleteCurrentSession() {
        if (!currentSessionId) return;
        sessions = sessions.filter(s => s.id !== currentSessionId);
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
            const displayTitle = s.rawTitle || s.title || '新对话';
            li.textContent = displayTitle;
            li.title = displayTitle;
            li.classList.toggle('active', s.id === currentSessionId);
            li.addEventListener('click', () => switchSession(s.id));
            sessionList.appendChild(li);
        });
    }

    function renderMessages() {
        messagesContainer.innerHTML = '';
        const s = findSession(currentSessionId);
        if (!s || s.messages.length === 0) {
            const emptyText = (s && s.isBackend) ? '该会话暂无历史消息' : '开始一段新对话吧';
            messagesContainer.innerHTML = `<div style="text-align:center;color:var(--text-secondary);margin-top:40px;">${emptyText}</div>`;
            return;
        }
        s.messages.forEach((msg, idx) => {
            appendMessageEl(msg.role, msg.content, idx === s.messages.length - 1 && msg.role === 'assistant' && isStreaming, msg.timestamp);
        });
        scrollToBottom();
    }

    function appendMessageEl(role, content, isStreamingMsg, timestamp) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        if (isStreamingMsg) div.classList.add('streaming');

        const label = document.createElement('div');
        label.className = 'role-label';
        label.textContent = roleLabel(role);

        const body = document.createElement('div');
        body.className = 'message-body';
        setMessageBodyContent(body, role, content);

        div.appendChild(label);
        div.appendChild(body);

        // HumanMessage 显示时间戳
        if (role === 'user' && timestamp) {
            const ts = document.createElement('div');
            ts.className = 'message-timestamp';
            ts.textContent = formatTimestamp(timestamp);
            div.appendChild(ts);
        }

        messagesContainer.appendChild(div);
        scrollToBottom();
        return { div, body };
    }

    function setMessageBodyContent(bodyEl, role, content) {
        // tool / system 等标识性消息用纯文本，避免被 markdown 误渲染
        if (role === 'tool' || role === 'system') {
            bodyEl.textContent = content;
            return;
        }
        bodyEl.innerHTML = renderMarkdown(content);
        highlightCodeBlocks(bodyEl);
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
            body: JSON.stringify({ thread_id: currentSessionId, message: message, user_id: DEFAULT_USER_ID })
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
            body: JSON.stringify({ thread_id: currentSessionId, message: message, user_id: DEFAULT_USER_ID })
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullContent = '';
        let buffer = '';

        // 创建流式消息元素
        const msgEl = document.createElement('div');
        msgEl.className = 'message assistant streaming';
        const label = document.createElement('div');
        label.className = 'role-label';
        label.textContent = 'PaperMate';
        const body = document.createElement('div');
        body.className = 'message-body';
        body.innerHTML = renderMarkdown('');
        msgEl.appendChild(label);
        msgEl.appendChild(body);
        messagesContainer.appendChild(msgEl);

        // 按 SSE 事件边界（\n\n）解析，保留 content 内部的换行符
        const flushEvents = () => {
            let idx;
            while ((idx = buffer.indexOf('\n\n')) >= 0) {
                const event = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 2);
                if (!event) continue;
                // 一个事件可能包含多行 data:，合并为换行符连接的内容
                const dataLines = event.split('\n');
                const data = dataLines
                    .filter(l => l.startsWith('data: '))
                    .map(l => l.slice(6))
                    .join('\n');
                if (!data || data === '[DONE]') continue;
                fullContent += data;
                body.innerHTML = renderMarkdown(fullContent);
                highlightCodeBlocks(body);
                scrollToBottom();
            }
        };

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            flushEvents();
        }
        // 处理尾部剩余 buffer
        if (buffer) {
            buffer += '\n\n';
            flushEvents();
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
        const nowTs = Math.floor(Date.now() / 1000);
        session.messages.push({ role: 'user', content: message, timestamp: nowTs });
        appendMessageEl('user', message, false, nowTs);

        // 更新标题（后端会话直接用 latest_message；本地新建会话用首条消息）
        const shortMsg = message.length > 30 ? message.slice(0, 30) + '...' : message;
        session.rawTitle = message;
        currentSessionTitle.textContent = shortMsg;
        renderSessionList();

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
            // 后端已更新 latest_message，刷新侧边栏会话列表顺序与标题
            refreshSessionList();
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
        // 新会话不需要拉取历史，直接渲染空状态
        renderSessionList();
        currentSessionTitle.textContent = '新对话';
        messagesContainer.innerHTML = '<div style="text-align:center;color:var(--text-secondary);margin-top:40px;">开始一段新对话吧</div>';
        msgInput.focus();
    });

    btnDeleteSession.addEventListener('click', () => {
        if (!confirm('确定要删除当前对话吗？')) return;
        // 调用后端接口 (fire-and-forget)
        fetch(`/chat/delete_session?thread_id=${encodeURIComponent(currentSessionId)}`);
        deleteCurrentSession();
        msgInput.focus();
    });

    // ==================== 初始化 ====================
    async function init() {
        loadSessions();
        // 从后端加载会话列表
        await refreshSessionList();
        if (sessions.length === 0) {
            createSession();
        }
        // 默认选中第一个会话（后端最新会话）
        currentSessionId = sessions[0].id;
        await switchSession(currentSessionId);
        msgInput.focus();
    }

    init();
})();
