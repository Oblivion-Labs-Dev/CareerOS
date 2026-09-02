"use client";

import { motion } from "framer-motion";
import { type ReactNode } from "react";
import { cn } from "./lib/cn";

interface GlassCardProps {
  children: ReactNode;
  glow?: boolean;
  className?: string;
  onClick?: () => void;
}

export function GlassCard({ children, className, glow, onClick }: GlassCardProps) {
  return (
    <motion.div
      whileHover={{ y: -6, scale: 1.015 }}
      whileTap={{ scale: 0.99 }}
      transition={{ type: "spring", stiffness: 350, damping: 25 }}
      className={cn(
        "rounded-arsenal border border-arsenal-border bg-gradient-to-b from-arsenal-surface/95 to-arsenal-elevated/85 backdrop-blur-xl p-6",
        "shadow-arsenal transition-all duration-300 ease-out",
        "hover:border-arsenal-border-hover hover:bg-arsenal-elevated/95",
        glow && "hover:shadow-arsenal-glow",
        className,
      )}
      data-cursor="card"
      onClick={onClick}
    >
      {children}
    </motion.div>
  );
}
