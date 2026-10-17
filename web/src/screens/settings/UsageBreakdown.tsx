import type { UsagePeriod } from "../../api/types.ts";
import { tokens } from "../../format.ts";
import { Loading, PageFrame, Row, Section } from "./rows.tsx";
import { periodTitle, probesLine, projectRows, share } from "./usageText.ts";
import { useUsage } from "./useUsage.ts";

/** Where the shown period's tokens went: by who, by kind and by project (B84). */
export function UsageBreakdown({ onBack }: { onBack: () => void }) {
  const today = new Date();
  const { unit, date, period } = useUsage(today);
  return (
    <PageFrame
      title={`${periodTitle(unit, date, today)} tokens`}
      back="Usage"
      onBack={onBack}
      extra={period !== null && <b className="stot">{tokens(period.tokens.total)}</b>}
    >
      {period === null ? <Loading title="By who" /> : <Breakdown period={period} />}
    </PageFrame>
  );
}

function Breakdown({ period }: { period: UsagePeriod }) {
  const { tokens: all, subagents } = period;
  const total = all.total;
  const part = (label: string, value: number) => (
    <Row key={label} label={label}>
      <span className="sval num">{tokens(value)}</span>
      <span className="ushr">{share(value, total)}</span>
    </Row>
  );
  const projects = projectRows(period.projects);
  const peak = projects[0]?.tokens ?? 0;
  const probes = probesLine(period.probes);
  return (
    <>
      <Section title="By who">
        {part("Chats", total - subagents.total)}
        {part("Subagents", subagents.total)}
      </Section>
      <Section title="By kind">
        {part("Cache read", all.cache_read_input_tokens)}
        {part("Cache write", all.cache_creation_input_tokens)}
        {part("Output", all.output_tokens)}
        {part("Input", all.input_tokens)}
      </Section>
      <Section title="By project">
        {projects.length === 0 ? (
          <div className="srow note">No tokens in this period</div>
        ) : (
          projects.map((p) => (
            <div key={p.name} className="srow col uproj">
              <div className="u1">
                <span>{p.name}</span>
                <b className="num">{tokens(p.tokens)}</b>
              </div>
              <div className="meter sm ink" aria-hidden="true">
                <i style={{ width: `${String(Math.min(100, (100 * p.tokens) / peak))}%` }} />
              </div>
            </div>
          ))
        )}
      </Section>
      {probes !== null && <p className="note uprobe">{probes}</p>}
    </>
  );
}
