import HelpButton from "./HelpButton";
import PasteboardButton from "./PasteboardButton";
import RunningTasksButton from "./RunningTasksButton";
import SettingsButton from "./SettingsButton";
import WorkspaceSwitcher from "./WorkspaceSwitcher";
import type { Workspaces } from "../ws";

type Props = {
  workspaces: Workspaces;
  modeName: string;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
};

export default function TopBar({ workspaces, modeName, onOpenSettings, onOpenHelp }: Props) {
  return (
    <>
      <span className="sy-brand">Switch Bay</span>
      <WorkspaceSwitcher workspaces={workspaces} modeName={modeName} />
      <span className="sy-spacer" />
      <RunningTasksButton />
      <PasteboardButton />
      <HelpButton onClick={onOpenHelp} />
      <SettingsButton onClick={onOpenSettings} />
    </>
  );
}
