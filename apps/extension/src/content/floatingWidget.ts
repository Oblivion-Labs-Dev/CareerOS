const WIDGET_STYLES = `
#jobfill-floating-wrapper {
  position: fixed;
  right: 20px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2147483647;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
}

#jobfill-floating-button {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(10, 18, 16, 0.92);
  color: #ecfdf5;
  border: 1px solid rgba(46, 229, 157, 0.28);
  border-radius: 999px;
  padding: 10px 14px 10px 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(12px);
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

#jobfill-floating-button:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(46, 229, 157, 0.45);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4);
}

#jobfill-floating-button:disabled {
  opacity: 0.85;
  cursor: wait;
}

#jobfill-floating-button .jf-mark {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: linear-gradient(145deg, #2ee59d, #14b8a6);
  color: #042f1e;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

#jobfill-floating-button .jf-label {
  white-space: nowrap;
  letter-spacing: -0.01em;
}

#jobfill-floating-button.is-loading {
  border-color: rgba(46, 229, 157, 0.42);
  box-shadow:
    0 0 0 1px rgba(46, 229, 157, 0.12) inset,
    0 0 24px rgba(46, 229, 157, 0.22),
    0 6px 24px rgba(0, 0, 0, 0.38);
  animation: ap-loading-glow 2.2s ease-in-out infinite;
}

#jobfill-floating-button.is-loading .jf-mark {
  background: rgba(4, 47, 30, 0.85);
  border: none;
  color: transparent;
  position: relative;
  overflow: visible;
}

#jobfill-floating-button.is-loading .jf-mark::before,
#jobfill-floating-button.is-loading .jf-mark::after {
  content: '';
  position: absolute;
  border-radius: 50%;
}

#jobfill-floating-button.is-loading .jf-mark::before {
  inset: -2px;
  background: conic-gradient(
    from 180deg,
    transparent 0deg,
    rgba(46, 229, 157, 0.2) 60deg,
    #2ee59d 150deg,
    #6ee7b7 220deg,
    transparent 300deg
  );
  animation: ap-spin 1.1s cubic-bezier(0.55, 0.1, 0.35, 0.9) infinite;
}

#jobfill-floating-button.is-loading .jf-mark::after {
  inset: 1px;
  background: rgba(4, 47, 30, 0.95);
  border-radius: 7px;
}

#jobfill-floating-button.is-loading .jf-label {
  background: linear-gradient(
    90deg,
    #a7f3d0 0%,
    #ecfdf5 40%,
    #6ee7b7 60%,
    #a7f3d0 100%
  );
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: jf-label-shimmer 2s ease-in-out infinite;
}

#jobfill-floating-button.is-success .jf-mark {
  animation: ap-pop 0.35s ease;
}

#jobfill-floating-button.is-warning .jf-mark {
  background: rgba(251, 191, 36, 0.2);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.35);
}

#jobfill-floating-dismiss {
  position: absolute;
  top: -6px;
  left: -6px;
  width: 18px;
  height: 18px;
  background: rgba(30, 41, 39, 0.95);
  color: #9ca3af;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  cursor: pointer;
  line-height: 1;
}

#jobfill-floating-dismiss:hover {
  color: #ecfdf5;
  background: rgba(55, 65, 81, 0.95);
}

@keyframes ap-spin {
  to { transform: rotate(360deg); }
}

@keyframes ap-loading-glow {
  0%, 100% {
    box-shadow:
      0 0 0 1px rgba(46, 229, 157, 0.1) inset,
      0 0 18px rgba(46, 229, 157, 0.16),
      0 6px 24px rgba(0, 0, 0, 0.38);
  }
  50% {
    box-shadow:
      0 0 0 1px rgba(46, 229, 157, 0.18) inset,
      0 0 28px rgba(46, 229, 157, 0.32),
      0 8px 28px rgba(0, 0, 0, 0.42);
  }
}

@keyframes jf-label-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}

@keyframes ap-pop {
  0% { transform: scale(0.85); }
  60% { transform: scale(1.08); }
  100% { transform: scale(1); }
}
`;

export type WidgetState = 'idle' | 'loading' | 'success' | 'warning';

export interface FloatingWidget {
  setState: (state: WidgetState, label: string) => void;
  setDisabled: (disabled: boolean) => void;
  onClick: (handler: () => void | Promise<void>) => void;
}

export function mountFloatingWidget(): FloatingWidget {
  if (document.getElementById('jobfill-floating-wrapper')) {
    const existing = document.getElementById('jobfill-floating-button') as HTMLButtonElement | null;
    return {
      setState: (state, label) => applyWidgetState(existing, state, label),
      setDisabled: (d) => existing?.toggleAttribute('disabled', d),
      onClick: () => {}
    };
  }

  if (!document.getElementById('jobfill-widget-styles')) {
    const style = document.createElement('style');
    style.id = 'jobfill-widget-styles';
    style.textContent = WIDGET_STYLES;
    document.head.appendChild(style);
  }

  const wrapper = document.createElement('div');
  wrapper.id = 'jobfill-floating-wrapper';

  const btn = document.createElement('button');
  btn.id = 'jobfill-floating-button';
  btn.type = 'button';
  btn.innerHTML = `<span class="jf-mark">JF</span><span class="jf-label">Fill application</span>`;

  const dismiss = document.createElement('button');
  dismiss.id = 'jobfill-floating-dismiss';
  dismiss.type = 'button';
  dismiss.setAttribute('aria-label', 'Dismiss');
  dismiss.textContent = '×';

  wrapper.appendChild(btn);
  wrapper.appendChild(dismiss);
  document.body.appendChild(wrapper);

  dismiss.addEventListener('click', (e) => {
    e.stopPropagation();
    wrapper.remove();
  });

  let clickHandler: (() => void | Promise<void>) | null = null;
  btn.addEventListener('click', () => {
    if (btn.disabled || !clickHandler) return;
    void clickHandler();
  });

  return {
    setState: (state, label) => applyWidgetState(btn, state, label),
    setDisabled: (disabled) => btn.toggleAttribute('disabled', disabled),
    onClick: (handler) => {
      clickHandler = handler;
    }
  };
}

function applyWidgetState(btn: HTMLButtonElement | null, state: WidgetState, label: string): void {
  if (!btn) return;
  btn.classList.remove('is-loading', 'is-success', 'is-warning');
  if (state === 'loading') btn.classList.add('is-loading');
  if (state === 'success') btn.classList.add('is-success');
  if (state === 'warning') btn.classList.add('is-warning');

  const mark = btn.querySelector('.jf-mark');
  const labelEl = btn.querySelector('.jf-label');
  if (labelEl) labelEl.textContent = label;
  if (!mark) return;

  if (state === 'idle') mark.innerHTML = 'AP';
  else if (state === 'loading') mark.innerHTML = '';
  else if (state === 'success') mark.innerHTML = '✓';
  else if (state === 'warning') mark.innerHTML = '!';
}
