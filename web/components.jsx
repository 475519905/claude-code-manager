// Shared icon + small UI components (JSX)
// Exposed on window for other Babel scripts.

const Icon = ({ name, size = 16, stroke = 1.75, style }) => {
  const paths = {
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    folder: <><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></>,
    tag: <><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><path d="M7 7h.01"/></>,
    inbox: <><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></>,
    star: <><path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></>,
    archive: <><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></>,
    trash: <><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></>,
    settings: <><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></>,
    check: <><path d="M20 6 9 17l-5-5"/></>,
    chevron: <><path d="m9 18 6-6-6-6"/></>,
    chevronDown: <><path d="m6 9 6 6 6-6"/></>,
    grid: <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></>,
    list: <><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></>,
    filter: <><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></>,
    sort: <><path d="M3 6h13M3 12h9M3 18h5"/><path d="m17 8 4-4 4 4" transform="translate(-4 4)"/></>,
    download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></>,
    move: <><polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></>,
    x: <><path d="M18 6 6 18M6 6l12 12"/></>,
    more: <><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></>,
    pin: <><path d="M12 2 9 7H5l3.5 4.5L7 17l5-3 5 3-1.5-5.5L19 7h-4z" fill="currentColor" stroke="none"/></>,
    calendar: <><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></>,
    clock: <><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></>,
    chart: <><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></>,
    message: <><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></>,
    users: <><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></>,
    bell: <><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></>,
    sparkles: <><path d="M12 3 14 9 20 11 14 13 12 19 10 13 4 11 10 9Z"/></>,
    eye: <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>,
    back: <><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></>,
    export: <><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></>,
    copy: <><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></>,
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={style}>
      {paths[name] || null}
    </svg>
  );
};

const Sparkline = ({ data, width = 56, height = 16, color }) => {
  if (!data || !data.length) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const step = width / (data.length - 1);
  const points = data.map((v, i) => {
    const x = i * step;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const last = data[data.length - 1];
  const lastX = (data.length - 1) * step;
  const lastY = height - ((last - min) / range) * (height - 2) - 1;
  return (
    <svg width={width} height={height} style={{display: 'block'}}>
      <polyline points={points} fill="none" stroke={color || 'var(--ink-4)'} strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx={lastX} cy={lastY} r="1.5" fill={color || 'var(--accent)'}/>
    </svg>
  );
};

const Tag = ({ tag, tags }) => {
  const t = tags.find(x => x.id === tag);
  if (!t) return null;
  return (
    <span className="tag" style={{background: `var(--tag-${t.color}-bg)`, color: `var(--tag-${t.color}-fg)`}}>
      {t.name}
    </span>
  );
};

const ProjectDot = ({ project, projects, size = 8 }) => {
  const p = projects.find(x => x.id === project);
  if (!p) return null;
  return (
    <span className="project-dot" style={{background: p.color, width: size, height: size}}/>
  );
};

const ConvPreviewPopover = ({ preview }) => {
  const { conv, x, y, msgs, loading } = preview;
  const W = 480, H = 380, pad = 12;
  const vw = window.innerWidth, vh = window.innerHeight;
  let left = x + 18;
  let top = y + 12;
  if (left + W + pad > vw) left = Math.max(pad, x - W - 18);
  if (top + H + pad > vh)  top  = Math.max(pad, y - H - 12);

  const firstMsgs = (msgs || []).filter(m => m.role !== 'summary' && !m.toolResult).slice(0, 6);

  return (
    <div style={{
      position: 'fixed', left, top, width: W, maxHeight: H,
      background: 'var(--bg-elevated)', border: '1px solid var(--border-strong)',
      borderRadius: 10, boxShadow: '0 10px 40px rgba(0,0,0,0.25)',
      zIndex: 200, overflow: 'hidden', display: 'flex', flexDirection: 'column',
      pointerEvents: 'none', userSelect: 'none',
    }}>
      <div style={{padding: '10px 14px', borderBottom: '1px solid var(--border)', background: 'var(--bg-sunk)'}}>
        <div style={{fontSize: 13, fontWeight: 500, color: 'var(--ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
          {conv.title}
        </div>
        <div style={{fontSize: 11, color: 'var(--ink-3)', marginTop: 2, fontFamily: 'var(--font-mono)'}}>
          {conv.userCount} × 用户 · {conv.assistantCount} × Claude · {conv.updated}
        </div>
      </div>
      <div style={{padding: 10, overflowY: 'auto', flex: 1, fontSize: 12}}>
        {loading && <div style={{color: 'var(--ink-3)', textAlign: 'center', padding: 20}}>加载中…</div>}
        {!loading && firstMsgs.length === 0 && <div style={{color:'var(--ink-3)', textAlign:'center', padding:20}}>无消息</div>}
        {!loading && firstMsgs.map((m, i) => (
          <div key={i} style={{
            padding: '6px 10px', marginBottom: 6, borderRadius: 6,
            background: m.role === 'user' ? 'var(--accent-soft)' : 'var(--bg-sunk)',
            borderLeft: `2px solid ${m.role === 'user' ? 'var(--accent)' : 'var(--ink-4)'}`,
          }}>
            <div style={{fontSize: 10, color: 'var(--ink-4)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.05em'}}>
              {m.role === 'user' ? '用户' : 'Claude'}
            </div>
            <div style={{color: 'var(--ink-2)', lineHeight: 1.5, maxHeight: '4.5em', overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical'}}>
              {m.text}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

Object.assign(window, { Icon, Sparkline, Tag, ProjectDot, ConvPreviewPopover });
