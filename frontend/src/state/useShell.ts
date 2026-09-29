import { SHELL_CONFIG, type ShellConfig, type ShellVariant } from './shellConfig';
import type { Settings } from './useSettings';

// plimsoll-two-shell-spec.md §1.2 — reads the one shell-selection setting and
// hands back the resolved config. Components branch on individual
// SHELL_CONFIG fields (imported directly where needed, see §3), never on
// `shell` itself, so a look at SHELL_CONFIG always shows the full set of
// divergences in one place.
export function useShell(settings: Settings): { shell: ShellVariant; config: ShellConfig } {
  return { shell: settings.shellVariant, config: SHELL_CONFIG[settings.shellVariant] };
}
