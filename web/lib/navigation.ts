export type MainView = "landing" | "interview" | "resume" | "guide" | "applications" | "questionbank" | "boss";

const PUBLIC_MAIN_VIEWS = new Set<MainView>(["landing", "guide", "applications", "questionbank"]);

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
      return value;
    default:
      return "landing";
  }
}
