import type { Tone } from "../components/tokens";
import { DeltaCell, TableScroll } from "../components/ui";

export interface Delta {
  qualified_name: string;
  base_score: number;
  head_score: number;
  delta: number;
  base_category: string | null;
  head_category: string | null;
}

export function MovementTable({
  title,
  rows,
  tone,
  goodWhenNegative,
}: {
  title: string;
  rows: Delta[];
  tone: (v: string | null | undefined) => Tone;
  goodWhenNegative: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <div style={{ marginTop: 8 }}>
      <div className="meta">
        <b>{title}</b>
      </div>
      <TableScroll>
        <table>
          <thead>
            <tr>
              <th>Component</th>
              <th>Base</th>
              <th>Head</th>
              <th>Δ</th>
              <th>Category</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.qualified_name}>
                <td className="meta">{c.qualified_name}</td>
                <td className="meta">{c.base_score.toFixed(1)}</td>
                <td className="meta">{c.head_score.toFixed(1)}</td>
                <DeltaCell value={c.delta} goodWhenNegative={goodWhenNegative} />
                <td className="meta">
                  {c.base_category} →{" "}
                  <span style={{ color: `var(--tone-${tone(c.head_category)})` }}>
                    {c.head_category}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
    </div>
  );
}
