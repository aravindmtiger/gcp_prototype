import { useMemo, useState } from 'react';
import { api } from '../../api';
import { EmptyState, ErrorBanner, PageHeader, PillTabs, formatDate, messageOf, useLoad, studioStyles as s } from '../../studio/ui';
import type { KnowledgeSource } from '../../types';

type Kind = 'structured' | 'unstructured';

export function KnowledgeStudioPage() {
  const sources = useLoad(api.listKnowledge);
  const [kind, setKind] = useState<Kind>('unstructured');
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const corpora = useLoad(api.listRagCorpora);
  const tables = useLoad(api.listBigQueryTables);
  const [location, setLocation] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const rows: KnowledgeSource[] = useMemo(
    () => (sources.data ?? []).filter((source) => source.kind === kind),
    [sources.data, kind],
  );

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const config: Record<string, string> =
        kind === 'structured' ? { backend: 'bigquery', table_ref: location } : { rag_corpus: location };
      await api.createKnowledge({ name, description, kind, config });
      setCreating(false);
      setName('');
      setDescription('');
      setLocation('');
      sources.reload();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={s.page}>
      <PageHeader
        title="Knowledge"
        subtitle="Tables for the SQL executor, documents for the retriever."
        actions={(
          <button type="button" className={s.btnPrimary} onClick={() => setCreating((v) => !v)}>
            {creating ? 'Close' : '+ Add data store'}
          </button>)}
      />
      <div className={s.toolbar}>
        <PillTabs<Kind>
          value={kind}
          onChange={(value) => {
            setKind(value);
            setCreating(false);
          }}
          options={[
            { value: 'unstructured', label: 'Unstructured documents' },
            { value: 'structured', label: 'Structured tables' },
          ]}
        />
      </div>
      <ErrorBanner message={error ?? sources.error} />

      {creating && (
        <form
          className={s.card}
          style={{ marginBottom: 18 }}
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className={s.form}>
            <label className={s.field}>
              Data store name
              <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} required />
            </label>
            <label className={s.field}>
              Description
              <input className={s.input} value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            {kind === 'structured' ? (
              <label className={s.field}>
                BigQuery table
                <select className={s.select} value={location} onChange={(e) => setLocation(e.target.value)} required>
                  <option value="">Choose a table…</option>
                  {(tables.data ?? []).map((table) => (
                    <option key={table.table_ref} value={table.table_ref}>{table.table_ref}</option>
                  ))}
                </select>
                {tables.error && <span className={s.muted}>{tables.error}</span>}
              </label>
            ) : (
              <label className={s.field}>
                RAG corpus
                <select className={s.select} value={location} onChange={(e) => setLocation(e.target.value)} required>
                  <option value="">Choose a corpus…</option>
                  {(corpora.data ?? []).map((corpus) => (
                    <option key={corpus.name} value={corpus.name}>{corpus.display_name}</option>
                  ))}
                </select>
                {corpora.error && <span className={s.muted}>{corpora.error}</span>}
              </label>
            )}
            <button type="submit" className={s.btnPrimary} disabled={busy || !name.trim() || !location.trim()} style={{ justifySelf: 'start' }}>
              Save data store
            </button>
          </div>
        </form>
      )}

      {rows.length === 0 && !sources.error ? (
        <EmptyState>No {kind} data stores yet.</EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>{kind === 'structured' ? 'Table' : 'Corpus'}</th>
              <th>Description</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((source) => (
              <tr key={source.id}>
                <td><strong>{source.name}</strong></td>
                <td className={s.muted}>{source.config.table_ref ?? source.config.rag_corpus}</td>
                <td className={s.muted}>{source.description}</td>
                <td className={s.muted}>{formatDate(source.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
