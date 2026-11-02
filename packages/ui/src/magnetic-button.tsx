"use client";

import * as React from "react";
import { motion, type HTMLMotionProps } from "framer-motion";

export interface MagneticButtonProps extends HTMLMotionProps<"button"> {
  children?: React.ReactNode;
  className?: string;
  onClick?: () => void;
}

export function MagneticButton({ children, className, onClick, ...props }: MagneticButtonProps) {
  return (
    <motion.button
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      className={className}
      onClick={onClick}
      {...props}
    >
      {children}
    </motion.button>
  );
}
