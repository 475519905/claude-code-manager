// Conversation detail view — loads real messages from /api/session

const _escHtml = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const _renderMd = (s) => {
  const text = String(s || '');
  try {
    if (window.marked) return window.marked.parse(text, {breaks: true, gfm: true});
  } catch {}
  return _escHtml(text).replace(/\n/g, '<br/>');
};

const _highlightHtml = (html, query) => {
  const q = String(query || '').trim();
  if (!q) return html;
  try {
    const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html');
    const root = doc.body.firstElementChild;
    if (!root) return html;
    const walker = doc.createTreeWalker(root, 4);
    const nodes = [];
    let node;
    while ((node = walker.nextNode())) nodes.push(node);
    const qLower = q.toLowerCase();
    for (const textNode of nodes) {
      const text = textNode.nodeValue || '';
      const lower = text.toLowerCase();
      let start = 0;
      let idx = lower.indexOf(qLower, start);
      if (idx < 0) continue;
      const frag = doc.createDocumentFragment();
      while (idx >= 0) {
        if (idx > start) frag.appendChild(doc.createTextNode(text.slice(start, idx)));
        const mark = doc.createElement('mark');
        mark.className = 'conv-find-mark';
        mark.textContent = text.slice(idx, idx + q.length);
        frag.appendChild(mark);
        start = idx + q.length;
        idx = lower.indexOf(qLower, start);
      }
      if (start < text.length) frag.appendChild(doc.createTextNode(text.slice(start)));
      textNode.parentNode.replaceChild(frag, textNode);
    }
    return root.innerHTML;
  } catch {
    return html;
  }
};

// Per-row component: markdown is parsed lazily and memoized per message.
// Tool returns are rendered as <pre> (raw text), never through marked.
const MessageRow = React.memo(({ m, searchQuery, activeSearchHit, rowRef }) => {
  const isTool = !!m.toolResult;
  const plainHtml = React.useMemo(() => (
    _highlightHtml(_escHtml(m.text || '').replace(/\n/g, '<br/>'), searchQuery)
  ), [m.text, searchQuery]);
  const html = React.useMemo(() => {
    if (isTool || m.role === 'summary') return null;
    const rendered = _renderMd(m.text);
    return _highlightHtml(rendered, searchQuery);
  }, [m.text, isTool, m.role, searchQuery]);

  if (m.role === 'summary') {
    return (
      <div ref={rowRef} className={`msg ${activeSearchHit ? 'search-active' : ''}`} style={{background:'var(--bg-sunk)', padding:12, borderRadius:8, margin:'8px 0', fontStyle:'italic', color:'var(--ink-2)'}}>
        <strong>摘要:</strong> <span dangerouslySetInnerHTML={{__html: plainHtml}}/>
      </div>
    );
  }

  const role = isTool ? 'tool' : m.role;
  const avatar = m.role === 'user' ? (isTool ? '🔧' : 'U') : 'C';
  const name = isTool ? '工具调用' : (m.role === 'user' ? '用户' : 'Codex');
  const ts = m.ts ? new Date(m.ts).toLocaleString() : '';

  return (
    <div ref={rowRef} className={`msg ${role} ${activeSearchHit ? 'search-active' : ''}`} style={isTool ? {opacity: 0.7} : null}>
      <div className="msg-avatar">{avatar}</div>
      <div className="msg-content">
        <div className="msg-author">{name}{m.model ? ` · ${m.model}` : ''}<span className="msg-time">{ts}</span></div>
        {isTool
          ? <pre className="msg-body msg-tool" style={{whiteSpace:'pre-wrap', wordBreak:'break-word', margin:0, fontFamily:'var(--font-mono)', fontSize:12}} dangerouslySetInnerHTML={{__html: plainHtml}}/>
          : <div className="msg-body" dangerouslySetInnerHTML={{__html: html}}/>}
      </div>
    </div>
  );
});

