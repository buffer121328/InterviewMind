/** Returns whether a session-row context-menu event should open delete confirmation. */
export function shouldOpenSessionDeleteConfirmation(button: number): boolean {
    return button === 2;
}
