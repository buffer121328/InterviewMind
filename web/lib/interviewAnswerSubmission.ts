/** Describes the keyboard state needed to decide whether a text answer should be sent. */
export interface InterviewAnswerSubmissionKey {
    key: string;
    ctrlKey: boolean;
    isComposing?: boolean;
}

/** Returns true only for an explicit Ctrl+Enter shortcut outside IME composition. */
export function shouldSubmitInterviewAnswer(keyEvent: InterviewAnswerSubmissionKey): boolean {
    return keyEvent.key === 'Enter' && keyEvent.ctrlKey && !keyEvent.isComposing;
}
