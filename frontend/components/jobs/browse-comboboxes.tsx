"use client";
import {useState,useEffect,useMemo,useRef,useId} from "react";

type ComboboxOption = {
  value: string;
  label?: string;
  sublabel?: string;
};

type SearchableComboboxProps = {
  name: string;
  value: string;
  onChange: (val: string) => void;
  options: ComboboxOption[];
  placeholder: string;
  required?: boolean;
  style?: React.CSSProperties;
};

export function SearchableCombobox({
  name,
  value,
  onChange,
  options,
  placeholder,
  required = false,
  style,
}: SearchableComboboxProps) {
  const dropdownId = useId();
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const filteredOptions = useMemo(() => {
    const query = value.trim().toLowerCase();
    if (!query) return options;
    return options.filter(
      (opt) =>
        opt.value.toLowerCase().includes(query) ||
        (opt.label && opt.label.toLowerCase().includes(query))
    );
  }, [options, value]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div
      ref={containerRef}
      className="cos-combobox-wrap"
      style={{ position: "relative", width: "100%", ...style }}
    >
      <input
        name={name}
        type="text"
        role="combobox" aria-label={name === "q" ? "Job title or keyword" : "Locations"} aria-expanded={open && filteredOptions.length > 0} aria-controls={dropdownId} aria-autocomplete="list" aria-activedescendant={open && filteredOptions[highlightIndex] ? `${dropdownId}-${highlightIndex}` : undefined}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setHighlightIndex(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setHighlightIndex((prev) => Math.min(prev + 1, Math.max(0, Math.min(40,filteredOptions.length) - 1)));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlightIndex((prev) => Math.max(prev - 1, 0));
          } else if (e.key === "Enter" && open && filteredOptions[highlightIndex]) {
            e.preventDefault();
            onChange(filteredOptions[highlightIndex].value);
            setOpen(false);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        className="cos-combobox-input"
        style={{ paddingRight: required ? "1.75rem" : "0.75rem" }}
        autoComplete="off"
      />
      {required ? (
        <span
          className="cos-required-badge"
          style={{
            position: "absolute",
            right: "0.65rem",
            top: "50%",
            transform: "translateY(-50%)",
            color: "#ef4444",
            fontWeight: 700,
            fontSize: "1rem",
            pointerEvents: "none",
            lineHeight: 1,
          }}
          title="Required field"
        >
          *
        </span>
      ) : null}

      {open && filteredOptions.length > 0 ? (
        <ul role="listbox" id={dropdownId} aria-label={name === "q" ? "Available job titles" : "Available locations"}
          className="cos-combobox-dropdown"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            maxHeight: "220px",
            overflowY: "auto",
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            boxShadow: "0 12px 32px rgba(0, 0, 0, 0.5)",
            zIndex: 100,
            padding: "0.35rem",
            margin: 0,
            listStyle: "none",
          }}
        >
          {filteredOptions.slice(0, 40).map((opt, idx) => {
            const isHighlighted = idx === highlightIndex;
            return (
              <li
                key={opt.value} id={`${dropdownId}-${idx}`} role="option" aria-selected={isHighlighted}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange(opt.value);
                  setOpen(false);
                }}
                onMouseEnter={() => setHighlightIndex(idx)}
                style={{
                  padding: "0.45rem 0.65rem",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "0.875rem",
                  color: isHighlighted ? "var(--accent)" : "var(--text)",
                  backgroundColor: isHighlighted ? "var(--bg-elevated)" : "transparent",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  transition: "background-color 0.12s ease",
                }}
              >
                <span>{opt.label ?? opt.value}</span>
                {opt.sublabel ? (
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: "0.5rem" }}>
                    {opt.sublabel}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

type MultiSelectComboboxProps = {
  name: string;
  selectedValues: string[];
  onChange: (vals: string[]) => void;
  options: ComboboxOption[];
  placeholder: string;
  required?: boolean;
  style?: React.CSSProperties;
};

export function MultiSelectCombobox({
  name,
  selectedValues,
  onChange,
  options,
  placeholder,
  required = false,
  style,
}: MultiSelectComboboxProps) {
  const [inputValue, setInputValue] = useState("");
  const dropdownId = useId();
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedSet = useMemo(
    () => new Set(selectedValues.map((v) => v.toLowerCase())),
    [selectedValues]
  );

  const filteredOptions = useMemo(() => {
    const query = inputValue.trim().toLowerCase();
    const available = options.filter((opt) => !selectedSet.has(opt.value.toLowerCase()));
    if (!query) return available;
    return available.filter(
      (opt) =>
        opt.value.toLowerCase().includes(query) ||
        (opt.label && opt.label.toLowerCase().includes(query))
    );
  }, [options, inputValue, selectedSet]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function addValue(val: string) {
    const clean = val.trim();
    if (!clean || !options.some(option=>option.value===clean)) return;
    if (!selectedValues.some((v) => v.toLowerCase() === clean.toLowerCase())) {
      onChange([...selectedValues, clean]);
    }
    setInputValue("");
    setOpen(false);
  }

  function removeValue(val: string) {
    onChange(selectedValues.filter((v) => v.toLowerCase() !== val.toLowerCase()));
  }

  return (
    <div
      ref={containerRef}
      className="cos-multiselect-combobox-wrap"
      style={{ position: "relative", width: "100%", ...style }}
    >
      <input type="hidden" name={name} value={selectedValues.join(", ")} />
      <div
        className="cos-multiselect-box"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "0.35rem",
          minHeight: "2.6rem",
          padding: "0.3rem 0.5rem",
          backgroundColor: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--cos-radius-control)",
          cursor: "text",
          position: "relative",
        }}
      >
        {selectedValues.map((val) => (
          <span
            key={val}
            className="cos-location-tag-pill"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.25rem",
              padding: "0.15rem 0.45rem",
              backgroundColor: "rgba(98, 221, 197, 0.15)",
              border: "1px solid rgba(98, 221, 197, 0.35)",
              color: "var(--accent)",
              borderRadius: "6px",
              fontSize: "0.8rem",
              fontWeight: 600,
            }}
          >
            {val}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeValue(val);
              }}
              style={{
                background: "none",
                border: 0,
                color: "var(--accent)",
                cursor: "pointer",
                padding: 0,
                fontSize: "0.85rem",
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          </span>
        ))}

        <input
          type="text"
        role="combobox" aria-label={name === "q" ? "Job title or keyword" : "Locations"} aria-expanded={open && filteredOptions.length > 0} aria-controls={dropdownId} aria-autocomplete="list" aria-activedescendant={open && filteredOptions[highlightIndex] ? `${dropdownId}-${highlightIndex}` : undefined}
          value={inputValue}
          placeholder={selectedValues.length === 0 ? placeholder : "Add location…"}
          onChange={(e) => {
            setInputValue(e.target.value);
            setOpen(true);
            setHighlightIndex(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (open && filteredOptions[highlightIndex]) {
                addValue(filteredOptions[highlightIndex].value);
              } else if (inputValue.trim()) {
                addValue(inputValue);
              }
            } else if (e.key === "Backspace" && !inputValue && selectedValues.length > 0) {
              removeValue(selectedValues[selectedValues.length - 1]);
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setHighlightIndex((prev) => Math.min(prev + 1, Math.max(0, Math.min(40,filteredOptions.length) - 1)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setHighlightIndex((prev) => Math.max(prev - 1, 0));
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          style={{
            flex: 1,
            minWidth: "120px",
            background: "transparent",
            border: 0,
            color: "var(--text)",
            fontSize: "0.875rem",
            outline: "none",
            padding: "0.2rem",
          }}
          autoComplete="off"
        />

        {required && selectedValues.length === 0 && !inputValue ? (
          <span
            style={{
              position: "absolute",
              right: "0.65rem",
              top: "50%",
              transform: "translateY(-50%)",
              color: "#ef4444",
              fontWeight: 700,
              fontSize: "1rem",
              pointerEvents: "none",
            }}
            title="Required field"
          >
            *
          </span>
        ) : null}
      </div>

      {open && filteredOptions.length > 0 ? (
        <ul role="listbox" id={dropdownId} aria-label={name === "q" ? "Available job titles" : "Available locations"}
          className="cos-combobox-dropdown"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            maxHeight: "220px",
            overflowY: "auto",
            backgroundColor: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            boxShadow: "0 12px 32px rgba(0, 0, 0, 0.5)",
            zIndex: 100,
            padding: "0.35rem",
            margin: 0,
            listStyle: "none",
          }}
        >
          {filteredOptions.slice(0, 40).map((opt, idx) => {
            const isHighlighted = idx === highlightIndex;
            return (
              <li
                key={opt.value} id={`${dropdownId}-${idx}`} role="option" aria-selected={isHighlighted}
                onMouseDown={(e) => {
                  e.preventDefault();
                  addValue(opt.value);
                }}
                onMouseEnter={() => setHighlightIndex(idx)}
                style={{
                  padding: "0.45rem 0.65rem",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "0.875rem",
                  color: isHighlighted ? "var(--accent)" : "var(--text)",
                  backgroundColor: isHighlighted ? "var(--bg-elevated)" : "transparent",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  transition: "background-color 0.12s ease",
                }}
              >
                <span>{opt.label ?? opt.value}</span>
                {opt.sublabel ? (
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: "0.5rem" }}>
                    {opt.sublabel}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

