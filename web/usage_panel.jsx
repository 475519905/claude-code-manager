// Usage panel with plan limits + heatmap — shown above 所有对话
const UsagePanel = () => {
  const [tab, setTab] = React.useState('overview');
  const [range, setRange] = React.useState('all');
  const [apiStats, setApiStats] = React.useState(null);
  const [costData, setCostData] = React.useState(null);

  React.useEffect(() => {
    fetch('/api/stats').then(r => r.json()).then(setApiStats).catch(() => {});
    fetch('/api/costs')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setCostData(d); })
      .catch(() => {});
  }, []);


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

  const planLabel = (label) => ({
    '本月会话': '短周期额度',
    '累计会话': '长周期额度',
  }[label] || label);

  const resetText = (unixSeconds) => {
    const ts = Number(unixSeconds || 0);
    if (!Number.isFinite(ts) || ts <= 0) return '未知';
    const diffMs = (ts * 1000) - Date.now();
    if (diffMs <= 0) return '即将重置';
    const mins = Math.ceil(diffMs / 60000);
    if (mins < 60) return `${mins} 分钟`;
    const hours = Math.ceil(mins / 60);
    if (hours < 48) return `${hours} 小时`;
    return `${Math.ceil(hours / 24)} 天`;
  };

  const windowLabel = (minutes) => {
    const n = Number(minutes || 0);
    if (!Number.isFinite(n) || n <= 0) return '真实额度';
    if (n % 1440 === 0) return `${n / 1440} 天窗口`;
    if (n % 60 === 0) return `${n / 60} 小时窗口`;
    return `${n} 分钟窗口`;
  };

  const quotaPlan = (label, limit) => {
    const used = Number(limit && limit.used_percent);
    if (!limit || !Number.isFinite(used)) {
      return {
        label,
        count: 0,
        cap: 100,
        pct: 0,
        displayValue: '未获取',
        reset: '运行一次会话后更新',
        sub: '真实额度',
        showBar: false,
      };
    }
    const pct = Math.max(0, Math.min(100, used));
    return {
      label,
      count: pct,
      cap: 100,
      pct: Math.round(pct),
      displayValue: `${Number.isInteger(pct) ? pct : pct.toFixed(1)}%`,
      reset: resetText(limit.resets_at),
      sub: windowLabel(limit.window_minutes),
      showBar: true,
    };
  };

  const activityPlans = (apiStats && apiStats.plans ? apiStats.plans : [
    {label:'今日会话',count:0,cap:20,reset:'—',sub:'每日'},
    {label:'本周会话',count:0,cap:80,reset:'—',sub:'每周'},
    {label:'短周期额度',count:0,cap:300,reset:'—',sub:'每月'},
    {label:'长周期额度',count:0,cap:500,reset:'—',sub:'全部历史'},
  ])
    .map(p => ({
      ...p,
      label: planLabel(p.label),
      cap: planLabel(p.label) === '今日会话' && p.cap <= 1 ? 20 : (planLabel(p.label) === '本周会话' && p.cap <= 1 ? 80 : p.cap),
      displayValue: ['今日会话', '本周会话'].includes(planLabel(p.label)) ? undefined : p.displayValue,
      showBar: ['今日会话', '本周会话'].includes(planLabel(p.label)) ? true : p.showBar,
    }))
    .filter(p => ['今日会话', '本周会话'].includes(p.label))
    .slice(0, 2)
    .map(p => ({
      ...p,
      pct: Math.round(Math.min(100, (p.count / Math.max(p.cap, 1)) * 100)),
    }));
  const rateLimits = costData && costData.rateLimits ? costData.rateLimits : {};
  const plans = [
    ...activityPlans,
    quotaPlan('短周期额度', rateLimits.primary),
    quotaPlan('长周期额度', rateLimits.secondary),
  ];

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
    { k: '总 tokens',      v: t.totalTokens || '—' },
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
                <span className="plan-pct mono">{p.displayValue ?? `${p.count}/${p.cap}`}</span>
              </div>
              {p.showBar !== false && (
                <div className="plan-bar">
                  <div className="plan-bar-fill" style={{width: `${Math.max(p.pct, 1)}%`, opacity: p.pct === 0 ? 0.2 : 1}}/>
                </div>
              )}
              <div className="plan-row-foot">
                <span className="plan-sub">{p.sub}</span>
                <span className="plan-reset mono">{p.reset}</span>
              </div>
            </div>
          ))}
          <span className="plan-learn" style={{opacity:0.5}}>基于本地 .codex/sessions 与 rate_limits 统计</span>
        </div>

        {/* Right: heatmap */}
        <div className="heatmap-col">
          <div className="heatmap-toolbar">
            <div className="seg heatmap-seg">
              {[{id:'all',l:'全部'},{id:'30d',l:'30天'},{id:'7d',l:'7天'}].map(r => (
                <button key={r.id} className={range === r.id ? 'active' : ''} onClick={() => setRange(r.id)}>{r.l}</button>
              ))}
            </div>
          </div>

          <div className="heatmap-wrap">
            {range === 'all' && (
              <div className="heatmap-months">
                {months.map((m, i) => (
                  <span key={i} style={{left: `${(i / (months.length - 1)) * 100}%`}}>{m}</span>
                ))}
              </div>
            )}

            {range === 'all' ? (
              <div className="heatmap-body">
                <div className="heatmap-days">
                  {dayLabels.map((d, i) => <span key={i}>{d}</span>)}
                </div>
                <svg className="heatmap-svg" key="all"
                  width={weeks * (cellSize + cellGap) - cellGap}
                  height={7 * (cellSize + cellGap) - cellGap}
                  viewBox={`0 0 ${weeks * (cellSize + cellGap) - cellGap} ${7 * (cellSize + cellGap) - cellGap}`}>
                  {heatmapData.map((row, d) =>
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
            ) : (() => {
              const n = range === '7d' ? 7 : 30;
              const series = (apiStats && apiStats.recentDays ? apiStats.recentDays : []).slice(-n);
              const cw = range === '7d' ? 34 : 16;     // cell width per day
              const ch = range === '7d' ? 44 : 38;     // cell height
              const gap = range === '7d' ? 6 : 3;
              return (
                <div className="heatmap-strip" key={range}>
                  <div className="strip-row" style={{display:'flex',gap:`${gap}px`}}>
                    {series.map((d, i) => (
                      <div key={d.date}
                        title={`${d.date} · ${d.count} 次会话`}
                        style={{
                          width: cw, height: ch, borderRadius: 4,
                          background: colorFor(d.level),
                          display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
                          paddingBottom: 2, fontSize: 9,
                          color: d.level >= 3 ? 'white' : 'var(--ink-3)',
                          fontFamily: 'var(--font-mono)',
                        }}>
                        {range === '7d' && new Date(d.date).getDate()}
                      </div>
                    ))}
                  </div>
                  <div style={{display:'flex',gap:`${gap}px`,marginTop:6,fontSize:10,color:'var(--ink-4)',fontFamily:'var(--font-mono)'}}>
                    {series.map((d, i) => {
                      const showLabel = range === '7d'
                        ? true
                        : (i === 0 || i === series.length - 1 || new Date(d.date).getDate() === 1);
                      return (
                        <div key={d.date} style={{width: cw, textAlign:'center'}}>
                          {showLabel ? (range === '7d' ? ['日','一','二','三','四','五','六'][new Date(d.date).getDay()] : d.date.slice(5)) : ''}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}

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
            <span>共扫描 <span className="mono" style={{color: 'var(--ink)'}}>{t.sessions != null ? t.sessions : '…'}</span> 条本地会话 · 活跃 <span className="mono" style={{color: 'var(--ink)'}}>{t.activeDays != null ? t.activeDays : '…'}</span> 天</span>
          </div>
        </div>
      </div>)}
    </section>
  );
};

Object.assign(window, { UsagePanel });
