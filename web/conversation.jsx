// Conversation detail view — loads real messages from /api/session
const ConversationView = ({ conv, data, onBack, onDeleted }) => {
  const { projects, tags } = data;
  const project = projects.find(p => p.id === conv.project);
  const [messages, setMessages] = React.useState(null);
  const [detail, setDetail] = React.useState(null);
  const [err, setErr] = React.useState('');

  React.useEffect(() => {
    let cancel = false;
    setMessages(null); setErr('');
    fetch(`/api/session/${encodeURIComponent(conv.project)}/${encodeURIComponent(conv.sid)}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP '+r.status)))
      .then(d => { if (!cancel) { setMessages(d.messages || []); setDetail(d); } })
      .catch(e => { if (!cancel) setErr(String(e)); });
    return () => { cancel = true; };
  }, [conv.project, conv.sid]);

  // derived: actual model used
  const modelShown = (messages || []).find(m => m.role === 'assistant' && m.model)?.model
    || conv.model || '—';

  const escHtml = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

  const doExport = (fmt) => {
    window.location = `/api/export/${encodeURIComponent(conv.project)}/${encodeURIComponent(conv.sid)}?format=${fmt}`;
  };
  const doResume = async () => {
    try {
      const r = await fetch('/api/resume', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: conv.project, sid: conv.sid})});
      const d = await r.json();
      if (await window.handleAuthGate(d)) return;
      if (d.ok) window.dialog.alert(`已在新终端启动:\ncd ${d.cwd}\nclaude --resume ${conv.sid}`, {title:'继续对话'});
      else window.dialog.alert('启动失败: ' + (d.error || '未知'), {title:'启动失败', danger:true});
    } catch (e) { window.dialog.alert('启动失败: ' + e, {title:'启动失败', danger:true}); }
  };
  const doCodex = async () => {
    try {
      const r = await fetch('/api/codex', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: conv.project, sid: conv.sid})});
      const d = await r.json();
      if (await window.handleAuthGate(d)) return;
      if (d.ok) window.dialog.alert(`已在新终端启动 Codex\ncd ${d.cwd}\n上下文: ${d.mdPath}`, {title:'转移到 Codex'});
      else window.dialog.alert('启动失败: ' + (d.error || '未知'), {title:'启动失败', danger:true});
    } catch (e) { window.dialog.alert('启动失败: ' + e, {title:'启动失败', danger:true}); }
  };
  const doDelete = async () => {
    const ok = await window.dialog.confirm(
      `确认永久删除此对话?\n${conv.title}`,
      {title:'永久删除', danger:true});
    if (!ok) return;
    const r = await fetch('/api/delete', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({project: conv.project, sid: conv.sid})});
    const d = await r.json();
    if (d.ok) { onDeleted && onDeleted(conv.id); onBack(); }
    else window.dialog.alert('删除失败: ' + d.error, {title:'删除失败', danger:true});
  };
  const doPin = () => {
    window.APP_STATE_API.togglePin(conv.id);
    conv.pinned = !conv.pinned;
    // light re-render trick
    setErr(x => x);
  };

  return (
    <div className="detail-layout">
      <div className="detail-main">
        <div className="detail-head">
          <button className="chip-btn" onClick={onBack} style={{marginBottom: 16}}>
            <Icon name="back" size={12}/> 返回
          </button>
          <h1 className="detail-title">{conv.title}</h1>
          <div className="detail-meta">
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--ink-2)', fontFamily: 'var(--font-sans)'}}>
              <ProjectDot project={conv.project} projects={projects} size={8}/>
              {project?.name}
            </span>
            <span className="sep">·</span>
            <span>{modelShown}</span>
            <span className="sep">·</span>
            <span>{conv.messages} 条消息</span>
            {conv.created && <><span className="sep">·</span><span>创建于 {conv.created}</span></>}
            {conv.gitBranch && <><span className="sep">·</span><span>⎇ {conv.gitBranch}</span></>}
          </div>
        </div>

        <div className="messages">
          {err && <div style={{color:'var(--danger, #ef4444)', padding:16}}>加载失败: {err}</div>}
          {!err && messages === null && <div style={{color:'var(--ink-3)', padding:16}}>加载中...</div>}
          {messages && messages.length === 0 && <div style={{color:'var(--ink-3)', padding:16}}>无消息</div>}
          {messages && messages.map((m, i) => {
            if (m.role === 'summary') {
              return <div key={i} className="msg" style={{background:'var(--bg-sunk)', padding:12, borderRadius:8, margin:'8px 0', fontStyle:'italic', color:'var(--ink-2)'}}>
                <strong>摘要:</strong> {m.text}
              </div>;
            }
            const isTool = m.toolResult;
            const role = isTool ? 'tool' : m.role;
            const avatar = m.role === 'user' ? (isTool ? '🔧' : 'U') : 'C';
            const name = isTool ? '工具返回' : (m.role === 'user' ? '用户' : 'Claude');
            const ts = m.ts ? new Date(m.ts).toLocaleString() : '';
            return (
              <div key={i} className={`msg ${role}`} style={isTool ? {opacity: 0.7} : {}}>
                <div className="msg-avatar">{avatar}</div>
                <div className="msg-content">
                  <div className="msg-author">{name}{m.model ? ` · ${m.model}` : ''}<span className="msg-time">{ts}</span></div>
                  <div className="msg-body"><pre style={{whiteSpace:'pre-wrap', wordBreak:'break-word', margin:0, fontFamily:'inherit'}}>{m.text}</pre></div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <aside className="detail-aside">
        <div className="aside-section">
          <div className="aside-label">对话信息</div>
          <div className="aside-row"><span className="k">模型</span><span className="v" title={modelShown}>{modelShown}</span></div>
          <div className="aside-row"><span className="k">消息数</span><span className="v">{conv.messages}</span></div>
          <div className="aside-row"><span className="k">User / AI</span><span className="v">{conv.userCount} / {conv.assistantCount}</span></div>
          <div className="aside-row"><span className="k">创建时间</span><span className="v">{conv.created}</span></div>
          <div className="aside-row"><span className="k">最后更新</span><span className="v">{conv.updated}</span></div>
          <div className="aside-row"><span className="k">大小</span><span className="v">{(conv.size/1024).toFixed(1)} KB</span></div>
        </div>

        <div className="aside-section">
          <div className="aside-label">工作目录</div>
          <div style={{fontFamily:'var(--font-mono)', fontSize: 11, color: 'var(--ink-2)', background: 'var(--bg-sunk)', padding: 10, borderRadius: 6, wordBreak: 'break-all'}}>
            {conv.cwd || '—'}
          </div>
        </div>

        <div className="aside-section">
          <div className="aside-label">Session ID</div>
          <div style={{fontFamily:'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-3)', wordBreak: 'break-all'}}>
            {conv.sid}
          </div>
        </div>

        <div className="aside-section">
          <div className="aside-label">标签</div>
          <div className="aside-tags">
            {conv.tags.map(t => (
              <span key={t} style={{display:'inline-flex',alignItems:'center',gap:4}}>
                <Tag tag={t} tags={tags}/>
                <button style={{color:'var(--ink-4)',padding:'0 2px',fontSize:12}} title="移除" onClick={() => {
                  const next = conv.tags.filter(x => x !== t);
                  window.APP_STATE_API.setTags(conv.id, next);
                  conv.tags = next;
                  setErr(x => x);
                }}>×</button>
              </span>
            ))}
            {conv.tags.length === 0 && <span style={{color:'var(--ink-4)', fontSize:12}}>未添加标签</span>}
            <button className="aside-add-tag" onClick={async () => {
              const names = tags.map(t => `${t.id} - ${t.name}`).join('\n');
              const picked = await window.dialog.prompt(
                `选择标签 ID (或输入新名称创建):\n${names}`,
                {title:'添加标签', defaultValue:'', placeholder:'标签 ID 或新名称'});
              if (!picked) return;
              let id = picked.trim();
              const exists = tags.find(t => t.id === id);
              if (!exists) id = window.APP_STATE_API.addTag(id);
              const next = Array.from(new Set([...(conv.tags || []), id]));
              window.APP_STATE_API.setTags(conv.id, next);
              conv.tags = next;
              setErr(x => x);
            }}>+ 添加</button>
          </div>
        </div>

        <div className="aside-section">
          <div className="aside-label">操作</div>
          <div style={{display: 'flex', flexDirection: 'column', gap: 2}}>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doResume}>
              <Icon name="message" size={14}/> 继续对话
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doCodex}>
              <Icon name="export" size={14}/> 转移到 Codex
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doPin}>
              <Icon name="pin" size={14}/> {conv.pinned ? '取消置顶' : '置顶'}
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={() => doExport('md')}>
              <Icon name="export" size={14}/> 导出为 Markdown
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={() => doExport('json')}>
              <Icon name="download" size={14}/> 导出原始 JSONL
            </button>
            <button className="nav-item" style={{padding: '8px 12px', color: 'var(--danger, #ef4444)'}} onClick={doDelete}>
              <Icon name="trash" size={14}/> 永久删除
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
};

Object.assign(window, { ConversationView });