const ConversationView = ({ conv, data, onBack, onDeleted, onTagsChanged, onPickTag }) => {
  const { projects, tags } = data;
  const project = projects.find(p => p.id === conv.project);
  const [messages, setMessages] = React.useState(null);
  const [detail, setDetail] = React.useState(null);
  const [err, setErr] = React.useState('');
  const [skillBusy, setSkillBusy] = React.useState(false);

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

  // Lazy windowing: only `visible` rows are mounted. IntersectionObserver reveals more.
  const MSG_PAGE = 40;
  const [visible, setVisible] = React.useState(MSG_PAGE);
  React.useEffect(() => { setVisible(MSG_PAGE); }, [conv.project, conv.sid]);

  const total = messages ? messages.length : 0;
  const allLoaded = messages && visible >= total;
  const [findOpen, setFindOpen] = React.useState(false);
  const [findQuery, setFindQuery] = React.useState('');
  const [activeHit, setActiveHit] = React.useState(0);
  const findInputRef = React.useRef(null);
  const rowRefs = React.useRef([]);
  const findNeedle = findQuery.trim().toLowerCase();
  const searchHits = React.useMemo(() => {
    if (!messages || !findNeedle) return [];
    const hits = [];
    messages.forEach((m, i) => {
      const hay = `${m.text || ''} ${m.model || ''}`.toLowerCase();
      if (hay.includes(findNeedle)) hits.push(i);
    });
    return hits;
  }, [messages, findNeedle]);
  const activeMsgIndex = searchHits[activeHit];

  const sentinelRef = React.useRef(null);
  React.useEffect(() => {
    if (!messages || allLoaded) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0] && entries[0].isIntersecting) {
        setVisible(v => Math.min(v + MSG_PAGE, total));
      }
    }, { rootMargin: '600px 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, [messages, visible, total, allLoaded]);

  React.useEffect(() => { setActiveHit(0); }, [findNeedle, conv.project, conv.sid]);
  React.useEffect(() => {
    if (activeHit >= searchHits.length) setActiveHit(Math.max(0, searchHits.length - 1));
  }, [activeHit, searchHits.length]);

  const jumpToHit = React.useCallback((hitPos = activeHit) => {
    const msgIndex = searchHits[hitPos];
    if (msgIndex == null) return;
    if (messages && visible <= msgIndex) {
      ReactDOM.flushSync(() => setVisible(Math.min(total, msgIndex + 1)));
    }
    requestAnimationFrame(() => {
      const el = rowRefs.current[msgIndex];
      if (el) el.scrollIntoView({behavior:'smooth', block:'center'});
    });
  }, [activeHit, searchHits, messages, visible, total]);

  React.useEffect(() => {
    if (findOpen && findNeedle && searchHits.length) jumpToHit(activeHit);
  }, [findOpen, findNeedle, searchHits.length, activeHit, jumpToHit]);

  const moveHit = (delta) => {
    if (!searchHits.length) return;
    setActiveHit(i => (i + delta + searchHits.length) % searchHits.length);
  };
  const openFind = React.useCallback(() => {
    setFindOpen(true);
    setTimeout(() => {
      findInputRef.current?.focus();
      findInputRef.current?.select();
    }, 0);
  }, []);

  // Ctrl-F / Cmd-F: open in-page find and expand rows so every match is reachable.
  React.useEffect(() => {
    if (!messages) return;
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
        openFind();
        if (visible < total) setVisible(total);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [messages, visible, total, openFind]);

  const doExport = (fmt) => {
    window.location = `/api/export/${encodeURIComponent(conv.project)}/${encodeURIComponent(conv.sid)}?format=${fmt}`;
  };
  const doGenerateSkill = async () => {
    if (skillBusy) return;
    setSkillBusy(true);
    try {
      const r = await fetch(`/api/generate-skill/${encodeURIComponent(conv.project)}/${encodeURIComponent(conv.sid)}`, {
        method: 'POST'
      });
      const d = await r.json().catch(() => ({}));
      if (await window.handleAuthGate(d)) return;
      if (!r.ok || !d.ok) {
        window.dialog.alert('生成失败: ' + (d.error || `HTTP ${r.status}`), {title:'生成 Skill 失败', danger:true});
        return;
      }
      window.dialog.alert(`已生成 Skill:\n${d.skillFile || d.path}`, {title:'生成 Skill 完成'});
    } catch (e) {
      window.dialog.alert('生成失败: ' + e, {title:'生成 Skill 失败', danger:true});
    } finally {
      setSkillBusy(false);
    }
  };
  const doResume = async () => {
    try {
      const r = await fetch('/api/resume', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: conv.project, sid: conv.sid})});
      const d = await r.json();
      if (await window.handleAuthGate(d)) return;
      if (!d.ok) window.dialog.alert('启动失败: ' + (d.error || '未知'), {title:'启动失败', danger:true});
    } catch (e) { window.dialog.alert('启动失败: ' + e, {title:'启动失败', danger:true}); }
  };
  const doFork = async () => {
    try {
      const r = await fetch('/api/claude', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: conv.project, sid: conv.sid})});
      const d = await r.json();
      if (await window.handleAuthGate(d)) return;
      if (!d.ok) window.dialog.alert('启动失败: ' + (d.error || '未知'), {title:'启动失败', danger:true});
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
  const doScrollBottom = () => {
    // Synchronously flush the visibility expansion so the new rows are in the DOM
    // before we measure / scroll. Avoids the rAF-timing assumption.
    if (messages && visible < total) {
      ReactDOM.flushSync(() => setVisible(total));
    }
    const msgs = document.querySelector('.messages');
    if (msgs && msgs.lastElementChild) {
      msgs.lastElementChild.scrollIntoView({behavior:'smooth', block:'end'});
    } else {
      window.scrollTo({top: document.documentElement.scrollHeight, behavior:'smooth'});
    }
  };
  const doLoadAll = () => setVisible(total);
  const doPin = () => {
    window.APP_STATE_API.togglePin(conv.id);
    conv.pinned = !conv.pinned;
    // light re-render trick
    setErr(x => x);
  };
  const doOpenCwd = async () => {
    try {
      const r = await fetch('/api/open-cwd', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({project: conv.project, sid: conv.sid})});
      const d = await r.json();
      if (!d.ok) window.dialog.alert('打开目录失败: ' + (d.error || '未知'), {title:'打开目录失败', danger:true});
    } catch (e) {
      window.dialog.alert('打开目录失败: ' + e, {title:'打开目录失败', danger:true});
    }
  };
  const removeTag = (tagId) => {
    const next = (conv.tags || []).filter(x => x !== tagId);
    if (onTagsChanged) onTagsChanged(conv.id, next);
    else {
      window.APP_STATE_API.setTags(conv.id, next);
      conv.tags = next;
      setErr(x => x);
    }
  };
  const addTag = async () => {
    const tagId = onPickTag ? await onPickTag(conv.tags || []) : null;
    if (!tagId) return;
    const next = Array.from(new Set([...(conv.tags || []), tagId]));
    if (onTagsChanged) onTagsChanged(conv.id, next);
    else {
      window.APP_STATE_API.setTags(conv.id, next);
      conv.tags = next;
      setErr(x => x);
    }
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

        {findOpen && (
          <div className="detail-find">
            <Icon name="search" size={14}/>
            <input
              ref={findInputRef}
              value={findQuery}
              placeholder="搜索当前会话"
              onChange={(e) => setFindQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); moveHit(e.shiftKey ? -1 : 1); }
                if (e.key === 'Escape') { setFindOpen(false); setFindQuery(''); }
              }}
            />
            <span className="find-count">{findNeedle ? `${searchHits.length ? activeHit + 1 : 0}/${searchHits.length}` : '—'}</span>
            <button title="上一处" disabled={!searchHits.length} onClick={() => moveHit(-1)}>
              <Icon name="chevronDown" size={14} style={{transform:'rotate(180deg)'}}/>
            </button>
            <button title="下一处" disabled={!searchHits.length} onClick={() => moveHit(1)}>
              <Icon name="chevronDown" size={14}/>
            </button>
            <button title="关闭" onClick={() => { setFindOpen(false); setFindQuery(''); }}>
              <Icon name="x" size={14}/>
            </button>
          </div>
        )}

        <div className="messages">
          {err && <div style={{color:'var(--danger, #ef4444)', padding:16}}>加载失败: {err}</div>}
          {!err && messages === null && <div style={{color:'var(--ink-3)', padding:16}}>加载中...</div>}
          {messages && messages.length === 0 && <div style={{color:'var(--ink-3)', padding:16}}>无消息</div>}
          {messages && messages.slice(0, visible).map((m, i) => (
            <MessageRow
              key={i}
              m={m}
              searchQuery={findQuery}
              activeSearchHit={i === activeMsgIndex}
              rowRef={(el) => { rowRefs.current[i] = el; }}
            />
          ))}
          {messages && messages.length > MSG_PAGE && (
            <div
              ref={allLoaded ? null : sentinelRef}
              style={{minHeight: 32, padding:'12px 16px', textAlign:'center', color:'var(--ink-3)', fontSize:12, display:'flex', alignItems:'center', justifyContent:'center', gap:8}}>
              {allLoaded ? (
                <span>已全部加载 · 共 {total} 条</span>
              ) : (
                <>
                  <span>已加载 {visible} / {total} 条 · 滚动加载更多</span>
                  <button className="chip-btn" style={{padding:'2px 8px', fontSize:11}} onClick={doLoadAll}>加载全部</button>
                </>
              )}
            </div>
          )}
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
          <div style={{display:'flex', alignItems:'flex-start', gap:6}}>
            <div style={{flex:1, fontFamily:'var(--font-mono)', fontSize: 11, color: 'var(--ink-2)', background: 'var(--bg-sunk)', padding: 10, borderRadius: 6, wordBreak: 'break-all'}}>
              {conv.cwd || '—'}
            </div>
            {conv.cwd && (
              <button className="cwd-open-icon" title="打开工作目录" onClick={doOpenCwd}>
                <Icon name="folder" size={12}/>
              </button>
            )}
          </div>
        </div>

        <div className="aside-section">
          <div className="aside-label">Session ID</div>
          <div style={{display:'flex', alignItems:'flex-start', gap:6}}>
            <div style={{flex:1, fontFamily:'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-3)', wordBreak: 'break-all'}}>
              codex resume {conv.sid}
            </div>
            <button
              className="chip-btn"
              title="复制命令"
              style={{padding:'4px 6px', flex:'0 0 auto'}}
              onClick={async () => {
                const text = `codex resume ${conv.sid}`;
                try {
                  if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(text);
                  } else {
                    const ta = document.createElement('textarea');
                    ta.value = text; ta.style.position='fixed'; ta.style.opacity='0';
                    document.body.appendChild(ta); ta.select();
                    document.execCommand('copy'); document.body.removeChild(ta);
                  }
                } catch (e) {
                  window.dialog.alert('复制失败: ' + e, {title:'复制失败', danger:true});
                }
              }}>
              <Icon name="copy" size={12}/>
            </button>
          </div>
        </div>

        <div className="aside-section">
          <div className="aside-label">标签</div>
          <div className="aside-tags">
            {conv.tags.map(t => (
              <span key={t} style={{display:'inline-flex',alignItems:'center',gap:4}}>
                <Tag tag={t} tags={tags}/>
                <button style={{color:'var(--ink-4)',padding:'0 2px',fontSize:12}} title="移除" onClick={() => {
                  removeTag(t);
                }}>×</button>
              </span>
            ))}
            {conv.tags.length === 0 && <span style={{color:'var(--ink-4)', fontSize:12}}>未添加标签</span>}
            <button className="aside-add-tag" onClick={async () => {
              await addTag();
            }}>+ 添加</button>
          </div>
        </div>

        <div className="aside-section">
          <div className="aside-label">操作</div>
          <div style={{display: 'flex', flexDirection: 'column', gap: 2}}>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doResume}>
              <Icon name="message" size={14}/> 继续对话
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doFork} title="在新终端打开这条会话">
              <Icon name="export" size={14}/> 发送到 Claude
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doPin}>
              <Icon name="pin" size={14}/> {conv.pinned ? '取消置顶' : '置顶'}
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doGenerateSkill} disabled={skillBusy} title="总结当前对话 SOP 并在桌面生成 Codex Skill">
              <Icon name="sparkles" size={14}/> {skillBusy ? '生成中...' : '生成 Skill'}
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={() => doExport('json')}>
              <Icon name="download" size={14}/> 导出原始 JSONL
            </button>
            <button className="nav-item" style={{padding: '8px 12px', color: 'var(--danger, #ef4444)'}} onClick={doDelete}>
              <Icon name="trash" size={14}/> 永久删除
            </button>
            <button className="nav-item" style={{padding: '8px 12px'}} onClick={doScrollBottom}>
              <Icon name="chevronDown" size={14}/> 滚动到底部
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
};

Object.assign(window, { ConversationView });
