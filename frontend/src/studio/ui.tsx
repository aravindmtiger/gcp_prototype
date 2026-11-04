import { useEffect, useState, type ReactNode } from 'react';
import { ApiError } from '../api';
import s from './studio.module.css';

export function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'Something went wrong';
}

/** Loads data on mount and whenever `reload()` is called. Ignores results after unmount. */
export function useLoad<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    load()
      .then((result) => {
        if (live) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (live) setError(messageOf(err));
      });
    return () => {
      live = false;
    };
    // `load` is recreated each render; `version` is the explicit trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  return { data, error, reload: () => setVersion((v) => v + 1) };
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className={s.pageHeader}>
      <div>
        <h1 className={s.title}>{title}</h1>
        {subtitle && <p className={s.subtitle}>{subtitle}</p>}
      </div>
      {actions && <div className={s.actions}>{actions}</div>}
    </div>
  );
}

export function PillTabs<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className={s.pillTabs} role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          className={`${s.pill} ${value === option.value ? s.pillActive : ''}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  in_review: 'In review',
  approved: 'Approved',
  rejected: 'Rejected',
  deployed: 'Deployed',
  pending: 'Pending',
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  passed: 'Passed',
  blocked: 'Blocked',
  connected: 'Connected',
  error: 'Error',
};

// Error reads as the failed style, so connection errors match failed runs.
const STATUS_STYLE: Record<string, string> = { error: 'failed' };

export function StatusBadge({ status }: { status: string }) {
  const style = s[STATUS_STYLE[status] ?? status] ?? '';
  return <span className={`${s.badge} ${style}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function ErrorBanner({ message }: { message: string | null }) {
  return message ? <div className={s.error}>{message}</div> : null;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className={s.empty}>{children}</div>;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export { s as studioStyles };
