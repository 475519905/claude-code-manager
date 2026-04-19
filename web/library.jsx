// Library / List view — main screen
const LibraryView = ({ data, onOpen, onPreview, selected, setSelected, viewMode, setViewMode, filter, setFilter, sortBy, setSortBy, scope }) => {
  const { conversations, projects, tags } = data;

  // Scope filtering
  let filtered = conversations;
  if (scope.view === 'pinned') filtered = filtered.filter(c => c.pinned);
  else if (scope.view === 'archive') filtered = filtered.filter(c => c.tags.includes('archive'));
  else if (scope.view === 'recent') filtered = filtered.slice().sort((a,b) => b.updatedSort - a.updatedSort).slice(0, 8);
  else if (scope.view === 'tag' && scope.selectedTag) filtered = filtered.filter(c => c.tags.includes(scope.selectedTag));

  // Filter chips
  if (filter === 'pinned') filtered = filtered.filter(c => c.pinned);
  else if (filter && filter.startsWith('project:')) {
    const pid = filter.slice(8);
    filtered = filtered.filter(c => c.project === pid);
  }

  // Sort
  if (sortBy === 'updated') filtered = filtered.slice().sort((a,b) => b.updatedSort - a.updatedSort);
  else if (sortBy === 'tokens') filtered = filtered.slice().sort((a,b) => b.tokens - a.tokens);
  else if (sortBy === 'messages') filtered = filtered.slice().sort((a,b) => b.messages - a.messages);

  const toggleSelect = (id) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const titleMap = {
    all:     { title: '所有对话',  sub: '浏览并整理你与 Claude 的全部对话' },
    pinned:  { title: '置顶',     sub: '固定在顶部的重要对话' },
    recent:  { title: '最近',     sub: '按最近活跃时间排序' },
    archive: { title: '归档',     sub: '已归档的对话 — 不显示在主列表中' },
    tag:     { title: scope.selectedTag ? `# ${tags.find(t => t.id === scope.selectedTag)?.name}` : '', sub: '带有此标签的对话' },
  };
  const header = titleMap[scope.view] || titleMap.all;

  const showUsage = scope.view === 'all' && filter === 'all';

  return (
    <div className="page">
      {showUsage && <UsagePanel/>}
      <div className="page-header">
        <div>
          <h1 className="page-title">{header.title}</h1>
          <p className="page-sub">
            <span className="mono">{filtered.length}</span> 条对话
            {scope.view === 'all' && <> · 共 <span className="mono">{conversations.reduce((s,c) => s + c.tokens, 0).toLocaleString()}</span> tokens</>}
          </p>
        </div>
      </div>

      <div className="toolbar">
        <button
          className={`chip-btn ${filter === 'all' ? 'active' : ''}`}
          onClick={() => setFilter('all')}
        >全部 <span className="count">{conversations.length}</span></button>
        <button
          className={`chip-btn ${filter === 'pinned' ? 'active' : ''}`}
          onClick={() => setFilter('pinned')}
        >
          <Icon name="pin" size={11}/> 置顶
        </button>
        {projects.slice(0, 4).map(p => (
          <button
            key={p.id}
            className={`chip-btn ${filter === `project:${p.id}` ? 'active' : ''}`}
            onClick={() => setFilter(`project:${p.id}`)}
          >
            <span className="project-dot" style={{background: p.color, width: 8, height: 8, borderRadius: 2, display: 'inline-block'}}/>
            {p.name}
          </button>
        ))}

        <div className="toolbar-spacer"/>

        {(() => {
          const visible = filtered.map(c => c.id);
          const allChecked = visible.length > 0 && visible.every(id => selected.includes(id));
          return (
            <button className="chip-btn" onClick={() => {
              if (allChecked) setSelected(prev => prev.filter(id => !visible.includes(id)));
              else setSelected(prev => Array.from(new Set([...prev, ...visible])));
            }} title={allChecked ? '取消全选' : '选择当前视图所有'}>
              <Icon name="check" size={11}/> {allChecked ? '取消全选' : `全选 (${visible.length})`}
            </button>
          );
        })()}

        <div className="seg" style={{background: 'var(--bg-sunk)', borderRadius: 'var(--radius-sm)', padding: 2, display: 'flex', fontSize: 12}}>
          <button
            onClick={() => setSortBy('updated')}
            className={sortBy === 'updated' ? 'active' : ''}
            style={{padding: '4px 10px', borderRadius: 4, color: sortBy === 'updated' ? 'var(--ink)' : 'var(--ink-3)', background: sortBy === 'updated' ? 'var(--bg-elevated)' : 'transparent', fontWeight: sortBy === 'updated' ? 500 : 400}}
          >最近</button>
          <button
            onClick={() => setSortBy('tokens')}
            className={sortBy === 'tokens' ? 'active' : ''}
            style={{padding: '4px 10px', borderRadius: 4, color: sortBy === 'tokens' ? 'var(--ink)' : 'var(--ink-3)', background: sortBy === 'tokens' ? 'var(--bg-elevated)' : 'transparent', fontWeight: sortBy === 'tokens' ? 500 : 400}}
          >Token</button>
          <button
            onClick={() => setSortBy('messages')}
            className={sortBy === 'messages' ? 'active' : ''}
            style={{padding: '4px 10px', borderRadius: 4, color: sortBy === 'messages' ? 'var(--ink)' : 'var(--ink-3)', background: sortBy === 'messages' ? 'var(--bg-elevated)' : 'transparent', fontWeight: sortBy === 'messages' ? 500 : 400}}
          >消息数</button>
        </div>

        <div className="view-toggle">
          <button className={viewMode === 'grid' ? 'active' : ''} onClick={() => setViewMode('grid')}>
            <Icon name="grid" size={12}/>
          </button>
          <button className={viewMode === 'list' ? 'active' : ''} onClick={() => setViewMode('list')}>
            <Icon name="list" size={13}/>
          </button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <div>这里还没有对话</div>
          <div className="hint">试试调整筛选条件</div>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="card-grid">
          {filtered.map(c => (
            <ConvCard
              key={c.id}
              conv={c}
              projects={projects}
              tags={tags}
              selected={selected.includes(c.id)}
              bulkMode={selected.length > 0}
              onToggleSelect={() => toggleSelect(c.id)}
              onOpen={() => onOpen(c.id)}
              onPreview={onPreview}
            />
          ))}
        </div>
      ) : (
        <div className="conv-list">
          <div className="conv-row header">
            <div></div>
            <div>对话</div>
            <div>项目</div>
            <div>标签</div>
            <div className="num">消息</div>
            <div className="num">更新</div>
          </div>
          {filtered.map(c => (
            <div
              key={c.id}
              className={`conv-row ${selected.includes(c.id) ? 'selected' : ''}`}
              onClick={() => onOpen(c.id)}
            >
              <div className="check" onClick={(e) => { e.stopPropagation(); toggleSelect(c.id); }}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
              </div>
              <div className="title-cell">
                <div className="row-title">
                  {c.pinned && <Icon name="pin" size={10} style={{color: 'var(--accent)', marginRight: 6, verticalAlign: -1}}/>}
                  {c.title}
                </div>
                <div className="row-sub">{c.snippet}</div>
              </div>
              <div className="project-cell">
                <ProjectDot project={c.project} projects={projects}/>
                {projects.find(p => p.id === c.project)?.name}
              </div>
              <div className="tag-cell">
                {c.tags.slice(0, 2).map(t => <Tag key={t} tag={t} tags={tags}/>)}
              </div>
              <div className="num">{c.messages}</div>
              <div className="num">{c.updated}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const ConvCard = ({ conv, projects, tags, selected, bulkMode, onToggleSelect, onOpen, onPreview }) => {
  const project = projects.find(p => p.id === conv.project);
  const timerRef = React.useRef(null);
  const longPressedRef = React.useRef(false);

  const clearTimer = () => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
  };
  const startPress = (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('.conv-checkbox')) return;
    longPressedRef.current = false;
    const x = e.clientX, y = e.clientY;
    timerRef.current = setTimeout(() => {
      longPressedRef.current = true;
      if (onPreview) onPreview(conv, {x, y});
    }, 380);
  };
  const endPress = () => {
    clearTimer();
    if (longPressedRef.current) {
      if (onPreview) onPreview(null);
    }
  };

  return (
    <div
      className={`conv-card ${selected ? 'selected' : ''}`}
      onMouseDown={startPress}
      onMouseUp={endPress}
      onMouseLeave={endPress}
      onClick={(e) => {
        if (e.target.closest('.conv-checkbox')) return;
        if (longPressedRef.current) { longPressedRef.current = false; e.preventDefault(); return; }
        if (e.metaKey || e.ctrlKey || e.shiftKey) { onToggleSelect(); return; }
        onOpen();
      }}
    >
      <div className="conv-checkbox"
        role="checkbox"
        aria-checked={selected}
        title="选择"
        onMouseDownCapture={(e) => {
          e.stopPropagation();
          e.preventDefault();
          onToggleSelect();
        }}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); }}
      >
        {selected && <Icon name="check" size={12} stroke={3}/>}
      </div>

      <div className="conv-meta-row">
        <span className="conv-project">
          <ProjectDot project={conv.project} projects={projects} size={6}/>
          {project?.name}
        </span>
        <span className="dot-sep">·</span>
        <span>{conv.updated}</span>
        {conv.pinned && <span className="pinned"><Icon name="pin" size={10}/></span>}
      </div>

      <h3 className="conv-title">{conv.title}</h3>

      <p className="conv-snippet">{conv.snippet}</p>

      <div className="conv-footer">
        <div className="conv-tags">
          {conv.tags.slice(0, 3).map(t => <Tag key={t} tag={t} tags={tags}/>)}
        </div>
        <div className="conv-stats">
          <Sparkline data={conv.sparkline} width={40} height={14}/>
          <span className="tokens">{(conv.tokens / 1000).toFixed(1)}k</span>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { LibraryView, ConvCard });
