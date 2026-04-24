/**
 * A controlled numeric input that keeps an internal string buffer so the user
 * can freely backspace, clear, and retype the value without getting stuck on "0".
 *
 * - While the field is focused the raw string drives the display.
 * - onChange is called whenever the raw string parses to a valid finite number.
 * - On blur, if the field is empty or invalid it snaps to `fallback` (default 0),
 *   clamped to [min, max] if those props are provided.
 * - When the parent `value` changes while the field is NOT focused (e.g. form
 *   reset), the display is synced from the parent.
 */
import { useEffect, useRef, useState } from 'react';

interface NumericInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'> {
  value: number;
  onChange: (value: number) => void;
  /** Value used when the field is left blank on blur. Defaults to 0. */
  fallback?: number;
}

export function NumericInput({ value, onChange, fallback = 0, onBlur, min, max, step, ...rest }: NumericInputProps) {
  const [raw, setRaw] = useState(String(value));
  const focused = useRef(false);

  // Sync display from parent when the field is not being edited
  useEffect(() => {
    if (!focused.current) {
      setRaw(String(value));
    }
  }, [value]);

  function clamp(n: number): number {
    let result = n;
    if (min !== undefined && min !== null) result = Math.max(Number(min), result);
    if (max !== undefined && max !== null) result = Math.min(Number(max), result);
    return result;
  }

  return (
    <input
      {...rest}
      type="number"
      min={min}
      max={max}
      step={step}
      value={raw}
      onFocus={() => {
        focused.current = true;
      }}
      onChange={(e) => {
        const v = e.target.value;
        setRaw(v);
        const n = parseFloat(v);
        if (isFinite(n)) onChange(clamp(n));
      }}
      onBlur={(e) => {
        focused.current = false;
        const n = parseFloat(raw);
        const final = clamp(isFinite(n) ? n : fallback);
        setRaw(String(final));
        onChange(final);
        onBlur?.(e);
      }}
    />
  );
}
