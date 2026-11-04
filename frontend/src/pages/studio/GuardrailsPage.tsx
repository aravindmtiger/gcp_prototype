import { useState, type FormEvent } from 'react';
import { api } from '../../api';
import { EmptyState, ErrorBanner, PageHeader, formatDate, messageOf, useLoad, studioStyles as s } from '../../studio/ui';
import type { GuardrailProvider, GuardrailTemplate } from '../../types';

type Protection = 'prompt_injection' | 'jailbreak';

const PROTECTIONS: { value: Protection; title: string; hint: string }[] = [
  { value: 'prompt_injection', title: 'Prompt injection', hint: 'Blocks prompts that try to override the agent’s instructions.' },
  { value: 'jailbreak', title: 'Jailbreak', hint: 'Blocks attempts to bypass the agent’s safety rules.' },
];

const PROVIDER_TITLE: Record<GuardrailProvider, string> = {
  model_armor: 'Model Armor',
  sdp: 'Sensitive Data Protection',
};

const PROVIDERS: { value: GuardrailProvider; hint: string }[] = [
  { value: 'model_armor', hint: 'Screens prompts and replies for attacks and unsafe content.' },
  { value: 'sdp', hint: 'Finds and masks personal and sensitive data.' },
];

interface CustomRow {
  name: string;
  regex: string;
}

/** Checkbox tile. The native checkbox stays visible so the choice is obvious at a glance. */
function CheckTile({ checked, title, hint, onToggle }: { checked: boolean; title: string; hint: string; onToggle: () => void }) {
  return (
    <label className={`${s.choice} ${checked ? s.choiceActive : ''}`}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input type="checkbox" checked={checked} onChange={onToggle} style={{ accentColor: '#f7931e', width: 16, height: 16 }} />
        <span className={s.choiceTitle}>{title}</span>
      </span>
      <span className={s.choiceHint}>{hint}</span>
    </label>
  );
}

