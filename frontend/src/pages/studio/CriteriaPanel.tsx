import { api } from '../../api';
import type { Criterion } from '../../lib/evaluation';
import { EmptyState, ErrorBanner, useLoad, studioStyles as s } from '../../studio/ui';
import type { EvalMetric } from '../../types';

const REQUIRES_HINT: Record<EvalMetric['requires'], string> = {
  expected_response: 'Needs an expected reply in each case',
  expected_tools: 'Needs the expected tool calls in each case',
  rubrics: 'Scored against the rubrics you write below',
  none: 'Needs no expected values',
};

/**
 * Criteria and thresholds, as in the ADK web UI's evaluate screen. The list comes from the
 * installed ADK, so it always matches the server.
 */
export function CriteriaPanel({ value, onChange }: { value: Criterion[]; onChange: (next: Criterion[]) => void }) {
  const metrics = useLoad(api.listEvalMetrics);

  const find = (key: string) => value.find((c) => c.key === key);
  const update = (key: string, patch: Partial<Criterion>, base: EvalMetric) => {
    const current = find(key) ?? { key, enabled: false, threshold: base.default_threshold, rubrics: [] };
    const next = { ...current, ...patch };
    onChange([...value.filter((c) => c.key !== key), next]);
  };

  if (metrics.error) return <ErrorBanner message={metrics.error} />;
  if ((metrics.data ?? []).length === 0) return <EmptyState>Loading criteria…</EmptyState>;

  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {(metrics.data ?? []).map((metric) => {
        const current = find(metric.key);
        const enabled = current?.enabled ?? false;
        const threshold = current?.threshold ?? metric.default_threshold;
        const rubrics = current?.rubrics ?? [];
        return (
          <div key={metric.key} className={s.choice} style={{ cursor: 'default', borderColor: enabled ? '#f7931e' : undefined }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => update(metric.key, { enabled: e.target.checked }, metric)}
                style={{ accentColor: '#f7931e', width: 16, height: 16 }}
                aria-label={metric.label}
              />
              <strong className={s.choiceTitle}>{metric.label}</strong>
              <span className={s.tag}>{metric.key}</span>
              <span style={{ marginLeft: 'auto' }} className={s.muted}>
                Threshold
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  className={s.input}
                  style={{ width: 90, marginLeft: 8 }}
                  value={threshold}
                  disabled={!enabled}
                  onChange={(e) => update(metric.key, { threshold: Number(e.target.value) }, metric)}
                />
              </span>
            </div>
            <span className={s.choiceHint}>
              {metric.description} {REQUIRES_HINT[metric.requires]}.
            </span>
            {metric.requires === 'rubrics' && enabled && (
              <div style={{ display: 'grid', gap: 6 }}>
                {rubrics.map((text, index) => (
                  <div key={index} style={{ display: 'flex', gap: 8 }}>
                    <input
                      className={s.input}
                      style={{ flex: 1 }}
                      value={text}
                      placeholder="The reply names the refund window"
                      onChange={(e) =>
                        update(metric.key, { rubrics: rubrics.map((r, i) => (i === index ? e.target.value : r)) }, metric)
                      }
                      aria-label={`Rubric ${index + 1} for ${metric.label}`}
                    />
                    <button
                      type="button"
                      className={s.btnGhost}
                      onClick={() => update(metric.key, { rubrics: rubrics.filter((_, i) => i !== index) }, metric)}
                    >
                      Remove
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className={s.btnGhost}
                  style={{ justifySelf: 'start' }}
                  onClick={() => update(metric.key, { rubrics: [...rubrics, ''] }, metric)}
                >
                  Add rubric
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
