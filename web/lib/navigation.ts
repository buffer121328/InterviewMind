export type MainView =
  | "landing"
  | "interview"
  | "resume"
  | "guide"
  | "applications"
  | "questionbank"
  | "boss"
  | "memory"
  | "runs";

export type WorkspaceView = Exclude<MainView, "landing" | "guide">;

const PUBLIC_MAIN_VIEWS = new Set<MainView>([
  "landing",
  "guide",
  "applications",
  "questionbank",
  "memory",
  "runs",
]);

export function isPublicMainView(view: MainView): boolean {
  return PUBLIC_MAIN_VIEWS.has(view);
}

export function requiresApiConfig(view: MainView): boolean {
  return !isPublicMainView(view);
}

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
      return value;
    default:
      return "landing";
  }
}
