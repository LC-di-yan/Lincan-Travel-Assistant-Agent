import { useMemo } from 'react'
import { useChatStore } from '../store/chatStore'
import { messageActivity } from '../utils/agentActivity'

export function useAgentActivity() {
  const last = useChatStore(s => s.messages.at(-1))
  return useMemo(() => ({ ...messageActivity(last?.role === 'assistant' ? last : undefined),
    historical: !!last?.historical }), [last])
}
