export interface BrowserSpeechRecognitionResult {
    isFinal: boolean;
    [index: number]: { transcript: string };
}

export interface BrowserSpeechRecognitionEvent {
    resultIndex: number;
    results: {
        length: number;
        [index: number]: BrowserSpeechRecognitionResult;
    };
}

export interface BrowserSpeechRecognitionErrorEvent {
    error: string;
}

export interface BrowserSpeechRecognition {
    continuous: boolean;
    interimResults: boolean;
    lang: string;
    onstart: (() => void) | null;
    onend: (() => void) | null;
    onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
    onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
    start: () => void;
    stop: () => void;
    abort: () => void;
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

interface BrowserAudioWindow extends Window {
    AudioContext?: typeof AudioContext;
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitAudioContext?: typeof AudioContext;
}

export function getSpeechRecognitionConstructor(): BrowserSpeechRecognitionConstructor | undefined {
    if (typeof window === 'undefined') return undefined;

    const browserWindow = window as BrowserAudioWindow;
    return browserWindow.SpeechRecognition || browserWindow.webkitSpeechRecognition;
}

export function getAudioContextConstructor(): typeof AudioContext {
    const browserWindow = window as BrowserAudioWindow;
    const AudioContextConstructor = browserWindow.AudioContext || browserWindow.webkitAudioContext;

    if (!AudioContextConstructor) {
        throw new Error('Browser does not support Web Audio.');
    }

    return AudioContextConstructor;
}
