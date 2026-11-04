import { useState } from 'react';
import { api } from '../../api';
import { useSession } from '../../session';
import { EmptyState, ErrorBanner, PageHeader, PillTabs, StatusBadge, formatDate, messageOf, useLoad, studioStyles as s } from '../../studio/ui';

type Scope = 'assigned' | 'requested';

export function ApprovalsPage() {
  const { email: me, isAdmin } = useSession();
  // Platform users only see their own requests. Admins start on the review queue.
  const [scope, setScope] = useState<Scope>(isAdmin ? 'assigned' : 'requested');
  const approvals = useLoad(() => api.listApprovals(scope));
  const [comments, setComments] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  // Admins decide the review queue. Anyone can decide their own submission.
  const canDecide = (requestedBy: string) => isAdmin || requestedBy === me;

  const decide = async (approvalId: string, decision: 'approve' | 'reject') => {
    setError(null);
    try {
      await api.decideApproval(approvalId, decision, comments[approvalId] ?? '');
      approvals.reload();
    } catch (err) {
      setError(messageOf(err));
    }
  };

  const showDecisionColumn = true;

  return (
    <div className={s.page}>
      <PageHeader title="Approvals" subtitle={isAdmin ? 'Agents waiting for review, and your own requests.' : 'Your submitted agents.'} />
      <div className={s.toolbar}>
        {isAdmin ? (
          <PillTabs<Scope>
            value={scope}
            onChange={setScope}
            options={[
              { value: 'assigned', label: 'Review queue' },
              { value: 'requested', label: 'My requests' },
            ]}
          />
        ) : null}
      </div>
      <ErrorBanner message={error ?? approvals.error} />

      {(approvals.data ?? []).length === 0 && !approvals.error ? (
        <EmptyState>{scope === 'assigned' ? 'No agents are waiting for review.' : 'You have not submitted any agents.'}</EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Submitted by</th>
              <th>Reviewer</th>
              <th>Submitted</th>
              <th>Status</th>
              {showDecisionColumn && <th>Decision</th>}
            </tr>
          </thead>
          <tbody>
            {(approvals.data ?? []).map((approval) => (
              <tr key={approval.id}>
                <td><strong>{approval.agent_name}</strong></td>
                <td className={s.muted}>{approval.requested_by}</td>
                <td className={s.muted}>Admins</td>
                <td className={s.muted}>{formatDate(approval.created_at)}</td>
                <td>
                  <StatusBadge status={approval.status} />
                  {approval.decision_comment && <div className={s.muted}>“{approval.decision_comment}”</div>}
                </td>
                {showDecisionColumn && (
                  <td>
                    {!canDecide(approval.requested_by) ? (
                      <span className={s.muted}>{approval.status === 'pending' ? '' : `by ${approval.decided_by}`}</span>
                    ) : approval.status === 'pending' ? (
                      <div style={{ display: 'grid', gap: 6 }}>
                        <input
                          className={s.input}
                          placeholder="Comment"
                          value={comments[approval.id] ?? ''}
                          onChange={(e) => setComments((c) => ({ ...c, [approval.id]: e.target.value }))}
                        />
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button type="button" className={s.btnPrimary} onClick={() => decide(approval.id, 'approve')}>Approve</button>
                          <button type="button" className={s.btnDanger} onClick={() => decide(approval.id, 'reject')}>Reject</button>
                        </div>
                      </div>
                    ) : (
                      <span className={s.muted}>by {approval.decided_by}</span>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
