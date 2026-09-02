'use client';

import { useEffect, useRef } from 'react';
import { cn } from './lib/cn';

type NetworkNode = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  phase: number;
  charge: -1 | 1;
  influence: number;
  offsetX: number;
  offsetY: number;
  color: string;
  lineColor: string;
};

export type NetworkBackgroundProps = {
  className?: string;
  density?: 'calm' | 'standard' | 'dense';
  accent?: 'ember' | 'cyan' | 'steel' | 'portfolio';
  interactive?: boolean;
};

const ACCENTS = {
  ember: {
    node: 'rgba(56, 189, 248, 0.74)',
    line: 'rgba(56, 189, 248,',
    influence: 'rgba(14, 165, 233,',
    ripple: 'rgba(56, 189, 248,',
  },
  cyan: {
    node: 'rgba(90, 169, 230, 0.7)',
    line: 'rgba(90, 169, 230,',
    influence: 'rgba(177, 227, 255,',
    ripple: 'rgba(90, 169, 230,',
  },
  steel: {
    node: 'rgba(176, 185, 197, 0.62)',
    line: 'rgba(176, 185, 197,',
    influence: 'rgba(255, 248, 240,',
    ripple: 'rgba(176, 185, 197,',
  },
  portfolio: {
    node: 'rgba(56, 189, 248, 0.74)',
    line: 'rgba(56, 189, 248,',
    influence: 'rgba(168, 85, 247,',
    ripple: 'rgba(56, 189, 248,',
  },
} as const;

function getTargetCount(width: number, height: number, density: NetworkBackgroundProps['density']) {
  const areaScale = Math.max(width * height, 1) / (1440 * 900);
  const base = density === 'dense' ? 120 : density === 'calm' ? 48 : 76;
  return Math.min(180, Math.max(36, Math.round(base * areaScale)));
}

