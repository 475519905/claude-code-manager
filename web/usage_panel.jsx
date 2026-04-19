// Usage panel with plan limits + heatmap — shown above 所有对话
const UsagePanel = () => {
  const [tab, setTab] = React.useState('overview');
  const [range, setRange] = React.useState('all');
  const [apiStats, setApiStats] = React.useState(null);

  React.useEffect(() => {
    fetch('/api/stats').then(r => r.json()).then(setApiStats).catch(() => {});
  }, []);

  // trim heatmap by range
  const trimHeatmap = (grid) => {
    if (!grid || grid.length !== 7) return grid;
    if (range === '7d')  return grid.map(row => row.slice(-1));
    if (range === '30d') return grid.map(row => row.slice(-5));
    return grid;
  };

  // Month labels relative to today going back 13 months
  const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const today = new Date();
  const months = [];
  for (let i = 12; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    months.push(monthNames[d.getMonth()]);
  }
  const weeks = 53;

  const heatmapData = React.useMemo(() => {
    if (apiStats && apiStats.heatmap && apiStats.heatmap.length === 7) return apiStats.heatmap;
    // empty grid until data arrives
    return Array.from({length:7}, () => Array(weeks).fill(0));
  }, [apiStats]);

  const plans = (apiStats && apiStats.plans ? apiStats.plans : [
    {label:'今日会话',count:0,cap:20,reset:'—',sub:'每日'},
    {label:'本周会话',count:0,cap:80,reset:'—',sub:'每周'},
    {label:'本月会话',count:0,cap:300,reset:'—',sub:'每月'},
    {label:'累计会话',count:0,cap:500,reset:'—',sub:'全部历史'},
  ]).map(p => ({...p, pct: Math.round(Math.min(100, (p.count / Math.max(p.cap, 1)) * 100))}));

  const colorFor = (v) => {
    if (v === 0) return 'var(--hm-0)';
    if (v === 1) return 'var(--hm-1)';
    if (v === 2) return 'var(--hm-2)';
    if (v === 3) return 'var(--hm-3)';
    return 'var(--hm-4)';
  };

  const t = apiStats ? apiStats.totals : {};
  const stats = [
    { k: '常用模型',       v: t.favoriteModel || '—' },
    { k: '总 tokens (估)', v: t.totalTokens || '—' },
    { k: '会话数',         v: t.sessions != null ? String(t.sessions) : '—' },
    { k: '最长会话',       v: t.longest || '—' },
    { k: '最活跃日',       v: t.mostActiveDay || '—' },
    { k: '当前连续',       v: t.streak || '—' },
  ];

  const cellSize = 10;
  const cellGap = 3;
  const dayLabels = ['', 'Mon', '', 'Wed', '', 'Fri', ''];

  return (
    <section className="usage-panel">
      <div className="usage-head">
        <div>
          <h2 className="usage-title">活跃度</h2>
          <div className="usage-sub">
            <span className="mono">Local</span>
            <span className="sep">·</span>
            <span>{apiStats ? '已加载' : '加载中…'}</span>
          </div>
        </div>
        <div className="tabs-inline">
          <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>概览</button>
          <button className={tab === 'models' ? 'active' : ''} onClick={() => setTab('models')}>按模型</button>
        </div>
      </div>

      {tab === 'models' && (
        <div style={{padding: '40px 20px', textAlign: 'center', color: 'var(--ink-3)', fontSize: 13}}>
          常用模型:<strong style={{color:'var(--ink)'}}>{t.favoriteModel || '—'}</strong>
          <div style={{marginTop: 8, fontSize: 12, color: 'var(--ink-4)'}}>(模型细分视图建设中)</div>
        </div>
      )}

      {tab === 'overview' && (<div className="usage-grid">
        {/* Left: plan limit bars */}
        <div className="plan-col">
          <div className="plan-col-label">活跃度</div>
          {plans.map((p, i) => (
            <div key={i} className="plan-row">
              <div className="plan-row-head">
                <span className="plan-label">{p.label}</span>
                <span className="plan-pct mono">{p.count}/{p.cap}</span>
              </div>
              <div className="plan-bar">
                <div className="plan-bar-fill" style={{width: `${Math.max(p.pct, 1)}%`, opacity: p.pct === 0 ? 0.2 : 1}}/>
              </div>
              <div className="plan-row-foot">
                <span className="plan-sub">{p.sub}</span>
                <span className="plan-reset mono">{p.reset}</span>
              </div>
            </div>
          ))}
          <span className="plan-learn" style={{opacity:0.5}}>基于本地 .claude/projects 统计</span>
        </div>

        {/* Right: heatmap */}
        <div className="heatmap-col">
          <div className="heatmap-toolbar">
            <div className="seg heatmap-seg">
              {[{id:'all',l:'全部时间'},{id:'30d',l:'最近 30 天'},{id:'7d',l:'最近 7 天'}].map(r => (
                <button key={r.id} className={range === r.id ? 'active' : ''} onClick={() => setRange(r.id)}>{r.l}</button>
              ))}
            </div>
          </div>

          <div className="heatmap-wrap">
            <div className="heatmap-months">
              {months.map((m, i) => (
                <span key={i} style={{left: `${(i / (months.length - 1)) * 100}%`}}>{m}</span>
              ))}
            </div>

            <div className="heatmap-body">
              <div className="heatmap-days">
                {dayLabels.map((d, i) => <span key={i}>{d}</span>)}
              </div>
              <svg className="heatmap-svg"
                width={(range === '7d' ? 1 : range === '30d' ? 5 : weeks) * (cellSize + cellGap) - cellGap}
                height={7 * (cellSize + cellGap) - cellGap}
                viewBox={`0 0 ${(range === '7d' ? 1 : range === '30d' ? 5 : weeks) * (cellSize + cellGap) - cellGap} ${7 * (cellSize + cellGap) - cellGap}`}
              >
                {trimHeatmap(heatmapData).map((row, d) =>
                  row.map((v, w) => (
                    <rect
                      key={`${d}-${w}`}
                      x={w * (cellSize + cellGap)}
                      y={d * (cellSize + cellGap)}
                      width={cellSize}
                      height={cellSize}
                      rx="2"
                      fill={colorFor(v)}
                    />
                  ))
                )}
              </svg>
            </div>

            <div className="heatmap-legend">
              <span>少</span>
              {[0, 1, 2, 3, 4].map(v => (
                <span key={v} className="legend-cell" style={{background: colorFor(v)}}/>
              ))}
              <span>多</span>
            </div>
          </div>

          <div className="stats-grid">
            {stats.map((s, i) => (
              <div key={i} className="stat-cell">
                <div className="stat-k">{s.k}</div>
                <div className="stat-v">{s.v}</div>
              </div>
            ))}
          </div>

          <div className="fun-fact">
            <Icon name="sparkles" size={13}/>
            <span>共扫描 <span className="mono" style={{color: 'var(--ink)'}}>{t.sessions != null ? t.sessions : '…'}</span> 条本地会话 · 连续活跃 <span className="mono" style={{color: 'var(--ink)'}}>{t.streak || '—'}</span></span>
          </div>
        </div>
      </div>)}
    </section>
  );
};

Object.assign(window, { UsagePanel });
