"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Keep in step with the aa-wizard-panel-out duration in globals.css. */
const EXIT_MS = 220;

type SidePanelPortalProps = {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  panelClassName?: string;
  backdropAriaLabel?: string;
  ariaLabelledBy?: string;
  role?: "dialog" | "status";
  ariaLive?: "polite" | "assertive" | "off";
};

export function SidePanelPortal({
  open,
  onClose,
  children,
  panelClassName = "",
  backdropAriaLabel = "Close panel",
  ariaLabelledBy,
  role = "dialog",
  ariaLive,
}: SidePanelPortalProps) {
  const panelRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  const [mounted, setMounted] = useState(false);
  // The panel used to unmount the instant `open` went false, so it vanished
  // rather than sliding out. `shouldRender` keeps it in the tree for one exit
  // animation and is raised *during render*, not from an effect: an effect runs
  // after the commit, so the panel would unmount for a frame and then come back
  // to animate — which is the flicker itself, not a fix for it.
  const [shouldRender, setShouldRender] = useState(open);
  if (open && !shouldRender) setShouldRender(true);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open || !mounted) return undefined;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = requestAnimationFrame(() => { if (role === "dialog") panelRef.current?.focus(); });

    document.body.classList.add("side-panel-open");
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
      if (event.key !== "Tab" || role !== "dialog" || !panelRef.current) return;
      const elements = [...panelRef.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex="0"]')].filter(element => element.getClientRects().length > 0);
      const first = elements[0]; const last = elements[elements.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);

    return () => {
      cancelAnimationFrame(frame);
      if (role === "dialog" && previousFocus?.isConnected) previousFocus.focus();
      document.body.classList.remove("side-panel-open");
      document.body.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, mounted, role]);

  useEffect(() => {
    if (open) return undefined;
    // Matches the 0.22s exit animation in globals.css. A timer rather than an
    // animationend listener so a viewer with reduced motion (where the
    // animation never runs) still gets the panel removed.
    const timer = setTimeout(() => setShouldRender(false), EXIT_MS);
    return () => clearTimeout(timer);
  }, [open]);

  if (!shouldRender || !mounted) return null;

  return createPortal(
    <>
      <button
        type="button"
        className="aa-wizard-panel-backdrop"
        data-state={open ? "open" : "closed"}
        aria-label={backdropAriaLabel}
        onClick={() => onCloseRef.current()}
      />
      <aside
        ref={panelRef}
        tabIndex={-1}
        className={`aa-wizard-panel ${panelClassName}`.trim()}
        data-state={open ? "open" : "closed"}
        role={role}
        aria-modal={role === "dialog" ? true : undefined}
        aria-labelledby={ariaLabelledBy}
        aria-live={ariaLive}
      >
        {children}
      </aside>
    </>,
    document.body,
  );
}
