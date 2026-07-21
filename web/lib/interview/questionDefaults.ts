import type { InterviewType } from "@/store/types";

export const ROUND_TYPE_DEFAULT_QUESTIONS: Record<InterviewType, number> = {
  tech_initial: 10,
  tech_deep: 20,
  hr_comprehensive: 5,
};

export const ROUND_INDEX_DEFAULT_TYPES: Record<number, InterviewType> = {
  1: "tech_initial",
  2: "tech_deep",
  3: "hr_comprehensive",
};

export function resolveRoundTypeByIndex(roundIndex: number): InterviewType {
  return ROUND_INDEX_DEFAULT_TYPES[roundIndex] ?? "hr_comprehensive";
}

export function defaultQuestionsForRoundType(roundType: InterviewType): number {
  return ROUND_TYPE_DEFAULT_QUESTIONS[roundType];
}

export function defaultQuestionsForRoundIndex(roundIndex: number): number {
  return defaultQuestionsForRoundType(resolveRoundTypeByIndex(roundIndex));
}

export const QUESTION_COUNT_OPTIONS = [3, 4, 5, 6, 7, 8, 9, 10, 15, 20];
