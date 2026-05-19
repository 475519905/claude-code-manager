// Cost dashboard — ccusage-style. Mounted only when sidebar "用量" is active,
// so /api/costs (which scans every JSONL on first run) is not paid until then.
const CostsView = () => {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState('');
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancel = false;
    setLoading(true); setErr('');
    fetch('/api/costs')
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP '+r.status)))
      .then(d => { if (!cancel) { setData(d); setLoading(false); } })
      .catch(e => { if (!cancel) { setErr(String(e)); setLoading(false); } });
    return () => { cancel = true; };
  }, []);

  const fmt$ = (v) => '$' + (Number(v) || 0).toFixed(2);
  const fmtN = (v) => Number(v || 0).toLocaleString();
  const fmtTok = (n) => {
    n = Number(n) || 0;
    if (n >= 1e9) return (n/1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n/1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
    return String(n);
  };

  const today = new Date().toISOString().slice(0, 10);
  const monthPrefix = today.slice(0, 7);

  const todayCost  = data ? (data.byDay[today] || 0) : 0;
  const monthCost  = data ? Object.entries(data.byDay).filter(([d]) => d.startsWith(monthPrefix)).reduce((a, [,v]) => a+v, 0) : 0;
  const total      = data ? data.total : 0;

  const byModel = data ? Object.entries(data.byModel).sort((a,b) => b[1].cost - a[1].cost) : [];
  const recentDays = data ? Object.entries(data.byDay).slice(0, 30) : [];

  const reload = () => {
    setLoading(true); setErr(''); setData(null);
    fetch('/api/costs')
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP '+r.status)))
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setErr(String(e)); setLoading(false); });
  };

  return (
    <section className="costs-view" style={{padding: '20px 32px', maxWidth: 1100}}>
      <div style={{display:'flex', alignItems:'baseline', justifyContent:'space-between', marginBottom: 16}}>
        <div>
          <h1 style={{margin: 0, fontSize: 22, fontWeight: 600, color: 'var(--ink)'}}>用量 / 费用</h1>
          <div style={{color: 'var(--ink-3)', fontSize: 13, marginTop: 4}}>
            按 Anthropic API 价格累加（Max Plan 实际为定额订阅 — 此处为 API 等价值）
          </div>
        </div>
        <button className="chip-btn" onClick={reload} disabled={loading} style={{padding:'6px 12px'}}>
          <Icon name="download" size={12} style={{transform:'rotate(180deg)'}}/> 刷新
        </button>
      </div>

      {loading && (
        <div style={{padding: '60px 0', textAlign: 'center', color: 'var(--ink-3)'}}>
          <span className="spinner" style={{display:'inline-block', verticalAlign:'middle', marginRight:8}}/>
          正在汇总（首次扫描所有会话…）
        </div>
      )}
      {err && <div style={{color:'var(--danger, #ef4444)', padding:16}}>加载失败: {err}</div>}

      {data && !loading && (
        <>
          {/* Totals */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:16, marginBottom:24}}>
            {[
              {k: '今日', v: fmt$(todayCost), sub: today},
              {k: '本月', v: fmt$(monthCost), sub: monthPrefix},
              {k: '累计', v: fmt$(total), sub: `${data.sessions} 个含 usage 的会话`},
            ].map((s, i) => (
              <div key={i} style={{
                padding: 18, borderRadius: 10,
                background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              }}>
                <div style={{fontSize: 12, color: 'var(--ink-3)', marginBottom: 6}}>{s.k}</div>
                <div style={{fontSize: 28, fontWeight: 600, color: 'var(--ink)', fontFamily: 'var(--font-mono)'}}>{s.v}</div>
                <div style={{fontSize: 11, color: 'var(--ink-4)', marginTop: 4, fontFamily: 'var(--font-mono)'}}>{s.sub}</div>
              </div>
            ))}
          </div>

          {/* Token totals */}
          <div style={{
            padding: 16, borderRadius: 10, marginBottom: 24,
            background: 'var(--bg-sunk)', border: '1px solid var(--border)',
          }}>
            <div style={{fontSize: 12, color: 'var(--ink-3)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.5}}>累计 tokens</div>
            <div style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:12}}>
              {[
                ['Input', data.tokens.input],
                ['Output', data.tokens.output],
                ['Cache write', data.tokens.cacheWrite],
                ['Cache read', data.tokens.cacheRead],
              ].map(([k, v]) => (
                <div key={k}>
                  <div style={{fontSize: 11, color: 'var(--ink-4)'}}>{k}</div>
                  <div style={{fontSize: 18, fontFamily: 'var(--font-mono)', color: 'var(--ink)'}}>{fmtTok(v)}</div>
                  <div style={{fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)'}}>{fmtN(v)}</div>
                </div>
              ))}
            </div>
          </div>

          {/* By model */}
          <div style={{marginBottom: 24}}>
            <h2 style={{fontSize: 14, fontWeight: 600, color: 'var(--ink)', margin: '0 0 12px'}}>按模型</h2>
            <table style={{width:'100%', fontSize: 12, borderCollapse:'collapse', fontFamily:'var(--font-mono)'}}>
              <thead>
                <tr style={{color: 'var(--ink-3)', textAlign: 'right', borderBottom: '1px solid var(--border)'}}>
                  <th style={{textAlign:'left', padding:'8px 12px'}}>模型</th>
                  <th style={{padding:'8px 12px'}}>Input</th>
                  <th style={{padding:'8px 12px'}}>Output</th>
                  <th style={{padding:'8px 12px'}}>Cache write</th>
                  <th style={{padding:'8px 12px'}}>Cache read</th>
                  <th style={{padding:'8px 12px'}}>费用</th>
                </tr>
              </thead>
              <tbody>
                {byModel.map(([model, m]) => (
                  <tr key={model} style={{borderBottom:'1px solid var(--border)'}}>
                    <td style={{padding:'8px 12px', color:'var(--ink)'}}>{model}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.input)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.output)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.cacheWrite)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.cacheRead)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink)', fontWeight: 500}}>{fmt$(m.cost)}</td>
                  </tr>
                ))}
                {byModel.length === 0 && (
                  <tr><td colSpan="6" style={{padding:'20px', textAlign:'center', color:'var(--ink-3)'}}>无数据</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* By day (recent 30) */}
          <div style={{marginBottom: 24}}>
            <h2 style={{fontSize: 14, fontWeight: 600, color: 'var(--ink)', margin: '0 0 12px'}}>近 30 天</h2>
            <table style={{width:'100%', fontSize: 12, borderCollapse:'collapse', fontFamily:'var(--font-mono)'}}>
              <thead>
                <tr style={{color: 'var(--ink-3)', textAlign: 'right', borderBottom: '1px solid var(--border)'}}>
                  <th style={{textAlign:'left', padding:'6px 12px'}}>日期</th>
                  <th style={{padding:'6px 12px'}}>Input</th>
                  <th style={{padding:'6px 12px'}}>Output</th>
                  <th style={{padding:'6px 12px'}}>Cache R</th>
                  <th style={{padding:'6px 12px'}}>费用</th>
                </tr>
              </thead>
              <tbody>
                {recentDays.map(([date, cost]) => {
                  const tk = (data.byDayTokens && data.byDayTokens[date]) || {};
                  return (
                    <tr key={date} style={{borderBottom:'1px solid var(--border)'}}>
                      <td style={{padding:'6px 12px', color:'var(--ink)'}}>{date}</td>
                      <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(tk.input)}</td>
                      <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(tk.output)}</td>
                      <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(tk.cacheRead)}</td>
                      <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink)', fontWeight: 500}}>{fmt$(cost)}</td>
                    </tr>
                  );
                })}
                {recentDays.length === 0 && (
                  <tr><td colSpan="5" style={{padding:'20px', textAlign:'center', color:'var(--ink-3)'}}>无数据</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div style={{fontSize: 11, color: 'var(--ink-4)', lineHeight: 1.6}}>
            价格表（每 100 万 tokens · USD）：
            {data.prices && Object.entries(data.prices).map(([k, v]) => (
              <span key={k} style={{marginLeft: 8, fontFamily:'var(--font-mono)'}}>
                {k}: in {v[0]} / out {v[1]} / cw {v[2]} / cr {v[3]}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
};

Object.assign(window, { CostsView });
