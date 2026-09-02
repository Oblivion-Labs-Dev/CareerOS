"use client";

import { useId, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { cn } from "./lib/cn";

export interface SegmentedControlOption<Value extends string> {
  value: Value;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SegmentedControlProps<Value extends string>
  extends Omit<ComponentPropsWithoutRef<"fieldset">, "children" | "onChange"> {
  label: string;
  options: readonly SegmentedControlOption<Value>[];
  value: Value;
  onValueChange: (value: Value) => void;
  name?: string;
  orientation?: "horizontal" | "vertical";
  size?: "sm" | "md";
  fullWidth?: boolean;
  containerClassName?: string;
}

const optionSizeClasses: Record<NonNullable<SegmentedControlProps<string>["size"]>, string> = {
  sm: "min-h-8 px-3 py-1.5 text-xs",
  md: "min-h-10 px-4 py-2 text-sm",
};

export function SegmentedControl<Value extends string>({
  label,
  options,
  value,
  onValueChange,
  name,
  orientation = "horizontal",
  size = "md",
  fullWidth = false,
  className,
  containerClassName,
  disabled,
  ...props
}: SegmentedControlProps<Value>) {
  const generatedId = useId();
  const groupName = name ?? `${generatedId}-segmented-control`;

  return (
    <fieldset
      {...props}
      disabled={disabled}
      className={cn("m-0 min-w-0 border-0 p-0", className)}
      data-orientation={orientation}
    >
      <legend className="sr-only">{label}</legend>
      <div
        className={cn(
          "max-w-full gap-1 rounded-arsenal border border-arsenal-border bg-arsenal-elevated p-1",
          orientation === "horizontal"
            ? "inline-flex overflow-x-auto"
            : "flex w-full flex-col",
          fullWidth && "flex w-full",
          containerClassName,
        )}
      >
        {options.map((option, index) => {
          const optionId = `${generatedId}-option-${index}`;
          const optionDisabled = disabled || option.disabled;

          return (
            <label
              key={option.value}
              htmlFor={optionId}
              className={cn("relative min-w-0", fullWidth && "flex-1")}
            >
              <input
                id={optionId}
                className="peer sr-only"
                type="radio"
                name={groupName}
                value={option.value}
                checked={value === option.value}
                disabled={option.disabled}
                onChange={(event) => {
                  if (event.currentTarget.checked) onValueChange(option.value);
                }}
              />
              <span
                className={cn(
                  "inline-flex w-full cursor-pointer select-none items-center justify-center gap-2 whitespace-nowrap rounded-arsenal-sm font-medium text-arsenal-secondary transition",
                  "hover:bg-arsenal-surface hover:text-arsenal-primary",
                  "peer-checked:bg-arsenal-accent peer-checked:text-arsenal-background",
                  "peer-focus-visible:outline-none peer-focus-visible:ring-2 peer-focus-visible:ring-arsenal-accent peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-arsenal-elevated",
                  "peer-disabled:cursor-not-allowed peer-disabled:opacity-40 peer-disabled:hover:bg-transparent peer-disabled:hover:text-arsenal-secondary",
                  optionSizeClasses[size],
                )}
                data-selected={value === option.value ? "true" : "false"}
              >
                {option.icon ? (
                  <span aria-hidden="true" className="shrink-0">
                    {option.icon}
                  </span>
                ) : null}
                <span className="truncate">{option.label}</span>
              </span>
              {optionDisabled ? <span className="sr-only">Unavailable</span> : null}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
