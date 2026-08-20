import { getLabelText, getFieldGroupQuestion } from './domScanner';
import { extractJobContext, isJobApplicationPage } from '../shared/jobPageDetection';

const INJECTED_FLAG = 'data-ap-ai-button';

function setNativeValue(element: HTMLTextAreaElement | HTMLInputElement, value: string): void {
  const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
  const prototype = Object.getPrototypeOf(element);
  const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;

  if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
    prototypeValueSetter.call(element, value);
  } else if (valueSetter) {
    valueSetter.call(element, value);
  } else {
    element.value = value;
  }

  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.dispatchEvent(new Event('blur', { bubbles: true }));
}

export function initAiGenerateButtons(doc: Document = document): void {
  if (!isJobApplicationPage(doc)) return;
  const textareas = Array.from(doc.querySelectorAll('textarea')) as HTMLTextAreaElement[];

  for (const textarea of textareas) {
    if (textarea.getAttribute(INJECTED_FLAG)) continue;
    textarea.setAttribute(INJECTED_FLAG, 'true');

    // Make sure container has relative positioning
    const parent = textarea.parentElement;
    if (!parent) continue;

    if (window.getComputedStyle(parent).position === 'static') {
      parent.style.position = 'relative';
    }

    const btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = 'ap-ai-generate-btn';
    const iconUrl = typeof chrome !== 'undefined' && chrome.runtime?.getURL ? chrome.runtime.getURL('icon-48.png') : '';
    btn.innerHTML = `
      <img src="${iconUrl}" width="16" height="16" style="margin-right:6px; object-fit:contain; vertical-align:middle;" alt="ApplyPilot" />
      <span>Generate with AI</span>
    `;

    // Apply inline style for high visual quality (matching design specs)
    Object.assign(btn.style, {
      position: 'absolute',
      right: '12px',
      bottom: '12px',
      zIndex: '10',
      display: 'inline-flex',
      alignItems: 'center',
      padding: '6px 12px',
      fontSize: '13px',
      fontWeight: '600',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      color: '#0284c7',
      backgroundColor: '#ffffff',
      border: '1.5px solid #e0f2fe',
      borderRadius: '8px',
      cursor: 'pointer',
      boxShadow: '0 2px 6px rgba(0,0,0,0.06)',
      transition: 'all 0.15s ease-in-out',
      outline: 'none'
    });

    btn.addEventListener('mouseenter', () => {
      btn.style.backgroundColor = '#f0f9ff';
      btn.style.borderColor = '#38bdf8';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.backgroundColor = '#ffffff';
      btn.style.borderColor = '#e0f2fe';
    });

    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const labelSpan = btn.querySelector('span');
      if (labelSpan) labelSpan.textContent = 'Generating...';
      btn.disabled = true;
      btn.style.opacity = '0.7';

      try {
        const questionText = getFieldGroupQuestion(textarea, doc) || getLabelText(textarea, doc) || textarea.name || textarea.placeholder;
        const ctx = extractJobContext(doc);
        console.log('[ApplyPilot AI Generate] Requesting AI answer for:', { questionText, ctx });

        const response = await new Promise<{ success?: boolean; answer?: string; error?: string }>((resolve) => {
          chrome.runtime.sendMessage(
            {
              action: 'generate-ai-answer',
              question: questionText,
              company: ctx.company,
              role: ctx.role,
              jobDescription: ctx.description
            },
            (res) => resolve(res || { success: false, error: 'No response from extension background' })
          );
        });

        if (response.success && response.answer) {
          setNativeValue(textarea, response.answer);
          if (labelSpan) labelSpan.textContent = 'Generated ✓';
          setTimeout(() => {
            if (labelSpan) labelSpan.textContent = 'Generate with AI';
            btn.disabled = false;
            btn.style.opacity = '1';
          }, 2000);
        } else {
          if (labelSpan) labelSpan.textContent = 'Failed';
          console.error('[ApplyPilot AI Generate] Failed:', response.error);
          setTimeout(() => {
            if (labelSpan) labelSpan.textContent = 'Generate with AI';
            btn.disabled = false;
            btn.style.opacity = '1';
          }, 2500);
        }
      } catch (err: any) {
        if (labelSpan) labelSpan.textContent = 'Error';
        console.error('[ApplyPilot AI Generate] Exception:', err);
        setTimeout(() => {
          if (labelSpan) labelSpan.textContent = 'Generate with AI';
          btn.disabled = false;
          btn.style.opacity = '1';
        }, 2500);
      }
    });

    parent.appendChild(btn);
  }
}
