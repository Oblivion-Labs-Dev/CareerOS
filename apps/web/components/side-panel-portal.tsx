"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

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
  const onCloseRef = useRef(onClose);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return undefined;

    document.body.classList.add("side-panel-open");
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.body.classList.remove("side-panel-open");
      document.body.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!open || !mounted) return null;

  return createPortal(
    <>
      <button
        type="button"
        className="aa-wizard-panel-backdrop"
        aria-label={backdropAriaLabel}
        onClick={() => onCloseRef.current()}
      />
      <aside
        className={`aa-wizard-panel ${panelClassName}`.trim()}
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
