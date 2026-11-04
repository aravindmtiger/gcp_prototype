import { useEffect, useState } from 'react';
import { api } from '../../api';
import { appConfig } from '../../config';
import type { ExporterStatus, ObservabilitySummary, TraceDetail, TraceSpan, TraceSummaryRow, CloudTraceRow } from '../../types';
import { EmptyState, ErrorBanner, PageHeader, PillTabs, StatusBadge, formatDate, messageOf, useLoad, studioStyles as s } from '../../studio/ui';
import { AgentCallsPanel } from './AgentCallsPanel';

type Tab = 'overview' | 'traces' | 'agent-calls' | 'cloud-trace' | 'exporters';

const TABS: { value: Tab; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'traces', label: 'Traces' },
  { value: 'agent-calls', label: 'Agent calls' },
  { value: 'cloud-trace', label: 'Cloud Trace' },
  { value: 'exporters', label: 'Exporters' },
];

/** Observability: metrics, OpenTelemetry traces (OTLP ingest), Cloud Trace, and exporter setup. */
export function ObservabilityPage() {
  const [tab, setTab] = useState<Tab>('overview');
  return (
    <div className={s.page}>
      <PageHeader title="Observability" subtitle="Traces, metrics and model usage for your agents." />
      <div className={s.toolbar}>
        <PillTabs<Tab> value={tab} onChange={setTab} options={TABS} />
      </div>
      {tab === 'overview' && <OverviewTab />}
      {tab === 'traces' && <TracesTab />}
      {tab === 'agent-calls' && <AgentCallsPanel />}
      {tab === 'cloud-trace' && <CloudTraceTab />}
      {tab === 'exporters' && <ExportersTab />}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.metric}>
      <div className={s.metricValue}>{value}</div>
      <div className={s.metricLabel}>{label}</div>
    </div>
  );
}

const ms = (value: number | null) => (value === null ? '—' : `${Math.round(value)} ms`);

