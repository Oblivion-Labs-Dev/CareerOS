"use client";
import { useEffect, useRef } from "react";

/** Pointer-only depth; no React updates on pointer movement. */
export function useSurfaceDepth(version?: string) {
  const ref = useRef<HTMLElement>(null);
  const previous = useRef(version);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const allowed = () => matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)").matches && document.documentElement.dataset.motion !== "paused";
    const reset = () => { element.style.removeProperty("transform"); };
    const move = (event: PointerEvent) => {
      if (!allowed() || event.pointerType !== "mouse") {reset(); return;}
      const rect = element.getBoundingClientRect();
      const x = (event.clientX-rect.left)/rect.width-.5;
      const y = (event.clientY-rect.top)/rect.height-.5;
      element.style.transform = `perspective(900px) rotateX(${-y*2}deg) rotateY(${x*2}deg) translateY(-2px)`;
    };
    element.addEventListener("pointermove",move); element.addEventListener("pointerleave",reset);
    return () => {element.removeEventListener("pointermove",move);element.removeEventListener("pointerleave",reset);};
  }, []);
  useEffect(() => {
    if (previous.current !== version && ref.current && document.documentElement.dataset.motion !== "paused" && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const animation = ref.current.animate([{filter:"brightness(1.12)"},{filter:"brightness(1)"}],{duration:650});
      previous.current = version;
      return () => animation.cancel();
    }
    previous.current = version;
  }, [version]);
  return ref;
}
