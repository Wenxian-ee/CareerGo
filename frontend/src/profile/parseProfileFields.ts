/** Live editing: split on newline/comma/semicolon but do not trim — preserves spaces while typing. */
export function parseListInputLive(s: string): string[] {
  const parts: string[] = [];
  for (const segment of s.split(/\n/)) {
    for (const piece of segment.split(/[,;]/)) {
      if (piece.length > 0) parts.push(piece);
    }
  }
  return parts;
}

/** Persist: trim each item and drop empties. */
export function normalizeStringList(items: string[]): string[] {
  return items.map((x) => x.trim()).filter(Boolean);
}

/** @deprecated use parseListInputLive + normalizeStringList on save */
export function parseListInput(s: string): string[] {
  return normalizeStringList(parseListInputLive(s));
}

/** Live: one cert per line / semicolon; no trim. */
export function parseCertLinesLive(s: string): string[] {
  return s.split(/\n|;/).filter((line) => line.length > 0);
}

export function normalizeCertList(items: string[]): string[] {
  return items.map((x) => x.trim()).filter(Boolean);
}

/** @deprecated */
export function parseCertLines(s: string): string[] {
  return normalizeCertList(parseCertLinesLive(s));
}

/** Live: one line per bullet; keep spaces; keep empty lines as empty strings until save. */
export function parseMultilineLive(s: string): string[] {
  return s.split('\n');
}

export function normalizeMultilineLines(lines: string[]): string[] {
  return lines.map((x) => x.trim()).filter(Boolean);
}

/** @deprecated */
export function parseMultilineItems(s: string): string[] {
  return normalizeMultilineLines(parseMultilineLive(s));
}

/** Parse languages textarea on save. */
export function parseLanguagesForSave(text: string): Record<string, string> {
  const o: Record<string, string> = {};
  text.split('\n').forEach((line) => {
    const m = line.split(/[:]/);
    if (m.length >= 2 && m[0].trim()) o[m[0].trim()] = m.slice(1).join(':').trim();
  });
  return o;
}
