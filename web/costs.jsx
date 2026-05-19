// Codex usage dashboard. This uses local token_count events rather than API
// pricing, because Codex CLI usage through ChatGPT plans is not billed here.
const CostsView = () => {
  const [data, setData] = React.useState(null);
  const [err, setErr] = React.useState('');
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(() => {
    setLoading(true);
    setErr('');
    fetch('/api/costs')
      .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setErr(String(e)); setLoading(false); });
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const fmtN = (v) => Number(v || 0).toLocaleString();
  const fmtTok = (n) => {
    n = Number(n) || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return String(n);
  };
  const tokenTotal = (t) => Number(t?.total ?? ((t?.input || 0) + (t?.output || 0))) || 0;
  const resetText = (unixSeconds) => {
    const ts = Number(unixSeconds || 0);
    if (!ts) return '—';
    const ms = ts * 1000 - Date.now();
    if (ms <= 0) return '即将重置';
    const mins = Math.round(ms / 60000);
    if (mins >= 1440) return `${Math.floor(mins / 1440)} 天后重置`;
    if (mins >= 60) return `${Math.floor(mins / 60)}h ${mins % 60}m 后重置`;
    return `${mins} 分钟后重置`;
  };
  const windowLabel = (mins) => {
    mins = Number(mins || 0);
    if (!mins) return '窗口';
    if (mins % 1440 === 0) return `${mins / 1440} 天窗口`;
    if (mins % 60 === 0) return `${mins / 60} 小时窗口`;
    return `${mins} 分钟窗口`;
  };

  const today = new Date().toISOString().slice(0, 10);
  const monthPrefix = today.slice(0, 7);
  const dayTokens = data?.byDayTokens || {};
  const todayTokens = tokenTotal(dayTokens[today]);
  const monthTokens = Object.entries(dayTokens)
    .filter(([d]) => d.startsWith(monthPrefix))
    .reduce((sum, [, v]) => sum + tokenTotal(v), 0);
  const totalTokens = tokenTotal(data?.tokens);
  const byModel = data ? Object.entries(data.byModel || {}).sort((a, b) => tokenTotal(b[1]) - tokenTotal(a[1])) : [];
  const recentDays = data ? Object.entries(dayTokens).slice(0, 30) : [];
  const limits = data?.rateLimits || {};
  const limitCards = ['primary', 'secondary']
    .map((key) => [key, limits[key]])
    .filter(([, v]) => v);

  return (
    <section className="costs-view" style={{padding: '20px 32px', maxWidth: 1120}}>
      <div style={{display:'flex', alignItems:'baseline', justifyContent:'space-between', marginBottom: 16}}>
        <div>
          <h1 style={{margin: 0, fontSize: 22, fontWeight: 600, color: 'var(--ink)'}}>Codex 用量</h1>
          <div style={{color: 'var(--ink-3)', fontSize: 13, marginTop: 4}}>
            基于本地 token_count 记录；显示 tokens、缓存命中和订阅窗口占用，不换算 API 费用
          </div>
        </div>
        <button className="chip-btn" onClick={load} disabled={loading} style={{padding:'6px 12px'}}>
          <Icon name="download" size={12} style={{transform:'rotate(180deg)'}}/> 刷新
        </button>
      </div>

      {loading && (
        <div style={{padding: '60px 0', textAlign: 'center', color: 'var(--ink-3)'}}>
          <span className="spinner" style={{display:'inline-block', verticalAlign:'middle', marginRight:8}}/>
          正在汇总本地 Codex 会话…
        </div>
      )}
      {err && <div style={{color:'var(--danger, #ef4444)', padding:16}}>加载失败: {err}</div>}

      {data && !loading && (
        <>
          <div style={{display:'grid', gridTemplateColumns:'repeat(4, minmax(0, 1fr))', gap:14, marginBottom:20}}>
            {[
              {k: '今日 tokens', v: fmtTok(todayTokens), sub: today},
              {k: '本月 tokens', v: fmtTok(monthTokens), sub: monthPrefix},
              {k: '累计 tokens', v: fmtTok(totalTokens), sub: `${data.sessions || 0} 个含 usage 的会话`},
              {k: '计划', v: limits.plan_type || '—', sub: limits.lastTs ? `更新 ${limits.lastTs.slice(0, 16).replace('T', ' ')}` : '无 rate limit 记录'},
            ].map((s) => (
              <div key={s.k} style={{
                padding: 16,
                borderRadius: 8,
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                minWidth: 0,
              }}>
                <div style={{fontSize: 12, color: 'var(--ink-3)', marginBottom: 6}}>{s.k}</div>
                <div style={{fontSize: 25, fontWeight: 600, color: 'var(--ink)', fontFamily: 'var(--font-mono)', overflow:'hidden', textOverflow:'ellipsis'}}>{s.v}</div>
                <div style={{fontSize: 11, color: 'var(--ink-4)', marginTop: 4, fontFamily: 'var(--font-mono)'}}>{s.sub}</div>
              </div>
            ))}
          </div>

          {limitCards.length > 0 && (
            <div style={{
              display:'grid',
              gridTemplateColumns:'repeat(2, minmax(0, 1fr))',
              gap:14,
              marginBottom:20,
            }}>
              {limitCards.map(([key, limit]) => {
                const pct = Math.max(0, Math.min(100, Number(limit.used_percent || 0)));
                return (
                  <div key={key} style={{padding:16, borderRadius:8, background:'var(--bg-sunk)', border:'1px solid var(--border)'}}>
                    <div style={{display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:8}}>
                      <div style={{fontSize:13, color:'var(--ink)', fontWeight:500}}>
                        {key === 'primary' ? '短周期额度' : '长周期额度'}
                      </div>
                      <div style={{fontSize:18, color:'var(--ink)', fontFamily:'var(--font-mono)', fontWeight:600}}>{pct.toFixed(0)}%</div>
                    </div>
                    <div style={{height:8, borderRadius:4, overflow:'hidden', background:'var(--bg-elevated)', border:'1px solid var(--border)'}}>
                      <div style={{height:'100%', width:`${pct}%`, background:'var(--accent)'}}/>
                    </div>
                    <div style={{display:'flex', justifyContent:'space-between', marginTop:8, fontSize:11, color:'var(--ink-4)', fontFamily:'var(--font-mono)'}}>
                      <span>{windowLabel(limit.window_minutes)}</span>
                      <span>{resetText(limit.resets_at)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div style={{
            padding: 16,
            borderRadius: 8,
            marginBottom: 22,
            background: 'var(--bg-sunk)',
            border: '1px solid var(--border)',
          }}>
            <div style={{fontSize: 12, color: 'var(--ink-3)', marginBottom: 10, textTransform: 'uppercase'}}>累计 token 明细</div>
            <div style={{display:'grid', gridTemplateColumns:'repeat(5, minmax(0, 1fr))', gap:12}}>
              {[
                ['Input', data.tokens.input],
                ['Non-cached', data.tokens.nonCachedInput],
                ['Cached input', data.tokens.cachedInput],
                ['Output', data.tokens.output],
                ['Reasoning', data.tokens.reasoningOutput],
              ].map(([k, v]) => (
                <div key={k}>
                  <div style={{fontSize: 11, color: 'var(--ink-4)'}}>{k}</div>
                  <div style={{fontSize: 18, fontFamily: 'var(--font-mono)', color: 'var(--ink)'}}>{fmtTok(v)}</div>
                  <div style={{fontSize: 10, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)'}}>{fmtN(v)}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{marginBottom: 22}}>
            <h2 style={{fontSize: 14, fontWeight: 600, color: 'var(--ink)', margin: '0 0 12px'}}>按模型</h2>
            <table style={{width:'100%', fontSize: 12, borderCollapse:'collapse', fontFamily:'var(--font-mono)'}}>
              <thead>
                <tr style={{color: 'var(--ink-3)', textAlign: 'right', borderBottom: '1px solid var(--border)'}}>
                  <th style={{textAlign:'left', padding:'8px 12px'}}>模型</th>
                  <th style={{padding:'8px 12px'}}>Total</th>
                  <th style={{padding:'8px 12px'}}>Input</th>
                  <th style={{padding:'8px 12px'}}>Cached</th>
                  <th style={{padding:'8px 12px'}}>Output</th>
                  <th style={{padding:'8px 12px'}}>Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {byModel.map(([model, m]) => (
                  <tr key={model} style={{borderBottom:'1px solid var(--border)'}}>
                    <td style={{padding:'8px 12px', color:'var(--ink)'}}>{model}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink)', fontWeight:500}}>{fmtTok(m.total)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.input)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.cachedInput)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.output)}</td>
                    <td style={{padding:'8px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(m.reasoningOutput)}</td>
                  </tr>
                ))}
                {byModel.length === 0 && (
                  <tr><td colSpan="6" style={{padding:'20px', textAlign:'center', color:'var(--ink-3)'}}>没有找到 token_count 记录</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div style={{marginBottom: 22}}>
            <h2 style={{fontSize: 14, fontWeight: 600, color: 'var(--ink)', margin: '0 0 12px'}}>近 30 天</h2>
            <table style={{width:'100%', fontSize: 12, borderCollapse:'collapse', fontFamily:'var(--font-mono)'}}>
              <thead>
                <tr style={{color: 'var(--ink-3)', textAlign: 'right', borderBottom: '1px solid var(--border)'}}>
                  <th style={{textAlign:'left', padding:'6px 12px'}}>日期</th>
                  <th style={{padding:'6px 12px'}}>Total</th>
                  <th style={{padding:'6px 12px'}}>Input</th>
                  <th style={{padding:'6px 12px'}}>Cached</th>
                  <th style={{padding:'6px 12px'}}>Output</th>
                  <th style={{padding:'6px 12px'}}>Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {recentDays.map(([date, tk]) => (
                  <tr key={date} style={{borderBottom:'1px solid var(--border)'}}>
                    <td style={{padding:'6px 12px', color:'var(--ink)'}}>{date}</td>
                    <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink)', fontWeight:500}}>{fmtTok(tk.total)}</td>
                    <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(tk.input)}</td>
                    <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(tk.cachedInput)}</td>
                    <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(tk.output)}</td>
                    <td style={{padding:'6px 12px', textAlign:'right', color:'var(--ink-2)'}}>{fmtTok(tk.reasoningOutput)}</td>
                  </tr>
                ))}
                {recentDays.length === 0 && (
                  <tr><td colSpan="6" style={{padding:'20px', textAlign:'center', color:'var(--ink-3)'}}>无数据</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
};

Object.assign(window, { CostsView });
