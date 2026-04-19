// Project detail, search, and settings views

const ProjectView = ({ project, data, onOpen, selected = [], setSelected = () => {}, onPreview }) => {
  const { conversations, projects, tags } = data;
  const convs = conversations.filter(c => c.project === project.id);
  const totalTokens = convs.reduce((s, c) => s + c.tokens, 0);
  const [tab, setTab] = React.useState('conversations');
  const toggleSelect = (id) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  const files = [
    { name: '产品研究访谈_2026Q1.pdf', meta: 'PDF · 2.4 MB · 上传于 4 月 12 日', ext: 'PDF' },
    { name: '竞品对比.numbers',       meta: 'Numbers · 840 KB · 上传于 4 月 10 日', ext: 'NUM' },
    { name: '用户画像 v3.md',          meta: 'Markdown · 18 KB · 上传于 4 月 09 日', ext: 'MD' },
    { name: '产品愿景.txt',             meta: 'Text · 4 KB · 永久上下文',           ext: 'TXT' },
  ];

  return (
    <div className="page">
      <div className="project-hero">
        <div className="project-badge" style={{background: project.color}}>{project.emoji}</div>
        <div className="project-info">
          <h2>{project.name}</h2>
          <p>{project.desc}</p>
        </div>
        <div className="project-stats">
          <div className="project-stat">
            <div className="num">{project.convs}</div>
            <div className="label">对话</div>
          </div>
          <div className="project-stat">
            <div className="num">{project.files}</div>
            <div className="label">上下文文件</div>
          </div>
          <div className="project-stat">
            <div className="num">{(totalTokens / 1000).toFixed(0)}k</div>
            <div className="label">Tokens</div>
          </div>
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === 'conversations' ? 'active' : ''}`} onClick={() => setTab('conversations')}>
          对话 <span className="count">{convs.length}</span>
        </button>
        <button className={`tab ${tab === 'info' ? 'active' : ''}`} onClick={() => setTab('info')}>
          项目信息
        </button>
      </div>

      {tab === 'conversations' && (
        <div className="project-layout">
          <div>
            <div className="card-grid" style={{gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))'}}>
              {convs.map(c => (
                <ConvCard key={c.id} conv={c} projects={projects} tags={tags}
                  selected={selected.includes(c.id)}
                  bulkMode={selected.length > 0}
                  onToggleSelect={() => toggleSelect(c.id)}
                  onOpen={() => onOpen(c.id)}
                  onPreview={onPreview}/>
              ))}
            </div>
          </div>
          <aside style={{display: 'flex', flexDirection: 'column', gap: 24}}>
            <div>
              <div className="aside-label">本项目常用标签</div>
              <div style={{display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 10}}>
                {tags.slice(0, 4).map(t => <Tag key={t.id} tag={t.id} tags={tags}/>)}
              </div>
            </div>
            <div>
              <div className="aside-label">活跃时段</div>
              <div style={{marginTop: 10, padding: 14, background: 'var(--bg-sunk)', borderRadius: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)'}}>
                <div style={{display: 'flex', alignItems: 'flex-end', gap: 3, height: 60, marginBottom: 8}}>
                  {[3, 5, 8, 12, 6, 14, 9, 11, 15, 18, 13, 10, 7, 4].map((h, i) => (
                    <div key={i} style={{flex: 1, height: `${(h / 18) * 100}%`, background: 'var(--accent)', opacity: 0.3 + (h / 18) * 0.7, borderRadius: '2px 2px 0 0'}}/>
                  ))}
                </div>
                <div style={{display: 'flex', justifyContent: 'space-between'}}>
                  <span>2 周前</span>
                  <span>今天</span>
                </div>
              </div>
            </div>
          </aside>
        </div>
      )}

      {tab === 'info' && (
        <div style={{maxWidth: 640}}>
          <div className="settings-group">
            <div className="settings-group-head">
              <h3>项目路径</h3>
              <p>项目由 Claude Code 根据工作目录自动生成。</p>
            </div>
            <div className="setting-row">
              <div className="setting-label"><div className="name">工作目录</div></div>
              <div style={{fontFamily:'var(--font-mono)', fontSize:12, wordBreak:'break-all', padding:'6px 10px', background:'var(--bg-sunk)', borderRadius:6}}>{project.cwd || '—'}</div>
            </div>
            <div className="setting-row">
              <div className="setting-label"><div className="name">编码目录名</div></div>
              <div style={{fontFamily:'var(--font-mono)', fontSize:12, wordBreak:'break-all', padding:'6px 10px', background:'var(--bg-sunk)', borderRadius:6}}>{project.rawName}</div>
            </div>
            <div className="setting-row">
              <div className="setting-label"><div className="name">会话总数</div></div>
              <div style={{fontFamily:'var(--font-mono)', fontSize:13}}>{project.convs}</div>
            </div>
            <div className="setting-row">
              <div className="setting-label"><div className="name">Token 估算</div></div>
              <div style={{fontFamily:'var(--font-mono)', fontSize:13}}>{(totalTokens / 1000).toFixed(1)}k</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const SearchView = ({ data, query, setQuery, onOpen }) => {
  const { conversations, projects, tags } = data;
  const q = query.trim();
  const ql = q.toLowerCase();
  const [deepHits, setDeepHits] = React.useState({});

  React.useEffect(() => {
    if (!q) { setDeepHits({}); return; }
    const t = setTimeout(() => {
      fetch('/api/search?q=' + encodeURIComponent(q))
        .then(r => r.json())
        .then(d => {
          const by = {};
          for (const r of d.results) by[r.project + '|' + r.sid] = r.hits;
          setDeepHits(by);
        }).catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const results = q
    ? conversations.filter(c =>
        c.title.toLowerCase().includes(ql) ||
        c.snippet.toLowerCase().includes(ql) ||
        deepHits[c.id]
      ).sort((a,b) => b.updatedSort - a.updatedSort)
    : [];

  const highlight = (text) => {
    if (!q) return text;
    const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    const parts = text.split(re);
    return parts.map((p, i) =>
      p.toLowerCase() === ql ? <mark key={i}>{p}</mark> : <React.Fragment key={i}>{p}</React.Fragment>
    );
  };

  return (
    <div className="page">
      <div className="search-big">
        <Icon name="search" size={18}/>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索对话标题或内容…"
          autoFocus
        />
        {query && <button className="clear-btn" onClick={() => setQuery('')}>清除</button>}
      </div>

      <div className="filter-row">
        <button className="chip-btn active">全部</button>
        <button className="chip-btn"><Icon name="folder" size={11}/> 按项目</button>
        <button className="chip-btn"><Icon name="tag" size={11}/> 按标签</button>
        <button className="chip-btn"><Icon name="calendar" size={11}/> 按时间</button>
        <button className="chip-btn"><Icon name="filter" size={11}/> 高级筛选</button>
      </div>

      {q && (
        <div className="search-results-header">
          <span>找到 <span style={{color: 'var(--ink)'}}>{results.length}</span> 条结果 · 关键词 "{query}"</span>
          <span>搜索范围: 标题 + 内容</span>
        </div>
      )}

      {!q && (
        <div style={{padding: '48px 0', textAlign: 'center'}}>
          <div style={{fontFamily: 'var(--font-serif)', fontSize: 17, color: 'var(--ink-2)', marginBottom: 6}}>开始搜索</div>
          <div style={{fontSize: 12.5, color: 'var(--ink-3)'}}>在所有对话中按标题、内容、标签或项目进行搜索</div>
          <div style={{marginTop: 28, display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap'}}>
            {['claude', 'python', 'error', 'git', '代码'].map(q2 => (
              <button key={q2} className="chip-btn" onClick={() => setQuery(q2)}>
                <Icon name="search" size={10}/> {q2}
              </button>
            ))}
          </div>
        </div>
      )}

      {results.map(c => {
        const project = projects.find(p => p.id === c.project);
        return (
          <div key={c.id} className="search-result" onClick={() => onOpen(c.id)}>
            <div className="sr-top">
              <ProjectDot project={c.project} projects={projects} size={6}/>
              <span style={{color: 'var(--ink-2)'}}>{project?.name}</span>
              <span>·</span>
              <span>{c.updated}</span>
              <span>·</span>
              <span>{c.messages} 条消息</span>
            </div>
            <h3 className="sr-title">{highlight(c.title)}</h3>
            <div className="sr-preview">{highlight(c.snippet)}</div>
            {deepHits[c.id] && deepHits[c.id].length > 0 && (
              <div style={{marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4}}>
                {deepHits[c.id].slice(0, 3).map((h, i) => (
                  <div key={i} style={{fontSize: 12, color: 'var(--ink-3)', background: 'var(--bg-sunk)', padding: '4px 8px', borderRadius: 4}}>
                    <span style={{color: 'var(--ink-4)', marginRight: 6}}>[{h.role}]</span>
                    {highlight(h.snippet)}
                  </div>
                ))}
              </div>
            )}
            <div style={{display: 'flex', gap: 4, marginTop: 8}}>
              {c.tags.map(t => <Tag key={t} tag={t} tags={tags}/>)}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const SettingsView = ({ theme, setTheme, accent, setAccent, density, setDensity }) => {
  const [section, setSection] = React.useState('appearance');
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">设置</h1>
          <p className="page-sub">管理你的偏好、导出与账户设置</p>
        </div>
      </div>

      <div className="settings-layout">
        <nav className="settings-nav">
          {[
            { id: 'appearance', label: '外观' },
            { id: 'general',    label: '通用' },
            { id: 'shortcuts',  label: '快捷键' },
            { id: 'export',     label: '导出与备份' },
            { id: 'account',    label: '账户' },
          ].map(s => (
            <div
              key={s.id}
              className={`nav-item ${section === s.id ? 'active' : ''}`}
              onClick={() => setSection(s.id)}
            >
              {s.label}
            </div>
          ))}
        </nav>

        <div>
          {section === 'appearance' && (
            <>
              <div className="settings-group">
                <div className="settings-group-head">
                  <h3>主题</h3>
                  <p>选择应用的颜色模式。</p>
                </div>
                <div className="setting-row">
                  <div className="setting-label">
                    <div className="name">颜色模式</div>
                    <div className="desc">你可以随时切换 — 当前为 {theme === 'light' ? '浅色' : theme === 'dark' ? '深色' : '棕褐'}</div>
                  </div>
                  <div style={{display: 'flex', gap: 14, alignItems: 'flex-end'}}>
                    {[
                      { id: 'light', bar: '#f8f7f4', body: '#1a1a1a', label: '浅色' },
                      { id: 'dark',  bar: '#1d2132', body: '#e8e8ea', label: '深色' },
                      { id: 'sepia', bar: '#e9dfc7', body: '#4a3826', label: '棕褐' },
                    ].map(sw => (
                      <div key={sw.id} style={{textAlign: 'center'}}>
                        <div
                          className={`theme-swatch ${theme === sw.id ? 'active' : ''}`}
                          style={{color: sw.body}}
                          onClick={() => setTheme(sw.id)}
                        >
                          <div className="bar" style={{background: sw.bar}}/>
                          <div className="body" style={{background: sw.bar, filter: 'brightness(1.02)'}}/>
                        </div>
                        <div style={{fontSize: 11, color: 'var(--ink-3)', marginTop: 6}}>{sw.label}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="setting-row">
                  <div className="setting-label">
                    <div className="name">跟随系统</div>
                    <div className="desc">根据系统的浅色/深色模式自动切换</div>
                  </div>
                  <div className="toggle"/>
                </div>
              </div>

              <div className="settings-group">
                <div className="settings-group-head">
                  <h3>字体与排版</h3>
                  <p>界面与阅读体验的微调。</p>
                </div>
                <div className="setting-row">
                  <div className="setting-label"><div className="name">界面字体</div></div>
                  <select className="text-input" defaultValue="inter">
                    <option value="inter">Inter + PingFang SC</option>
                    <option value="system">系统默认</option>
                    <option value="serif">Source Serif 4 + 宋体</option>
                  </select>
                </div>
                <div className="setting-row">
                  <div className="setting-label"><div className="name">对话阅读字号</div></div>
                  <select className="text-input" defaultValue="m" style={{width: 120}}>
                    <option value="s">小</option>
                    <option value="m">中 (推荐)</option>
                    <option value="l">大</option>
                  </select>
                </div>
              </div>
            </>
          )}

          {section === 'general' && (
            <div className="settings-group">
              <div className="settings-group-head">
                <h3>通用</h3>
              </div>
              {[
                { name: '自动归档 30 天未活跃的对话', desc: '不会删除,可在归档中找到', on: true },
                { name: '新对话默认置顶',              desc: '创建后固定在列表顶部',       on: false },
                { name: '在侧边栏显示 token 用量',   desc: '个人资料下方显示本月消耗',   on: true },
                { name: '发送使用数据以改进产品',     desc: '匿名、可随时关闭',           on: false },
              ].map((r, i) => (
                <div key={i} className="setting-row">
                  <div className="setting-label">
                    <div className="name">{r.name}</div>
                    <div className="desc">{r.desc}</div>
                  </div>
                  <div className={`toggle ${r.on ? 'on' : ''}`}/>
                </div>
              ))}
            </div>
          )}

          {section === 'shortcuts' && (
            <div className="settings-group">
              <div className="settings-group-head">
                <h3>快捷键</h3>
                <p>键盘优先操作,提升整理效率。</p>
              </div>
              {[
                ['新对话', '⌘ N'],
                ['搜索', '⌘ K'],
                ['打开命令面板', '⌘ ⇧ P'],
                ['切换侧边栏', '⌘ \\'],
                ['置顶当前对话', '⌘ D'],
                ['归档当前对话', 'E'],
                ['移动到项目', '⌘ ⇧ M'],
                ['导出为 Markdown', '⌘ E'],
              ].map(([name, key]) => (
                <div key={name} className="setting-row">
                  <div className="setting-label"><div className="name">{name}</div></div>
                  <kbd style={{fontFamily: 'var(--font-mono)', fontSize: 11, padding: '3px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg-sunk)', color: 'var(--ink-2)'}}>{key}</kbd>
                </div>
              ))}
            </div>
          )}

          {section === 'export' && (
            <div className="settings-group">
              <div className="settings-group-head">
                <h3>导出与备份</h3>
                <p>以多种格式导出你的对话,便于归档或分享。</p>
              </div>
              {[
                { name: '导出全部对话为 Markdown', desc: '每个对话一个 .md 文件,打包为 zip' },
                { name: '导出为 JSON',              desc: '完整数据,包含元信息与标签,便于迁移' },
                { name: '导出为 PDF',               desc: '适合打印或长期存档' },
                { name: '定期自动备份',              desc: '每周自动打包到你的 iCloud Drive' },
              ].map((r, i) => (
                <div key={i} className="setting-row">
                  <div className="setting-label">
                    <div className="name">{r.name}</div>
                    <div className="desc">{r.desc}</div>
                  </div>
                  <button className="chip-btn">{i === 3 ? '开启' : '导出'}</button>
                </div>
              ))}
            </div>
          )}

          {section === 'account' && (
            <div className="settings-group">
              <div className="settings-group-head">
                <h3>账户</h3>
              </div>
              <div className="setting-row">
                <div className="setting-label" style={{display: 'flex', alignItems: 'center', gap: 14}}>
                  <div className="avatar" style={{width: 44, height: 44, fontSize: 15}}>林</div>
                  <div>
                    <div className="name">林知远</div>
                    <div className="desc" style={{fontFamily: 'var(--font-mono)'}}>zhihyuan.lin@mail.com</div>
                  </div>
                </div>
                <button className="chip-btn">编辑</button>
              </div>
              <div className="setting-row">
                <div className="setting-label">
                  <div className="name">订阅方案</div>
                  <div className="desc">Pro · 下次续费 2026-05-12</div>
                </div>
                <button className="chip-btn">管理订阅</button>
              </div>
              <div className="setting-row">
                <div className="setting-label">
                  <div className="name" style={{color: 'oklch(55% 0.14 25)'}}>退出登录</div>
                </div>
                <button className="chip-btn">退出</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { ProjectView, SearchView, SettingsView });
