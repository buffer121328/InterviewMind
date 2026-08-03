export interface InterviewSeriesSession {
  session_id: string;
  title: string;
  updated_at: string;
  status: 'active' | 'completed' | 'archived';
  round_index?: number;
  series_id?: string;
  parent_session_id?: string;
  company_info?: string;
}

export interface InterviewSeriesGroup<T extends InterviewSeriesSession> {
  key: string;
  companyLabel: string;
  updatedAt: string;
  rounds: T[];
}

/** Group only explicitly linked rounds; matching company text never merges sessions. */
export function groupInterviewSeries<T extends InterviewSeriesSession>(sessions: T[]): InterviewSeriesGroup<T>[] {
  const byKey = new Map<string, T[]>();
  for (const session of sessions) {
    const key = session.series_id?.trim() || session.session_id;
    const current = byKey.get(key) || [];
    current.push(session);
    byKey.set(key, current);
  }
  return [...byKey.entries()]
    .map(([key, rounds]) => {
      rounds.sort((a, b) => (a.round_index || 1) - (b.round_index || 1));
      const latest = rounds.reduce((winner, item) =>
        new Date(item.updated_at).getTime() > new Date(winner.updated_at).getTime() ? item : winner,
      rounds[0]);
      const root = rounds[0];
      return {
        key,
        companyLabel: root.company_info?.trim() || root.title || '模拟面试',
        updatedAt: latest.updated_at,
        rounds,
      };
    })
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
}

/** Lock answer actions after persisted completion or immediate exhaustion of the configured question limit. */
export function isInterviewFinished(
  status: 'active' | 'completed' | 'archived' | undefined,
  currentQuestions: number,
  maxQuestions: number,
): boolean {
  // 持久化状态优先，同时用题目上限立即锁定尚未来得及刷新状态的客户端。
  return status === 'completed' || status === 'archived' || (maxQuestions > 0 && currentQuestions >= maxQuestions);
}
