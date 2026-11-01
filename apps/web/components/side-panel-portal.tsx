"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { FLIP_MS, runFlip } from "@/lib/flip-dialog";

/** Keep in step with the aa-wizard-panel-out duration in globals.css. */
const EXIT_MS = 220;
/** The flip dialog lands back on its card before it unmounts. */
const FLIP_EXIT_MS = FLIP_MS + 40;

type SidePanelPortalProps = {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  panelClassName?: string;
  backdropAriaLabel?: string;
  ariaLabelledBy?: string;
  role?: "dialog" | "status";
  ariaLive?: "polite" | "assertive" | "off";
  /**
   * "side" slides a drawer in from the right. "flip" opens a centred dialog
   * that flips up out of `originEl` (the card that was clicked) and back into
   * it on close.
   */
  variant?: "side" | "flip";
  originEl?: () => HTMLElement | null;
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
  variant = "side",
  originEl,
}: SidePanelPortalProps) {
  const flip = variant === "flip";
  const originRef = useRef<HTMLElement | null>(null);
  const originElRef = useRef(originEl);
  originElRef.current = originEl;
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
  // Callers render `{item && <Details …/>}`, so their children turn empty the
  // moment they close. Keep what was last shown while the panel animates out,
  // otherwise it slides (or flips) away as a blank shell.
  const lastChildrenRef = useRef<ReactNode>(children);
  if (open) lastChildrenRef.current = children;
  const shown = open ? children : lastChildrenRef.current;

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
    const prevPaddingRight = document.body.style.paddingRight;
    // Hiding overflow drops body's scrollbar, which widened the page under the
    // dialog: a flip dialog then landed on the wider card and the card snapped
    // smaller once the scrollbar came back. Hold the scrollbar's space instead.
    const { borderLeftWidth, borderRightWidth, paddingRight } = getComputedStyle(document.body);
    const scrollbar = document.body.getBoundingClientRect().width - document.body.clientWidth
      - parseFloat(borderLeftWidth) - parseFloat(borderRightWidth);
    if (scrollbar > 0) document.body.style.paddingRight = `${parseFloat(paddingRight) + scrollbar}px`;
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
      if (role === "dialog" && previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
      document.body.classList.remove("side-panel-open");
      document.body.style.overflow = prevOverflow;
      document.body.style.paddingRight = prevPaddingRight;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, mounted, role]);

  useEffect(() => {
    if (open) return undefined;
    // Matches the 0.22s exit animation in globals.css. A timer rather than an
    // animationend listener so a viewer with reduced motion (where the
    // animation never runs) still gets the panel removed.
    const timer = setTimeout(() => setShouldRender(false), flip ? FLIP_EXIT_MS : EXIT_MS);
    return () => clearTimeout(timer);
  }, [open, flip]);

  // Flip in before the first paint, so the dialog is never seen at its final
  // place first; flip back out when `open` drops.
  useLayoutEffect(() => {
    if (!flip || !mounted || !shouldRender || !panelRef.current) return undefined;
    if (open) originRef.current = originElRef.current?.() ?? null;
    const run = runFlip(panelRef.current, originRef.current, !open);
    return () => {
      run?.animation.cancel();
      run?.restore();
    };
  }, [flip, open, mounted, shouldRender]);

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
        className={`${flip ? "aa-flip-dialog" : "aa-wizard-panel"} ${panelClassName}`.trim()}
        data-state={open ? "open" : "closed"}
        role={role}
        aria-modal={role === "dialog" ? true : undefined}
        aria-labelledby={ariaLabelledBy}
        aria-live={ariaLive}
      >
        {flip ? (
          <>
            <div className="aa-flip-cover" data-flip-cover aria-hidden="true" inert />
            <div className="aa-flip-face">{shown}</div>
          </>
        ) : (
          shown
        )}
      </aside>
    </>,
    document.body,
  );
}
