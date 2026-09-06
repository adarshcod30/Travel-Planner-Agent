/**
 * A small Markdown renderer for the plans the graph produces.
 *
 * Deliberately not a library. The planner emits a known, narrow subset —
 * headings, bold, italics, lists, tables, rules — because its own renderer
 * writes it, so a 90-line converter covers everything and adds no dependency,
 * no bundle weight, and no sanitiser to reason about. Anything unrecognised
 * falls through as text rather than being interpreted.
 */

import React from "react";

function inline(text: string, key: string): React.ReactNode {
  // Bold first, then italics, so **a _b_** nests the way it reads.
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_|`[^`]+`)/g);
  return parts.map((part, i) => {
    const k = `${key}-${i}`;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={k}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("_") && part.endsWith("_")) return <em key={k}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={k}>{part.slice(1, -1)}</code>;
    return <React.Fragment key={k}>{part}</React.Fragment>;
  });
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split("\n");
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  let table: string[][] = [];

  const flushList = () => {
    if (!list.length) return;
    out.push(
      <ul key={`ul-${out.length}`}>
        {list.map((item, i) => (
          <li key={i}>{inline(item, `li-${out.length}-${i}`)}</li>
        ))}
      </ul>,
    );
    list = [];
  };

  const flushTable = () => {
    if (!table.length) return;
    const [head, ...body] = table;
    out.push(
      <div key={`tw-${out.length}`} className="overflow-x-auto">
        <table>
          <thead>
            <tr>{head.map((c, i) => <th key={i}>{inline(c, `th-${i}`)}</th>)}</tr>
          </thead>
          <tbody>
            {body.map((row, r) => (
              <tr key={r}>{row.map((c, i) => <td key={i}>{inline(c, `td-${r}-${i}`)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
    table = [];
  };

  const flushAll = () => {
    flushList();
    flushTable();
  };

  for (const raw of lines) {
    const line = raw.trimEnd();

    if (line.startsWith("|")) {
      const cells = line.split("|").slice(1, -1).map((c) => c.trim());
      // The |---|---| separator row carries no data.
      if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) table.push(cells);
      continue;
    }
    flushTable();

    if (line.startsWith("- ")) {
      list.push(line.slice(2));
      continue;
    }
    flushList();

    if (!line.trim()) continue;
    if (line.startsWith("### ")) out.push(<h3 key={out.length}>{inline(line.slice(4), `h3-${out.length}`)}</h3>);
    else if (line.startsWith("## ")) out.push(<h2 key={out.length}>{inline(line.slice(3), `h2-${out.length}`)}</h2>);
    else if (line.startsWith("# ")) out.push(<h1 key={out.length}>{inline(line.slice(2), `h1-${out.length}`)}</h1>);
    else if (/^-{3,}$/.test(line.trim())) out.push(<hr key={out.length} />);
    else out.push(<p key={out.length}>{inline(line, `p-${out.length}`)}</p>);
  }
  flushAll();

  return <div className="plan">{out}</div>;
}
