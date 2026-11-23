import type { PlanVersion } from '../../api/personal'

export function versionEvents(version: PlanVersion | null | undefined) {
  const snapshot = version?.snapshot
  const option = snapshot?.options.find(row => row.option_id === snapshot.selected_option_id)
  return [...(snapshot?.schedule_items || []), ...(option?.schedule_items || [])]
}
