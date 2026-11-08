"use client";

import ModulePage from "@/components/ModulePage";
import BackupPanel from "@/components/settings/BackupPanel";

export default function BackupPage() {
  return (
    <ModulePage title="Backup and sync" perm="manage_settings">
      <BackupPanel />
    </ModulePage>
  );
}
