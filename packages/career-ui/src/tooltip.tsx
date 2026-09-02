"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "./lib/cn";

export type TooltipSide = "top" | "bottom" | "left" | "right";

export interface TooltipProps {
  content?: string;
  /** Alias for `content` — supported for legacy CareerOS usage. */
  text?: string;
  label?: string;
  side?: TooltipSide;
  children?: ReactNode;
  className?: string;
  triggerClassName?: string;
}

function getPosition(side: TooltipSide, rect: DOMRect) {
  switch (side) {
    case "top":
      return { top: rect.top - 8, left: rect.left + rect.width / 2 };
    case "left":
      return { top: rect.top + rect.height / 2, left: rect.left - 8 };
    case "right":
      return { top: rect.top + rect.height / 2, left: rect.right + 10 };
    case "bottom":
    default:
      return {
        top: rect.bottom + 8,
        left: Math.min(Math.max(rect.left + rect.width / 2, 150), window.innerWidth - 150),
      };
  }
}

function tooltipTransform(side: TooltipSide) {
  if (side === "bottom") return "translateX(-50%)";
  if (side === "top") return "translate(-50%, -100%)";
  if (side === "left") return "translate(-100%, -50%)";
  return "translateY(-50%)";
}

export function Tooltip({
  content,
  text,
  label = "More info",
  side = "bottom",
  children,
  className,
  triggerClassName,
}: TooltipProps) {
  const resolvedContent = content ?? text ?? "";
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const anchorRef = useRef<HTMLDivElement>(null);
  const tooltipId = useId();

  const updatePosition = useCallback(() => {
    const anchor = anchorRef.current;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    setPosition(getPosition(side, rect));
  }, [side]);

  const show = () => {
    updatePosition();
    setOpen(true);
  };

  const hide = () => setOpen(false);

  const handleShow = (event: MouseEvent | FocusEvent) => {
    event.stopPropagation();
    show();
  };

  const handleHide = (event: MouseEvent | FocusEvent) => {
    event.stopPropagation();
    hide();
  };

  useEffect(() => {
    if (!open) return;
    const handleReposition = () => updatePosition();
    window.addEventListener("scroll", handleReposition, true);
    window.addEventListener("resize", handleReposition);
    return () => {
      window.removeEventListener("scroll", handleReposition, true);
      window.removeEventListener("resize", handleReposition);
    };
  }, [open, updatePosition]);

  return (
    <>
      <div
        ref={anchorRef}
        className={cn(children ? className : cn("inline-flex", className))}
        tabIndex={children ? undefined : 0}
        role={children ? undefined : "button"}
        aria-label={children ? undefined : `${label}: ${resolvedContent}`}
        aria-describedby={open ? tooltipId : undefined}
        onMouseEnter={handleShow}
        onMouseLeave={handleHide}
        onFocus={handleShow}
        onBlur={handleHide}
      >
        {children ?? (
          <span
            className={cn(
              "inline-flex h-4 w-4 shrink-0 cursor-help items-center justify-center rounded-full border border-arsenal-border text-[0.62rem] font-extrabold italic leading-none text-arsenal-muted transition hover:border-arsenal-accent hover:text-arsenal-accent",
              triggerClassName,
            )}
          >
            i
          </span>
        )}
      </div>
      {open && typeof document !== "undefined"
        ? createPortal(
            <span
              id={tooltipId}
              className="pointer-events-none fixed z-[9999] max-w-[min(280px,calc(100vw-2rem))] rounded-arsenal-sm border border-arsenal-border bg-arsenal-elevated px-3 py-2.5 text-xs font-medium leading-snug text-arsenal-secondary shadow-arsenal"
              style={{ top: position.top, left: position.left, transform: tooltipTransform(side) }}
              role="tooltip"
            >
              {resolvedContent}
            </span>,
            document.body,
          )
        : null}
    </>
  );
}

/** @deprecated Use `Tooltip` — kept for existing imports. */
export function InfoTooltip(props: TooltipProps) {
  return <Tooltip {...props} />;
}