export function NetworkBackground({
  className,
  density = 'standard',
  accent = 'ember',
  interactive = true,
}: NetworkBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pointerRef = useRef({ x: -1000, y: -1000, active: false, pressed: false });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reducedMotion = motionQuery.matches;
    let width = 0;
    let height = 0;
    let frame = 0;
    let raf = 0;
    let nodes: NetworkNode[] = [];

    const colors = ACCENTS[accent];

    const PORTFOLIO_COLORS = [
      { node: 'rgba(56, 189, 248, 0.72)', line: 'rgba(56, 189, 248,' },
      { node: 'rgba(245, 158, 11, 0.65)', line: 'rgba(245, 158, 11,' },
      { node: 'rgba(236, 72, 153, 0.65)', line: 'rgba(236, 72, 153,' },
      { node: 'rgba(74, 222, 128, 0.58)', line: 'rgba(74, 222, 128,' },
    ];

    const createNodes = () => {
      nodes = Array.from({ length: getTargetCount(width, height, density) }, () => {
        const randColor = PORTFOLIO_COLORS[Math.floor(Math.random() * PORTFOLIO_COLORS.length)];
        return {
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.18,
          vy: (Math.random() - 0.5) * 0.18,
          size: Math.random() * 1.6 + 0.8,
          phase: Math.random() * Math.PI * 2,
          charge: Math.random() > 0.5 ? 1 : -1,
          influence: 0,
          offsetX: 0,
          offsetY: 0,
          color: accent === 'portfolio' ? randColor.node : colors.node,
          lineColor: accent === 'portfolio' ? randColor.line : colors.line,
        };
      });
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      if (rect.width < 1 || rect.height < 1) return;
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      createNodes();
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      frame += reducedMotion ? 0 : 1;

      for (const node of nodes) {
        if (!reducedMotion) {
          node.x += node.vx + Math.sin(frame * 0.008 + node.phase) * 0.08;
          node.y += node.vy + Math.cos(frame * 0.007 + node.phase) * 0.08;

          if (node.x < -20) node.x = width + 20;
          if (node.x > width + 20) node.x = -20;
          if (node.y < -20) node.y = height + 20;
          if (node.y > height + 20) node.y = -20;
        }

        node.offsetX *= 0.93;
        node.offsetY *= 0.93;
        node.influence *= 0.91;

        if (interactive && pointerRef.current.active && !reducedMotion) {
          const dx = pointerRef.current.x - (node.x + node.offsetX);
          const dy = pointerRef.current.y - (node.y + node.offsetY);
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 0.001);
          const radius = pointerRef.current.pressed ? 180 : 112;

          if (dist < radius) {
            const force = (radius - dist) / radius;
            const direction = pointerRef.current.pressed ? 1 : node.charge;
            const strength = pointerRef.current.pressed ? 7 : direction > 0 ? 1.5 : 2.8;
            const bend = Math.sin(node.phase + frame * 0.012) * force * 1.2;

            node.offsetX += (dx / dist) * force * strength * direction;
            node.offsetY += (dy / dist) * force * strength * direction;
            if (!pointerRef.current.pressed) {
              node.offsetX += (-dy / dist) * bend;
              node.offsetY += (dx / dist) * bend;
            }
            node.influence = Math.max(node.influence, force);
          }
        }
      }

      for (let i = 0; i < nodes.length; i += 1) {
        const first = nodes[i];
        const firstX = first.x + first.offsetX;
        const firstY = first.y + first.offsetY;

        for (let j = i + 1; j < nodes.length; j += 1) {
          const second = nodes[j];
          const secondX = second.x + second.offsetX;
          const secondY = second.y + second.offsetY;
          const dx = firstX - secondX;
          const dy = firstY - secondY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const maxDist = density === 'dense' ? 132 : 110;

          if (dist < maxDist) {
            const influence = Math.max(first.influence, second.influence);
            const alpha = ((maxDist - dist) / maxDist) * (0.22 + influence * 0.42);
            ctx.strokeStyle =
              influence > 0.1 ? `${colors.influence}${alpha})` : `${first.lineColor}${alpha})`;
            ctx.lineWidth = 0.8 + influence * 0.8;
            ctx.beginPath();
            ctx.moveTo(firstX, firstY);
            ctx.lineTo(secondX, secondY);
            ctx.stroke();
          }
        }
      }

      for (const node of nodes) {
        const influence = Math.min(1, node.influence);
        const pulse = reducedMotion ? 0 : (Math.sin(frame * 0.018 + node.phase) + 1) * 0.35;
        ctx.shadowBlur = 6 + influence * 12;
        ctx.shadowColor = influence > 0.1 ? `${colors.influence}0.7)` : node.color;
        ctx.fillStyle =
          influence > 0.1 ? `${colors.influence}${0.38 + influence * 0.38})` : node.color;
        ctx.beginPath();
        ctx.arc(
          node.x + node.offsetX,
          node.y + node.offsetY,
          node.size + pulse + influence,
          0,
          Math.PI * 2,
        );
        ctx.fill();
      }
      ctx.shadowBlur = 0;

      if (interactive && pointerRef.current.active && !reducedMotion) {
        const ripple = pointerRef.current.pressed ? 76 : 38;
        const gradient = ctx.createRadialGradient(
          pointerRef.current.x,
          pointerRef.current.y,
          0,
          pointerRef.current.x,
          pointerRef.current.y,
          ripple,
        );
        gradient.addColorStop(0, `${colors.ripple}0.16)`);
        gradient.addColorStop(1, `${colors.ripple}0)`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(pointerRef.current.x, pointerRef.current.y, ripple, 0, Math.PI * 2);
        ctx.fill();
      }

      raf = window.requestAnimationFrame(draw);
    };

    const onPointerMove = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointerRef.current.x = event.clientX - rect.left;
      pointerRef.current.y = event.clientY - rect.top;
      pointerRef.current.active = true;
    };

    const onPointerLeave = () => {
      pointerRef.current.active = false;
      pointerRef.current.pressed = false;
    };

    const onPointerDown = () => {
      pointerRef.current.pressed = true;
    };

    const onPointerUp = () => {
      pointerRef.current.pressed = false;
    };

    const onMotionChange = (event: MediaQueryListEvent) => {
      reducedMotion = event.matches;
    };

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    motionQuery.addEventListener('change', onMotionChange);
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerleave', onPointerLeave);
    window.addEventListener('pointerdown', onPointerDown, { passive: true });
    window.addEventListener('pointerup', onPointerUp, { passive: true });

    resize();
    draw();

    return () => {
      observer.disconnect();
      motionQuery.removeEventListener('change', onMotionChange);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerleave', onPointerLeave);
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointerup', onPointerUp);
      window.cancelAnimationFrame(raf);
    };
  }, [accent, density, interactive]);

  return (
    <canvas
      ref={canvasRef}
      className={cn(
        'pointer-events-none absolute inset-0 h-full w-full opacity-80 mix-blend-screen',
        className,
      )}
      aria-hidden="true"
    />
  );
}
