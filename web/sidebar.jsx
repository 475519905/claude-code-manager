// Sidebar component
const Sidebar = ({ view, setView, selectedProject, setSelectedProject, selectedTag, setSelectedTag, data, counts }) => {
  const [account, setAccount] = React.useState(null);
  const profile = { name: '林知远', email: 'zhihyuan.lin@mail.com' };
  React.useEffect(() => {
    fetch('/api/account').then(r => r.json()).then(setAccount).catch(() => {});
  }, []);
  const navItems = [
    { id: 'all',     label: '所有对话', icon: 'message', count: counts.all },
    { id: 'pinned',  label: '置顶',     icon: 'pin',     count: counts.pinned },
    { id: 'recent',  label: '最近',     icon: 'clock',   count: counts.recent },
    { id: 'archive', label: '归档',     icon: 'archive', count: counts.archive },
  ];

  const go = (v, extra = {}) => {
    setView(v);
    if (!extra.keepProject) setSelectedProject(null);
    if (!extra.keepTag) setSelectedTag(null);
    Object.assign(window.__appState || {}, extra);
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <img className="brand-mark" src="/icon.png" alt="" draggable="false"/>
        <div className="brand-name"><span className="zh">Claude Manager</span></div>
      </div>

      <button className="new-chat-btn" onClick={() => window.location.reload()} title="重新扫描 ~/.claude/projects/">
        <Icon name="plus" size={14}/>
        <span>刷新数据</span>
        <kbd>⌘R</kbd>
      </button>

      <div className="side-section">
        {navItems.map(item => (
          <div
            key={item.id}
            className={`nav-item ${view === item.id && !selectedProject && !selectedTag ? 'active' : ''}`}
            onClick={() => { setView(item.id); setSelectedProject(null); setSelectedTag(null); }}
          >
            <Icon name={item.icon} size={14} style={{strokeWidth: 1.75}}/>
            <span>{item.label}</span>
            <span className="count">{item.count}</span>
          </div>
        ))}
      </div>

      <div className="side-section">
        <div className="side-label">
          <span>项目</span>
        </div>
        {data.projects.map(p => (
          <div
            key={p.id}
            className={`nav-item ${selectedProject === p.id ? 'active' : ''}`}
            onClick={() => { setView('project'); setSelectedProject(p.id); setSelectedTag(null); }}
          >
            <span className="project-dot" style={{background: p.color}}/>
            <span>{p.name}</span>
            <span className="count">{p.convs}</span>
          </div>
        ))}
      </div>

      <div className="side-section">
        <div className="side-label">
          <span>标签</span>
          <button className="add" title="新建标签" onClick={() => {
            const name = prompt('标签名称?');
            if (name && name.trim()) { window.APP_STATE_API.addTag(name.trim()); window.location.reload(); }
          }}><Icon name="plus" size={12}/></button>
        </div>
        {data.tags.map(t => (
          <div
            key={t.id}
            className={`nav-item ${selectedTag === t.id ? 'active' : ''}`}
            onClick={() => { setView('tag'); setSelectedTag(t.id); setSelectedProject(null); }}
          >
            <span className="tag-dot" style={{background: `var(--tag-${t.color}-fg)`}}/>
            <span>{t.name}</span>
            <span className="count">{t.count}</span>
          </div>
        ))}
      </div>

      <div className="side-section">
        <div
          className={`nav-item ${view === 'settings' ? 'active' : ''}`}
          onClick={() => { setView('settings'); setSelectedProject(null); setSelectedTag(null); }}
        >
          <Icon name="settings" size={14}/>
          <span>设置</span>
        </div>
      </div>

      <div className="sidebar-footer">
        <div className="avatar">{profile.name.charAt(0)}</div>
        <div className="user-meta">
          <div className="user-name" title={profile.email}>{profile.name}</div>
          <div className="user-plan">
            {account && account.ok
              ? `${account.plan}${account.tier ? ' · ' + account.tier : ''}`
              : `${data.conversations.length} 会话`}
          </div>
          <div className="user-email" title={profile.email}>{profile.email}</div>
        </div>
      </div>
    </aside>
  );
};

Object.assign(window, { Sidebar });
