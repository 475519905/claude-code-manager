// Bridge: fetch real sessions from backend and shape to UI model.
(function() {
  function hashColor(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffffffff;
    const hue = Math.abs(h) % 360;
    return `oklch(60% 0.12 ${hue})`;
  }

  function prettyProjectName(projDir, cwdSample) {
    if (cwdSample) {
      const parts = cwdSample.replace(/\\/g, '/').split('/').filter(Boolean);
      const last = parts[parts.length - 1] || projDir;
      return last;
    }
    return projDir.replace(/^[A-Z]--/, '').split('-').slice(-2).join(' ') || projDir;
  }

  function relTime(ts) {
    if (!ts) return '';
    const t = new Date(ts).getTime();
    if (!t) return '';
    const now = Date.now();
    const diffMin = (now - t) / 60000;
    if (diffMin < 1) return '刚刚';
    if (diffMin < 60) return `${Math.floor(diffMin)} 分钟前`;
    const d = new Date(t);
    const today = new Date(); today.setHours(0,0,0,0);
    const yest = new Date(today.getTime() - 86400000);
    const dDay = new Date(d); dDay.setHours(0,0,0,0);
    const hhmm = d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0');
    if (dDay.getTime() === today.getTime()) return `今天 ${hhmm}`;
    if (dDay.getTime() === yest.getTime()) return `昨天 ${hhmm}`;
    const daysDiff = Math.floor((today.getTime() - dDay.getTime()) / 86400000);
    if (daysDiff < 7) return `${daysDiff} 天前`;
    if (daysDiff < 30) return `${Math.floor(daysDiff/7)} 周前`;
    return d.toISOString().slice(0,10);
  }

  function dateOnly(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    if (isNaN(d.getTime())) return '';
    return d.toISOString().slice(0,10);
  }

  function loadLocal(key, defaultValue) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : defaultValue; }
    catch { return defaultValue; }
  }

  const xhr = new XMLHttpRequest();
  xhr.open('GET', '/api/sessions', false);
  try { xhr.send(null); } catch(e) {}
  const raw = (xhr.status === 200) ? JSON.parse(xhr.responseText) : { projects: [], sessions: [] };

  const cwdByProj = {};
  for (const s of raw.sessions) {
    if (s.cwd && !cwdByProj[s.project]) cwdByProj[s.project] = s.cwd;
  }

  const pinned = new Set(loadLocal('cm.pinned', []));
  const tagMap = loadLocal('cm.tagMap', {});
  const customTags = loadLocal('cm.tags', [
    { id: 'important', name: '重要', color: 1, count: 0 },
    { id: 'reference', name: '参考', color: 4, count: 0 },
    { id: 'todo',      name: '待办', color: 5, count: 0 },
    { id: 'archive',   name: '归档', color: 6, count: 0 },
  ]);

  const projects = raw.projects.map(p => {
    const cwdSample = cwdByProj[p.name] || '';
    const disp = prettyProjectName(p.name, cwdSample);
    return {
      id: p.name,
      name: disp,
      rawName: p.name,
      cwd: cwdSample,
      emoji: (disp[0] || '·').toUpperCase(),
      color: hashColor(p.name),
      desc: cwdSample || p.name,
      files: 0,
      convs: p.count,
    };
  });

  const conversations = raw.sessions.map(s => {
    const convId = `${s.project}|${s.sid}`;
    const userTags = tagMap[convId] || [];
    const isPinned = pinned.has(convId);
    const msgCount = (s.userCount || 0) + (s.assistantCount || 0);
    const title = (s.summary || s.preview || '(无标题)').slice(0, 120);
    const snippet = (s.preview || s.summary || '').slice(0, 200);
    const spark = [];
    const steps = Math.min(12, Math.max(2, msgCount));
    for (let i = 1; i <= steps; i++) spark.push(Math.round((i / steps) * (msgCount || 1)));
    return {
      id: convId,
      project: s.project,
      sid: s.sid,
      title,
      snippet,
      tags: userTags.slice(),
      updated: relTime(s.lastTs),
      updatedSort: s.mtime || 0,
      messages: msgCount,
      tokens: Math.round((s.size || 0) / 4),
      pinned: isPinned,
      model: '',
      created: dateOnly(s.firstTs),
      sparkline: spark,
      cwd: s.cwd,
      gitBranch: s.gitBranch,
      size: s.size,
      userCount: s.userCount || 0,
      assistantCount: s.assistantCount || 0,
      active: !!s.active,
    };
  });

  const tagCounts = {};
  for (const c of conversations) for (const t of c.tags) tagCounts[t] = (tagCounts[t] || 0) + 1;
  const tags = customTags.map(t => ({ ...t, count: tagCounts[t.id] || 0 }));

  window.APP_STATE_API = {
    togglePin(convId) {
      if (pinned.has(convId)) pinned.delete(convId); else pinned.add(convId);
      localStorage.setItem('cm.pinned', JSON.stringify([...pinned]));
    },
    setTags(convId, tagIds) {
      if (!tagIds || !tagIds.length) delete tagMap[convId]; else tagMap[convId] = tagIds;
      localStorage.setItem('cm.tagMap', JSON.stringify(tagMap));
    },
    addTag(name) {
      const id = 't_' + Date.now();
      const color = ((customTags.length) % 6) + 1;
      customTags.push({ id, name, color, count: 0 });
      localStorage.setItem('cm.tags', JSON.stringify(customTags));
      return id;
    },
  };

  window.APP_DATA = { projects, tags, conversations, sampleDialogue: [] };
})();
