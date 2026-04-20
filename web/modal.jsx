// In-app dialog host — replaces native window.confirm / alert / prompt
// so the UI stays visually consistent and avoids the "localhost:8765 说"
// system popup from WebView2.
//
// Usage (anywhere, after DialogHost has mounted):
//   await window.dialog.alert('已保存');
//   if (await window.dialog.confirm('删除?', {danger:true})) ...
//   const name = await window.dialog.prompt('标签名?', {defaultValue:''});

(() => {
  let notify = null;   // set by DialogHost, receives a dialog spec or null
  const queue = [];    // pending requests when DialogHost hasn't mounted yet

  const push = (spec) => new Promise(resolve => {
    const entry = { ...spec, _resolve: resolve };
    if (notify) notify(entry);
    else queue.push(entry);
  });

  // Handle a 401 `{needsLogin: true}` response by offering to re-login.
  // Returns true iff the caller should abort (login flow was launched OR user
  // cancelled). Returns false when the response was fine (no login needed).
  window.handleAuthGate = async (responseJson) => {
    if (!responseJson || !responseJson.needsLogin) return false;
    const ok = await window.dialog.confirm(
      `${responseJson.error || 'Claude 登录已过期'}\n现在打开终端重新登录?`,
      {title: 'Claude 登录已过期', okLabel: '重新登录', danger: false});
    if (ok) {
      try {
        const r = await fetch('/api/claude-login', {method:'POST'});
        const d = await r.json();
        if (!d.ok) {
          await window.dialog.alert('启动登录失败: ' + (d.error || '未知'),
            {title:'启动失败', danger:true});
        } else {
          await window.dialog.alert(
            '已打开终端窗口。完成 `claude /login` 后,回到这里再次点击操作即可。',
            {title:'请在新终端中完成登录'});
        }
      } catch (e) {
        await window.dialog.alert('启动登录失败: ' + e, {title:'启动失败', danger:true});
      }
    }
    return true;
  };

  window.dialog = {
    confirm: (message, opts = {}) => push({
      kind: 'confirm',
      title: opts.title || '请确认',
      message,
      okLabel: opts.okLabel || (opts.danger ? '删除' : '确定'),
      cancelLabel: opts.cancelLabel || '取消',
      danger: !!opts.danger,
    }),
    alert: (message, opts = {}) => push({
      kind: 'alert',
      title: opts.title || '提示',
      message,
      okLabel: opts.okLabel || '好',
      danger: !!opts.danger,
    }),
    prompt: (message, opts = {}) => push({
      kind: 'prompt',
      title: opts.title || '请输入',
      message,
      defaultValue: opts.defaultValue != null ? String(opts.defaultValue) : '',
      placeholder: opts.placeholder || '',
      okLabel: opts.okLabel || '确定',
      cancelLabel: opts.cancelLabel || '取消',
      multiline: !!opts.multiline,
    }),
  };

  const DialogHost = () => {
    const [spec, setSpec] = React.useState(null);
    const [value, setValue] = React.useState('');
    const inputRef = React.useRef(null);

    React.useEffect(() => {
      notify = (s) => {
        setSpec(s);
        setValue(s && s.kind === 'prompt' ? (s.defaultValue || '') : '');
      };
      // Drain any requests queued before mount
      while (queue.length) notify(queue.shift());
      return () => { notify = null; };
    }, []);

    React.useEffect(() => {
      if (spec && inputRef.current) {
        inputRef.current.focus();
        if (spec.kind === 'prompt' && inputRef.current.select) inputRef.current.select();
      }
    }, [spec]);

    const close = (result) => {
      if (!spec || spec._done) return;
      spec._done = true;
      const r = spec._resolve;
      setSpec(null);
      r(result);
    };

    const onOk = () => {
      if (!spec) return;
      if (spec.kind === 'prompt') close(value);
      else if (spec.kind === 'confirm') close(true);
      else close(undefined);
    };
    const onCancel = () => {
      if (!spec) return;
      if (spec.kind === 'prompt') close(null);
      else if (spec.kind === 'confirm') close(false);
      else close(undefined);
    };

    const onKeyDown = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
      else if (e.key === 'Enter' && !(spec && spec.kind === 'prompt' && spec.multiline && !e.ctrlKey && !e.metaKey)) {
        e.preventDefault(); onOk();
      }
    };

    if (!spec) return null;

    const showCancel = spec.kind !== 'alert';
    const messageLines = String(spec.message || '').split('\n');

    return (
      <div className="cm-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
        <div className={`cm-modal ${spec.danger ? 'danger' : ''}`} onKeyDown={onKeyDown}>
          <div className="cm-modal-title">{spec.title}</div>
          <div className="cm-modal-body">
            {messageLines.map((line, i) => <div key={i} className="cm-modal-line">{line || '\u00A0'}</div>)}
          </div>
          {spec.kind === 'prompt' && (
            spec.multiline ? (
              <textarea
                ref={inputRef}
                className="cm-modal-input"
                rows={4}
                value={value}
                placeholder={spec.placeholder}
                onChange={(e) => setValue(e.target.value)}
              />
            ) : (
              <input
                ref={inputRef}
                className="cm-modal-input"
                type="text"
                value={value}
                placeholder={spec.placeholder}
                onChange={(e) => setValue(e.target.value)}
              />
            )
          )}
          <div className="cm-modal-actions">
            {showCancel && (
              <button className="cm-modal-btn" onClick={onCancel}>{spec.cancelLabel}</button>
            )}
            <button
              ref={spec.kind === 'prompt' ? null : inputRef}
              className={`cm-modal-btn primary ${spec.danger ? 'danger' : ''}`}
              onClick={onOk}
            >
              {spec.okLabel}
            </button>
          </div>
        </div>
      </div>
    );
  };

  Object.assign(window, { DialogHost });
})();
