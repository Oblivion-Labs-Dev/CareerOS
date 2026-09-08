"use client";

import React from "react";
import styles from "./primitives.module.css";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: styles.btnPrimary,
  secondary: styles.btnSecondary,
  ghost: styles.btnGhost,
  danger: styles.btnDanger,
};

const SIZE_CLASS: Partial<Record<ButtonSize, string>> = {
  sm: styles.btnSm,
  lg: styles.btnLg,
};

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Renders a spinner and blocks interaction without collapsing the layout. */
  loading?: boolean;
  /** Square icon-only button; pass an aria-label for it to stay accessible. */
  iconOnly?: boolean;
  block?: boolean;
  leadingIcon?: React.ReactNode;
  trailingIcon?: React.ReactNode;
};

/**
 * The single button in CareerOS. Sections should contain exactly one primary —
 * everything else is secondary or ghost, so action priority is always obvious.
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    iconOnly = false,
    block = false,
    leadingIcon,
    trailingIcon,
    disabled,
    className = "",
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  const classes = [
    styles.btn,
    VARIANT_CLASS[variant],
    SIZE_CLASS[size],
    iconOnly ? styles.btnIcon : "",
    block ? styles.btnBlock : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={ref}
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className={styles.btnSpinner} aria-hidden /> : leadingIcon}
      {!iconOnly && children}
      {!loading && trailingIcon}
    </button>
  );
});