export function GuardrailsPage() {
  const guardrails = useLoad(api.listGuardrails);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [providers, setProviders] = useState<GuardrailProvider[]>(['model_armor']);
  const [protections, setProtections] = useState<Protection[]>(['prompt_injection', 'jailbreak']);
  const [infoTypes, setInfoTypes] = useState('');
  const [custom, setCustom] = useState<CustomRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const usesArmor = providers.includes('model_armor');
  const usesSdp = providers.includes('sdp');

  const toggle = <T extends string>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value];

  const reset = () => {
    setName('');
    setProviders(['model_armor']);
    setProtections(['prompt_injection', 'jailbreak']);
    setInfoTypes('');
    setCustom([]);
    setError(null);
  };

  const problem = (() => {
    if (!name.trim()) return 'Give the guardrail a name';
    if (usesArmor && protections.length === 0) return 'Choose at least one Model Armor check';
    const hasTypes = infoTypes.trim() || custom.some((c) => c.name.trim() && c.regex.trim());
    if (usesSdp && !hasTypes) return 'Add at least one data type for Sensitive Data Protection';
    return null;
  })();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    try {
      await api.createGuardrail({
        name: name.trim(),
        providers,
        ...(usesArmor ? { protections } : {}),
        ...(usesSdp
          ? {
              info_types: infoTypes.split(',').map((t) => t.trim()).filter(Boolean),
              custom_infotypes: custom.filter((c) => c.name.trim() && c.regex.trim()),
            }
          : {}),
      });
      reset();
      setCreating(false);
      guardrails.reload();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={s.page}>
      <PageHeader
        title="Guardrails"
        subtitle="Screen prompts and replies before they reach a model."
        actions={(
          <button type="button" className={s.btnPrimary} onClick={() => setCreating((v) => !v)}>
            {creating ? 'Cancel' : 'New guardrail'}
          </button>)}
      />
      <ErrorBanner message={error ?? guardrails.error} />

      {creating && (
        <form className={s.card} style={{ marginBottom: 18 }} onSubmit={submit}>
          <div className={s.form}>
            <label className={s.field}>
              Name
              <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="customer-support" />
            </label>

            <div>
              <p className={s.sectionTitle}>Screening</p>
              <div className={s.choices}>
                {PROVIDERS.map((option) => (
                  <CheckTile
                    key={option.value}
                    checked={providers.includes(option.value)}
                    title={PROVIDER_TITLE[option.value]}
                    hint={option.hint}
                    onToggle={() => setProviders((current) => toggle(current, option.value))}
                  />
                ))}
              </div>
            </div>

            {usesArmor && (
              <div>
                <p className={s.sectionTitle}>Model Armor checks</p>
                <div className={s.choices}>
                  {PROTECTIONS.map((option) => (
                    <CheckTile
                      key={option.value}
                      checked={protections.includes(option.value)}
                      title={option.title}
                      hint={option.hint}
                      onToggle={() => setProtections((current) => toggle(current, option.value))}
                    />
                  ))}
                </div>
              </div>
            )}

            {usesSdp && (
              <div style={{ display: 'grid', gap: 12 }}>
                <p className={s.sectionTitle}>Sensitive Data Protection types</p>
                <label className={s.field}>
                  Built-in types
                  <input className={s.input} value={infoTypes} onChange={(e) => setInfoTypes(e.target.value)} placeholder="EMAIL_ADDRESS, PHONE_NUMBER" />
                  <span className={s.muted}>Separate with commas.</span>
                </label>
                {custom.map((row, index) => (
                  <div key={index} style={{ display: 'grid', gridTemplateColumns: '1fr 2fr auto', gap: 8 }}>
                    <input
                      className={s.input}
                      placeholder="EMPLOYEE_ID"
                      value={row.name}
                      onChange={(e) => setCustom((c) => c.map((r, i) => (i === index ? { ...r, name: e.target.value } : r)))}
                    />
                    <input
                      className={s.input}
                      placeholder="[A-Z]{2}\d{6}"
                      value={row.regex}
                      onChange={(e) => setCustom((c) => c.map((r, i) => (i === index ? { ...r, regex: e.target.value } : r)))}
                    />
                    <button type="button" className={s.btnGhost} onClick={() => setCustom((c) => c.filter((_, i) => i !== index))}>
                      Remove
                    </button>
                  </div>
                ))}
                <button type="button" className={s.btnGhost} style={{ justifySelf: 'start' }} onClick={() => setCustom((c) => [...c, { name: '', regex: '' }])}>
                  Add custom type
                </button>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12 }}>
              {problem && <span className={s.muted}>{problem}</span>}
              <button type="submit" className={s.btnPrimary} disabled={busy || problem !== null || providers.length === 0}>
                Save guardrail
              </button>
            </div>
          </div>
        </form>
      )}

      {(guardrails.data ?? []).length === 0 && !guardrails.error ? (
        <EmptyState>No guardrails yet.</EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Screening</th>
              <th>Owner</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {(guardrails.data ?? []).map((template) => (
              <tr key={template.id}>
                <td>
                  <strong>{template.name}</strong> {template.is_default && <span className={s.tag}>Default</span>}
                </td>
                <td>{describe(template)}</td>
                <td className={s.muted}>{template.owner_email}</td>
                <td className={s.muted}>{formatDate(template.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const PROTECTION_TITLE = Object.fromEntries(PROTECTIONS.map((p) => [p.value, p.title])) as Record<Protection, string>;

function describe(template: GuardrailTemplate) {
  const protections = template.config.protections ?? [];
  const infotypes = [...(template.config.info_types ?? []), ...(template.config.custom_infotypes ?? []).map((c) => c.name)];
  return (
    <>
      {template.providers.map((p) => (
        <span key={p} className={s.tag}>{PROVIDER_TITLE[p]}</span>
      ))}
      {protections.map((p) => (
        <span key={p} className={s.tag}>{PROTECTION_TITLE[p]}</span>
      ))}
      {infotypes.map((t) => (
        <span key={t} className={s.tag}>{t}</span>
      ))}
    </>
  );
}