function OverviewTab() {
  const [hours, setHours] = useState(24);
  const summary = useLoad(() => api.traceSummary(hours));
  const data: ObservabilitySummary | null = summary.data;
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <span className={s.muted}>Window</span>
        <select className={s.select} value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Time window">
          <option value={1}>Last hour</option>
          <option value={24}>Last 24 hours</option>
          <option value={168}>Last 7 days</option>
        </select>
      </div>
      <ErrorBanner message={summary.error} />
      {data && (
        <>
          <div className={s.metrics}>
            <Metric label="Traces" value={String(data.traces)} />
            <Metric label="Spans" value={String(data.spans)} />
            <Metric label="Error rate" value={`${Math.round(data.error_rate * 100)}%`} />
            <Metric label="Latency p50" value={ms(data.p50_ms)} />
            <Metric label="Latency p95" value={ms(data.p95_ms)} />
            <Metric label="Input tokens" value={data.input_tokens.toLocaleString()} />
            <Metric label="Output tokens" value={data.output_tokens.toLocaleString()} />
          </div>
          <div className={s.card} style={{ display: 'grid', gap: 12 }}>
            <strong>Model usage</strong>
            {data.by_model.length === 0 ? (
              <span className={s.muted}>No model calls in this window.</span>
            ) : (
              data.by_model.map((row) => (
                <div key={row.model} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{row.model}</span>
                  <span className={s.muted}>{row.spans} spans</span>
                </div>
              ))
            )}
          </div>
          <div className={s.card} style={{ display: 'grid', gap: 12 }}>
            <strong>Services</strong>
            {Object.keys(data.by_service).length === 0 ? (
              <span className={s.muted}>No services reported spans in this window.</span>
            ) : (
              Object.entries(data.by_service).map(([service, count]) => (
                <div key={service} style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>{service}</span>
                  <span className={s.muted}>{count} spans</span>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** Waterfall: each span as a bar, placed by its start time within the trace. */
function Waterfall({ spans }: { spans: TraceSpan[] }) {
  const byId = new Map(spans.map((span) => [span.span_id, span]));
  const depth = (span: TraceSpan): number => {
    let level = 0;
    let parent = span.parent_span_id ? byId.get(span.parent_span_id) : undefined;
    while (parent && level < 50) {
      level += 1;
      parent = parent.parent_span_id ? byId.get(parent.parent_span_id) : undefined;
    }
    return level;
  };
  const start = Math.min(...spans.map((x) => Date.parse(x.start_time)));
  const end = Math.max(...spans.map((x) => Date.parse(x.end_time)));
  const total = Math.max(end - start, 1);

  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {spans.map((span) => {
        const left = ((Date.parse(span.start_time) - start) / total) * 100;
        const width = Math.max((span.duration_ms / total) * 100, 0.5);
        return (
          <div key={span.span_id} style={{ display: 'grid', gridTemplateColumns: '260px 1fr 90px', gap: 10, alignItems: 'center' }}>
            <span style={{ paddingLeft: depth(span) * 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {span.name}
              <span className={s.muted}> · {span.service_name || 'service?'}</span>
            </span>
            <div style={{ position: 'relative', height: 14, background: '#f1f1f5', borderRadius: 6 }}>
              <div
                style={{
                  position: 'absolute',
                  left: `${left}%`,
                  width: `${width}%`,
                  height: '100%',
                  borderRadius: 6,
                  background: span.status_code === 'error' ? '#e05a4f' : '#4f7fc4',
                }}
              />
            </div>
            <span className={s.muted} style={{ textAlign: 'right' }}>{Math.round(span.duration_ms)} ms</span>
          </div>
        );
      })}
    </div>
  );
}

function TracesTab() {
  const traces = useLoad(api.listTraces);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDetail(null);
    api.getTrace(open).then(setDetail).catch((err: unknown) => setError(messageOf(err)));
  }, [open]);

  const rows: TraceSummaryRow[] = traces.data ?? [];
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <ErrorBanner message={error ?? traces.error} />
      {rows.length === 0 ? (
        <EmptyState>No traces yet. Point an OpenTelemetry exporter at this server's /v1/traces endpoint (see Exporters).</EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Root span</th>
              <th>Service</th>
              <th>Started</th>
              <th>Duration</th>
              <th>Spans</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.trace_id} className={s.clickableRow} onClick={() => setOpen(open === row.trace_id ? null : row.trace_id)}>
                <td><strong>{row.root_name}</strong><div className={s.muted}>{row.trace_id}</div></td>
                <td className={s.muted}>{row.service_name || '—'}</td>
                <td className={s.muted}>{formatDate(row.started_at)}</td>
                <td className={s.muted}>{Math.round(row.duration_ms)} ms</td>
                <td className={s.muted}>{row.span_count}</td>
                <td><StatusBadge status={row.has_error ? 'failed' : 'succeeded'} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && (
        <div className={s.card} style={{ display: 'grid', gap: 12 }}>
          <strong>Trace {open}</strong>
          {detail ? <Waterfall spans={detail.spans} /> : <span className={s.muted}>Loading spans…</span>}
        </div>
      )}
    </div>
  );
}

function CloudTraceTab() {
  const rows = useLoad(api.listCloudTraces);
  const data: CloudTraceRow[] = rows.data ?? [];
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <span className={s.muted}>Recent traces in Cloud Trace for the configured project.</span>
      <ErrorBanner message={rows.error} />
      {data.length === 0 && !rows.error ? (
        <EmptyState>No traces in Cloud Trace yet.</EmptyState>
      ) : (
        data.length > 0 && (
          <table className={s.table}>
            <thead>
              <tr>
                <th>Root span</th>
                <th>Trace</th>
                <th>Started</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.trace_id}>
                  <td>{row.root_span || '—'}</td>
                  <td className={s.muted}>{row.trace_id}</td>
                  <td className={s.muted}>{row.start_time ? formatDate(row.start_time) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </div>
  );
}

function ExportersTab() {
  const status = useLoad(api.exporterStatus);
  const data: ExporterStatus | null = status.data;
  const endpoint = `${appConfig.apiBaseUrl}${data?.ingest_path ?? '/v1/traces'}`;
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <ErrorBanner message={status.error} />
      {data && (
        <div className={s.card} style={{ display: 'grid', gap: 10 }}>
          <div>Tracing: <StatusBadge status={data.tracing_enabled ? 'succeeded' : 'unset'} /> exporter <strong>{data.exporter}</strong></div>
          <div className={s.muted}>Cloud Trace project: {data.cloud_trace_project ?? 'not set (GCP_PROJECT_ID)'}</div>
        </div>
      )}
      <div className={s.card} style={{ display: 'grid', gap: 10 }}>
        <strong>OTLP ingestion</strong>
        <span className={s.muted}>
          Send traces to this endpoint over OTLP/HTTP. It accepts {data?.accepted_formats.join(' or ') ?? 'protobuf or JSON'}.
          Authenticate with the same Authorization header the API uses.
        </span>
        <code className={s.pre} style={{ padding: 10, background: '#fafafc', borderRadius: 10 }}>{endpoint}</code>
        <span className={s.muted}>Environment for an OpenTelemetry SDK:</span>
        <pre className={s.pre} style={{ padding: 10, background: '#fafafc', borderRadius: 10 }}>
{`OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${endpoint}
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <token>"`}
        </pre>
      </div>
      <div className={s.card} style={{ display: 'grid', gap: 6 }}>
        <strong>Exporting this server's own traces</strong>
        <span className={s.muted}>
          Set OTEL_ENABLED=true and OTEL_EXPORTER to console, gcp (Cloud Trace), or otlp (with OTEL_OTLP_ENDPOINT).
        </span>
      </div>
    </div>
  );
}
