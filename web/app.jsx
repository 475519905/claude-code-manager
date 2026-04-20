// Main app — shell, routing, bulk bar, tweaks
const { useState, useEffect, useMemo } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "density": "cozy",
  "accent": "indigo"
}/*EDITMODE-END*/;

const App = () => {
  const [data, setData] = useState(window.APP_DATA);
  const reloadData = async () => {
    const r = await fetch('/api/sessions');
    const raw = await r.json();
    // Re-run the data.js bootstrap against new raw — we just cheat and reload the page,
    // which is simpler and also refreshes all derived state cleanly.
    window.location.reload();
  };
  const removeFromUi = (convIds) => {
    const ids = new Set(Array.isArray(convIds) ? convIds : [convIds]);
    setData(prev => ({
      ...prev,
      conversations: prev.conversations.filter(c => !ids.has(c.id)),
      projects: prev.projects.map(p => ({
        ...p,
        convs: prev.conversations.filter(c => c.project === p.id && !ids.has(c.id)).length,
      })),
    }));
  };

  // Persistent state
  const [view, setView] = useState(() => localStorage.getItem('cm.view') || 'all');
  const [selectedProject, setSelectedProject] = useState(() => localStorage.getItem('cm.project') || null);
  const [selectedTag, setSelectedTag] = useState(() => localStorage.getItem('cm.tag') || null);
  const [selected, setSelected] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem('cm.selected') || '[]'); } catch { return []; }
  });
  useEffect(() => { sessionStorage.setItem('cm.selected', JSON.stringify(selected)); }, [selected]);
  const [viewMode, setViewMode] = useState(() => localStorage.getItem('cm.viewMode') || 'grid');
  const [filter, setFilter] = useState('all');
  const [sortBy, setSortBy] = useState('updated');
  const [openConvId, setOpenConvId] = useState(() => localStorage.getItem('cm.openConv') || null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [preview, setPreview] = useState(null); // { conv, x, y, msgs, loading }
  const [merging, setMerging] = useState(false);
  const scrollRef = React.useRef(0);

  const mergeTargets = async (targets) => {
    setMerging(true);
    try {
      const r = await fetch('/api/merge', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ targets })});
      const d = await r.json().catch(() => null);
      if (!r.ok || !d || !d.ok) {
        const msg = (d && d.error) || `HTTP ${r.status}`;
        window.dialog.alert('合并失败: ' + String(msg).slice(0, 400), {title:'合并失败', danger:true});
        return;
      }
      window.dialog.alert(`已生成合并摘要 (${(d.bytes/1024).toFixed(1)} KB,${d.count} 条)\n保存到:\n${d.path}`, {title:'合并完成'});
    } catch (e) {
      window.dialog.alert('合并异常: ' + e, {title:'合并异常', danger:true});
    } finally {
      setMerging(false);
    }
  };

  const handlePreview = (conv, pos) => {
    if (!conv) { setPreview(null); return; }
    setPreview({ conv, x: pos.x, y: pos.y, msgs: null, loading: true });
    fetch(`/api/session/${encodeURIComponent(conv.project)}/${encodeURIComponent(conv.sid)}`)
      .then(r => r.json())
      .then(d => setPreview(p => p && p.conv && p.conv.id === conv.id ? { ...p, msgs: d.messages, loading: false } : p))
      .catch(() => setPreview(p => p && p.conv && p.conv.id === conv.id ? { ...p, loading: false } : p));
  };

  // Close preview on window-level mouseup so dragging off the card still releases it
  useEffect(() => {
    const up = () => setPreview(null);
    window.addEventListener('mouseup', up);
    return () => window.removeEventListener('mouseup', up);
  }, []);

  // Poll active-sessions every 20s; update conversations' active flag in place
  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      try {
        const r = await fetch('/api/active');
        const d = await r.json();
        if (stopped) return;
        const activeSet = new Set((d.active || []).map(a => a.project + '|' + a.sid));
        setData(prev => {
          let changed = false;
          const next = prev.conversations.map(c => {
            const isActive = activeSet.has(c.id);
            if (isActive === c.active) return c;
            changed = true;
            return { ...c, active: isActive };
          });
          return changed ? { ...prev, conversations: next } : prev;
        });
      } catch {}
    };
    tick();
    const id = setInterval(tick, 20_000);
    return () => { stopped = true; clearInterval(id); };
  }, []);

  const handleOpenConv = (id) => {
    scrollRef.current = window.scrollY;
    setOpenConvId(id);
    window.scrollTo(0, 0);
  };
  const handleCloseConv = () => {
    setOpenConvId(null);
    requestAnimationFrame(() => window.scrollTo(0, scrollRef.current));
  };

  // Tweaks
  const [theme, setTheme] = useState(TWEAK_DEFAULTS.theme);
  const [density, setDensity] = useState(TWEAK_DEFAULTS.density);
  const [accent, setAccent] = useState(TWEAK_DEFAULTS.accent);
  const [tweaksOpen, setTweaksOpen] = useState(false);

  useEffect(() => localStorage.setItem('cm.view', view), [view]);
  useEffect(() => { if (selectedProject) localStorage.setItem('cm.project', selectedProject); else localStorage.removeItem('cm.project'); }, [selectedProject]);
  useEffect(() => { if (selectedTag) localStorage.setItem('cm.tag', selectedTag); else localStorage.removeItem('cm.tag'); }, [selectedTag]);
  useEffect(() => localStorage.setItem('cm.viewMode', viewMode), [viewMode]);
  useEffect(() => { if (openConvId) localStorage.setItem('cm.openConv', openConvId); else localStorage.removeItem('cm.openConv'); }, [openConvId]);

  // Theme application
  useEffect(() => {
    if (theme === 'light') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // Accent application
  useEffect(() => {
    const map = {
      indigo: { accent: 'oklch(58% 0.12 265)', soft: 'oklch(92% 0.04 265)', ink: 'oklch(42% 0.12 265)' },
      emerald:{ accent: 'oklch(58% 0.12 160)', soft: 'oklch(92% 0.04 160)', ink: 'oklch(42% 0.12 160)' },
      amber:  { accent: 'oklch(62% 0.14 60)',  soft: 'oklch(92% 0.05 60)',  ink: 'oklch(45% 0.12 60)' },
      rose:   { accent: 'oklch(60% 0.14 15)',  soft: 'oklch(92% 0.04 15)',  ink: 'oklch(42% 0.13 15)' },
    };
    const c = map[accent] || map.indigo;
    document.documentElement.style.setProperty('--accent', c.accent);
    document.documentElement.style.setProperty('--accent-soft', c.soft);
    document.documentElement.style.setProperty('--accent-ink', c.ink);
  }, [accent]);

  // Tweaks host messaging
  useEffect(() => {
    const listener = (e) => {
      if (!e.data || typeof e.data !== 'object') return;
      if (e.data.type === '__activate_edit_mode') setTweaksOpen(true);
      if (e.data.type === '__deactivate_edit_mode') setTweaksOpen(false);
    };
    window.addEventListener('message', listener);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', listener);
  }, []);

  const persist = (key, value) => {
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { [key]: value } }, '*');
  };

  // Keyboard shortcut for search
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen(true);
        setOpenConvId(null);
      }
      if (e.key === 'Escape') {
        if (searchOpen) setSearchOpen(false);
        else setSelected([]);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [searchOpen]);

  // Counts
  const counts = useMemo(() => ({
    all: data.conversations.length,
    pinned: data.conversations.filter(c => c.pinned).length,
    recent: 8,
    archive: data.conversations.filter(c => c.tags.includes('archive')).length,
  }), [data]);

  // Determine what's showing
  const openConv = openConvId ? data.conversations.find(c => c.id === openConvId) : null;
  const project = selectedProject ? data.projects.find(p => p.id === selectedProject) : null;

  // Breadcrumbs
  const crumbs = (() => {
    if (openConv) {
      const proj = data.projects.find(p => p.id === openConv.project);
      return [
        { label: proj?.name || '所有对话', onClick: () => { setOpenConvId(null); setSelectedProject(proj?.id || null); setView('project'); } },
        { label: openConv.title, current: true }
      ];
    }
    if (searchOpen) return [{ label: '搜索', current: true }];
    if (view === 'settings') return [{ label: '设置', current: true }];
    if (project) return [
      { label: '项目', onClick: () => { setSelectedProject(null); setView('all'); } },
      { label: project.name, current: true }
    ];
    if (view === 'tag' && selectedTag) {
      const t = data.tags.find(x => x.id === selectedTag);
      return [{ label: '标签', onClick: () => { setSelectedTag(null); setView('all'); } }, { label: `# ${t?.name}`, current: true }];
    }
    const names = { all: '所有对话', pinned: '置顶', recent: '最近', archive: '归档' };
    return [{ label: names[view] || '所有对话', current: true }];
  })();

  return (
    <div className="app">
      <Sidebar
        view={view}
        setView={(v) => { setView(v); setOpenConvId(null); setSearchOpen(false); }}
        selectedProject={selectedProject}
        setSelectedProject={(p) => { setSelectedProject(p); setOpenConvId(null); setSearchOpen(false); }}
        selectedTag={selectedTag}
        setSelectedTag={(t) => { setSelectedTag(t); setOpenConvId(null); setSearchOpen(false); }}
        data={data}
        counts={counts}
      />

      <main className="main">
        <div className="topbar">
          <div className="crumbs">
            {crumbs.map((c, i) => (
              <React.Fragment key={i}>
                {i > 0 && <span className="sep"><Icon name="chevron" size={12}/></span>}
                {c.current ? (
                  <span className="current" style={{maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{c.label}</span>
                ) : (
                  <button onClick={c.onClick} style={{color: 'var(--ink-3)'}}>{c.label}</button>
                )}
              </React.Fragment>
            ))}
          </div>

          <div className="search-wrap">
            <Icon name="search" size={14} style={{position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--ink-3)', pointerEvents: 'none'}}/>
            <input
              className="search-input"
              placeholder="搜索对话…"
              onFocus={() => { setSearchOpen(true); setOpenConvId(null); }}
              value={searchOpen ? searchQuery : ''}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <span className="search-kbd">⌘K</span>
          </div>

          <div className="topbar-actions">
            <button className="icon-btn" title="刷新" onClick={() => window.location.reload()}>
              <Icon name="download" size={15} style={{transform:'rotate(180deg)'}}/>
            </button>
          </div>
        </div>

        {merging && (
          <div className="assistant-status">
            <span className="spinner"/>
            <span>Claude 正在归纳合并,请稍候…</span>
          </div>
        )}

        <div className={selected.length > 0 ? 'bulk-mode' : ''}>
          {searchOpen ? (
            <SearchView
              data={data}
              query={searchQuery}
              setQuery={setSearchQuery}
              onOpen={(id) => { handleOpenConv(id); setSearchOpen(false); }}
            />
          ) : openConv ? (
            <ConversationView
              conv={openConv}
              data={data}
              onBack={handleCloseConv}
              onDeleted={(id) => { removeFromUi(id); setOpenConvId(null); }}
            />
          ) : view === 'settings' ? (
            <SettingsView
              theme={theme}
              setTheme={(t) => { setTheme(t); persist('theme', t); }}
              accent={accent}
              setAccent={setAccent}
              density={density}
              setDensity={setDensity}
            />
          ) : project ? (
            <ProjectView project={project} data={data} onOpen={handleOpenConv}
              selected={selected} setSelected={setSelected} onPreview={handlePreview}/>
          ) : (
            <LibraryView
              data={data}
              onOpen={handleOpenConv}
              onPreview={handlePreview}
              selected={selected}
              setSelected={setSelected}
              viewMode={viewMode}
              setViewMode={setViewMode}
              filter={filter}
              setFilter={setFilter}
              sortBy={sortBy}
              setSortBy={setSortBy}
              scope={{ view, selectedTag }}
            />
          )}
        </div>
      </main>

      {preview && <ConvPreviewPopover preview={preview}/>}

      <DialogHost/>

      {/* Bulk action bar */}
      <div className={`bulk-bar ${selected.length > 0 ? 'show' : ''}`}>
        <span className="count-pill">已选 {selected.length}</span>
        <button onClick={() => {
          for (const id of selected) {
            const c = data.conversations.find(x => x.id === id);
            if (c) window.APP_STATE_API.togglePin(c.id);
          }
          setSelected([]);
          window.location.reload();
        }}><Icon name="pin" size={13}/> 置顶</button>
        <button onClick={async () => {
          for (const id of selected) {
            const c = data.conversations.find(x => x.id === id); if (!c) continue;
            window.open(`/api/export/${encodeURIComponent(c.project)}/${encodeURIComponent(c.sid)}?format=md`);
          }
        }}><Icon name="export" size={13}/> 导出 MD</button>
        <button onClick={async () => {
          const targets = selected.map(id => {
            const c = data.conversations.find(x => x.id === id);
            return c ? { project: c.project, sid: c.sid } : null;
          }).filter(Boolean);
          const ok = await window.dialog.confirm(
            `让 Claude 把这 ${targets.length} 条合并为摘要 Markdown?`,
            {title:'合并摘要', okLabel:'开始合并'});
          if (ok) mergeTargets(targets);
        }}><Icon name="sparkles" size={13}/> 合并摘要</button>
        <button className="danger" onClick={async () => {
          const ok = await window.dialog.confirm(
            `确认删除选中的 ${selected.length} 条对话?\n此操作不可恢复。`,
            {title:'删除对话', danger:true});
          if (!ok) return;
          for (const id of selected) {
            const c = data.conversations.find(x => x.id === id); if (!c) continue;
            await fetch('/api/delete', {method:'POST', headers:{'Content-Type':'application/json'},
              body: JSON.stringify({project: c.project, sid: c.sid})});
          }
          removeFromUi(selected);
          setSelected([]);
        }}><Icon name="trash" size={13}/> 删除</button>
        <button onClick={() => setSelected([])} style={{marginLeft: 4, padding: 6}} title="取消">
          <Icon name="x" size={14}/>
        </button>
      </div>

      {/* Tweaks panel */}
      <div className={`tweaks-panel ${tweaksOpen ? 'open' : ''}`}>
        <div className="tweaks-head">
          <span className="title">Tweaks</span>
          <button onClick={() => setTweaksOpen(false)} style={{color: 'var(--ink-3)'}}>
            <Icon name="x" size={12}/>
          </button>
        </div>
        <div className="tweak-row">
          <label>主题</label>
          <div className="seg">
            {['light', 'dark', 'sepia'].map(t => (
              <button
                key={t}
                className={theme === t ? 'active' : ''}
                onClick={() => { setTheme(t); persist('theme', t); }}
              >{t === 'light' ? '浅色' : t === 'dark' ? '深色' : '棕褐'}</button>
            ))}
          </div>
        </div>
        <div className="tweak-row">
          <label>强调色</label>
          <div style={{display: 'flex', gap: 8}}>
            {[
              { id: 'indigo', c: 'oklch(58% 0.12 265)' },
              { id: 'emerald', c: 'oklch(58% 0.12 160)' },
              { id: 'amber', c: 'oklch(62% 0.14 60)' },
              { id: 'rose', c: 'oklch(60% 0.14 15)' },
            ].map(a => (
              <button
                key={a.id}
                onClick={() => { setAccent(a.id); persist('accent', a.id); }}
                style={{
                  width: 28, height: 28, borderRadius: 999, background: a.c,
                  boxShadow: accent === a.id ? `0 0 0 2px var(--bg-elevated), 0 0 0 4px ${a.c}` : 'none',
                  transition: 'box-shadow 0.15s'
                }}
              />
            ))}
          </div>
        </div>
        <div className="tweak-row">
          <label>视图</label>
          <div className="seg">
            <button className={viewMode === 'grid' ? 'active' : ''} onClick={() => setViewMode('grid')}>网格</button>
            <button className={viewMode === 'list' ? 'active' : ''} onClick={() => setViewMode('list')}>列表</button>
          </div>
        </div>
      </div>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
