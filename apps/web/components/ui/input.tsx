"use client";

import React from "react";
import styles from "./primitives.module.css";

type FieldShellProps = {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
  htmlFor?: string;
};

/** Label + control + hint/error, so every form in the app reads the same. */
function FieldShell({ label, hint, error, className = "", children, htmlFor }: FieldShellProps) {
  return (
    <div className={`${styles.field} ${className}`}>
      {label ? (
        <label className={styles.label} htmlFor={htmlFor}>
          {label}
        </label>
      ) : null}
      {children}
      {error ? <span className={styles.fieldError}>{error}</span> : hint ? <span className={styles.fieldHint}>{hint}</span> : null}
    </div>
  );
}

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  wrapperClassName?: string;
};

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, wrapperClassName, className = "", id, ...rest },
  ref,
) {
  const autoId = React.useId();
  const fieldId = id || autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} className={wrapperClassName} htmlFor={fieldId}>
      <input
        ref={ref}
        id={fieldId}
        className={`${styles.input} ${error ? styles.inputInvalid : ""} ${className}`}
        aria-invalid={error ? true : undefined}
        {...rest}
      />
    </FieldShell>
  );
});

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  wrapperClassName?: string;
};

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, wrapperClassName, className = "", id, ...rest },
  ref,
) {
  const autoId = React.useId();
  const fieldId = id || autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} className={wrapperClassName} htmlFor={fieldId}>
      <textarea
        ref={ref}
        id={fieldId}
        className={`${styles.textarea} ${error ? styles.inputInvalid : ""} ${className}`}
        aria-invalid={error ? true : undefined}
        {...rest}
      />
    </FieldShell>
  );
});

export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement> & {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  wrapperClassName?: string;
};

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, wrapperClassName, className = "", id, children, ...rest },
  ref,
) {
  const autoId = React.useId();
  const fieldId = id || autoId;
  return (
    <FieldShell label={label} hint={hint} error={error} className={wrapperClassName} htmlFor={fieldId}>
      <select
        ref={ref}
        id={fieldId}
        className={`${styles.select} ${error ? styles.inputInvalid : ""} ${className}`}
        aria-invalid={error ? true : undefined}
        {...rest}
      >
        {children}
      </select>
    </FieldShell>
  );
});

export type SearchInputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
  value: string;
  onValueChange: (value: string) => void;
  wrapperClassName?: string;
};

/** Search is the control people touch most, so it gets the extra affordances. */
export const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(function SearchInput(
  { value, onValueChange, placeholder = "Search…", wrapperClassName = "", className = "", ...rest },
  ref,
) {
  return (
    <div className={`${styles.search} ${wrapperClassName}`}>
      <span className={styles.searchIcon} aria-hidden>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.2-3.2" />
        </svg>
      </span>
      <input
        ref={ref}
        type="search"
        role="searchbox"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onValueChange(e.target.value)}
        className={`${styles.input} ${styles.searchInput} ${className}`}
        {...rest}
      />
      {value ? (
        <button type="button" className={styles.searchClear} onClick={() => onValueChange("")} aria-label="Clear search">
          ×
        </button>
      ) : null}
    </div>
  );
});
