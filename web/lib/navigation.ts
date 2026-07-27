export type MainView =
  | "landing"
  | "interview"
  | "resume"
  | "guide"
  | "applications"
  | "questionbank"
  | "boss"
  | "memory"
  | "runs"
  | "prompts";

export type WorkspaceView = Exclude<MainView, "landing" | "guide">;

const PUBLIC_MAIN_VIEWS = new Set<MainView>([
  "landing",
  "guide",
  "applications",
  "questionbank",
  "memory",
  "runs",
  "prompts",
]);

/** Determines whether is public main view so callers can apply the same UI or safety boundary consistently. */
export function isPublicMainView(view: MainView): boolean {
  return PUBLIC_MAIN_VIEWS.has(view);
}

/** Determines whether requires api config so callers can apply the same UI or safety boundary consistently. */
export function requiresApiConfig(view: MainView): boolean {
  return !isPublicMainView(view);
}

/** Parses saved main view at the frontend boundary and returns a typed safe fallback when the payload is malformed or missing. */
export function parseSavedMainView(value: string | null): MainView {
  switch (value) {
    case "landing":
    case "interview":
    case "resume":
    case "guide":
    case "applications":
    case "questionbank":
    case "boss":
    case "memory":
    case "runs":
    case "prompts":
      return value;
    default:
      return "landing";
  }
}
