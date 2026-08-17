import type { BossExperience } from './api/jobs';

export const BOSS_EXPERIENCE_OPTIONS: ReadonlyArray<{ value: BossExperience; label: string }> = [
    { value: 'any', label: '不限' },
    { value: 'no_experience', label: '无经验' },
    { value: 'experience_unlimited', label: '经验不限' },
    { value: 'one_to_three', label: '1–3 年' },
];

export const BOSS_NO_EXPERIENCE_NOTICE = '无经验会在采集完整 JD 后，排除明确要求既往工作经验的岗位。';

export const BOSS_JOB_TYPE_LABEL = '全职';
