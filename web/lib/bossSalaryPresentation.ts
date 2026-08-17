/** User-facing fallback for BOSS salary text that depends on an unavailable site font mapping. */
export const BOSS_SALARY_CONFIRMATION_LABEL = '薪资请在 BOSS 原页面确认';

// BOSS salary anti-scraping fonts can leave Private Use or block/box-drawing glyphs in DOM text.
const BOSS_SALARY_OBFUSCATION_PATTERN = /[\uE000-\uF8FF\u2500-\u259F]/u;

/**
 * Keeps reliable salary text unchanged and labels glyphs that cannot be safely interpreted
 * outside the original BOSS page. It deliberately does not decode or infer compensation.
 */
export function displayBossSalaryText(salaryText: string): string {
    return BOSS_SALARY_OBFUSCATION_PATTERN.test(salaryText)
        ? BOSS_SALARY_CONFIRMATION_LABEL
        : salaryText;
}
